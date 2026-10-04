"""ごみ収集の予定表から、ごみ出しの質問に答える（AI を使わず、コードで判定する）。

予定表は Pi 上の garbage.json（リポジトリには入れない。雛形は config/garbage.example.json）。
質問のたびに読み直すので、ファイルを直せば再起動なしで反映される。

答える質問（2026-10-04 に「今日」だけ、同日に次の段階まで広げた）：
- 日を指す：「今日のごみは？」「ごみの日」「明日のごみは？」「明後日は何のごみ？」「水曜日は何のごみの日？」
- 種類を指す：「燃やさないごみはいつ？」「缶はいつ捨てるの？」（次の収集日も答える）
- 種類と日：「明日は燃やすごみの日？」（はい／いいえで答える）

日付や種類を取り違えるより AI に任せるほうがよいので、次のような質問は答えずに None を返す：
今週・来週・昨日、「10月5日」のような日付、時間、複数の日や種類を同時に指す質問、日を指さない「次のごみの日」。

予定表が無い・読めないときは、日を指す定型の質問に限り、その旨を答える（AI には送らない。AI は家の収集日を知らず、
的外れな返答になるため）。予定表と関係ないごみの質問（「ごみの分別は？」など）は AI に任せる。
"""

import json
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .config import PROJECT_ROOT

DEFAULT_PATH = PROJECT_ROOT / "garbage.json"
# 会話ログの「返答（予定表）」の括弧の中身。AI の返答と区別し、利用回数に数えないために使う
LOG_LABEL = "予定表"
WEEKDAYS = "月火水木金土日"
# 予定表を使えないときに読み上げる文（短く、利用者が次にすることが分かるように）
MISSING_MESSAGE = "ごみの予定表が登録されていません。設定を確認してください。"
UNREADABLE_MESSAGE = "ごみの予定表を読み込めません。設定を確認してください。"
# 「次の収集日」を探す日数の上限
SEARCH_DAYS = 366

# 以下は、正規化した質問（ひらがな、空白と句読点なし）に含まれるかを見る言葉
_TODAY = ("今日", "きょう", "本日")
_TOMORROW = ("明日", "あした", "あす")
_DAY_AFTER = ("明後日", "あさって")
_ASK_WHEN = ("いつ", "何曜")
# 答えない質問（別の日・時間を指している。日付や時間は予定表だけでは答えられない）
_OTHER = ("昨日", "きのう", "おととい", "来週", "今週", "先週", "来月", "今月", "先月", "何日", "何時", "時間")
# 種類を指さない質問で「次の」と言うときは、日を指していないので答えない（今日と取り違えないため）
_NEXT = ("次", "つぎ")
# 「ごみ」と言わなくても、種類の名前と一緒にあればごみの話とみなす言葉
_GARBAGE_WORDS = ("収集", "捨て", "出す", "出し")
# 種類だけを指す質問が「いつ出すか」を聞いているとみなす言葉（「燃やすごみって何」を除くため）
_WHEN_HINTS = _ASK_WHEN + ("の日", "収集", "捨て", "出す", "出し")
_PUNCTUATION = re.compile(r"[\s、。，．,.!?！？「」『』（）()]")
_DIGIT = re.compile(r"[0-9]")
_WEEKDAY = re.compile(r"([月火水木金土日])曜")


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
    aliases: tuple[tuple[str, tuple[str, ...]], ...] = ()  # （ごみの種類, 別の言い方の一覧）


def _weekday(value: object, where: str) -> int:
    if not isinstance(value, str) or len(value) != 1 or value not in WEEKDAYS:
        raise ValueError(f"{where}：曜日は 月火水木金土日 のどれか 1 文字で書いてください（{value!r}）")
    return WEEKDAYS.index(value)


def _parse_aliases(data: Mapping, rules: list[Rule]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    raw = data.get("aliases") or {}
    if not isinstance(raw, Mapping):
        raise ValueError("aliases の形が違います（ごみの種類ごとに、別の言い方の一覧を書いてください）")
    known = {item for rule in rules for item in rule.items}
    aliases = []
    for name, values in raw.items():
        if name not in known:
            raise ValueError(f"aliases：{name} は rules にないごみの種類です")
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and v.strip() for v in values):
            raise ValueError(f"aliases：{name} の別の言い方は、文字列の一覧で書いてください")
        aliases.append((name, tuple(v.strip() for v in values)))
    # 同じ言い方が別の種類に付いていると、どちらの質問か分からない
    owner: dict[str, str] = {}
    for name in known:
        owner[normalize(name)] = name
    for name, values in aliases:
        for value in values:
            if owner.setdefault(normalize(value), name) != name:
                raise ValueError(f"aliases：「{value}」が複数のごみの種類に使われています")
    return tuple(aliases)


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
    return Schedule(tuple(rules), off_weekdays, frozenset(off_dates), _parse_aliases(data, rules))


