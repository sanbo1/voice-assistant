"""ごみ収集の予定表から、今日のごみを答える（AI を使わず、コードで判定する）。

予定表は Pi 上の garbage.json（リポジトリには入れない。雛形は config/garbage.example.json）。
質問のたびに読み直すので、ファイルを直せば再起動なしで反映される。

答えるのは「今日のごみ」「ごみの日」などの定型の質問だけ。「明日」「水曜日」「燃やさないごみはいつ」
など日付や種類を指す質問は、日付を取り違えないよう答えずに None を返す（AI に任せる）。

予定表が無い・読めないときは、定型の質問に限り、その旨を答える（AI には送らない。AI は家の収集日を知らず、
的外れな返答になるため）。定型でないごみの質問（「ごみの分別は？」など）は、これまでどおり AI に任せる。
"""

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .config import PROJECT_ROOT

DEFAULT_PATH = PROJECT_ROOT / "garbage.json"
# 会話ログの「返答（予定表）」の括弧の中身。AI の返答と区別し、利用回数に数えないために使う
LOG_LABEL = "予定表"
WEEKDAYS = "月火水木金土日"
# 予定表を使えないときに読み上げる文（短く、利用者が次にすることが分かるように）
MISSING_MESSAGE = "ごみの予定表が登録されていません。設定を確認してください。"
UNREADABLE_MESSAGE = "ごみの予定表を読み込めません。設定を確認してください。"

# 正規化した質問（ひらがな、空白と句読点なし）に含まれていれば「今日のこと」と読む言葉
_TODAY_WORDS = ("今日", "きょう", "本日", "ごみの日", "ごみのひ")
# これらが含まれる質問は、今日のごみではない（別の日や種類、時間を聞いている）ので答えない
_OTHER_WORDS = ("明日", "あした", "あす", "明後日", "あさって", "昨日", "きのう", "おととい",
                "来週", "今週", "先週", "来月", "今月", "先月", "曜", "いつ", "次", "つぎ",
                "何日", "何時", "時間")
_PUNCTUATION = re.compile(r"[\s、。，．,.!?！？「」『』（）()]")
_DIGIT = re.compile(r"[0-9]")


@dataclass(frozen=True)
class Answer:
    text: str  # 読み上げる文
    problem: str | None = None  # 予定表を使えなかった理由（会話ログに残す。正常なら None）


@dataclass(frozen=True)
class Rule:
    weekday: int  # 0=月 … 6=日
    weeks: tuple[int, ...] | None  # 第何週か（None なら毎週）
    items: tuple[str, ...]


@dataclass(frozen=True)
class Schedule:
    rules: tuple[Rule, ...]
    off_weekdays: frozenset[int]  # 収集がない曜日
    off_dates: frozenset[tuple[int, int]]  # 収集がない日（月, 日）。毎年同じ


def _weekday(value: object, where: str) -> int:
    if not isinstance(value, str) or len(value) != 1 or value not in WEEKDAYS:
        raise ValueError(f"{where}：曜日は 月火水木金土日 のどれか 1 文字で書いてください（{value!r}）")
    return WEEKDAYS.index(value)


def parse_schedule(data: object) -> Schedule:
    """JSON を読んだ内容から予定表を作る。形が違えば、直す場所が分かる ValueError にする。"""
    if not isinstance(data, Mapping) or not isinstance(data.get("rules"), list):
        raise ValueError("rules（収集の規則の一覧）がありません")
    rules = []
    for number, raw in enumerate(data["rules"], start=1):
        where = f"rules の {number} 番目"
        if not isinstance(raw, Mapping):
            raise ValueError(f"{where}：形が違います")
        weekday = _weekday(raw.get("weekday"), where)
        weeks = raw.get("weeks")
        if weeks is not None:
            if not isinstance(weeks, list) or not weeks or not all(isinstance(w, int) and 1 <= w <= 5 for w in weeks):
                raise ValueError(f"{where}：weeks は 1〜5 の数字の一覧で書いてください（毎週なら書かない）")
            weeks = tuple(weeks)
        items = raw.get("items")
        if not isinstance(items, list) or not items or not all(isinstance(i, str) and i.strip() for i in items):
            raise ValueError(f"{where}：items にごみの種類を書いてください")
        rules.append(Rule(weekday, weeks, tuple(i.strip() for i in items)))

    off = data.get("no_collection") or {}
    if not isinstance(off, Mapping):
        raise ValueError("no_collection の形が違います")
    off_weekdays = frozenset(_weekday(w, "no_collection の weekdays") for w in off.get("weekdays", []))
    off_dates = set()
    for text in off.get("dates", []):
        match = re.fullmatch(r"(\d{1,2})-(\d{1,2})", str(text))
        if not match or not (1 <= int(match[1]) <= 12 and 1 <= int(match[2]) <= 31):
            raise ValueError(f"no_collection の dates は 月-日（例：01-01）で書いてください（{text!r}）")
        off_dates.add((int(match[1]), int(match[2])))
    return Schedule(tuple(rules), off_weekdays, frozenset(off_dates))


