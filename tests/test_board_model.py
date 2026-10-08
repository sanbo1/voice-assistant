from datetime import datetime, timedelta

from tools.board_model import (
    CONFIRMING,
    SELECTED,
    UNKNOWN_COLOR,
    build_model,
    dim,
    legend_lines,
    page_note,
    text_color_for,
    time_label,
)
from voice_assistant.board import Board, add_message, parse_settings

NOW = datetime(2026, 10, 8, 18, 30, 0)
SETTINGS = parse_settings({"people": [
    {"key": "1", "name": "お父さん", "color": "#4C9AFF"},
    {"key": "2", "name": "お母さん", "color": "#FF6B81"},
]})


def board_of(*items, start=NOW - timedelta(hours=5)):
    """items は（宛先、本文）。古いものから順に、1 分おきに預かったことにする。"""
    board = Board()
    for number, (to, text) in enumerate(items):
        board, error = add_message(board, to, text, start + timedelta(minutes=number))
        assert error is None
    return board


def model(board, view=None, now=NOW):
    return build_model(board, SETTINGS, view or {}, now)


# ---------- チップ（宛先ごとの件数）----------


def test_chips_list_every_person_then_everyone_with_counts():
    got = model(board_of(("1", "a"), ("1", "b"), ("2", "c"), ("0", "d")))
    assert [(c.name, c.count) for c in got.chips] == [("お父さん", 2), ("お母さん", 1), ("みんな", 1)]
    assert got.chips[0].color == "#4C9AFF"


def test_chips_count_all_pages_not_only_the_visible_ones():
    board = board_of(*[("1", f"伝言{n}") for n in range(8)])
    got = model(board)
    assert len(got.cards) == 5
    assert got.chips[0].count == 8


def test_chips_with_no_messages_have_zero():
    assert [c.count for c in model(Board()).chips] == [0, 0, 0]


# ---------- カード ----------


def test_cards_are_numbered_newest_first_with_name_color_and_time():
    got = model(board_of(("1", "古い"), ("2", "新しい")))
    assert [(c.number, c.name, c.text) for c in got.cards] == [(1, "お母さん", "新しい"), (2, "お父さん", "古い")]
    assert got.cards[0].color == "#FF6B81"
    assert got.cards[1].time == "10/8 13:30"


def test_a_message_for_an_unknown_recipient_still_shows():
    board, _ = add_message(Board(), "7", "宛先が消えた伝言", NOW)
    card = model(board).cards[0]
    assert (card.name, card.color) == ("7番", UNKNOWN_COLOR)


def test_new_marker_for_ten_minutes():
    board = board_of(("1", "古い"), start=NOW - timedelta(hours=1))
    assert model(board).cards[0].is_new is False
    board, _ = add_message(board, "1", "さっき", NOW - timedelta(minutes=3))
    assert [c.is_new for c in model(board).cards] == [True, False]
    assert model(board, now=NOW + timedelta(minutes=20)).cards[0].is_new is False


def test_pages_show_five_each_and_count_the_hidden_ones():
    board = board_of(*[("0", f"伝言{n}") for n in range(12)])
    first = model(board, {"page": 0})
    second = model(board, {"page": 1})
    assert (first.page, first.pages, len(first.cards), first.hidden) == (0, 3, 5, 7)
    assert [c.number for c in second.cards] == [1, 2, 3, 4, 5]
    assert second.cards[0].text == "伝言6"
    last = model(board, {"page": 2})
    assert (len(last.cards), last.hidden) == (2, 10)
    assert model(board, {"page": 99}).page == 2    # 範囲外は、最後のページ


def test_selected_and_confirming_cards():
    board = board_of(("1", "a"), ("1", "b"), ("1", "c"))
    ids = [m.id for m in board.messages]
    selected = model(board, {"selected": ids[1], "selected_until": "2026-10-08T18:30:05"})
    assert [c.state for c in selected.cards] == ["", SELECTED, ""]
    confirming = model(board, {"confirming": ids[2], "selected": ids[2], "selected_until": None})
    assert [c.state for c in confirming.cards] == ["", "", CONFIRMING]


def test_selection_expires_by_time_even_if_the_file_still_says_so():
    board = board_of(("1", "a"))
    view = {"selected": board.messages[0].id, "selected_until": "2026-10-08T18:29:59"}
    assert model(board, view).cards[0].state == ""


