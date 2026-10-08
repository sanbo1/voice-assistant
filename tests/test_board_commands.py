import pytest

from voice_assistant.board import EMPTY, BoardSettings, parse_settings
from voice_assistant.board_commands import (
    AddCommand,
    DeleteAllCommand,
    DeleteCommand,
    Problem,
    UndoCommand,
    normalize,
    parse,
    parse_confirmation,
)

SETTINGS = parse_settings({"people": [
    {"key": "1", "name": "お父さん", "color": "#112233", "aliases": ["父", "パパ"]},
    {"key": "2", "name": "お母さん", "color": "#112233", "aliases": ["母", "ママ"]},
    {"key": "3", "name": "たろう", "color": "#112233"},
]})


def command(text):
    return parse(text, SETTINGS)


# ---------- 預ける ----------


@pytest.mark.parametrize("text, expected", [
    ("伝言明日は早く帰ります", AddCommand("0", "明日は早く帰ります")),
    ("伝言、明日は早く帰ります", AddCommand("0", "明日は早く帰ります")),
    ("伝言：明日は早く帰ります。", AddCommand("0", "明日は早く帰ります")),
    ("でんごん明日は早く帰ります", AddCommand("0", "明日は早く帰ります")),
    ("デンゴン 明日は早く帰ります", AddCommand("0", "明日は早く帰ります")),
    ("ん伝言明日は早く帰ります", AddCommand("0", "明日は早く帰ります")),          # 頭に余計な音が付いても
    ("えーと伝言明日は早く帰ります", AddCommand("0", "明日は早く帰ります")),
])
def test_add_for_everyone(text, expected):
    assert command(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("お母さんに伝言牛乳を買ってきて", AddCommand("2", "牛乳を買ってきて")),
    ("お母さんへ伝言、牛乳を買ってきて", AddCommand("2", "牛乳を買ってきて")),
    ("お母さん宛ての伝言牛乳を買ってきて", AddCommand("2", "牛乳を買ってきて")),
    ("ママに伝言牛乳を買ってきて", AddCommand("2", "牛乳を買ってきて")),            # 別の言い方
    ("母に伝言牛乳を買ってきて", AddCommand("2", "牛乳を買ってきて")),
    ("んお母さんに伝言牛乳を買ってきて", AddCommand("2", "牛乳を買ってきて")),     # 頭に余計な音が付いても
    ("たろうに伝言宿題を忘れないで", AddCommand("3", "宿題を忘れないで")),
    ("伝言、お母さんに牛乳を買ってきて", AddCommand("2", "牛乳を買ってきて")),     # 「伝言」のあとに宛先
    ("伝言お父さんへ今日は遅くなります", AddCommand("1", "今日は遅くなります")),
])
def test_add_with_a_recipient(text, expected):
    assert command(text) == expected


def test_a_name_in_the_content_is_not_a_recipient_unless_followed_by_a_particle():
    """「お母さんから」は送り主を指すので、宛先にしない。"""
    assert command("伝言お母さんから電話がありました") == AddCommand("0", "お母さんから電話がありました")


def test_a_recipient_name_that_is_not_registered_stays_in_the_content():
    assert command("伝言じいじに電話してね") == AddCommand("0", "じいじに電話してね")


def test_add_with_a_preamble():
    assert command("伝言を残して明日は遅くなります") == AddCommand("0", "明日は遅くなります")


@pytest.mark.parametrize("text", ["伝言", "伝言を残して", "伝言を残したい", "伝言をお願い", "お母さんに伝言", "伝言、"])
def test_add_without_content_is_a_problem(text):
    assert command(text) == Problem(EMPTY)


# ---------- ふつうの質問は、命令とみなさない ----------


@pytest.mark.parametrize("text", [
    "今日の天気は",
    "今日のごみは",
    "伝言ゲームって何",                  # 「伝言」が頭でない
    "今日の伝言ゲームについて教えて",
    "明日の天気を伝言して",
    "",
])
def test_ordinary_questions_are_not_commands(text):
    assert command(text) is None


# ---------- 内容に、命令の言葉が入っていても、命令にしない ----------


@pytest.mark.parametrize("text, expected", [
    ("伝言電気を消してから寝てね", AddCommand("0", "電気を消してから寝てね")),
    ("伝言出かけるときは電気を消して", AddCommand("0", "出かけるときは電気を消して")),
    ("伝言、2番の部屋の電気を消して", AddCommand("0", "2番の部屋の電気を消して")),
    ("伝言さっきの話は元に戻してください", AddCommand("0", "さっきの話は元に戻してください")),
    ("伝言洗濯物を戻して", AddCommand("0", "洗濯物を戻して")),
])
def test_command_words_inside_the_content_do_not_make_a_command(text, expected):
    assert command(text) == expected


