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
    is_today_question,
    load_schedule,
    looks_like_today_question,
    normalize,
    parse_schedule,
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


# ---------- 質問の判定 ----------


def test_normalize():
    assert normalize("今日のゴミは？") == "今日のごみは"
    assert normalize("　ｷｮｳ の ゴミ、") == "きょうのごみ"
    assert normalize("１０月５日") == "10月5日"


@pytest.mark.parametrize("text", [
    "今日は何のごみの日",
    "今日のゴミは？",
    "今日のごみは",
    "ごみの日",
    "ゴミの日は？",
    "きょうのごみ",
    "本日のゴミ出し",
    "今日はごみの日ですか",
    "今日 の ゴミ は 何",   # 空白が入って認識された場合
])
def test_today_questions_are_recognized(schedule, text):
    assert is_today_question(text, schedule) is True


@pytest.mark.parametrize("text", [
    "明日のごみは？",
    "あしたのゴミは",
    "水曜日は何のごみの日",
    "ごみの日はいつ",
    "次のごみの日は",
    "来週のごみは",
    "10月5日のごみは",
    "今日のごみ出しは何時まで",
    "今日は燃えるごみの日？",       # 種類を指している（次の段階で対応）
    "燃えないごみはいつ",
    "今日の天気は",                  # ごみの話ではない
    "ごみ箱ってなに",                # 「今日」も「ごみの日」も無い
    "",
])
def test_other_questions_are_left_to_ai(schedule, text):
    assert is_today_question(text, schedule) is False


# ---------- answer（ファイルを読んで答える）----------


def write_schedule(path, **overrides):
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data.update(overrides)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_answer_reads_the_file(tmp_path):
    path = tmp_path / "garbage.json"
    write_schedule(path)
    assert answer("今日のごみは", date(2026, 10, 5), path) == Answer("今日は月曜日です。燃えるごみの日です。")
    assert answer("明日のごみは", date(2026, 10, 5), path) is None


def test_answer_picks_up_edits_without_restart(tmp_path):
    path = tmp_path / "garbage.json"
    write_schedule(path)
    assert "燃えるごみ" in answer("今日のごみは", date(2026, 10, 5), path).text
    write_schedule(path, rules=[{"weekday": "月", "items": ["ペットボトル"]}])
    assert "ペットボトル" in answer("今日のごみは", date(2026, 10, 5), path).text


def test_answer_does_not_touch_the_file_unless_garbage_is_mentioned(tmp_path):
    """ごみの話でなければ、予定表が無くても例外にならない（ふだんの質問を巻き込まない）。"""
    assert answer("今日の天気は", date(2026, 10, 5), tmp_path / "ない.json") is None


# ---------- 予定表を使えないとき（2026-10-04）----------


@pytest.mark.parametrize("text", ["今日のごみは", "ごみの日", "今日は何のゴミの日？"])
def test_routine_question_without_a_file_says_so_instead_of_asking_ai(tmp_path, text):
    got = answer(text, date(2026, 10, 5), tmp_path / "garbage.json")
    assert got.text == MISSING_MESSAGE
    assert "garbage.json がありません" in got.problem
    assert str(tmp_path) not in got.problem  # ファイルの場所（ユーザー名を含みうる）は記録に残さない


@pytest.mark.parametrize("text", ["ごみの分別のしかたは", "明日のごみは", "水曜日は何のごみの日", "ごみ箱ってなに"])
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


def test_looks_like_today_question_does_not_need_the_schedule():
    assert looks_like_today_question("今日のごみは") is True
    assert looks_like_today_question("明日のごみは") is False
    assert looks_like_today_question("今日の天気は") is False
    # 種類の名前を含むかは予定表が要る。予定表が無いときは、ゆるく定型の質問とみなす
    assert looks_like_today_question("今日は燃えるごみの日？") is True


def test_log_label_matches_the_display():
    """画面の集計が、予定表の返答を AI の利用回数に数えないための印が一致していること。"""
    from tools.display_log import LOCAL_SOURCES

    assert garbage.LOG_LABEL in LOCAL_SOURCES
