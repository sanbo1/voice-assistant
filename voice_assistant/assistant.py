"""音声アシスタントの本体。ウェイクワード → お知らせ音 → 聞き取り → AI → 読み上げ を繰り返す。

読み上げの間はマイクを閉じる（自分の声やお知らせ音にウェイクワードが反応しないように）。
返答のあとは、決めた秒数だけ「続けて話せる状態」になり、話しかけられなければウェイクワード待ちに戻る。
ウェイクワードの待ち受けに戻るたびに、検知時と逆向きのお知らせ音（ready_chime）を鳴らす。
"""

import dataclasses
import logging
import time
from collections.abc import Callable, Iterator

import numpy as np

from . import audio
from .ai import AiError, ChatClient
from .config import AssistantConfig, AudioConfig, GeminiConfig, SttConfig, WakeWordConfig
from .conversation_log import ConversationLog
from .frames import rechunk
from .history import ConversationHistory
from .settings import SettingsWatcher, changes, needs_restart
from .sounds import listen_chime, ready_chime, wake_chime
from .state import (
    FOLLOWUP,
    LISTENING,
    SPEAKING,
    STARTING,
    THINKING,
    WAITING,
    StateFile,
)
from .stt import RecognitionStream, VoskRecognizer, model_dir_from_config
from .talk_key import TalkSignal, collect_while_held
from .tts import OpenJTalk, to_speakable
from .vad import EndpointConfig, Endpointer, SileroVad, Utterance, collect_utterance
from .wakeword import FRAME_SAMPLES, WakeWordDetector

logger = logging.getLogger(__name__)

STARTUP_MESSAGE = "音声アシスタントを起動しました。"
# ウェイクワードを待ち受ける状態になったことを会話ログに残す文言（画面で「止まっている」と見えないように）
WAITING_MESSAGE = "ウェイクワードを待っています（「hey jarvis」と話しかけてください）"
RATE_LIMIT_MESSAGE = "利用回数の上限に達しました。少し時間をおいてから話しかけてください。"
DAILY_LIMIT_MESSAGE = "今日の利用回数の上限に達しました。しばらくしてから、もう一度お試しください。"
AI_ERROR_MESSAGE = "すみません、今は答えを用意できませんでした。少し待ってから、もう一度お試しください。"
# 想定外のエラーのあと、次に試すまで待つ秒数（マイクが外れたときなどに空回りしないため）
ERROR_BACKOFF_SECONDS = 5.0
# 起動直後に出力を目覚めさせてから待つ秒数（HDMI は休止から戻る間の音が失われるため）
OUTPUT_WAKE_SECONDS = 2.0
# 再生にかかった時間が音声の長さのこの倍を超えたら、遅くなったとみなして会話ログに記録する。
# 読み上げが途中から遅く・低くなる現象を調べるため。1.15 では 1.1 倍ほどの遅れを拾えなかったので 1.08 にした（2026-09-20）
SLOW_PLAYBACK_FACTOR = 1.08
# 話し終わりの判定から読み上げ開始までがこの秒数を超えたら、会話ログにも記録する
# （技術ログは Pi の再起動で消えるため。2026-09-20）
SLOW_RESPONSE_SECONDS = 5.0
# 読み上げのあと、続けて話せる状態にする前に待つ秒数
# （スピーカーから出た読み上げの終わりをマイクが拾い、話し始めと判定されないように）
FOLLOWUP_DELAY_SECONDS = 0.5
# 聞き取った文字がこれより短いときは AI に送らない（周りの音による短い誤認識を送らないため）
MIN_QUESTION_CHARS = 2
# 待ち受け中に設定の変更を見る間隔（フレーム数。1 フレーム 80ms なので約 1 秒ごと）
SETTINGS_CHECK_FRAMES = 12


def is_slow_playback(expected_seconds: float, elapsed_seconds: float) -> bool:
    """再生にかかった時間が、音声の長さに対して長すぎるか。"""
    return expected_seconds > 0 and elapsed_seconds > expected_seconds * SLOW_PLAYBACK_FACTOR