# ---------- 消す ----------


@pytest.mark.parametrize("text, number", [
    ("伝言の2番を消して", 2),
    ("伝言の２番を消して", 2),
    ("伝言の二番を消して", 2),
    ("伝言2番を消して", 2),
    ("伝言の5番目を消して", 5),
    ("伝言の3番を削除して", 3),
    ("伝言の1番を消す", 1),
    ("ん伝言の4番を消して", 4),
    ("伝言2番消して", 2),
])
def test_delete_with_a_number(text, number):
    assert command(text) == DeleteCommand(number)


@pytest.mark.parametrize("text", ["伝言を消して", "伝言消して", "伝言を削除して"])
def test_delete_without_a_number_is_reported_with_none(text):
    assert command(text) == DeleteCommand(None)


# ---------- 元に戻す ----------


@pytest.mark.parametrize("text", ["伝言を元に戻して", "伝言元に戻して", "伝言を戻して", "伝言をもとにもどして", "伝言を復元して",
                                  "ん伝言を元に戻して"])
def test_undo(text):
    assert command(text) == UndoCommand()


# ---------- 確認の返事 ----------


@pytest.mark.parametrize("text", ["はい", "うん", "お願いします", "オーケー", "OK", "いいよ", "はい消して", "ええ", "どうぞ", "はい、お願い"])
def test_confirmation_yes(text):
    assert parse_confirmation(text) == "yes"


@pytest.mark.parametrize("text", ["いいえ", "いや", "やめて", "やめておく", "だめ", "ダメです", "違う", "キャンセル", "消さないで", "いいえ、やめて"])
def test_confirmation_no(text):
    assert parse_confirmation(text) == "no"


@pytest.mark.parametrize("text", ["", "今日の天気は", "えー", "さあ"])
def test_confirmation_unclear(text):
    assert parse_confirmation(text) is None


def test_no_wins_over_yes_in_the_same_reply():
    """「いいえ、いいよ」のように、迷う返事は、消さない側に倒す。"""
    assert parse_confirmation("いや、いいよ") == "no"


def test_normalize_removes_punctuation_and_unifies_width():
    assert normalize("伝言、２番を 消して。") == "伝言2番を消して"


def test_default_settings_still_parse_everyone_messages():
    assert parse("伝言明日は早く帰ります", BoardSettings()) == AddCommand("0", "明日は早く帰ります")


# ---------- 言いよどみ・聞き間違い（2026-10-08 の実機で出たもの）----------


def test_a_marker_said_twice_is_still_a_delete_command():
    assert command("伝言伝言の3番を消して") == DeleteCommand(3)


def test_a_marker_said_twice_before_the_content_is_stored_once():
    assert command("伝言伝言明日は早く帰ります") == AddCommand("0", "明日は早く帰ります")


@pytest.mark.parametrize("text", ["伝言の地盤を削除して", "伝言の地番を消して"])
def test_a_delete_command_with_a_misheard_number_is_not_stored(text):
    from voice_assistant.board_commands import NOT_HEARD
    assert command(text) == Problem(NOT_HEARD)


def test_a_normal_message_starting_with_no_is_still_stored():
    assert command("伝言、のりを買ってきて") == AddCommand("0", "のりを買ってきて")


# ---------- 全部消す（2026-10-08）----------


@pytest.mark.parametrize("text", [
    "伝言を全部消して", "伝言を全部削除して", "伝言を全て消して", "伝言をすべて消して", "伝言の全部を消して",
    "伝言を一括で削除して", "伝言、全部消して", "えーと伝言を全部消して", "全部の伝言を消して", "すべての伝言を削除して",
])
def test_delete_everything_by_voice(text):
    assert command(text) == DeleteAllCommand()


def test_delete_everything_is_not_mixed_up_with_deleting_one_number():
    assert command("伝言の3番を消して") == DeleteCommand(3)
    assert command("伝言の全部を消して") == DeleteAllCommand()


@pytest.mark.parametrize("text", ["今日は全部消して", "伝言ゲームを全部消して", "全部の電気を消して", "伝言板って全部消せる"])
def test_ordinary_sentences_are_not_delete_everything(text):
    assert not isinstance(command(text), DeleteAllCommand)


def test_a_message_that_mentions_everything_is_still_stored():
    assert command("伝言、全部食べたよ") == AddCommand("0", "全部食べたよ")