def load_schedule(path: Path = DEFAULT_PATH) -> Schedule:
    """予定表のファイルを読む。無い・読めない・形が違うときは OSError か ValueError。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON として読めません（{e.lineno} 行目付近）") from None
    return parse_schedule(data)


# ---------- 日付から種類を決める ----------


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


def _when(rules: list[Rule]) -> str:
    """規則の並びを「毎週月曜日と木曜日」「第2、第4火曜日」のような言い方にする。"""
    weekly = [f"{WEEKDAYS[rule.weekday]}曜日" for rule in rules if rule.weeks is None]
    parts = [("毎週" + "と".join(weekly))] if weekly else []
    parts += [f"{_weeks(rule.weeks)}{WEEKDAYS[rule.weekday]}曜日" for rule in rules if rule.weeks is not None]
    return "と".join(parts)


def _weeks(weeks: tuple[int, ...]) -> str:
    return "、".join(f"第{week}" for week in weeks)


# ---------- 読み上げる文 ----------


def describe(schedule: Schedule, day: date, label: str = "今日") -> str:
    """その日のごみを、読み上げる文にする。label は「今日」「明日」など。"""
    items = collection_on(schedule, day)
    if items:
        return f"{label}は{WEEKDAYS[day.weekday()]}曜日です。{'、'.join(items)}の日です。"
    if day.weekday() in schedule.off_weekdays:
        return f"{label}は{WEEKDAYS[day.weekday()]}曜日です。ごみの収集はありません。"
    return f"{label}は{day.month}月{day.day}日です。ごみの収集はありません。"


def describe_weekday(schedule: Schedule, weekday: int) -> str:
    """その曜日に出すごみを、週の指定も含めて読み上げる文にする。"""
    name = f"{WEEKDAYS[weekday]}曜日"
    rules = [rule for rule in schedule.rules if rule.weekday == weekday]
    if weekday in schedule.off_weekdays or not rules:
        return f"{name}は、ごみの収集はありません。"
    weekly = [item for rule in rules if rule.weeks is None for item in rule.items]
    weekly = list(dict.fromkeys(weekly))
    nth = [rule for rule in rules if rule.weeks is not None]
    sentences = []
    if weekly:
        sentences.append(f"{name}は、毎週{'、'.join(weekly)}の日です。" if nth else f"{name}は、{'、'.join(weekly)}の日です。")
    for rule in nth:
        items = "、".join(rule.items)
        if weekly:  # 毎週のものに加えて出せるもの
            sentences.append(f"{_weeks(rule.weeks)}{name}は、{items}も出せます。")
        else:
            lead = "" if sentences else f"{name}は、"
            sentences.append(f"{lead}{_weeks(rule.weeks)}{name}に、{items}の日です。")
    return "".join(sentences)


def describe_item(schedule: Schedule, item: str, today: date) -> str:
    """そのごみをいつ出すか（毎週何曜日、第何何曜日）と、次の収集日を読み上げる文にする。"""
    rules = [rule for rule in schedule.rules if item in rule.items]
    text = f"{item}は、{_when(rules)}です。"
    for offset in range(SEARCH_DAYS):
        day = today + timedelta(days=offset)
        if item in collection_on(schedule, day):
            when = {0: "今日", 1: "明日"}.get(offset, f"{day.month}月{day.day}日の{WEEKDAYS[day.weekday()]}曜日")
            return text + f"次は{when}です。"
    return text


def _yes_no_on(schedule: Schedule, item: str, day: date, label: str) -> str:
    items = collection_on(schedule, day)
    weekday = f"{WEEKDAYS[day.weekday()]}曜日"
    if item in items:
        return f"はい、{label}は{weekday}で、{item}の日です。"
    return f"いいえ、{label}は{weekday}で、" + (f"{'、'.join(items)}の日です。" if items else "ごみの収集はありません。")


def _yes_no_weekday(schedule: Schedule, item: str, weekday: int) -> str:
    rules = [rule for rule in schedule.rules if item in rule.items]
    on_that_day = [rule for rule in rules if rule.weekday == weekday]
    if on_that_day:
        return f"はい、{item}は、{_when(on_that_day)}です。"
    return f"いいえ、{item}は{WEEKDAYS[weekday]}曜日の収集ではありません。{item}は、{_when(rules)}です。"


# ---------- 質問の読み取り ----------


def normalize(text: str) -> str:
    """質問の表記ゆれをそろえる（全角・半角、カタカナ → ひらがな、空白と句読点を除く）。"""
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in text)
    return _PUNCTUATION.sub("", text)


def _mentions_garbage(heard: str) -> bool:
    return "ごみ" in heard or any(word in heard for word in _GARBAGE_WORDS)


def _day_refs(heard: str) -> list[tuple]:
    """質問が指している日。（"relative", 今日からの日数, 呼び方）か（"weekday", 曜日番号）の一覧。"""
    refs: list[tuple] = []
    if any(word in heard for word in _TODAY):
        refs.append(("relative", 0, "今日"))
    if any(word in heard for word in _TOMORROW):
        refs.append(("relative", 1, "明日"))
    if any(word in heard for word in _DAY_AFTER):
        refs.append(("relative", 2, "明後日"))
    refs += [("weekday", WEEKDAYS.index(name)) for name in dict.fromkeys(_WEEKDAY.findall(heard))]
    return refs


def _matched_items(heard: str, schedule: Schedule) -> list[str]:
    """質問に出てくるごみの種類（別の言い方も含む）。長い言い方に含まれる短い言い方は数えない。"""
    names: dict[str, str] = {}
    for rule in schedule.rules:
        for item in rule.items:
            names[normalize(item)] = item
    for item, values in schedule.aliases:
        for value in values:
            names[normalize(value)] = item
    hits = {name: item for name, item in names.items() if name in heard}
    hits = {name: item for name, item in hits.items() if not any(name != other and name in other for other in hits)}
    return list(dict.fromkeys(hits.values()))


def looks_like_schedule_question(text: str) -> bool:
    """日を指すごみの質問に見えるか（予定表を読めなくても判定できる範囲）。

    予定表が無いときに、「登録されていません」と答えるかを決めるのに使う。
    """
    heard = normalize(text)
    if "ごみ" not in heard or _DIGIT.search(heard) or any(word in heard for word in _OTHER):
        return False
    return bool(_day_refs(heard)) or "ごみの日" in heard or any(word in heard for word in _ASK_WHEN)


def reply_for(text: str, schedule: Schedule, today: date) -> str | None:
    """質問に答える文を返す。答えられない（取り違えるおそれがある）質問は None（AI に任せる）。"""
    heard = normalize(text)
    if _DIGIT.search(heard) or any(word in heard for word in _OTHER):
        return None
    refs = _day_refs(heard)
    items = _matched_items(heard, schedule)
    asking_when = any(word in heard for word in _ASK_WHEN)
    if len(refs) > 1 or len(items) > 1:
        return None  # 複数の日や種類を同時に指している

    if items:
        item = items[0]
        if not _mentions_garbage(heard):
            return None  # 「紙の作り方は」など、種類の名前だけではごみの質問とみなさない
        if not refs:
            return describe_item(schedule, item, today) if any(word in heard for word in _WHEN_HINTS) else None
        if asking_when:
            return None  # 「明日はいつ」のように、矛盾している
        kind, *rest = refs[0]
        if kind == "weekday":
            return _yes_no_weekday(schedule, item, rest[0])
        offset, label = rest
        return _yes_no_on(schedule, item, today + timedelta(days=offset), label)

    if "ごみ" not in heard or asking_when:
        return None
    if refs:
        kind, *rest = refs[0]
        if kind == "weekday":
            return describe_weekday(schedule, rest[0])
        offset, label = rest
        return describe(schedule, today + timedelta(days=offset), label)
    # 日を指していない。「ごみの日」は今日のことと読むが、「次のごみの日」は日が分からないので答えない
    if "ごみの日" in heard and not any(word in heard for word in _NEXT):
        return describe(schedule, today)
    return None


def answer(text: str, day: date, path: Path = DEFAULT_PATH) -> Answer | None:
    """ごみ出しの質問なら答えを返す。そうでなければ None（AI に任せる）。

    予定表が無い・読めないときは、日を指す定型の質問に限り、その旨の Answer（problem 付き）を返す。
    ごみの話でなければ、ファイルは読まない。
    """
    if not _mentions_garbage(normalize(text)):
        return None
    try:
        schedule = load_schedule(path)
    except FileNotFoundError:
        problem = f"{path.name} がありません（config/garbage.example.json を写して作ってください）"
        return Answer(MISSING_MESSAGE, problem) if looks_like_schedule_question(text) else None
    except (OSError, ValueError) as e:
        problem = str(e) if isinstance(e, ValueError) else f"{path.name} を読めません（{type(e).__name__}）"
        return Answer(UNREADABLE_MESSAGE, problem) if looks_like_schedule_question(text) else None
    reply = reply_for(text, schedule, day)
    return Answer(reply) if reply else None
