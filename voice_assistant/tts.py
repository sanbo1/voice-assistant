"""音声合成（Open JTalk のコマンドを呼ぶ）。

apt の open-jtalk・open-jtalk-mecab-naist-jdic・hts-voice-nitech-jp-atr503-m001 を使う（tools/apt-packages.txt）。
合成した WAV は標準出力で受け取り、ファイルには書かない（SD カードへの書き込みを避ける）。
"""

import io
import re
import subprocess
from pathlib import Path

import numpy as np

from .levels import normalize_peak
from .wav import read_wav

DEFAULT_DICTIONARY = Path("/var/lib/mecab/dic/open-jtalk/naist-jdic")
DEFAULT_VOICE = Path("/usr/share/hts-voice/nitech-jp-atr503-m001/nitech_jp_atr503_m001.htsvoice")
# 合成した音声の最大振幅（dBFS）。そのままでは小さい（実効値 -22〜-24 dBFS）ため、ここまで持ち上げる
OUTPUT_PEAK_DBFS = -1.0
# 話す速さ。1.0 はゆっくりに感じられ、1.2 が自然に近かった（2026-09-19）
DEFAULT_SPEED = 1.2

# 辞書が読みを誤る言葉と、正しい読み（見つけたら追加する）
READINGS = {
    "お手数": "おてすう",  # 「おてかず」と読まれた（2026-09-19）
}

_URL = re.compile(r"https?://\S+")
# Markdown などの装飾に使われる記号（読み上げると不自然になるもの）
_DECORATION = re.compile(r"[*#`>|_~]+")
_BULLET = re.compile(r"^\s*(?:[-・•]|\d+\.)\s+", re.MULTILINE)
# 絵文字と、その見た目を変える記号
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def apply_readings(text: str, readings: dict[str, str] = READINGS) -> str:
    """辞書が読みを誤る言葉を、正しい読みのかなに置き換える。"""
    for word, reading in readings.items():
        text = text.replace(word, reading)
    return text


def to_speakable(text: str) -> str:
    """AI の返答を読み上げ向けに整える。記号・URL・絵文字を除き、改行は句点の区切りにし、誤読する言葉を直す。"""
    text = _URL.sub("", text)
    text = _BULLET.sub("", text)
    text = _DECORATION.sub("", text)
    text = _EMOJI.sub("", text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    sentences = [line if line.endswith(("。", "！", "？", "!", "?")) else line + "。" for line in lines if line]
    return apply_readings("".join(sentences))


class OpenJTalk:
    def __init__(
        self,
        *,
        dictionary: Path = DEFAULT_DICTIONARY,
        voice: Path = DEFAULT_VOICE,
        speed: float = DEFAULT_SPEED,
        postfilter: float = 0.0,
        all_pass: float | None = None,
        command: str = "open_jtalk",
        timeout: float = 30.0,
    ):
        """postfilter は -b（0〜1）、all_pass は -a（None なら声のデータの既定値）。

        postfilter を上げてもこもりは改善せず、雑音が増えて音量も下がったため、既定は 0.0（2026-09-19）。
        """
        for path in (dictionary, voice):
            if not path.exists():
                raise FileNotFoundError(f"{path} がありません（tools/setup_pi.sh で apt パッケージを入れてください）")
        self._args = [command, "-x", str(dictionary), "-m", str(voice), "-r", str(speed), "-b", str(postfilter)]
        if all_pass is not None:
            self._args += ["-a", str(all_pass)]
        self._args += ["-ow", "/dev/stdout"]
        self._timeout = timeout

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """文章を読み上げた音声を (int16 の配列, サンプリング周波数) で返す。音量は OUTPUT_PEAK_DBFS にそろえる。"""
        result = subprocess.run(
            self._args, input=text.encode("utf-8"), capture_output=True, timeout=self._timeout, check=False
        )
        if result.returncode != 0 or not result.stdout:
            message = result.stderr.decode("utf-8", errors="replace").strip()[:200]
            raise RuntimeError(f"open_jtalk が失敗しました（終了コード {result.returncode}）：{message}")
        samples, sample_rate = read_wav(io.BytesIO(result.stdout))
        return normalize_peak(samples, OUTPUT_PEAK_DBFS), sample_rate
