"""声で言われた伝言板の命令を読み取る（AI は使わない）。標準ライブラリだけで動く。

- 預かる：「伝言、明日は早く帰ります」「お母さんに伝言、牛乳を買ってきて」（宛先は、名前・別の言い方で指定できる）
- 消す：「伝言の 2 番を消して」（番号は、いま画面に出ているカードの番号）
- 全部消す：「伝言を全部消して」「全部の伝言を消して」（件数を言って確認する）
- 元に戻す：「伝言を元に戻して」
- 確認の返事：「はい」「いいえ」（消してよいか聞いたあとの返事）

「伝言」を含まない質問は、伝言板の命令とみなさない（ふつうの質問を取り違えないため）。
「今日の伝言ゲームについて教えて」のように、「伝言」の前に別の言葉が続く文も、命令とみなさない。
"""

import re
import unicodedata
from dataclasses import dataclass

from .board import EMPTY, EVERYONE_KEY, BoardSettings

_MARKERS = ("伝言", "でんごん", "デンゴン")
_PUNCTUATION = re.compile(r"[\s、。，．,.!?！？「」『』（）()：:;；]")
# 「伝言」の前に付いてもよい、言いよどみ（これだけなら、命令の頭とみなす）
_FILLERS = ("えーと", "えっと", "えー", "あのー", "あの", "ええと", "あのう", "ん", "と", "あ", "え", "はい", "ねえ", "ねぇ", "すみません")
# 宛先の名前のあとに付く、助詞
_PARTICLES = ("宛てに", "宛に", "あてに", "宛て", "宛", "あて", "に", "へ")
# 「伝言」のすぐあとに、これが続くときは、質問とみなして命令にしない（「伝言ゲームって何」「伝言板とは」）
_QUESTION_AFTER = ("ゲーム", "って", "とは", "板", "というのは")
# 「伝言」のあとに続く、内容でない言い回し（「伝言を残して」など）
_PREAMBLES = ("を残したい", "を残して", "を残す", "を入れて", "を預かって", "を預けたい", "を書いて", "をお願い", "お願い", "を")
_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
# 命令は、「伝言」の**すぐあと**が命令の形のときだけ。伝言の内容に「消して」が含まれていても（「電気を消して」）、
# 削除の命令と取り違えないため
_DELETE = re.compile(r"^(?:の|を)?(?:([1-9]|[一二三四五六七八九])番(?:目)?)?(?:を|は)?(?:消|削除|けし|ケシ)")
_DELETE_ALL = re.compile(r"^(?:の|を|は)?(?:全部|ぜんぶ|すべて|全て|一括)(?:を|は|で)?(?:消|削除|けし|ケシ)")
# 「全部の伝言を消して」のように、「伝言」の前に「全部の」が付く言い方
_ALL_BEFORE = ("全部の", "ぜんぶの", "すべての", "全ての")
_DELETE_VERB = re.compile(r"^(?:を|は)?(?:消|削除|けし|ケシ)")
_UNDO = re.compile(r"^(?:を|は)?(?:元に戻|もとにもど|戻し|もどし|復元)")
# 削除の命令のつもりが、番号を聞き間違えられたとき（「伝言の地盤を削除して」）。伝言として預からず、言い直してもらう
_BROKEN_DELETE = re.compile(r"^の.{1,4}?(?:を|は)?(?:消|削除|けし|ケシ)")
NOT_HEARD = "番号が聞き取れませんでした。もう一度言ってください"
_YES = ("はい", "うん", "ええ", "お願い", "おねがい", "オーケー", "おーけー", "ok", "いいよ", "いいです", "消して", "けして",
        "そう", "よろしく", "どうぞ")
_NO = ("いいえ", "いえ", "いや", "やめ", "だめ", "ダメ", "ちがう", "違う", "キャンセル", "きゃんせる", "消さない", "けさない")


@dataclass(frozen=True)
class AddCommand:
    to: str  # 宛先のキー
    text: str  # 伝言の内容


@dataclass(frozen=True)
class DeleteCommand:
    number: int | None  # いま画面に出ているカードの番号（言われなければ None）


