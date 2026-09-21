"""ウェイクワード検知（openWakeWord を onnxruntime で動かす）。

モデルは models/openwakeword/ に置く（tools/setup_pi.sh がダウンロードする）。
調整値（しきい値など）は config.WakeWordConfig にあり、.env から変えられる。
"""

from collections import deque
from pathlib import Path

import numpy as np

from .config import PROJECT_ROOT, WakeWordConfig

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80ms。openWakeWord の処理単位
MODELS_DIR = PROJECT_ROOT / "models" / "openwakeword"
DEFAULT_MODEL = MODELS_DIR / "hey_jarvis_v0.1.onnx"
# 検知したときに記録しておく、直前のスコアの数（本物の反応と誤反応の違いを見分ける材料にする）。
# 確認窓（WakeWordConfig.confirm_frames）のぶんも入るよう 8 から増やした。
# 増やしすぎると、モニターに出す会話ログ（90 桁）での折り返しが増える。
SCORE_HISTORY_FRAMES = 10


class TriggerGate:
    """スコアの並びを見て、ウェイクワードとして反応してよいかを決める。

    1. しきい値以上のフレームが patience_frames 回続く（＝立ち上がり）。
    2. そこからさらに confirm_frames 回ぶんスコアを見る（確認窓）。
    3. 1 と 2 を通してのいちばん高いスコアが confirm_threshold 以上なら反応する。
    4. 反応したあと cooldown_frames の間は反応しない。

    確認窓を入れているのは、本物の発話ではスコアが 0.8 以上まで伸びるのに対し、
    物音などの誤検知は 0.5 手前で頭打ちになる傾向があるため（2026-09-20 の記録）。
    しきい値そのものを上げると、立ち上がりの遅い本物を取りこぼすので、
    「少し待ってから、いちばん高いところで決める」形にしている。
    confirm_threshold が 0 のときは見送りが起きないので、反応の判断は確認窓なしと同じになる
    （反応が confirm_frames ぶん遅れるだけ。材料を集める段階ではこの設定で使う）。
    """

    def __init__(
        self,
        threshold: float,
        cooldown_frames: int,
        patience_frames: int = 1,
        confirm_frames: int = 0,
        confirm_threshold: float = 0.0,
    ):
        self.threshold = threshold
        self.cooldown_frames = cooldown_frames
        self.patience_frames = max(1, patience_frames)
        self.confirm_frames = max(0, confirm_frames)
        self.confirm_threshold = confirm_threshold
        self.run_frames = 0  # 反応したときに、しきい値を超えて続いていたフレーム数
        self.peak = 0.0  # 反応したときの、確認窓までを含めた最大スコア
        self.suppressed = 0  # 確認窓で見送った回数（利用者が読む記録に残すため、反応したら数え直す）
        self._above = 0
        self._run_peak = 0.0
        self._confirming = 0
        self._remaining = 0

    def reset(self) -> None:
        """それまでのスコアによる状態を消す（設定は残す）。"""
        self._above = 0
        self._run_peak = 0.0
        self._confirming = 0
        self._remaining = 0
        self.suppressed = 0

    def update(self, score: float) -> bool:
        """1 フレーム分のスコアを渡し、反応すべきなら True を返す。"""
        if self._remaining > 0:
            self._remaining -= 1
            self._above = 0
            return False
        if self._confirming > 0:  # 確認窓の途中
            self._run_peak = max(self._run_peak, score)
            self._confirming -= 1
            return self._decide() if self._confirming == 0 else False
        if score < self.threshold:
            self._above = 0
            self._run_peak = 0.0
            return False
        self._above += 1
        self._run_peak = max(self._run_peak, score)
        if self._above < self.patience_frames:
            return False
        self.run_frames = self._above
        if self.confirm_frames > 0:
            self._confirming = self.confirm_frames
            return False
        return self._decide()

    def _decide(self) -> bool:
        """立ち上がりと確認窓を見終わったので、最大スコアで反応するかを決める。"""
        peak, self._run_peak, self._above = self._run_peak, 0.0, 0
        if peak < self.confirm_threshold:
            self.suppressed += 1
            return False
        self.peak = peak
        self._remaining = self.cooldown_frames
        return True


class WakeWordDetector:
    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL,
        *,
        config: WakeWordConfig = WakeWordConfig(),
        cooldown_seconds: float = 2.0,
        models_dir: Path = MODELS_DIR,
    ):
        from openwakeword.model import Model

        melspec_path = models_dir / "melspectrogram.onnx"
        embedding_path = models_dir / "embedding_model.onnx"
        for path in (model_path, melspec_path, embedding_path):
            if not path.exists():
                raise FileNotFoundError(f"モデルがありません：{path}（tools/setup_pi.sh を実行してください）")

        self._model = Model(
            wakeword_models=[str(model_path)],
            inference_framework="onnx",
            melspec_model_path=str(melspec_path),
            embedding_model_path=str(embedding_path),
        )
        self.name = next(iter(self._model.models))
        self._gate = TriggerGate(
            config.threshold,
            round(cooldown_seconds * SAMPLE_RATE / FRAME_SAMPLES),
            config.patience_frames,
            config.confirm_frames,
            config.confirm_threshold,
        )
        self.last_score = 0.0
        self.last_peak = 0.0  # 反応したときの最大スコア（確認窓まで含む）
        self.last_suppressed = 0  # その反応までに、確認窓で見送った回数
        self.last_scores: list[float] = []  # 検知したときの、直前のスコアの並び
        self._recent: deque[float] = deque(maxlen=SCORE_HISTORY_FRAMES)

    def reset(self) -> None:
        """それまでの音声による状態を消す（マイクを開き直したときに呼ぶ）。"""
        self._model.reset()
        self._gate.reset()
        self.last_score = 0.0
        self._recent.clear()

    def process(self, frame: np.ndarray) -> bool:
        """80ms 分（int16、16kHz、モノラル）の音声を渡し、ウェイクワードを検知したら True を返す。"""
        self.last_score = float(self._model.predict(frame)[self.name])
        self._recent.append(self.last_score)
        detected = self._gate.update(self.last_score)
        if detected:
            self.last_scores = list(self._recent)
            self.last_peak = self._gate.peak
            self.last_suppressed = self._gate.suppressed
            self._gate.suppressed = 0
            self._model.reset()
            self._recent.clear()
        return detected
