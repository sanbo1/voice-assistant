"""ウェイクワード検知（openWakeWord を onnxruntime で動かす）。

モデルは models/openwakeword/ に置く（tools/setup_pi.sh がダウンロードする）。
"""

from collections import deque
from pathlib import Path

import numpy as np

from .config import PROJECT_ROOT

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1280  # 80ms。openWakeWord の処理単位
MODELS_DIR = PROJECT_ROOT / "models" / "openwakeword"
DEFAULT_MODEL = MODELS_DIR / "hey_jarvis_v0.1.onnx"
# 2026-09-19 の確認では、取りこぼしを減らすため 0.35 にした（約 11 分間の確認では誤検知なし）。
# その後の運用（2026-09-20）で誤検知が多かったため、しきい値は 0.35 のままにして、
# 「続けて超えたフレーム数」（DEFAULT_PATIENCE_FRAMES）で誤検知を減らす方式にした。
DEFAULT_THRESHOLD = 0.35
# 何フレーム続けてしきい値を超えたら反応するか。1 フレームは 80ms。
# 本物の発話ではスコアが数フレーム続けて高くなり、物音などの誤検知は 1 フレームだけ跳ね上がることが多い、という想定。
# 実際の続き方は、検知のたびに記録している（会話ログと技術ログの「連続 N フレーム」）。
DEFAULT_PATIENCE_FRAMES = 2
# 検知したときに記録しておく、直前のスコアの数（本物の反応と誤反応の違いを見分ける材料にする）
SCORE_HISTORY_FRAMES = 8


class TriggerGate:
    """スコアがしきい値以上のフレームが patience_frames 回続いたら 1 回だけ反応し、その後しばらくは反応しない。"""

    def __init__(self, threshold: float, cooldown_frames: int, patience_frames: int = 1):
        self.threshold = threshold
        self.cooldown_frames = cooldown_frames
        self.patience_frames = max(1, patience_frames)
        self.run_frames = 0  # 反応したときに、しきい値を超えて続いていたフレーム数
        self._above = 0
        self._remaining = 0

    def update(self, score: float) -> bool:
        """1 フレーム分のスコアを渡し、反応すべきなら True を返す。"""
        if self._remaining > 0:
            self._remaining -= 1
            self._above = 0
            return False
        if score < self.threshold:
            self._above = 0
            return False
        self._above += 1
        if self._above < self.patience_frames:
            return False
        self.run_frames = self._above
        self._above = 0
        self._remaining = self.cooldown_frames
        return True


class WakeWordDetector:
    def __init__(
        self,
        model_path: Path = DEFAULT_MODEL,
        *,
        threshold: float = DEFAULT_THRESHOLD,
        patience_frames: int = DEFAULT_PATIENCE_FRAMES,
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
        self._gate = TriggerGate(threshold, round(cooldown_seconds * SAMPLE_RATE / FRAME_SAMPLES), patience_frames)
        self.last_score = 0.0
        self.last_scores: list[float] = []  # 検知したときの、直前のスコアの並び
        self._recent: deque[float] = deque(maxlen=SCORE_HISTORY_FRAMES)

    def reset(self) -> None:
        """それまでの音声による状態を消す（マイクを開き直したときに呼ぶ）。"""
        self._model.reset()
        self._gate = TriggerGate(self._gate.threshold, self._gate.cooldown_frames, self._gate.patience_frames)
        self.last_score = 0.0
        self._recent.clear()

    def process(self, frame: np.ndarray) -> bool:
        """80ms 分（int16、16kHz、モノラル）の音声を渡し、ウェイクワードを検知したら True を返す。"""
        self.last_score = float(self._model.predict(frame)[self.name])
        self._recent.append(self.last_score)
        detected = self._gate.update(self.last_score)
        if detected:
            self.last_scores = list(self._recent)
            self._model.reset()
            self._recent.clear()
        return detected