def reply_or_error_message(ai: ChatClient, history: ConversationHistory, text: str, log: ConversationLog) -> str:
    """AI に質問して返答を返す。失敗したら利用者に伝える文言を返す。成功したときだけ履歴に残す。

    ai が予備のモデルを持つ場合（FallbackChatClient）、予備のモデルで答えたときは会話ログにモデル名を付ける。
    """
    try:
        answer = ai.reply(text, history.messages())
    except AiError as e:
        log.error(str(e))
        if e.status == 429:
            return DAILY_LIMIT_MESSAGE if e.quota == "day" else RATE_LIMIT_MESSAGE
        return AI_ERROR_MESSAGE
    history.add(text, answer)
    model = getattr(ai, "last_model", None)
    log.reply(answer, model if model and model != getattr(ai, "primary", model) else None)
    return answer


class Assistant:
    def __init__(
        self,
        ai: ChatClient,
        *,
        audio_config: AudioConfig,
        log: ConversationLog,
        assistant_config: AssistantConfig = AssistantConfig(),
        wakeword_config: WakeWordConfig = WakeWordConfig(),
        stt_config: SttConfig = SttConfig(),
        history: ConversationHistory | None = None,
        endpoint_config: EndpointConfig = EndpointConfig(),
        watcher: SettingsWatcher | None = None,
        ai_factory: Callable[[GeminiConfig], ChatClient] | None = None,
    ):
        self._ai = ai
        self._audio = audio_config
        self._log = log
        self._config = assistant_config
        self._history = history or ConversationHistory()
        self._endpoint_config = endpoint_config
        self._detector = WakeWordDetector(config=wakeword_config)
        self._wake_note = ""  # 直前の検知のスコア（空振りだったときに記録へ残すため）
        self._vad = SileroVad()
        self._stt_config = stt_config
        self._recognizer = VoskRecognizer(model_dir_from_config(stt_config))
        # いまの様子を画面へ渡す（書けなくても本体は動く）
        self._state = StateFile()
        # ボタン（いまは画面のスペースキー）を押している間だけ聞き取るための合図
        self._talk = TalkSignal()
        # .env の変更を待ち受け中に反映する（再起動せずに調整できるように）
        self._watcher = watcher
        self._ai_factory = ai_factory
        self._tts = OpenJTalk()
        # お知らせ音も再生に使う周波数で作り、PipeWire での変換をなくす
        self._chime = wake_chime(audio.OUTPUT_SAMPLE_RATE)
        self._ready_chime = ready_chime(audio.OUTPUT_SAMPLE_RATE)
        self._listen_chime = listen_chime(audio.OUTPUT_SAMPLE_RATE)

    def run(self) -> None:
        """止められるまで（Ctrl+C など）動き続ける。"""
        self._log.status("起動しました")
        self._note_state(STARTING)
        # 起動直後の読み上げが聞こえないことがあるため、そのときの出力先を残す（2026-09-21）
        before = audio.output_summary(self._audio.output_device)
        logger.info("起動時の出力先：%s", before)
        self._log.status(f"起動時の出力先：{before}")
        audio.play(np.zeros(audio.OUTPUT_SAMPLE_RATE // 2, dtype=np.int16), audio.OUTPUT_SAMPLE_RATE,
                   device=self._audio.output_device)
        time.sleep(OUTPUT_WAKE_SECONDS)
        self._speak(STARTUP_MESSAGE)
        after = audio.output_summary(self._audio.output_device)
        if after != before:
            # 読み上げの途中で出力先が増えた・変わった場合（＝読み上げが間に合わなかった可能性）
            logger.info("読み上げのあと出力先が変わりました：%s", after)
            self._log.status(f"読み上げのあと出力先が変わりました：{after}")
        while True:
            try:
                # 待ち受けに戻ったことを知らせる（鳴らし終わってからマイクを開く）
                audio.play(self._ready_chime, audio.OUTPUT_SAMPLE_RATE, device=self._audio.output_device)
                # 画面の会話ログだけを見ていると、待ち受けに戻ったことが分からず止まって見えるため残す
                # （短い聞き取りのあとは何も言わずに戻るので、直前の行が「聞き取り：…」のままになる。2026-09-22）
                self._log.status(WAITING_MESSAGE)
                self._note_state(WAITING)
                self.handle_one_turn()
            except Exception as e:
                logger.exception("想定外のエラー")
                self._log.error(f"想定外のエラーが起きました（{type(e).__name__}）。{ERROR_BACKOFF_SECONDS:g} 秒後に再開します")
                time.sleep(ERROR_BACKOFF_SECONDS)

    def handle_one_turn(self) -> None:
        """ウェイクワードを待って質問に答え、そのあとは決めた回数まで続けて話せるようにする。"""
        if not self._answer_once(self._wake_and_listen, after_wake=True):
            return
        # 質問にならなかった回があれば、その時点で待ち受けに戻る（雑音を拾い続けないため）
        for _ in range(self._config.followup_max_turns):
            if self._config.followup_seconds <= 0:
                return
            if not self._answer_once(self._listen_again):
                return

    def _answer_once(self, listen: Callable[[], tuple[Utterance, RecognitionStream]],
                     *, after_wake: bool = False) -> bool:
        """聞き取って答える。続けて話せる状態にしてよければ True を返す。

        after_wake が True のとき、質問にならなかった回は「空振り」として会話ログに残す
        （ウェイクワードの誤反応をあとから数えられるようにするため。2026-09-21）。
        """
        utterance, recognition = listen()
        if utterance.samples is None:
            if after_wake:
                self._log_empty_wake(utterance.reason.value)
            else:
                self._log.status(f"聞き取りを終了しました（{utterance.reason.value}）")
            return False

        self._note_state(THINKING)
        started = time.perf_counter()
        text = recognition.finish()
        recognized = time.perf_counter()
        self._log.heard(text, recognition.confidence)
        if len(text) < MIN_QUESTION_CHARS:
            # 周りの音を拾っただけのことが多いため、AI には送らず、何も言わずに待ち受けへ戻る
            # （ウェイクワードの誤反応のたびに話すとうるさいため。2026-09-20）
            if after_wake:
                self._log_empty_wake("聞き取りが短い")
            return False
        if self._is_noise(recognition.confidence):
            # テレビの音などを文字にしただけの結果を AI に送らない（利用回数の枠を守るため。2026-09-22）
            self._log.status("雑音とみなして AI に送りませんでした")
            if after_wake:
                self._log_empty_wake("雑音とみなした")
            return False

        answer = reply_or_error_message(self._ai, self._history, text, self._log)
        answered = time.perf_counter()
        self._note_state(SPEAKING)
        self._speak(answer, before_play=lambda: self._log_response_time(started, recognized, answered))
        return True

    def _wake_and_listen(self) -> tuple[Utterance, RecognitionStream]:
        """ウェイクワードを待ち、お知らせ音を鳴らしてから聞き取る（マイクは開いたまま続ける）。"""
        stream = audio.stream_frames(FRAME_SAMPLES, device=self._audio.input_device)
        try:
            self._detector.reset()
            by_key = False
            waited = 0
            for frame in stream:
                # 待ち受け中だけ設定の変更を見る（約 1 秒ごと。会話の途中では変えない）
                waited += 1
                if waited % SETTINGS_CHECK_FRAMES == 0:
                    self._apply_new_settings()
                if self._talk.pressed():
                    by_key = True
                    break
                if self._detector.process(frame):
                    break
            audio.play_nowait(self._chime, audio.OUTPUT_SAMPLE_RATE, device=self._audio.output_device)
            if by_key:
                return self._collect_held(stream)
            # 最大スコアとスコアの並びも残す（本物の反応と誤反応の違いを見分ける材料にする）
            self._wake_note = (f"最大 {self._detector.last_peak:.2f}、"
                               f"並び {' '.join(f'{score:.2f}' for score in self._detector.last_scores)}"
                               + (f"、見送り {self._detector.last_suppressed} 回"
                                  if self._detector.last_suppressed else ""))
            logger.info("ウェイクワードを検知（%s）", self._wake_note)
            # 音が出ない場合でも、画面の会話ログで話しかけるタイミングがわかるようにする
            self._log.status(f"聞き取り中…話してください（ウェイクワードを検知、{self._wake_note}）")
            self._note_state(LISTENING)
            return self._collect(stream, self._endpoint_config)
        finally:
            stream.close()  # 読み上げの間はマイクを閉じる

    def _collect_held(self, stream: Iterator[np.ndarray]) -> tuple[Utterance, RecognitionStream]:
        """ボタンを押している間だけ聞き取る（話し終わりの無音判定は使わない）。"""
        self._wake_note = "ボタン"
        logger.info("ボタンで聞き取りを開始")
        self._log.status("聞き取り中…話してください（ボタンを押している間）")
        self._note_state(LISTENING)
        recognition = self._recognizer.start()
        max_frames = int(self._endpoint_config.max_seconds * audio.SAMPLE_RATE / FRAME_SAMPLES)
        utterance = collect_while_held(stream, self._talk.held, max_frames, recognition)
        return utterance, recognition

    def _listen_again(self) -> tuple[Utterance, RecognitionStream]:
        """返答のあと、ウェイクワードなしで続けて話せる状態にする。"""
        # スピーカーから出た読み上げの終わりを拾わないよう、少し待ってからマイクを開く
        time.sleep(FOLLOWUP_DELAY_SECONDS)
        audio.play(self._listen_chime, audio.OUTPUT_SAMPLE_RATE, device=self._audio.output_device)
        seconds = self._config.followup_seconds
        # 残り回数は出さない。短い聞き取りが 1 回あればそこで終わるため、
        # 「このあと N 回まで」は実際の挙動と食い違っていた（2026-09-22）
        self._log.status(f"続けて話せます（{seconds:g} 秒以内）")
        self._note_state(FOLLOWUP)
        config = dataclasses.replace(self._endpoint_config, start_timeout_seconds=seconds)
        stream = audio.stream_frames(FRAME_SAMPLES, device=self._audio.input_device)
        try:
            return self._collect(stream, config)
        finally:
            stream.close()

    def _collect(self, stream: Iterator[np.ndarray], config: EndpointConfig) -> tuple[Utterance, RecognitionStream]:
        """発話を切り出しながら、同時に音声認識へ渡す。"""
        self._vad.reset()
        recognition = self._recognizer.start()
        utterance = collect_utterance(
            rechunk(stream, SileroVad.FRAME_SAMPLES),
            self._vad.speech_probability,
            Endpointer(config, SileroVad.FRAME_SAMPLES / audio.SAMPLE_RATE),
            recognition,
        )
        return utterance, recognition

    def _apply_new_settings(self) -> None:
        """`.env` が変わっていれば、動作中の設定を入れ替える（待ち受け中だけ呼ぶ）。"""
        if self._watcher is None:
            return
        before = self._watcher.settings
        new = self._watcher.reload_if_changed()
        if new is None:
            return
        self._config = new.assistant
        self._stt_config = new.stt
        self._audio = new.audio
        self._detector.apply(new.wakeword)
        if self._ai_factory is not None and new.gemini != before.gemini:
            try:
                self._ai = self._ai_factory(new.gemini)
            except AiError as e:
                self._log.error(f"AI の設定を変えられませんでした（{e}）")
        for line in changes(before, new):
            logger.info("設定の変更：%s", line)
            self._log.status(f"設定を読み直しました：{line}")
        for label in needs_restart(before, new):
            self._log.status(f"{label}の変更は、再起動してから反映されます")

    def _note_state(self, state: str) -> None:
        """いまの様子を画面に渡す（docs/display-spec.md の段階 2）。"""
        primary = getattr(self._ai, "primary", None)
        model = getattr(self._ai, "last_model", None) or primary or getattr(self._ai, "model", None)
        self._state.write(state, self._history.seconds_left(),
                          model=model, fallback=bool(model and primary and model != primary))

    def _is_noise(self, confidence: float | None) -> bool:
        """聞き取りの確信度が低すぎるか（雑音を文字にしただけとみなすか）。

        2026-09-22 の実測では、雑音だけ（テレビ）が 0.465、離れた位置からの質問が 0.576〜0.847 だった。
        確信度では「雑音」と「誤って認識された質問」は区別できない（0.79 で全く違う言葉のこともある）。
        あくまで、雑音を AI に送って利用回数の枠を使い切るのを防ぐための足切り。
        """
        threshold = self._stt_config.min_confidence
        if threshold <= 0 or confidence is None:
            return False
        if confidence >= threshold:
            return False
        logger.info("確信度が低いため AI に送りません（%.2f < %.2f）", confidence, threshold)
        return True

    def _log_empty_wake(self, reason: str) -> None:
        """ウェイクワードで始まった回が質問にならなかったことを、検知時のスコアと一緒に記録する。

        誤反応だったかをあとから調べるための材料
        （本物でも、話しかけずに黙っていればここに来る）。
        """
        logger.info("ウェイクワードは空振り（%s、%s）", reason, self._wake_note)
        self._log.status(f"ウェイクワードは空振りでした（{reason}、{self._wake_note}）")

    def _log_response_time(self, started: float, recognized: float, answered: float) -> None:
        """話し終わりの判定から読み上げ開始までの時間を記録する。遅いときは会話ログにも残す。"""
        now = time.perf_counter()
        total, recognition, ai, synthesis = now - started, recognized - started, answered - recognized, now - answered
        logger.info("話し終わりの判定から読み上げ開始まで %.2f 秒（認識 %.2f、AI %.2f、合成 %.2f）",
                    total, recognition, ai, synthesis)
        if total >= SLOW_RESPONSE_SECONDS:
            model = getattr(self._ai, "last_model", None)
            self._log.status(f"応答に時間がかかりました（合計 {total:.1f} 秒／認識 {recognition:.1f}／"
                             f"AI {ai:.1f}／合成 {synthesis:.1f}" + (f"／モデル {model}）" if model else "）"))

    def _speak(self, text: str, before_play: Callable[[], None] | None = None) -> None:
        """文章を読み上げる（終わるまで待つ）。合成に失敗したら会話ログに残す。"""
        speakable = to_speakable(text)
        if not speakable:
            return
        try:
            samples, sample_rate = self._tts.synthesize(speakable)
        except (RuntimeError, OSError) as e:
            self._log.error(f"読み上げの音声を作れませんでした（{e}）")
            return
        if before_play is not None:
            before_play()
        expected = len(samples) / sample_rate
        start = time.perf_counter()
        underflowed = audio.play(samples, sample_rate, device=self._audio.output_device)
        elapsed = time.perf_counter() - start
        if underflowed:
            # 局所的な間延びは、全体の長さではほとんど変わらないため下の倍率では拾えない（2026-09-21）
            logger.warning("読み上げ中に音が途切れました（%.1f 秒の音声、再生 %.1f 秒）", expected, elapsed)
            self._log.status(f"読み上げ中に音が途切れました（{expected:.1f} 秒の音声、再生 {elapsed:.1f} 秒）")
        # 遅くなかった回も記録しておき、あとから比べられるようにする（2026-09-20）
        logger.info("読み上げ：%.1f 秒の音声に %.1f 秒（%.2f 倍）", expected, elapsed, elapsed / max(expected, 1e-9))
        if is_slow_playback(expected, elapsed):
            logger.warning("読み上げが遅くなりました：%.1f 秒の音声に %.1f 秒（%.2f 倍）",
                           expected, elapsed, elapsed / expected)
            self._log.status(f"読み上げが遅くなりました（{expected:.1f} 秒の音声に {elapsed:.1f} 秒、{elapsed / expected:.2f} 倍）")
