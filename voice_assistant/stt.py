"""音声認識（Vosk の日本語モデル）。

モデルは models/ に置く（tools/setup_pi.sh がダウンロードして展開する）。
どのモデルを使うかは .env の VOSK_MODEL_DIR で変えられる（config.SttConfig）。
"""

import json
import re
from pathlib import Path

import numpy as np

from .config import PROJECT_ROOT, SttConfig

SAMPLE_RATE = 16000
MODELS_DIR = PROJECT_ROOT / "models"
DEFAULT_MODEL_DIR = MODELS_DIR / SttConfig.model_dir


def model_dir_from_config(config: SttConfig) -> Path:
    """.env の設定から、使うモデルのフォルダを決める。"""
    return MODELS_DIR / config.model_dir

# 半角の英数字・記号以外（ひらがな・カタカナ・漢字など）
_WIDE = r"[^\x00-\x7f]"


def join_japanese_words(text: str) -> str:
    """Vosk の日本語の結果は単語ごとに空白で区切られているので、日本語の文字の前後の空白を取り除く。

    英単語どうしの間の空白は残す（例：「hey jarvis 今日 の 天気」→「hey jarvis今日の天気」）。
    """
    text = " ".join(text.split())
    return re.sub(rf"(?<={_WIDE}) | (?={_WIDE})", "", text)


class RecognitionStream:
    """話しながら少しずつ音声を渡し、話し終わったら結果を受け取る（話し終わり後の待ち時間を短くするため）。

    Vosk は発話の途中の間で結果を区切ることがあるため、区切られた結果もすべて集めてつなげる。
    """

    def __init__(self, recognizer):
        self._recognizer = recognizer
        self._texts: list[str] = []

    def accept(self, frame: np.ndarray) -> None:
        if self._recognizer.AcceptWaveform(np.asarray(frame, dtype="<i2").tobytes()):
            self._texts.append(json.loads(self._recognizer.Result()).get("text", ""))

    def reset(self) -> None:
        """それまでに渡した音声を捨てる（短すぎる声として取り消されたとき）。"""
        self._recognizer.Reset()
        self._texts.clear()

    def finish(self) -> str:
        """結果を返す。聞き取れなかった場合は空文字。"""
        self._texts.append(json.loads(self._recognizer.FinalResult()).get("text", ""))
        text = join_japanese_words(" ".join(self._texts))
        self._texts.clear()
        return text


class VoskRecognizer:
    # 発話全体をまとめて認識するときに、少しずつ渡す長さ（RecognitionStream と同じ処理にするため）
    _CHUNK_SAMPLES = 4000

    def __init__(self, model_dir: Path = DEFAULT_MODEL_DIR):
        import vosk

        if not model_dir.is_dir():
            raise FileNotFoundError(f"モデルがありません：{model_dir}（tools/setup_pi.sh を実行してください）")
        vosk.SetLogLevel(-1)  # Vosk（Kaldi）の詳細なログを出さない
        self._vosk = vosk
        self._model = vosk.Model(str(model_dir))

    def start(self, sample_rate: int = SAMPLE_RATE) -> RecognitionStream:
        """話しながら認識するための RecognitionStream を作る。"""
        return RecognitionStream(self._vosk.KaldiRecognizer(self._model, sample_rate))

    def transcribe(self, samples: np.ndarray, sample_rate: int = SAMPLE_RATE) -> str:
        """発話全体（int16、モノラル）を文字にする。聞き取れなかった場合は空文字。"""
        stream = self.start(sample_rate)
        for i in range(0, len(samples), self._CHUNK_SAMPLES):
            stream.accept(samples[i:i + self._CHUNK_SAMPLES])
        return stream.finish()
