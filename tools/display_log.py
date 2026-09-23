"""会話ログを読んで、画面に出す形にまとめる（表示アプリ用。音声アシスタント本体とは別プロセス）。

本体の venv ではなくシステムの python3 で動かすため、voice_assistant のモジュールは使わない。
画面の描画は display.py にあり、ここには画面に依存しない処理だけを置く（PC でテストできるように）。
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_LOG = Path.home() / "voice-assistant" / "logs" / "conversation.log"
# 読み込む行数の上限（過去のやり取りと当日の集計に足りればよい）
MAX_LINES = 2000
# 画面に出す過去のやり取りの数
PAST_LIMIT = 4

# 「09/23 14:30:00  聞き取り（確信度 0.92）：今日は何の日」
_LINE = re.compile(r"^(\d{2}/\d{2} \d{2}:\d{2}:\d{2})\s+([^：]+)：(.*)$")
_CONFIDENCE = re.compile(r"確信度 ([0-9.]+)")
_MODEL = re.compile(r"^返答（(.+)）$")
_SUPPRESSED = re.compile(r"見送り (\d+) 回")


@dataclass(frozen=True)
class Entry:
    time: str  # 「09/23 14:30:00」
    kind: str  # heard / reply / status / error / other
    body: str
    confidence: float | None = None
    model: str | None = None

    @property
    def clock(self) -> str:
        """「14:30」の形（画面に出す用）。"""
        return self.time[6:11]


def parse_line(line: str) -> Entry | None:
    """会話ログの 1 行を読む。形が違えば None。"""
    matched = _LINE.match(line.rstrip("\n"))
    if not matched:
        return None
    time, label, body = matched.groups()
    if label.startswith("聞き取り"):
        found = _CONFIDENCE.search(label)
        return Entry(time, "heard", body, float(found.group(1)) if found else None)
    if label.startswith("返答"):
        model = _MODEL.match(label)
        return Entry(time, "reply", body, model=model.group(1) if model else None)
    if label == "状態":
        return Entry(time, "status", body)
    if label == "エラー":
        return Entry(time, "error", body)
    return Entry(time, "other", body)


def read_entries(path: Path = DEFAULT_LOG, max_lines: int = MAX_LINES) -> list[Entry]:
    """会話ログの末尾を読む。ファイルが無ければ空。"""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [entry for line in lines[-max_lines:] if (entry := parse_line(line)) is not None]


def exchanges(entries: list[Entry]) -> list[tuple[Entry, Entry | None]]:
    """「聞き取り」と、その直後の「返答」の組。返答が無い（雑音として弾いた）回は None。"""
    out: list[tuple[Entry, Entry | None]] = []
    for i, entry in enumerate(entries):
        if entry.kind != "heard":
            continue
        reply = next((e for e in entries[i + 1:i + 4] if e.kind == "reply"), None)
        # 次の「聞き取り」より前にある返答だけを組にする
        following_heard = next((e for e in entries[i + 1:i + 4] if e.kind == "heard"), None)
        if reply is not None and following_heard is not None and following_heard.time < reply.time:
            reply = None
        out.append((entry, reply))
    return out


def latest_exchange(entries: list[Entry]) -> tuple[Entry, Entry | None] | None:
    """いちばん新しいやり取り。まだ無ければ None。"""
    found = exchanges(entries)
    return found[-1] if found else None


def past_exchanges(entries: list[Entry], limit: int = PAST_LIMIT) -> list[tuple[Entry, Entry]]:
    """直近より前の、返答まで揃ったやり取り（新しい順）。"""
    found = [(heard, reply) for heard, reply in exchanges(entries)[:-1] if reply is not None]
    return list(reversed(found))[:limit]


def default_state_path() -> Path | None:
    """本体が書く状態ファイル。$XDG_RUNTIME_DIR が無ければ None。"""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return Path(runtime) / "voice-assistant" / "state.json" if runtime else None


def _process_alive(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


def read_state(path: Path | None = None, is_alive=_process_alive) -> dict | None:
    """本体が書いた状態を読む。無い・壊れている・本体が動いていない場合は None。

    None のときは会話ログから推定した状態を使う（画面は本体が止まっていても動き続ける）。
    """
    path = default_state_path() if path is None else path
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("state") not in STATE_LABELS:
        return None
    pid = data.get("pid")
    if isinstance(pid, int) and not is_alive(pid):
        return None  # 本体が終わっている。古い状態を出さない
    return data


def history_alive(state: dict | None, now: datetime | None = None) -> bool:
    """会話履歴がまだ生きている（前の話の続きを話せる）か。"""
    if not state or "history_alive_until" not in state:
        return False
    try:
        until = datetime.fromisoformat(state["history_alive_until"])
    except (TypeError, ValueError):
        return False
    return (now or datetime.now()) < until


def confidence_mark(confidence: float | None) -> tuple[str, str]:
    """確信度を、家族にも分かる記号と文言にする。数値は画面に出さない。"""
    if confidence is None:
        return "", ""
    if confidence >= 0.85:
        return "○", "よく聞こえました"
    if confidence >= 0.6:
        return "△", "少し聞き取りにくいです"
    return "×", "うまく聞き取れませんでした（近くで話してみてください）"


# 会話ログの「状態」から、いまの様子を決める。前にあるものから順に当てはめる
_STATES = (
    ("ウェイクワードを待っています", "waiting"),
    ("聞き取り中", "listening"),
    ("続けて話せます", "followup"),
    ("起動しました", "starting"),
    ("起動時の出力先", "starting"),
    ("ウェイクワードは空振り", "waiting"),
    ("雑音とみなして", "waiting"),
    ("聞き取りを終了しました", "waiting"),
)

STATE_LABELS = {
    "starting": ("● 準備中です", "もう少しお待ちください"),
    "waiting": ("● 待ち受け中", "「ヘイ、ジャービス」と話しかけてください"),
    "listening": ("● 聞き取り中", "話してください"),
    "thinking": ("● 考えています…", ""),
    "speaking": ("● 話しています", ""),
    "followup": ("● 続けてどうぞ", "そのまま話しかけられます"),
    "error": ("● エラーが起きました", ""),
    "unknown": ("● 状態が分かりません", "音声アシスタントが動いていないかもしれません"),
}


def current_state(entries: list[Entry], state: dict | None = None) -> str:
    """いまの様子。本体が書いた状態があればそれを使い、無ければ会話ログから推定する。

    推定はログに書かれた時点でしか変わらないため、実際より遅れることがある。
    """
    if state:
        return state["state"]
    if not entries:
        return "unknown"
    last = entries[-1]
    if last.kind == "error":
        return "error"
    if last.kind == "heard":
        return "thinking"
    if last.kind == "reply":
        return "speaking"
    if last.kind == "status":
        for text, name in _STATES:
            if last.body.startswith(text):
                return name
    return "unknown"


@dataclass(frozen=True)
class Statistics:
    ai_calls: int = 0  # AI に送って返答を得た回数
    false_wakes: int = 0  # ウェイクワードの空振り
    suppressed: int = 0  # ウェイクワードの見送りと、雑音として弾いた回数の合計
    slow_responses: int = 0
    errors: int = 0
    fallback_model: str | None = None  # 直近の返答が予備のモデルだった場合だけ入る


def statistics(entries: list[Entry]) -> Statistics:
    """会話ログ 1 ファイル分（＝その日）の集計。"""
    replies = [e for e in entries if e.kind == "reply"]
    status = [e.body for e in entries if e.kind == "status"]
    suppressed = sum(int(m.group(1)) for body in status if (m := _SUPPRESSED.search(body)))
    suppressed += sum(1 for body in status if body.startswith("雑音とみなして"))
    return Statistics(
        ai_calls=len(replies),
        false_wakes=sum(1 for body in status if body.startswith("ウェイクワードは空振り")),
        suppressed=suppressed,
        slow_responses=sum(1 for body in status if body.startswith("応答に時間がかかりました")),
        errors=sum(1 for e in entries if e.kind == "error"),
        fallback_model=replies[-1].model if replies else None,
    )
