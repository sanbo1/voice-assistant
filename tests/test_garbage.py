import json
from datetime import date

import pytest

from voice_assistant import garbage
from voice_assistant.config import PROJECT_ROOT
from voice_assistant.garbage import (
    MISSING_MESSAGE,
    UNREADABLE_MESSAGE,
    Answer,
    Schedule,
    answer,
    collection_on,
    describe,
    load_schedule,
    looks_like_schedule_question,
    normalize,
    parse_schedule,
    reply_for,
)

EXAMPLE = PROJECT_ROOT / "config" / "garbage.example.json"


@pytest.fixture
def schedule() -> Schedule:
    """雛形（月：燃えるごみ／水：資源ごみ／第 1・3 金：燃えないごみ／土日と 1/1〜3 は収集なし）。"""
    return load_schedule(EXAMPLE)


# ---------- 予定表の読み込み ----------


def test_example_file_is_valid(schedule):
    assert len(schedule.rules) == 3


def test_parse_rejects_missing_rules():
    with pytest.raises(ValueError, match="rules"):
        parse_schedule({})


@pytest.mark.parametrize("rule, message", [
    ({"weekday": "月曜", "items": ["a"]}, "曜日"),
    ({"weekday": "月", "items": []}, "items"),
    ({"weekday": "月", "items": [""]}, "items"),
    ({"weekday": "月", "weeks": [6], "items": ["a"]}, "weeks"),
    ({"weekday": "月", "weeks": [], "items": ["a"]}, "weeks"),
    ("月", "形が違います"),
])
def test_parse_rejects_bad_rules(rule, message):
    with pytest.raises(ValueError, match=message):
        parse_schedule({"rules": [rule]})


def test_parse_rejects_bad_off_date():
    with pytest.raises(ValueError, match="dates"):
        parse_schedule({"rules": [], "no_collection": {"dates": ["1月1日"]}})


def test_load_reports_broken_json(tmp_path):
    path = tmp_path / "garbage.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_schedule(path)


def test_load_reports_missing_file(tmp_path):
    with pytest.raises(OSError):
        load_schedule(tmp_path / "ない.json")


# ---------- 日付から種類を決める ----------


def test_weekly_rule(schedule):
    assert collection_on(schedule, date(2026, 10, 5)) == ["燃えるごみ"]   # 月
    assert collection_on(schedule, date(2026, 10, 7)) == ["資源ごみ"]     # 水


def test_nth_week_rule(schedule):
    """第 1・3 金曜だけ。第 2・4・5 は出ない。"""
    assert collection_on(schedule, date(2026, 10, 2)) == ["燃えないごみ"]    # 第 1
    assert collection_on(schedule, date(2026, 10, 9)) == []                   # 第 2
    assert collection_on(schedule, date(2026, 10, 16)) == ["燃えないごみ"]   # 第 3
    assert collection_on(schedule, date(2026, 10, 23)) == []                  # 第 4
    assert collection_on(schedule, date(2026, 10, 30)) == []                  # 第 5


def test_weekly_and_nth_week_rules_are_combined_without_duplicates():
    schedule = parse_schedule({"rules": [
        {"weekday": "金", "items": ["紙"]},
        {"weekday": "金", "weeks": [1, 3], "items": ["電池", "紙"]},
    ]})
    assert collection_on(schedule, date(2026, 10, 2)) == ["紙", "電池"]
    assert collection_on(schedule, date(2026, 10, 9)) == ["紙"]


def test_no_collection_on_weekends_and_new_year(schedule):
    assert collection_on(schedule, date(2026, 10, 4)) == []    # 日
    assert collection_on(schedule, date(2026, 10, 10)) == []   # 土
    # 1/1 は金曜（第 1 週）で規則に当たるが、収集なしの日が優先される
    assert collection_on(schedule, date(2027, 1, 1)) == []
    assert collection_on(schedule, date(2027, 1, 4)) == ["燃えるごみ"]


def test_holidays_and_year_end_are_collected(schedule):
    """祝日・年末は、規則どおり収集がある（予定表に載せていないので特別扱いしない）。"""
    assert collection_on(schedule, date(2026, 10, 12)) == ["燃えるごみ"]   # スポーツの日（月）
    assert collection_on(schedule, date(2026, 12, 30)) == ["資源ごみ"]     # 水


# ---------- 読み上げる文 ----------


