"""伝言板のデータ（伝言の保存、宛先の設定、画面に渡す表示の状態）。標準ライブラリだけで動く。

本体が書き、画面（tools/display.py、システムの python3）が読む。画面は書かない（書き込み元を 1 つにして競合を避ける）。

- 伝言：Pi 上の board.json（家族の会話なので、リポジトリには入れない）。20 件まで、1 件 60 文字まで。
  消した伝言は、24 時間は元に戻せる（board.json の deleted に残す）。
- 宛先の設定：Pi 上の board-settings.json（名前・色・声での別の言い方。雛形は config/board-settings.example.json）。
- 表示の状態（ページ、選んでいる伝言、お知らせ）：$XDG_RUNTIME_DIR の下（メモリ上）。再起動で消えてよい。

仕様は docs/design.md の「伝言板」を参照。
"""

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path

# config.py は外部のライブラリ（dotenv）を読み込むので使わない（画面アプリは、システムの python3 で動く）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = PROJECT_ROOT / "board.json"
SETTINGS_PATH = PROJECT_ROOT / "board-settings.json"
# 会話ログの「返答（伝言板）」の括弧の中身。AI の返答と区別し、利用回数に数えないために使う
LOG_LABEL = "伝言板"

MAX_CHARS = 60  # 1 件の長さの上限
MAX_MESSAGES = 20  # 保存できる件数の上限
PER_PAGE = 5  # 画面に出す件数（1 ページ）
UNDO_HOURS = 24  # 消した伝言を、元に戻せる時間
EVERYONE_KEY = "0"  # 宛先なし（みんな宛）のキー
TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"

TOO_LONG = f"{MAX_CHARS}文字までです"
EMPTY = "伝言の内容を言ってください"
FULL = "伝言がいっぱいです"
NOTHING_TO_RESTORE = "戻せる伝言はありません"
NOTHING_TO_DELETE = "消す伝言はありません"
FULL_FOR_BATCH = "いっぱいで、まとめて戻せません"
_COLOR = re.compile(r"#[0-9A-Fa-f]{6}")


# ---------- 宛先の設定 ----------


@dataclass(frozen=True)
class Person:
    key: str  # 押すキー（上段の数字。"1"〜"9"。"0" は、みんな宛）
    name: str  # 画面に出す名前
    color: str  # 画面の色（#RRGGBB）
    aliases: tuple[str, ...] = ()  # 声で宛先を言うときの、別の言い方

    @property
    def names(self) -> tuple[str, ...]:
        return (self.name, *self.aliases)


@dataclass(frozen=True)
class BoardSettings:
    people: tuple[Person, ...] = ()  # 宛先の人（キー 1〜9）。人数は、増やせる
    everyone: Person = Person(EVERYONE_KEY, "みんな", "#C0C4C8")

    def person(self, key: str) -> Person | None:
        """キーに対応する宛先。みんな宛のキーも含む。無ければ None。"""
        if key == self.everyone.key:
            return self.everyone
        return next((person for person in self.people if person.key == key), None)

    def find_by_name(self, text: str) -> Person | None:
        """文の中に出てくる宛先の名前（別の言い方も含む）。長い名前を優先する。"""
        candidates = [(name, person) for person in self.people for name in person.names if name]
        for name, person in sorted(candidates, key=lambda item: -len(item[0])):
            if name in text:
                return person
        return None


def _person(raw: object, where: str, *, everyone: bool = False) -> Person:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{where}：形が違います")
    key = raw.get("key", EVERYONE_KEY if everyone else None)
    allowed = EVERYONE_KEY if everyone else "123456789"
    if not isinstance(key, str) or len(key) != 1 or key not in allowed:
        raise ValueError(f"{where}：key は {'0' if everyone else '1〜9 の数字 1 文字'} で書いてください（{key!r}）")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{where}：name を書いてください")
    color = raw.get("color")
    if not isinstance(color, str) or not _COLOR.fullmatch(color):
        raise ValueError(f"{where}：color は #RRGGBB（例：#4C9AFF）で書いてください（{color!r}）")
    aliases = raw.get("aliases", [])
    if not isinstance(aliases, list) or not all(isinstance(a, str) and a.strip() for a in aliases):
        raise ValueError(f"{where}：aliases は、文字列の一覧で書いてください")
    return Person(key, name.strip(), color, tuple(a.strip() for a in aliases))