def load_schedule(path: Path = DEFAULT_PATH) -> Schedule:
    """予定表のファイルを読む。無い・読めない・形が違うときは OSError か ValueError。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON として読めません（{e.lineno} 行目付近）") from None
    return parse_schedule(data)


def collection_on(schedule: Schedule, day: date) -> list[str]:
    """その日に出すごみの種類（収集がなければ空）。種類は規則の並び順で、重複は除く。"""
    if day.weekday() in schedule.off_weekdays or (day.month, day.day) in schedule.off_dates:
        return []
    week = (day.day - 1) // 7 + 1
    found: list[str] = []
    for rule in schedule.rules:
        if rule.weekday == day.weekday() and (rule.weeks is None or week in rule.weeks):
            found.extend(item for item in rule.items if item not in found)
    return found


def normalize(text: str) -> str:
    """質問の表記ゆれをそろえる（全角・半角、カタカナ → ひらがな、空白と句読点を除く）。"""
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
    return _PUNCTUATION.sub("", text)


def looks_like_today_question(text: str) -> bool:
    """「今日のごみ」「ごみの日」などの定型の質問に見えるか（予定表を読めなくても判定できる範囲）。

    別の日や時間を指す言葉があれば False。種類の名前を含むかどうかは予定表が要るので、is_today_question で見る。
    """
    heard = normalize(text)
    if "ごみ" not in heard or _DIGIT.search(heard):
        return False
    if not any(word in heard for word in _TODAY_WORDS):
        return False
    return not any(word in heard for word in _OTHER_WORDS)


def is_today_question(text: str, schedule: Schedule) -> bool:
    """定型の質問か。上に加えて、種類の名前（「燃やすごみは？」など）を指していれば False。"""
    if not looks_like_today_question(text):
        return False
    heard = normalize(text)
    return not any(normalize(item) in heard for rule in schedule.rules for item in rule.items)


def describe(schedule: Schedule, day: date) -> str:
    """その日のごみを、読み上げる文にする。"""
    items = collection_on(schedule, day)
    if items:
        return f"今日は{WEEKDAYS[day.weekday()]}曜日です。{'、'.join(items)}の日です。"
    if day.weekday() in schedule.off_weekdays:
        return f"今日は{WEEKDAYS[day.weekday()]}曜日です。ごみの収集はありません。"
    return f"今日は{day.month}月{day.day}日です。ごみの収集はありません。"


def answer(text: str, day: date, path: Path = DEFAULT_PATH) -> Answer | None:
    """ごみの定型の質問なら答えを返す。そうでなければ None（AI に任せる）。

    予定表が無い・読めないときは、定型の質問に限り、その旨の Answer（problem 付き）を返す。
    ごみの話でなければ、ファイルは読まない。
    """
    if "ごみ" not in normalize(text):
        return None
    try:
        schedule = load_schedule(path)
    except FileNotFoundError:
        problem = f"{path.name} がありません（config/garbage.example.json を写して作ってください）"
        return Answer(MISSING_MESSAGE, problem) if looks_like_today_question(text) else None
    except (OSError, ValueError) as e:
        problem = str(e) if isinstance(e, ValueError) else f"{path.name} を読めません（{type(e).__name__}）"
        return Answer(UNREADABLE_MESSAGE, problem) if looks_like_today_question(text) else None
    return Answer(describe(schedule, day)) if is_today_question(text, schedule) else None