def test_describe(schedule):
    assert describe(schedule, date(2026, 10, 5)) == "今日は月曜日です。燃えるごみの日です。"
    assert describe(schedule, date(2026, 10, 4)) == "今日は日曜日です。ごみの収集はありません。"
    assert describe(schedule, date(2026, 10, 9)) == "今日は10月9日です。ごみの収集はありません。"


def test_describe_lists_all_items_of_the_day():
    schedule = parse_schedule({"rules": [{"weekday": "火", "items": ["ビン", "電池", "有害ごみ"]}]})
    assert describe(schedule, date(2026, 10, 6)) == "今日は火曜日です。ビン、電池、有害ごみの日です。"


def test_normalize():
    assert normalize("今日のゴミは？") == "今日のごみは"
    assert normalize("　ｷｮｳ の ゴミ、") == "きょうのごみ"
    assert normalize("１０月５日") == "10月5日"


# ---------- 質問に答える（日・曜日・種類）----------

# 質問の読み取りを試すための予定表（雛形とは別。週指定の重なりや、複数の曜日・種類を含む）
QUESTION_SCHEDULE = parse_schedule({
    "rules": [
        {"weekday": "月", "items": ["燃えるごみ"]},
        {"weekday": "金", "items": ["燃えるごみ"]},
        {"weekday": "火", "weeks": [1, 3], "items": ["古紙"]},
        {"weekday": "水", "items": ["ビン"]},
        {"weekday": "水", "weeks": [2, 4], "items": ["電池", "有害ごみ"]},
        {"weekday": "木", "items": ["ペットボトル", "缶"]},
    ],
    "aliases": {"燃えるごみ": ["可燃ごみ"], "電池": ["乾電池"]},
    "no_collection": {"weekdays": ["土", "日"], "dates": ["01-01", "01-02", "01-03"]},
})
MON = date(2026, 10, 5)   # 第 1 月曜
FRI = date(2026, 10, 9)   # 第 2 金曜（翌日は土曜）


def ask(text, today=MON):
    return reply_for(text, QUESTION_SCHEDULE, today)


@pytest.mark.parametrize("text, expected", [
    ("今日のごみは", "今日は月曜日です。燃えるごみの日です。"),
    ("今日のゴミは？", "今日は月曜日です。燃えるごみの日です。"),
    ("きょうのごみ", "今日は月曜日です。燃えるごみの日です。"),
    ("本日のゴミ出し", "今日は月曜日です。燃えるごみの日です。"),
    ("今日は何のごみの日", "今日は月曜日です。燃えるごみの日です。"),
    ("ごみの日", "今日は月曜日です。燃えるごみの日です。"),
    ("ゴミの日は？", "今日は月曜日です。燃えるごみの日です。"),
    ("今 日 の ゴ ミ は", "今日は月曜日です。燃えるごみの日です。"),   # 空白が入って認識された場合
    ("明日のごみは？", "明日は火曜日です。古紙の日です。"),
    ("あしたのゴミは", "明日は火曜日です。古紙の日です。"),
    ("明後日のごみは", "明後日は水曜日です。ビンの日です。"),
    ("あさってのゴミは何", "明後日は水曜日です。ビンの日です。"),
])
def test_relative_day_questions(text, expected):
    assert ask(text) == expected


def test_relative_day_without_collection():
    assert ask("明日のごみは", FRI) == "明日は土曜日です。ごみの収集はありません。"


@pytest.mark.parametrize("text, expected", [
    ("水曜日は何のごみの日？", "水曜日は、毎週ビンの日です。第2、第4水曜日は、電池、有害ごみも出せます。"),
    ("木曜日のごみは", "木曜日は、ペットボトル、缶の日です。"),
    ("月曜日は何のごみ", "月曜日は、燃えるごみの日です。"),
    ("火曜日のごみは", "火曜日は、第1、第3火曜日に、古紙の日です。"),
    ("土曜日のごみは", "土曜日は、ごみの収集はありません。"),
    ("日曜は何のごみの日", "日曜日は、ごみの収集はありません。"),
])
def test_weekday_questions(text, expected):
    assert ask(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("燃えるごみはいつ", "燃えるごみは、毎週月曜日と金曜日です。次は今日です。"),
    ("可燃ごみはいつ？", "燃えるごみは、毎週月曜日と金曜日です。次は今日です。"),     # 別の言い方でも、予定表の名前で答える
    ("電池のごみは何曜日", "電池は、第2、第4水曜日です。次は10月14日の水曜日です。"),
    ("乾電池はいつ捨てるの", "電池は、第2、第4水曜日です。次は10月14日の水曜日です。"),
    ("古紙のごみの日は", "古紙は、第1、第3火曜日です。次は明日です。"),
    ("次の古紙の収集はいつ", "古紙は、第1、第3火曜日です。次は明日です。"),
    ("缶はいつ出すの", "缶は、毎週木曜日です。次は10月8日の木曜日です。"),   # 「ごみ」と言わなくても、出す・捨てるがあれば答える
])
def test_item_questions(text, expected):
    assert ask(text) == expected


