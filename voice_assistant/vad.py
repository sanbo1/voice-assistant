"""発話区間の検出（Silero VAD を onnxruntime で動かす）と、話し始め・話し終わりの判定。

モデルは models/silero_vad/ に置く（tools/setup_pi.sh がダウンロードする）。
"""

from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

import numpy as np

from .config import PROJECT_ROOT

SAMPLE_RATE = 16000
DEFAULT_MODEL = PROJECT_ROOT / "models" / "silero_vad" / "silero_vad.onnx"


class SileroVad:
    """512 サンプル（32ms）ごとに、人の声である確率（0〜1）を返す。"""

    FRAME_SAMPLES = 512
    _CONTEXT_SAMPLES = 64  # 前のフレームの末尾をつなげて渡す（公式の実装に合わせる）

    def __init__(self, model_path: Path = DEFAULT_MODEL):
        import onnxruntime as ort

        if not model_path.exists():
            raise FileNotFoundError(f"モデルがありません：{model_path}（tools/setup_pi.sh を実行してください）")
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._sample_rate = np.array(SAMPLE_RATE, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        """内部状態を消す。新しく聞き取りを始めるときに呼ぶ。"""
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self._CONTEXT_SAMPLES), dtype=np.float32)

    def speech_probability(self, frame: np.ndarray) -> float:
        """512 サンプル（int16、16kHz、モノラル）を渡し、人の声である確率を返す。"""
        if len(frame) != self.FRAME_SAMPLES:
            raise ValueError(f"{self.FRAME_SAMPLES} サンプルのフレームを渡してください（{len(frame)} サンプル）")
        x = (frame.astype(np.float32) / 32768.0)[np.newaxis, :]
        x = np.concatenate([self._context, x], axis=1)
        prob, self._state = self._session.run(
            None, {"input": x, "state": self._state, "sr": self._sample_rate}
        )
        self._context = x[:, -self._CONTEXT_SAMPLES:]
        return float(prob[0, 0])


class EndReason(Enum):
    SILENCE = "話し終わり（無音が続いた）"
    MAX_LENGTH = "最大の長さに達した"
    NO_SPEECH = "時間内に話し始めなかった"
    RELEASED = "ボタンを離した"
    INPUT_ENDED = "音声の入力が終わった"


@dataclass(frozen=True)
class EndpointConfig:
    threshold: float = 0.5  # これ以上なら声とみなす
    end_silence_seconds: float = 1.0  # 話し始めたあと、これだけ無音が続いたら話し終わり
    start_timeout_seconds: float = 5.0  # 聞き取り開始からこの時間内に話し始めなければ打ち切る
    max_seconds: float = 15.0  # 聞き取り開始からの最大の長さ
    min_speech_seconds: float = 0.25  # これより短い声（咳・物音など）は発話とみなさない
    pre_roll_seconds: float = 0.3  # 話し始める前の音声もこれだけ残す（最初の音が切れないように）


class Endpointer:
    """フレームごとの「声である確率」から、話し始めと話し終わりを判定する。"""

    def __init__(self, config: EndpointConfig, frame_seconds: float):
        self._threshold = config.threshold
        # 一度無音になりかけたら、threshold より少し低い値までは無音として数え続ける（公式の実装に合わせる）
        self._neg_threshold = max(config.threshold - 0.15, 0.01)
        self._end_silence_frames = max(1, round(config.end_silence_seconds / frame_seconds))
        self._start_timeout_frames = max(1, round(config.start_timeout_seconds / frame_seconds))
        self._max_frames = max(1, round(config.max_seconds / frame_seconds))
        self._min_speech_frames = max(1, round(config.min_speech_seconds / frame_seconds))
        self.pre_roll_frames = round(config.pre_roll_seconds / frame_seconds)
        self.started = False
        self._frames = 0
        self._speech_frames = 0
        self._silent_frames = 0

    def update(self, prob: float) -> EndReason | None:
        """1 フレーム分の確率を渡す。聞き取りを終えるべきなら理由を、続けるなら None を返す。"""
        self._frames += 1
        if not self.started:
            if prob >= self._threshold:
                self.started = True
                self._speech_frames = 1
                self._silent_frames = 0
            elif self._frames >= self._start_timeout_frames:
                return EndReason.NO_SPEECH
            return None

        if prob >= self._threshold:
            self._speech_frames += 1
            self._silent_frames = 0
        elif prob < self._neg_threshold or self._silent_frames > 0:
            self._silent_frames += 1

        if self._silent_frames >= self._end_silence_frames:
            if self._speech_frames < self._min_speech_frames:
                # 短すぎる声は発話とみなさず、話し始めを待ち直す
                self.started = False
                return None
            return EndReason.SILENCE
        if self._frames >= self._max_frames:
            return EndReason.MAX_LENGTH
        return None


@dataclass(frozen=True)
class Utterance:
    samples: np.ndarray | None  # 話し始めなかった場合は None
    reason: EndReason


class UtteranceListener(Protocol):
    """発話として集めた音声を、そのつど受け取る（話しながら音声認識に渡すため）。"""

    def accept(self, frame: np.ndarray) -> None: ...

    def reset(self) -> None:
        """それまでに渡した音声が、短すぎる声として取り消された。"""
        ...


def collect_utterance(
    frames: Iterable[np.ndarray],
    speech_probability: Callable[[np.ndarray], float],
    endpointer: Endpointer,
    listener: UtteranceListener | None = None,
) -> Utterance:
    """フレームを読み進め、話し始めの少し前から話し終わりまでの音声を集める。

    listener を渡すと、集めた音声を順に listener.accept() に渡す。取り消したときは listener.reset() を呼ぶ。
    """
    pre_roll: deque[np.ndarray] = deque(maxlen=endpointer.pre_roll_frames)
    collected: list[np.ndarray] = []
    reason = EndReason.INPUT_ENDED
    for frame in frames:
        result = endpointer.update(speech_probability(frame))
        if endpointer.started:
            if not collected:
                collected.extend(pre_roll)
                if listener is not None:
                    for earlier in pre_roll:
                        listener.accept(earlier)
            collected.append(frame)
            if listener is not None:
                listener.accept(frame)
        else:
            if collected:
                # 短すぎて取り消された音声は、次の話し始めの前の部分として扱う
                pre_roll.extend(collected)
                collected.clear()
                if listener is not None:
                    listener.reset()
            pre_roll.append(frame)
        if result is not None:
            reason = result
            break

    if reason is EndReason.NO_SPEECH or not collected:
        return Utterance(samples=None, reason=reason)
    return Utterance(samples=np.concatenate(collected), reason=reason)
