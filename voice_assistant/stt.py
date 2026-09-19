"""音声認識（Vosk の日本語モデル）。

モデルは models/vosk-model-small-ja-0.22/ に置く（tools/setup_pi.sh がダウンロードして展開する）。
"""

import json
import re
from pathlib import Path

import numpy as np

from .config import PROJECT_ROOT

SAMPLE_RATE = 16000
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "vosk-model-small-ja-0.22"

# 半角の英数字・記号以外（ひらがな・カタカナ・漢字など）
_WIDE = r"[^\x00-\x7f]"


def join_japanese_words(text: str) -> str:
    """Vosk の日本語の結果は単語ごとに空白で区切られているので、日本語の文字の前後の空白を取り除く。

    英単語どうしの間の空白は残す（例：「hey jarvis 今日 の 天気」→「hey jarvis今日の天気」）。
    """
    text = " ".join(text.split())
    return re.sub(rf"(?<={_WIDE}) | (?={_WIDE})", "", text)


class VoskRecognizer:
    def __init__(self, model_dir: Path = DEFAULT_MODEL_DIR):
        import vosk

        if not model_dir.is_dir():
            raise FileNotFoundError(f"モデルがありません：{model_dir}（tools/setup_pi.sh を実行してください）")
        vosk.SetLogLevel(-1)  # Vosk（Kaldi）の詳細なログを出さない
        self._vosk = vosk
        self._model = vosk.Model(str(model_dir))

    def transcribe(self, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
        """発話全体（int16、モノラル）を文字にする。聞き取れなかった場合は空文字。"""
        recognizer = self._vosk.KaldiRecognizer(self._model, sample_rate)
        recognizer.AcceptWaveform(np.asarray(samples, dtype="<i2").tobytes())
        result = json.loads(recognizer.FinalResult())
        return join_japanese_words(result.get("text", ""))