def parse_settings(data: object) -> BoardSettings:
    """JSON を読んだ内容から宛先の設定を作る。形が違えば、直す場所が分かる ValueError にする。"""
    if not isinstance(data, Mapping) or not isinstance(data.get("people", []), list):
        raise ValueError("people（宛先の一覧）の形が違います")
    people = tuple(_person(raw, f"people の {number} 番目") for number, raw in enumerate(data.get("people", []), start=1))
    keys = [person.key for person in people]
    if len(set(keys)) != len(keys):
        raise ValueError("people の key が重なっています（同じキーを 2 人に付けられません）")
    names = [name for person in people for name in person.names]
    if len(set(names)) != len(names):
        raise ValueError("people の name や aliases に、同じ言葉が重なっています")
    everyone = _person(data["everyone"], "everyone", everyone=True) if "everyone" in data else BoardSettings().everyone
    return BoardSettings(people, everyone)


def load_settings(path: Path = SETTINGS_PATH) -> BoardSettings:
    """宛先の設定を読む。ファイルが無ければ、みんな宛だけの既定。読めない・形が違うときは OSError か ValueError。"""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return BoardSettings()
    try:
        return parse_settings(json.loads(text))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON として読めません（{e.lineno} 行目付近）") from None


# ---------- 伝言 ----------


@dataclass(frozen=True)
class Message:
    id: int  # 通し番号（消しても再利用しない）
    to: str  # 宛先のキー
    text: str
    created: str  # TIME_FORMAT
    deleted_at: str | None = None  # 消した時刻（消した伝言だけ）
    batch: str | None = None  # 全部まとめて消したときの印（同じ印の伝言は、まとめて元に戻す）

    def as_json(self) -> dict:
        data = {"id": self.id, "to": self.to, "text": self.text, "created": self.created}
        if self.deleted_at:
            data["deleted_at"] = self.deleted_at
        if self.batch:
            data["batch"] = self.batch
        return data


@dataclass(frozen=True)
class Board:
    messages: tuple[Message, ...] = ()  # 新しい順
    deleted: tuple[Message, ...] = ()  # 消した順（新しく消したものが先）
    next_id: int = 1


def _timestamp(now: datetime) -> str:
    return now.strftime(TIME_FORMAT)


def _newest_first(messages) -> tuple[Message, ...]:
    return tuple(sorted(messages, key=lambda m: (m.created, m.id), reverse=True))


def clean_text(text: str) -> str:
    """伝言の文を整える（前後の空白、途中の改行と連続した空白を、1 つの空白にする）。"""
    return " ".join(text.split())


def add_message(board: Board, to: str, text: str, now: datetime) -> tuple[Board, str | None]:
    """伝言を足す。足せなければ（Board はそのまま、理由）を返す。"""
    text = clean_text(text)
    if not text:
        return board, EMPTY
    if len(text) > MAX_CHARS:
        return board, TOO_LONG
    if len(board.messages) >= MAX_MESSAGES:
        return board, FULL
    message = Message(board.next_id, to, text, _timestamp(now))
    return replace(board, messages=_newest_first((*board.messages, message)), next_id=board.next_id + 1), None


def delete_message(board: Board, message_id: int, now: datetime) -> Board:
    """伝言を消す（24 時間は元に戻せるよう、deleted に残す）。無い番号なら、そのまま。"""
    target = next((m for m in board.messages if m.id == message_id), None)
    if target is None:
        return board
    gone = replace(target, deleted_at=_timestamp(now))
    return replace(board, messages=tuple(m for m in board.messages if m.id != message_id),
                   deleted=(gone, *board.deleted))


def delete_all(board: Board, now: datetime) -> Board:
    """伝言を全部消す（まとめて元に戻せるよう、同じ印を付けて deleted に残す）。1 件も無ければ、そのまま。"""
    if not board.messages:
        return board
    stamp = _timestamp(now)
    gone = tuple(replace(m, deleted_at=stamp, batch=stamp) for m in board.messages)
    return replace(board, messages=(), deleted=(*gone, *board.deleted))


def restore_last(board: Board, now: datetime) -> tuple[Board, tuple[Message, ...], str | None]:
    """最後に消した伝言を戻す（全部まとめて消した分は、まとめて戻す）。

    戻せなければ（Board はそのまま、空、理由）を返す。まとめて戻すとき上限を超えるなら、1 件も戻さない。
    """
    board = purge(board, now)
    if not board.deleted:
        return board, (), NOTHING_TO_RESTORE
    last = board.deleted[0]
    group = [m for m in board.deleted if m.batch == last.batch] if last.batch else [last]
    if len(board.messages) + len(group) > MAX_MESSAGES:
        return board, (), FULL_FOR_BATCH if len(group) > 1 else FULL
    restored = tuple(replace(m, deleted_at=None, batch=None) for m in group)
    rest = tuple(m for m in board.deleted if m not in group)
    return replace(board, messages=_newest_first((*board.messages, *restored)), deleted=rest), restored, None


