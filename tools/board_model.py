"""伝言板の画面に、何をどう出すかを決める（描画は tools/display.py）。標準ライブラリだけで動く。

画面は、本体が書いた伝言（board.json）、表示の状態（board-view.json）、宛先の設定（board-settings.json）を読む。
ここでは、それらから「宛先のチップ」「伝言のカード」「お知らせ」「凡例」を、描くだけの形にする。
描画から切り離しているのは、PC のテストで確かめられるようにするため。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from voice_assistant.board import (
    MAX_CHARS,
    TIME_FORMAT,
    Board,
    BoardSettings,
    counts_by_recipient,
    page_count,
    page_of,
)

NEW_MINUTES = 10  # 預かってからこの時間は、「新着」として強調する
UNKNOWN_COLOR = "#8b9299"  # 設定にない宛先の色
SELECTED = "selected"
CONFIRMING = "confirming"


@dataclass(frozen=True)
class Chip:
    key: str
    name: str
    color: str
    count: int  # すべてのページの合計


@dataclass(frozen=True)
class Card:
    number: int  # いま出しているページの中の番号（1〜5）。テンキーと声で使う
    name: str  # 宛名
    color: str
    text: str
    time: str  # 「10/8 18:20」
    is_new: bool
    state: str = ""  # "selected"（テンキーで選んだ）か "confirming"（声で消すか確認中）か ""


@dataclass(frozen=True)
class BoardModel:
    chips: tuple[Chip, ...]
    cards: tuple[Card, ...]
    page: int  # 0 から
    pages: int
    hidden: int  # このページに出ていない伝言の件数
    banner: str
    legend: tuple[str, str]
    problem: str | None = None
    danger: bool = False  # 全部消す確認の途中か（お知らせを赤くし、カードをすべて強調する）


def parse_time(text: str) -> datetime | None:
    try:
        return datetime.strptime(text, TIME_FORMAT)
    except (TypeError, ValueError):
        return None


def time_label(created: str) -> str:
    moment = parse_time(created)
    return f"{moment.month}/{moment.day} {moment.hour}:{moment.minute:02d}" if moment else ""


def _active(until: str | None, now: datetime) -> bool:
    """期限（TIME_FORMAT）がまだ来ていないか。期限が無い（None）なら、いつまでも有効。"""
    if until is None:
        return True
    limit = parse_time(until)
    return limit is None or now < limit


def legend_lines(settings: BoardSettings, restorable: int = 0) -> tuple[str, str]:
    """常時出す凡例（宛先のキー、文字数の上限、操作）。目立たせすぎない、小さな文字で出す。"""
    people = "　".join(f"{p.key} {p.name}" for p in (*settings.people, settings.everyone))
    undo = f"　Insert：戻す（{restorable}件）" if restorable else "　Insert：戻す"
    return (f"宛先のキー（押しながら話す）　{people}",
            f"{MAX_CHARS}文字まで　↑↓で選ぶ→Delete：消す{undo}　← →：ページ")


def build_model(board: Board, settings: BoardSettings, view: dict, now: datetime,
                problem: str | None = None) -> BoardModel:
    counts = counts_by_recipient(board)
    people = (*settings.people, settings.everyone)
    chips = tuple(Chip(p.key, p.name, p.color, counts.get(p.key, 0)) for p in people)

    pages = page_count(len(board.messages))
    page = min(max(int(view.get("page") or 0), 0), pages - 1)
    selected = view.get("selected") if _active(view.get("selected_until"), now) else None
    confirming = view.get("confirming")
    clearing_all = bool(view.get("confirming_all")) or (
        view.get("clear_all_until") is not None and _active(view.get("clear_all_until"), now))
    cards = []
    for number, message in enumerate(page_of(board, page), start=1):
        person = settings.person(message.to)
        created = parse_time(message.created)
        is_new = created is not None and timedelta(0) <= now - created <= timedelta(minutes=NEW_MINUTES)
        state = (CONFIRMING if clearing_all or confirming == message.id
                 else SELECTED if selected == message.id else "")
        cards.append(Card(number, person.name if person else f"{message.to}番", person.color if person else UNKNOWN_COLOR,
                          message.text, time_label(message.created), is_new, state))

    banner = view.get("banner") or ""
    if banner and not _active(view.get("banner_until"), now):
        banner = ""
    return BoardModel(chips, tuple(cards), page, pages, len(board.messages) - len(cards), banner,
                      legend_lines(settings, int(view.get("restorable") or 0)), problem, danger=clearing_all and bool(banner))


def page_note(model: BoardModel) -> str:
    """ページ送りの案内（2 ページ以上あるときだけ）。"""
    if model.pages <= 1:
        return ""
    return f"{model.page + 1}/{model.pages}ページ　← → で切り替え　（ほか {model.hidden} 件）"


def _luminance(color: str) -> float:
    """相対輝度（WCAG の定義）。0 が黒、1 が白。"""
    def linear(channel: int) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(int(color[i:i + 2], 16)) for i in (1, 3, 5))
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def text_color_for(background: str, dark: str = "#101418", light: str = "#ffffff") -> str:
    """背景色の上に置く文字の色。コントラスト比が大きいほう（暗い文字か、白い文字か）を選ぶ。"""
    luminance = _luminance(background)
    contrast_light = 1.05 / (luminance + 0.05)
    contrast_dark = (luminance + 0.05) / (_luminance(dark) + 0.05)
    return dark if contrast_dark >= contrast_light else light


def dim(color: str, ratio: float = 0.55) -> str:
    """色を暗くする（点滅のもう一方の色、選んでいないカードの色帯などに使う）。"""
    red, green, blue = (int(int(color[i:i + 2], 16) * ratio) for i in (1, 3, 5))
    return f"#{red:02x}{green:02x}{blue:02x}"

