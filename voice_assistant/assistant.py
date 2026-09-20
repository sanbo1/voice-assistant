"""音声アシスタントの本体。ウェイクワード → お知らせ音 → 聞き取り → AI → 読み上げ を繰り返す。

読み上げの間はマイクを閉じる（自分の声やお知らせ音にウェイクワードが反応しないように）。
ウェイクワードの待ち受けに戻るたびに、検知時と逆向きのお知らせ音（ready_chime）を鳴らす。
"""

import logging
import time
from collections.abc import Callable

import numpy as np

from . import audio
from .ai import AiError, ChatClient
from .config import AudioConfig
from .conversation_log import ConversationLog
from .frames import rechunk
from .history import ConversationHistory
from .sounds import ready_chime, wake_chime
from .stt import VoskRecognizer
from .tts import OpenJTalk, to_speakable
from .vad import EndpointConfig, Endpointer, SileroVad, collect_utterance
from .wakeword import FRAME_SAMPLES, WakeWordDetector

logger = logging.getLogger(__name__)

STARTUP_MESSAGE = "音声アシスタントを起動しました。"
NOT_HEARD_MESSAGE = "すみません、聞き取れませんでした。もう一度話しかけてください。"
RATE_LIMIT_MESSAGE = "利用回数の上限に達しました。少し時間をおいてから話しかけてください。"
DAILY_LIMIT_MESSAGE = "今日の利用回数の上限に達しました。しばらくしてから、もう一度お試しください。"
AI_ERROR_MESSAGE = "すみません、今は答えを用意できませんでした。少し待ってから、もう一度お試しください。"
# 想定外のエラーのあと、次に試すまで待つ秒数（マイクが外れたときなどに空回りしないため）
ERROR_BACKOFF_SECONDS = 5.0
# 起動直後に出力を目覚めさせてから待つ秒数（HDMI は休止から戻る間の音が失われるため）
OUTPUT_WAKE_SECONDS = 2.0
# 再生にかかった時間が音声の長さのこの倍を超えたら、遅くなったとみなして記録する
# （読み上げが途中から遅く・低くなる現象を調べるため。2026-09-20）
SLOW_PLAYBACK_FACTOR = 1.15


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
        history: ConversationHistory | None = None,
        endpoint_config: EndpointConfig = EndpointConfig(),
    ):
        self._ai = ai
        self._audio = audio_config
        self._log = log
        self._history = history or ConversationHistory()
        self._endpoint_config = endpoint_config
        self._detector = WakeWordDetector()
        self._vad = SileroVad()
        self._recognizer = VoskRecognizer()
        self._tts = OpenJTalk()
        # お知らせ音も再生に使う周波数で作り、PipeWire での変換をなくす
        self._chime = wake_chime(audio.OUTPUT_SAMPLE_RATE)
        self._ready_chime = ready_chime(audio.OUTPUT_SAMPLE_RATE)

    def run(self) -> None:
        """止められるまで（Ctrl+C など）動き続ける。"""
        self._log.status("起動しました")
        audio.play(np.zeros(audio.OUTPUT_SAMPLE_RATE // 2, dtype=np.int16), audio.OUTPUT_SAMPLE_RATE,
                   device=self._audio.output_device)
        time.sleep(OUTPUT_WAKE_SECONDS)
        self._speak(STARTUP_MESSAGE)
        while True:
            try:
                # 待ち受けに戻ったことを知らせる（鳴らし終わってからマイクを開く）
                audio.play(self._ready_chime, audio.OUTPUT_SAMPLE_RATE, device=self._audio.output_device)
                self.handle_one_turn()
            except Exception as e:
                logger.exception("想定外のエラー")
                self._log.error(f"想定外のエラーが起きました（{type(e).__name__}）。{ERROR_BACKOFF_SECONDS:g} 秒後に再開します")
                time.sleep(ERROR_BACKOFF_SECONDS)

    def handle_one_turn(self) -> None:
        """ウェイクワードを待ち、1 回分の質問に答える。"""
        stream = audio.stream_frames(FRAME_SAMPLES, device=self._audio.input_device)
        try:
            self._detector.reset()
            for frame in stream:
                if self._detector.process(frame):
                    break
            audio.play_nowait(self._chime, audio.OUTPUT_SAMPLE_RATE, device=self._audio.output_device)
            logger.info("ウェイクワードを検知（スコア %.2f、連続 %d フレーム）",
                        self._detector.last_score, self._detector.last_run_frames)
            # 音が出ない場合でも、画面の会話ログで話しかけるタイミングがわかるようにする
            self._log.status("聞き取り中…話してください（ウェイクワードを検知、"
                             f"スコア {self._detector.last_score:.2f}、連続 {self._detector.last_run_frames} フレーム）")

            self._vad.reset()
            recognition = self._recognizer.start()
            utterance = collect_utterance(
                rechunk(stream, SileroVad.FRAME_SAMPLES),
                self._vad.speech_probability,
                Endpointer(self._endpoint_config, SileroVad.FRAME_SAMPLES / audio.SAMPLE_RATE),
                recognition,
            )
        finally:
            stream.close()  # 読み上げの間はマイクを閉じる

        if utterance.samples is None:
            self._log.status(f"聞き取りを終了しました（{utterance.reason.value}）")
            return

        started = time.perf_counter()
        text = recognition.finish()
        recognized = time.perf_counter()
        self._log.heard(text)
        if not text:
            self._speak(NOT_HEARD_MESSAGE)
            return

        answer = reply_or_error_message(self._ai, self._history, text, self._log)
        answered = time.perf_counter()
        self._speak(answer, before_play=lambda: logger.info(
            "話し終わりの判定から読み上げ開始まで %.2f 秒（認識 %.2f、AI %.2f、合成 %.2f）",
            time.perf_counter() - started, recognized - started, answered - recognized,
            time.perf_counter() - answered,
        ))

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
        audio.play(samples, sample_rate, device=self._audio.output_device)
        elapsed = time.perf_counter() - start
        if is_slow_playback(expected, elapsed):
            # 読み上げが途中から遅く・低くなる現象を調べるための記録（2026-09-20）
            logger.warning("読み上げが遅くなりました：%.1f 秒の音声に %.1f 秒（%.2f 倍）",
                           expected, elapsed, elapsed / expected)
            self._log.status(f"読み上げが遅くなりました（{expected:.1f} 秒の音声に {elapsed:.1f} 秒）")