@dataclass(frozen=True)
class DeleteAllCommand:
    pass


@dataclass(frozen=True)
class UndoCommand:
    pass


@dataclass(frozen=True)
class Problem:
    message: str  # 伝言板の命令だが、このままでは実行できない理由（短く、読み上げる）


Command = AddCommand | DeleteCommand | DeleteAllCommand | UndoCommand | Problem


def normalize(text: str) -> str:
    """全角・半角をそろえ、空白と句読点を除く。"""
    return _PUNCTUATION.sub("", unicodedata.normalize("NFKC", text))


def _marker(text: str) -> tuple[int, int] | None:
    """「伝言」の位置（先頭の位置、長さ）。無ければ None。"""
    found = [(text.index(m), len(m)) for m in _MARKERS if m in text]
    return min(found) if found else None


def _only_fillers(text: str) -> bool:
    """言いよどみ（と助詞）だけで、できているか。"""
    rest = text
    for token in sorted((*_FILLERS, *_PARTICLES, "の"), key=len, reverse=True):
        rest = rest.replace(token, "")
    return rest == ""


def _strip_recipient(text: str, settings: BoardSettings) -> tuple[str | None, str]:
    """文の頭にある宛先の名前（と助詞）を取り除く。（宛先のキー、残りの文）を返す。無ければ（None、そのまま）。"""
    for name, person in sorted(((n, p) for p in settings.people for n in p.names),
                               key=lambda item: -len(item[0])):
        if text.startswith(name):
            rest = text[len(name):]
            for particle in _PARTICLES:
                if rest.startswith(particle):
                    return person.key, rest[len(particle):]
    return None, text


def _number(digit: str | None) -> int | None:
    if digit is None:
        return None
    return int(digit) if digit.isdigit() else _DIGITS[digit]


def parse(text: str, settings: BoardSettings) -> Command | None:
    """声で言われた文が、伝言板の命令なら、その命令を返す。そうでなければ None（ふつうの質問として扱う）。"""
    t = normalize(text)
    found = _marker(t)
    if found is None:
        return None
    start, length = found
    before, after = t[:start], t[start + length:]
    while (repeat := next((m for m in _MARKERS if after.startswith(m)), None)):
        after = after[len(repeat):]  # 「伝言、伝言の 3 番を消して」のように、言いよどんで 2 回言われたとき
    if after.startswith(_QUESTION_AFTER):
        return None

    if before in _ALL_BEFORE and _DELETE_VERB.match(after):
        return DeleteAllCommand()
    if _only_fillers(before):
        if _UNDO.match(after):
            return UndoCommand()
        if _DELETE_ALL.match(after):
            return DeleteAllCommand()
        deleting = _DELETE.match(after)
        if deleting:
            return DeleteCommand(_number(deleting.group(1)))
        if _BROKEN_DELETE.match(after):
            return Problem(NOT_HEARD)

    # 預ける：宛先は、「伝言」の前（「お母さんに伝言、〜」）か、あと（「伝言、お母さんに〜」）に言える
    to, rest = _strip_recipient(before, settings)
    if to is None:
        person = settings.find_by_name(before)
        if person is not None:
            to, rest = person.key, before.replace(next(n for n in person.names if n in before), "", 1)
        else:
            rest = before
    if not _only_fillers(rest):
        return None  # 「今日の伝言ゲームは」のように、頭に別の言葉が続く
    content = after
    for preamble in sorted(_PREAMBLES, key=len, reverse=True):
        if content.startswith(preamble):
            content = content[len(preamble):]
            break
    if to is None:
        to, content = _strip_recipient(content, settings)
    if not content:
        return Problem(EMPTY)
    return AddCommand(to or EVERYONE_KEY, content)


def parse_confirmation(text: str) -> str | None:
    """確認の返事。「はい」の意味なら "yes"、「いいえ」の意味なら "no"、どちらでもなければ None。"""
    t = normalize(text).lower()
    if any(word in t for word in _NO):
        return "no"
    if any(word in t for word in _YES):
        return "yes"
    return None