def test_next_collection_skips_days_without_collection():
    """次の収集日は、収集のない日（1/1 は金曜だが休み）を飛ばして探す。"""
    assert ask("燃えるごみはいつ", date(2026, 12, 31)) == "燃えるごみは、毎週月曜日と金曜日です。次は1月4日の月曜日です。"


@pytest.mark.parametrize("text, expected", [
    ("明日は古紙のごみの日ですか", "はい、明日は火曜日で、古紙の日です。"),
    ("明日は燃えるごみの日？", "いいえ、明日は火曜日で、古紙の日です。"),
    ("可燃ごみは明日ですか", "いいえ、明日は火曜日で、古紙の日です。"),
    ("今日は燃えるごみの日？", "はい、今日は月曜日で、燃えるごみの日です。"),
    ("明後日は燃えるごみの日", "いいえ、明後日は水曜日で、ビンの日です。"),
    ("水曜日はビンのごみの日？", "はい、ビンは、毎週水曜日です。"),
    ("水曜日は電池のごみの日？", "はい、電池は、第2、第4水曜日です。"),
    ("木曜日は燃えるごみの日？", "いいえ、燃えるごみは木曜日の収集ではありません。燃えるごみは、毎週月曜日と金曜日です。"),
])
def test_yes_no_questions(text, expected):
    assert ask(text) == expected


def test_yes_no_about_a_day_without_collection():
    assert ask("明日は燃えるごみの日？", FRI) == "いいえ、明日は土曜日で、ごみの収集はありません。"


@pytest.mark.parametrize("text", [
    "今週のごみは",
    "来週の水曜日のごみは",
    "昨日のごみは",
    "10月5日のごみは",
    "今日のごみ出しは何時まで",
    "ごみ出しの時間は",
    "明日の水曜日のごみは",           # 複数の日を指している
    "今日と明日のごみは",
    "燃えるごみと古紙はいつ",         # 複数の種類を指している
    "次のごみの日は",                  # 日を指していない
    "ごみの日はいつ",
    "明日のごみはいつ",                # 矛盾している
    "明日は燃えるごみはいつ",
    "ごみの分別のしかたは",
    "燃えるごみって何",                # 種類を指すが、いつ出すかを聞いていない
    "明日は古紙の日ですか",            # 種類の名前だけで、ごみ・収集・捨てる・出すが無い（ごみの話と決めつけない）
    "古紙の作り方は",                  # ごみの話ではない
    "缶コーヒーの作り方",
    "今日の天気は",
    "明日は何の日",
    "ごみ箱ってなに",
    "",
])
def test_questions_left_to_ai(text):
    assert ask(text) is None


def test_looks_like_schedule_question_does_not_need_the_schedule():
    assert looks_like_schedule_question("今日のごみは") is True
    assert looks_like_schedule_question("明日のごみは") is True
    assert looks_like_schedule_question("水曜日は何のごみの日") is True
    assert looks_like_schedule_question("ごみの日はいつ") is True
    assert looks_like_schedule_question("来週のごみは") is False
    assert looks_like_schedule_question("ごみの分別のしかたは") is False
    assert looks_like_schedule_question("今日の天気は") is False


# ---------- 別の言い方（aliases）----------


def test_aliases_are_optional():
    assert parse_schedule({"rules": [{"weekday": "月", "items": ["a"]}]}).aliases == ()


def test_alias_must_belong_to_a_known_item():
    with pytest.raises(ValueError, match="rules にないごみの種類"):
        parse_schedule({"rules": [{"weekday": "月", "items": ["a"]}], "aliases": {"b": ["c"]}})


@pytest.mark.parametrize("aliases", [{"a": []}, {"a": "x"}, {"a": [""]}, ["a"]])
def test_alias_shape_is_checked(aliases):
    with pytest.raises(ValueError, match="aliases"):
        parse_schedule({"rules": [{"weekday": "月", "items": ["a"]}], "aliases": aliases})