def purge(board: Board, now: datetime) -> Board:
    """24 時間より前に消した伝言を、完全に消す。"""
    limit = _timestamp(now - timedelta(hours=UNDO_HOURS))
    kept = tuple(m for m in board.deleted if (m.deleted_at or "") >= limit)
    return board if len(kept) == len(board.deleted) else replace(board, deleted=kept)


def page_count(total: int, per_page: int = PER_PAGE) -> int:
    """ページ数（伝言が 0 件でも 1 ページ）。"""
    return max(1, -(-total // per_page))


def page_of(board: Board, page: int, per_page: int = PER_PAGE) -> tuple[Message, ...]:
    """そのページ（0 から数える）の伝言。範囲外なら、最後のページ。"""
    page = min(max(page, 0), page_count(len(board.messages), per_page) - 1)
    return board.messages[page * per_page:(page + 1) * per_page]


def counts_by_recipient(board: Board) -> dict[str, int]:
    """宛先ごとの件数（すべてのページの合計）。"""
    counts: dict[str, int] = {}
    for message in board.messages:
        counts[message.to] = counts.get(message.to, 0) + 1
    return counts


# ---------- 保存 ----------


def parse_board(data: object) -> Board:
    if not isinstance(data, Mapping):
        raise ValueError("形が違います")

    def messages(items) -> tuple[Message, ...]:
        found = []
        for item in items or []:
            found.append(Message(int(item["id"]), str(item["to"]), str(item["text"]), str(item["created"]),
                                 item.get("deleted_at"), item.get("batch")))
        return tuple(found)

    try:
        live = _newest_first(messages(data.get("messages")))
        gone = tuple(sorted(messages(data.get("deleted")), key=lambda m: m.deleted_at or "", reverse=True))
        highest = max([m.id for m in (*live, *gone)] or [0])
        return Board(live, gone, max(int(data.get("next_id", 1)), highest + 1))
    except (KeyError, TypeError, ValueError):
        raise ValueError("伝言の形が違います") from None


def load_board(path: Path = DEFAULT_PATH) -> Board:
    """伝言を読む。ファイルが無ければ空。読めない・形が違うときは OSError か ValueError。"""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return Board()
    try:
        return parse_board(json.loads(text))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON として読めません（{e.lineno} 行目付近）") from None


def save_board(path: Path, board: Board) -> None:
    """伝言を保存する。画面が書きかけを読まないよう、別名で書いてから置き換える。"""
    payload = {"version": 1, "next_id": board.next_id,
               "messages": [m.as_json() for m in board.messages],
               "deleted": [m.as_json() for m in board.deleted]}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(temporary, path)


# ---------- 画面に渡す、表示の状態 ----------


@dataclass
class View:
    """画面の見え方。メモリ上のファイルに書き、画面が読む。"""

    page: int = 0  # いま出しているページ（0 から）
    selected: int | None = None  # 選んでいる伝言の id（テンキーで選んだもの。Delete で消せる）
    selected_until: str | None = None
    confirming: int | None = None  # 声で「消してよいですか」と確認中の伝言の id
    confirming_all: bool = False  # 声で「全部消してよいですか」と確認中か
    clear_all_until: str | None = None  # Ctrl+Delete のあと、もう一度 Delete を待つ期限（全部消す確認）
    banner: str = ""  # 画面に出すお知らせ（「消しました（Insert で元に戻せます）」など）
    banner_until: str | None = None
    restorable: int = 0  # 元に戻せる件数
    updated: str = field(default="")

    def as_json(self) -> dict:
        return {"page": self.page, "selected": self.selected, "selected_until": self.selected_until,
                "confirming": self.confirming, "confirming_all": self.confirming_all,
                "clear_all_until": self.clear_all_until, "banner": self.banner, "banner_until": self.banner_until,
                "restorable": self.restorable, "updated": self.updated}


def default_view_path() -> Path | None:
    """表示の状態の置き場所。$XDG_RUNTIME_DIR が無ければ None（書かない）。"""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return Path(runtime) / "voice-assistant" / "board-view.json" if runtime else None


def write_view(path: Path | None, view: View) -> None:
    """表示の状態を書く。**失敗しても例外を投げない**（画面のための情報で、本体の動作には要らない）。"""
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(view.as_json(), ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        pass


def read_view(path: Path | None) -> dict:
    """表示の状態を読む（画面用）。無い・壊れているときは、既定（先頭のページ、お知らせなし）。"""
    if path is None:
        return View().as_json()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else View().as_json()
    except (OSError, ValueError):
        return View().as_json()