# ---------- お知らせ・ページの案内 ----------


def test_banner_shows_until_its_deadline():
    view = {"banner": "消しました（Insert で元に戻せます）", "banner_until": "2026-10-08T18:30:10"}
    assert model(Board(), view).banner == "消しました（Insert で元に戻せます）"
    assert model(Board(), view, now=NOW + timedelta(seconds=11)).banner == ""


def test_banner_without_a_deadline_stays():
    assert model(Board(), {"banner": "2番を削除しますか？", "banner_until": None}).banner == "2番を削除しますか？"


def test_page_note_only_when_there_are_several_pages():
    assert page_note(model(board_of(("0", "a")))) == ""
    board = board_of(*[("0", f"伝言{n}") for n in range(8)])
    assert page_note(model(board, {"page": 0})) == "1/2ページ　← → で切り替え　（ほか 3 件）"
    assert page_note(model(board, {"page": 1})) == "2/2ページ　← → で切り替え　（ほか 5 件）"


# ---------- 常時表示の凡例 ----------


def test_legend_shows_recipient_keys_and_the_character_limit():
    first, second = legend_lines(SETTINGS)
    assert first == "宛先のキー（押しながら話す）　1 お父さん　2 お母さん　0 みんな"
    assert "60文字まで" in second and "Delete：消す" in second and "Insert：戻す" in second


def test_legend_shows_how_many_can_be_restored():
    assert "戻す（2件）" in legend_lines(SETTINGS, 2)[1]
    assert "（" not in legend_lines(SETTINGS, 0)[1].split("Insert")[1]


def test_legend_follows_the_settings():
    more = parse_settings({"people": [{"key": "3", "name": "たろう", "color": "#112233"}]})
    assert "3 たろう" in legend_lines(more)[0]


# ---------- 色・時刻 ----------


def test_text_color_is_readable_on_the_background():
    assert text_color_for("#F2C14E") == "#101418"      # 明るい背景には、黒
    assert text_color_for("#4C9AFF") == "#101418"
    assert text_color_for("#112233") == "#ffffff"      # 暗い背景には、白


def test_dim_darkens_a_color():
    assert dim("#FF8000", 0.5) == "#7f4000"


def test_time_label():
    assert time_label("2026-10-08T07:05:09") == "10/8 7:05"
    assert time_label("壊れた値") == ""


# ---------- 全部消す確認（2026-10-08）----------


def test_all_cards_are_marked_while_the_key_confirmation_waits():
    board = board_of(("1", "a"), ("2", "b"))
    view = {"clear_all_until": "2026-10-08T18:30:05", "banner": "全部で 2 件を消します。", "banner_until": "2026-10-08T18:30:05"}
    got = model(board, view)
    assert [c.state for c in got.cards] == [CONFIRMING, CONFIRMING] and got.danger is True


def test_all_cards_are_marked_during_a_voice_confirmation():
    got = model(board_of(("1", "a")), {"confirming_all": True, "banner": "全部で 1 件を消しますか？", "banner_until": None})
    assert got.cards[0].state == CONFIRMING and got.danger is True


def test_the_marks_go_away_when_the_deadline_passes():
    board = board_of(("1", "a"))
    view = {"clear_all_until": "2026-10-08T18:29:59", "banner": "全部で 1 件を消します。", "banner_until": "2026-10-08T18:29:59"}
    got = model(board, view)
    assert got.cards[0].state == "" and got.danger is False and got.banner == ""


def test_an_ordinary_banner_is_not_dangerous():
    assert model(Board(), {"banner": "消しました", "banner_until": None}).danger is False


def test_a_two_line_banner_keeps_its_line_break_for_the_screen():
    banner = "全部で 2 件を消します。もう一度 Delete で実行します。" + chr(10) + "（中止したい場合は Esc）"
    got = model(board_of(("1", "a")), {"clear_all_until": "2026-10-08T18:30:05", "banner": banner,
                                       "banner_until": "2026-10-08T18:30:05"})
    assert got.banner.split(chr(10)) == ["全部で 2 件を消します。もう一度 Delete で実行します。", "（中止したい場合は Esc）"]
