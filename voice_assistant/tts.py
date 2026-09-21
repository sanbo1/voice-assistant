"""音声合成（Open JTalk のコマンドを呼ぶ）。

apt の open-jtalk・open-jtalk-mecab-naist-jdic・hts-voice-nitech-jp-atr503-m001 を使う（tools/apt-packages.txt）。
合成した WAV は標準出力で受け取り、ファイルには書かない（SD カードへの書き込みを避ける）。
"""

import io
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

import numpy as np

from .config import PROJECT_ROOT
from .levels import normalize_peak
from .wav import read_wav

DEFAULT_DICTIONARY = Path("/var/lib/mecab/dic/open-jtalk/naist-jdic")
DEFAULT_VOICE = Path("/usr/share/hts-voice/nitech-jp-atr503-m001/nitech_jp_atr503_m001.htsvoice")
# 合成した音声の最大振幅（dBFS）。そのままでは小さい（実効値 -22〜-24 dBFS）ため、ここまで持ち上げる
OUTPUT_PEAK_DBFS = -1.0
# 話す速さ。1.0 はゆっくりに感じられ、1.2 が自然に近かった（2026-09-19）
DEFAULT_SPEED = 1.2

# 辞書が読みを誤る言葉と、正しい読みの表（見つけたらこのファイルに 1 行ずつ追加する）
READINGS_FILE = PROJECT_ROOT / "config" / "readings.tsv"

# 区切りのない部分がこの文字数を超えると、Open JTalk が極端に長く合成する（2026-09-21 に Pi で実測）。
# 例：「戦う時はゴムの実の能力で体を変幻自在に伸ばして動きます。」は 13.94 秒。読点を 1 つ入れると 5.10 秒。
# 値は、過去の返答 60 件を 14・16・18・20・22 で合成し直して決めた。20 なら、間延びしていた 7 件が
# いちばん細かく区切った場合と同じところまで直り、余計な区切り（もともと正常な回に入るもの）は
# 16 のときの 25 件から 16 件に減る。22 まで上げると間延びが直りきらない回が出る。
MAX_RUN_CHARS = 20
# 合成に渡すときの区切り。空白は読点と同じ働きをする（休止の長さも同じ）
BREAK_MARKER = " "
# この助詞のあとは文節の切れ目になりやすい
_BREAK_PARTICLES = "はがをにでともて"
# 助詞の次がこれ（漢字・カタカナ）なら、新しい語の始まりとみなす。
# ひらがなが続くときは語の途中のおそれがあるので切らない（「はなし」を「は／なし」にしないため）
_WORD_START = re.compile(r"[一-鿿゠-ヿ々ー]")
# すでに区切りとして働いている文字
_EXISTING_BREAK = re.compile(r"[、。！？!?\s　]")

_URL = re.compile(r"https?://\S+")
# Markdown などの装飾に使われる記号（読み上げると不自然になるもの）
_DECORATION = re.compile(r"[*#`>|_~]+")
_BULLET = re.compile(r"^\s*(?:[-・•]|\d+\.)\s+", re.MULTILINE)
# 絵文字と、その見た目を変える記号
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️‍]")


def load_readings(path: Path = READINGS_FILE) -> dict[str, str]:
    """置き換え表（1 行に「言葉<タブ>読み」、# 以降はコメント）を読む。ファイルがなければ空の表。"""
    if not path.exists():
        return {}
    readings: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        fields = [field.strip() for field in line.split("\t") if field.strip()]
        if len(fields) != 2:
            raise ValueError(f"{path.name} の {number} 行目：「言葉<タブ>読み」の形になっていません：{line}")
        readings[fields[0]] = fields[1]
    return readings


def apply_readings(text: str, readings: Mapping[str, str]) -> str:
    """辞書が読みを誤る言葉を、正しい読みのかなに置き換える。長い言葉から先に置き換える。"""
    for word in sorted(readings, key=len, reverse=True):
        text = text.replace(word, readings[word])
    return text


def _break_points(run: str, limit: int) -> list[int]:
    """区切りを入れる位置（その文字の「あと」で切る）を選ぶ。安全な切れ目がなければ切らない。"""
    candidates = [i for i in range(len(run) - 1)
                  if run[i] in _BREAK_PARTICLES and _WORD_START.match(run[i + 1])]
    points, start = [], 0
    while len(run) - start > limit:
        nearby = [i for i in candidates if start < i + 1 <= start + limit]
        # 範囲内に切れ目がなければ、その先のいちばん近い切れ目を使う（切らないよりは短くなる）
        chosen = nearby[-1] if nearby else next((i for i in candidates if i + 1 > start + limit), None)
        if chosen is None:
            return points
        points.append(chosen)
        start = chosen + 1
    return points


def _split_run(run: str, limit: int, marker: str) -> str:
    pieces, prev = [], 0
    for point in _break_points(run, limit):
        pieces.append(run[prev:point + 1])
        prev = point + 1
    pieces.append(run[prev:])
    return marker.join(pieces)


def split_long_runs(text: str, limit: int = MAX_RUN_CHARS, marker: str = BREAK_MARKER) -> str:
    """句読点のない長い部分に区切りを入れる（Open JTalk が極端に長く合成するのを防ぐ）。

    もともと間延びしない文章にも区切りが入ることがあり、わずかに不自然になるが、
    間延びよりはよいと判断した（2026-09-21 に聞き比べて決定）。
    """
    out: list[str] = []
    run: list[str] = []
    for char in text:
        if _EXISTING_BREAK.match(char):
            out.append(_split_run("".join(run), limit, marker))
            out.append(char)
            run = []
        else:
            run.append(char)
    out.append(_split_run("".join(run), limit, marker))
    return "".join(out)


def to_speakable(text: str, readings: Mapping[str, str] | None = None) -> str:
    """AI の返答を読み上げ向けに整える。記号・URL・絵文字を除き、改行は句点の区切りにし、誤読する言葉を直す。

    最後に、句読点のない長い部分へ区切りを入れる（間延び対策。split_long_runs を参照）。
    readings を省略すると、置き換え表のファイルをそのつど読む（ファイルを直せば、再起動なしで反映される）。
    """
    text = _URL.sub("", text)
    text = _BULLET.sub("", text)
    text = _DECORATION.sub("", text)
    text = _EMOJI.sub("", text)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    sentences = [line if line.endswith(("。", "！", "？", "!", "?")) else line + "。" for line in lines if line]
    spoken = apply_readings("".join(sentences), load_readings() if readings is None else readings)
    return split_long_runs(spoken)


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
