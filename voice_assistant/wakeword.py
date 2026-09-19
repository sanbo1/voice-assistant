"""ウェイクワード検知（openWakeWord を onnxruntime で動かす）。

モデルは models/openwakeword/ に置く（tools/setup_pi.sh がダウンロードする）。
"""

from pathlib import Path

import numpy as np

from .config import PROJECT_ROOT

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80ms。openWakeWord の処理単位
MODELS_DIR = PROJECT_ROOT / "models" / "openwakeword"
DEFAULT_MODEL = MODELS_DIR / "hey_jarvis_v0.1.onnx"
# 2026-09-19 の確認で決めた値。0.5 では取りこぼしが多く、0.35 で約 11 分間誤検知がなかった
DEFAULT_THRESHOLD = 0.35


class TriggerGate:
    """スコアがしきい値以上になったら 1 回だけ反応し、その後しばらくは反応しない。"""

    def __init__(self, threshold: float, cooldown_frames: int):
        self.threshold = threshold
        self.cooldown_frames = cooldown_frames
        self._remaining = 0

    def update(self, score: float) -> bool:
        """1 フレーム分のスコアを渡し、反応すべきなら True を返す。"""
        if self._remaining > 0:
            self._remaining -= 1
            return False
        if score >= self.threshold:
            self._remaining = self.cooldown_frames
            return True
        return False


class WakeWordDetector:
    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL,
        *,
        threshold: float = DEFAULT_THRESHOLD,
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
        self._gate = TriggerGate(threshold, round(cooldown_seconds * SAMPLE_RATE / FRAME_SAMPLES))
        self.last_score = 0.0

    def reset(self) -> None:
        """それまでの音声による状態を消す（マイクを開き直したときに呼ぶ）。"""
        self._model.reset()
        self._gate = TriggerGate(self._gate.threshold, self._gate.cooldown_frames)
        self.last_score = 0.0

    def process(self, frame: np.ndarray) -> bool:
        """80ms 分（int16、16kHz、モノラル）の音声を渡し、ウェイクワードを検知したら True を返す。"""
        self.last_score = float(self._model.predict(frame)[self.name])
        detected = self._gate.update(self.last_score)
        if detected:
            self._model.reset()
        return detected