def test_same_alias_for_two_items_is_rejected():
    rules = [{"weekday": "月", "items": ["a", "b"]}]
    with pytest.raises(ValueError, match="複数のごみの種類"):
        parse_schedule({"rules": rules, "aliases": {"a": ["x"], "b": ["x"]}})
    with pytest.raises(ValueError, match="複数のごみの種類"):
        parse_schedule({"rules": rules, "aliases": {"a": ["b"]}})   # 別の種類の名前と同じ


def test_example_file_aliases(schedule):
    assert reply_for("可燃ごみはいつ", schedule, date(2026, 10, 5)) == "燃えるごみは、毎週月曜日です。次は今日です。"
    # 10/9 は第 2 金曜なので、次の収集は第 3 金曜の 10/16
    assert reply_for("不燃ごみはいつ", schedule, date(2026, 10, 5)) ==         "燃えないごみは、第1、第3金曜日です。次は10月16日の金曜日です。"


# ---------- answer（ファイルを読んで答える）----------


def write_schedule(path, **overrides):
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data.update(overrides)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_answer_reads_the_file(tmp_path):
    path = tmp_path / "garbage.json"
    write_schedule(path)
    assert answer("今日のごみは", date(2026, 10, 5), path) == Answer("今日は月曜日です。燃えるごみの日です。")
    assert answer("明日のごみは", date(2026, 10, 5), path) == Answer("明日は10月6日です。ごみの収集はありません。")
    assert answer("来週のごみは", date(2026, 10, 5), path) is None


def test_answer_picks_up_edits_without_restart(tmp_path):
    path = tmp_path / "garbage.json"
    write_schedule(path)
    assert "燃えるごみ" in answer("今日のごみは", date(2026, 10, 5), path).text
    write_schedule(path, rules=[{"weekday": "月", "items": ["ペットボトル"]}], aliases={})
    assert "ペットボトル" in answer("今日のごみは", date(2026, 10, 5), path).text


def test_answer_does_not_touch_the_file_unless_garbage_is_mentioned(tmp_path):
    """ごみの話でなければ、予定表が無くても例外にならない（ふだんの質問を巻き込まない）。"""
    assert answer("今日の天気は", date(2026, 10, 5), tmp_path / "ない.json") is None


# ---------- 予定表を使えないとき（2026-10-04）----------


@pytest.mark.parametrize("text", ["今日のごみは", "ごみの日", "今日は何のゴミの日？", "明日のごみは",
                                  "水曜日は何のごみの日", "ごみの日はいつ"])
def test_routine_question_without_a_file_says_so_instead_of_asking_ai(tmp_path, text):
    got = answer(text, date(2026, 10, 5), tmp_path / "garbage.json")
    assert got.text == MISSING_MESSAGE
    assert "garbage.json がありません" in got.problem
    assert str(tmp_path) not in got.problem  # ファイルの場所（ユーザー名を含みうる）は記録に残さない


@pytest.mark.parametrize("text", ["ごみの分別のしかたは", "来週のごみは", "缶はいつ", "ごみ箱ってなに", "今日の天気は"])
def test_other_garbage_questions_without_a_file_are_left_to_ai(tmp_path, text):
    """予定表と関係ないごみの質問まで止めない（AI が答えられるため）。"""
    assert answer(text, date(2026, 10, 5), tmp_path / "garbage.json") is None


def test_routine_question_with_a_broken_file_says_so(tmp_path):
    path = tmp_path / "garbage.json"
    path.write_text("{", encoding="utf-8")
    got = answer("今日のごみは", date(2026, 10, 5), path)
    assert got.text == UNREADABLE_MESSAGE
    assert "JSON" in got.problem


def test_routine_question_with_a_wrong_shape_file_shows_where_to_fix(tmp_path):
    path = tmp_path / "garbage.json"
    path.write_text(json.dumps({"rules": [{"weekday": "月曜", "items": ["a"]}]}), encoding="utf-8")
    got = answer("今日のごみは", date(2026, 10, 5), path)
    assert got.text == UNREADABLE_MESSAGE
    assert "rules の 1 番目" in got.problem


def test_log_label_matches_the_display():
    """画面の集計が、予定表の返答を AI の利用回数に数えないための印が一致していること。"""
    from tools.display_log import LOCAL_SOURCES

    assert garbage.LOG_LABEL in LOCAL_SOURCES


def test_board_log_label_matches_the_display():
    from tools.display_log import LOCAL_SOURCES
    from voice_assistant import board

    assert board.LOG_LABEL in LOCAL_SOURCES
