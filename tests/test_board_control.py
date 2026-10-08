import json
from datetime import datetime, timedelta

import pytest

from voice_assistant import board_control as bc
from voice_assistant.board import (
    FULL,
    MAX_MESSAGES,
    NOTHING_TO_RESTORE,
    TOO_LONG,
    load_board,
    read_view,
)
from voice_assistant.board_control import BoardController

START = datetime(2026, 10, 8, 18, 0, 0)


class Clock:
    def __init__(self):
        self.now = START

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


SETTINGS = {"people": [
    {"key": "1", "name": "お父さん", "color": "#4C9AFF"},
    {"key": "2", "name": "お母さん", "color": "#FF6B81"},
]}


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def ctl(tmp_path, clock):
    (tmp_path / "board-settings.json").write_text(json.dumps(SETTINGS, ensure_ascii=False), encoding="utf-8")
    return make(tmp_path, clock)


def make(tmp_path, clock):
    return BoardController(tmp_path / "board.json", tmp_path / "board-settings.json",
                           tmp_path / "run" / "board-view.json", clock)


def fill(ctl, clock, count, to="0"):
    for number in range(count):
        clock.advance(1)
        ctl.add(to, f"伝言{number}")


def texts(ctl):
    return [m.text for m in ctl.board.messages]


def saved(tmp_path):
    return load_board(tmp_path / "board.json")


# ---------- 預かる ----------


def test_add_stores_and_saves(ctl, tmp_path):
    assert ctl.add("0", "明日は早く帰ります") == bc.STORED
    assert texts(ctl) == ["明日は早く帰ります"]
    assert [m.text for m in saved(tmp_path).messages] == ["明日は早く帰ります"]


def test_add_for_a_person_says_the_name(ctl):
    assert ctl.add("2", "牛乳を買ってきて") == "お母さん宛に預かりました"


def test_add_errors_are_returned_and_nothing_is_stored(ctl, tmp_path):
    assert ctl.add("0", "あ" * 61) == TOO_LONG == "60文字までです"
    assert ctl.board.messages == ()
    assert not (tmp_path / "board.json").exists()


def test_add_when_full(ctl, clock):
    fill(ctl, clock, MAX_MESSAGES)
    assert ctl.add("0", "21 件目") == FULL
    assert len(ctl.board.messages) == MAX_MESSAGES


def test_add_goes_back_to_the_first_page(ctl, clock):
    fill(ctl, clock, 8)
    ctl.handle_key(bc.KEY_RIGHT)
    assert ctl.view.page == 1
    ctl.add("0", "新着")
    assert ctl.view.page == 0


def test_add_fails_safely_when_the_file_cannot_be_written(tmp_path, clock):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    ctl = BoardController(blocker / "board.json", tmp_path / "s.json", tmp_path / "v.json", clock)
    assert ctl.add("0", "保存できない") == bc.SAVE_FAILED
    assert ctl.board.messages == ()
    assert any("保存できませんでした" in p for p in ctl.take_problems())


def test_known_recipients(ctl):
    assert [ctl.knows_recipient(k) for k in ("0", "1", "2", "3")] == [True, True, True, False]


# ---------- 声で消す（確認つき）----------


def test_request_delete_highlights_and_asks(ctl, clock):
    fill(ctl, clock, 3)   # 新しい順：伝言2、伝言1、伝言0
    assert ctl.request_delete(2) == "2番を削除します。よろしいですか"
    assert ctl.confirming is True
    target = ctl.board.messages[1]
    assert ctl.view.confirming == target.id == ctl.view.selected
    assert "2番を削除しますか" in ctl.view.banner
    assert ctl.view.banner_until is None   # 確認が終わるまで出し続ける


def test_confirm_yes_deletes_and_the_message_can_be_restored(ctl, clock, tmp_path):
    fill(ctl, clock, 3)
    ctl.request_delete(2)
    assert ctl.answer_confirmation(True) == bc.DELETED == "削除しました"
    assert texts(ctl) == ["伝言2", "伝言0"]
    assert ctl.confirming is False and ctl.view.selected is None
    assert ctl.view.restorable == 1
    assert "Insert で元に戻せます" in ctl.view.banner
    assert [m.text for m in saved(tmp_path).messages] == ["伝言2", "伝言0"]


def test_confirm_no_keeps_everything(ctl, clock):
    fill(ctl, clock, 3)
    ctl.request_delete(1)
    assert ctl.answer_confirmation(False) == bc.CANCELED
    assert len(ctl.board.messages) == 3
    assert ctl.view.confirming is None and ctl.view.banner == ""


def test_no_answer_cancels_without_deleting(ctl, clock):
    fill(ctl, clock, 3)
    ctl.request_delete(1)
    ctl.cancel_confirmation()
    assert len(ctl.board.messages) == 3 and ctl.confirming is False


def test_confirmation_expires_by_itself(ctl, clock):
    fill(ctl, clock, 3)
    ctl.request_delete(1)
    clock.advance(bc.CONFIRM_SECONDS + 1)
    ctl.tick()
    assert ctl.confirming is False and ctl.view.banner == "" and ctl.view.selected is None
    assert len(ctl.board.messages) == 3


@pytest.mark.parametrize("number, expected", [(None, bc.NO_NUMBER), (0, bc.NO_SUCH_NUMBER), (4, bc.NO_SUCH_NUMBER)])
def test_request_delete_with_a_bad_number(ctl, clock, number, expected):
    fill(ctl, clock, 3)
    assert ctl.request_delete(number) == expected
    assert ctl.confirming is False


def test_voice_numbers_refer_to_the_page_on_screen(ctl, clock):
    fill(ctl, clock, 8)               # 1 ページ目：伝言7〜3、2 ページ目：伝言2〜0
    ctl.handle_key(bc.KEY_RIGHT)
    ctl.request_delete(1)
    ctl.answer_confirmation(True)
    assert "伝言2" not in texts(ctl) and len(ctl.board.messages) == 7


# ---------- キーで消す（選んでから Delete）----------


def test_keypad_selects_then_delete_removes(ctl, clock):
    fill(ctl, clock, 3)
    assert ctl.handle_key(81) is None                     # テンキーの 3
    assert ctl.view.selected == ctl.board.messages[2].id
    assert ctl.handle_key(bc.KEY_DELETE) == bc.DELETED
    assert texts(ctl) == ["伝言2", "伝言1"]


def test_delete_without_selection_does_nothing(ctl, clock):
    fill(ctl, clock, 3)
    assert ctl.handle_key(bc.KEY_DELETE) is None
    assert len(ctl.board.messages) == 3


def test_selection_expires(ctl, clock):
    fill(ctl, clock, 3)
    ctl.handle_key(80)
    clock.advance(bc.SELECT_SECONDS + 1)
    ctl.tick()
    assert ctl.view.selected is None
    assert ctl.handle_key(bc.KEY_DELETE) is None
    assert len(ctl.board.messages) == 3


def test_keypad_number_without_a_card_is_ignored(ctl, clock):
    fill(ctl, clock, 2)
    ctl.handle_key(76)   # テンキーの 5
    assert ctl.view.selected is None


def test_selecting_another_card_moves_the_selection(ctl, clock):
    fill(ctl, clock, 3)
    ctl.handle_key(79)
    ctl.handle_key(80)
    ctl.handle_key(bc.KEY_DELETE)
    assert texts(ctl) == ["伝言2", "伝言0"]


def test_escape_clears_the_selection(ctl, clock):
    fill(ctl, clock, 3)
    ctl.handle_key(79)
    ctl.handle_key(bc.KEY_ESC)
    assert ctl.view.selected is None and ctl.handle_key(bc.KEY_DELETE) is None


def test_delete_key_does_not_override_a_voice_confirmation(ctl, clock):
    fill(ctl, clock, 3)
    ctl.request_delete(1)
    assert ctl.handle_key(bc.KEY_DELETE) is None
    assert len(ctl.board.messages) == 3 and ctl.confirming is True


def test_keypad_number_cancels_a_voice_confirmation_and_selects(ctl, clock):
    fill(ctl, clock, 3)
    ctl.request_delete(1)
    ctl.handle_key(80)
    assert ctl.confirming is False and ctl.view.selected == ctl.board.messages[1].id


# ---------- 元に戻す ----------


def test_undo_by_key_and_by_voice(ctl, clock):
    fill(ctl, clock, 3)
    ctl.handle_key(79)
    ctl.handle_key(bc.KEY_DELETE)
    ctl.handle_key(80)
    ctl.handle_key(bc.KEY_DELETE)
    assert ctl.handle_key(bc.KEY_INSERT) == bc.RESTORED == "戻しました"
    assert ctl.undo() == bc.RESTORED
    assert texts(ctl) == ["伝言2", "伝言1", "伝言0"]
    assert ctl.view.restorable == 0


def test_undo_with_nothing_to_restore(ctl):
    assert ctl.undo() == NOTHING_TO_RESTORE
    assert ctl.handle_key(bc.KEY_INSERT) == NOTHING_TO_RESTORE


def test_deleted_messages_are_forgotten_after_24_hours(ctl, clock):
    fill(ctl, clock, 2)
    ctl.handle_key(79)
    ctl.handle_key(bc.KEY_DELETE)
    clock.advance(25 * 3600)
    ctl.tick()
    assert ctl.view.restorable == 0
    assert ctl.undo() == NOTHING_TO_RESTORE


# ---------- ページ ----------


def test_arrows_move_between_pages_and_stop_at_the_ends(ctl, clock):
    fill(ctl, clock, 12)   # 3 ページ
    pages = []
    for code in (bc.KEY_RIGHT, bc.KEY_RIGHT, bc.KEY_RIGHT, bc.KEY_LEFT, bc.KEY_PAGEUP, bc.KEY_PAGEUP, bc.KEY_PAGEDOWN):
        ctl.handle_key(code)
        pages.append(ctl.view.page)
    assert pages == [1, 2, 2, 1, 0, 0, 1]


def test_keypad_numbers_count_from_the_top_of_the_current_page(ctl, clock):
    fill(ctl, clock, 8)
    ctl.handle_key(bc.KEY_RIGHT)
    ctl.handle_key(79)
    assert ctl.view.selected == ctl.board.messages[5].id


def test_page_goes_back_to_the_first_after_being_left_alone(ctl, clock):
    fill(ctl, clock, 8)
    ctl.handle_key(bc.KEY_RIGHT)
    clock.advance(bc.IDLE_SECONDS - 5)
    ctl.tick()
    assert ctl.view.page == 1
    clock.advance(10)
    ctl.tick()
    assert ctl.view.page == 0


def test_page_is_clamped_after_deleting_the_last_message_on_the_last_page(ctl, clock):
    fill(ctl, clock, 6)   # 2 ページ目は 1 件
    ctl.handle_key(bc.KEY_RIGHT)
    ctl.handle_key(79)
    ctl.handle_key(bc.KEY_DELETE)
    assert ctl.view.page == 0


# ---------- 画面に渡す状態 ----------


def test_view_file_follows_the_state(ctl, clock, tmp_path):
    fill(ctl, clock, 8)
    ctl.handle_key(bc.KEY_RIGHT)
    ctl.handle_key(80)
    got = read_view(tmp_path / "run" / "board-view.json")
    assert (got["page"], got["selected"]) == (1, ctl.board.messages[6].id)


def test_banner_expires(ctl, clock):
    fill(ctl, clock, 2)
    ctl.handle_key(79)
    ctl.handle_key(bc.KEY_DELETE)
    assert ctl.view.banner
    clock.advance(bc.BANNER_SECONDS + 1)
    ctl.tick()
    assert ctl.view.banner == ""


# ---------- 設定・ファイルの変更 ----------


def test_settings_are_reloaded_when_the_file_changes(tmp_path, clock):
    path = tmp_path / "board-settings.json"
    ctl = make(tmp_path, clock)
    assert ctl.knows_recipient("3") is False
    path.write_text(json.dumps({"people": [{"key": "3", "name": "たろう", "color": "#57D977"}]}), encoding="utf-8")
    import os
    os.utime(path, (clock.now.timestamp() + 5, clock.now.timestamp() + 5))
    assert ctl.knows_recipient("3") is True


def test_broken_settings_are_reported_and_the_default_stays(tmp_path, clock):
    (tmp_path / "board-settings.json").write_text("{", encoding="utf-8")
    ctl = make(tmp_path, clock)
    assert ctl.knows_recipient("0") is True and ctl.knows_recipient("1") is False
    assert any("宛先の設定を読めませんでした" in p for p in ctl.take_problems())
    assert ctl.take_problems() == []


def test_a_board_file_edited_by_hand_is_picked_up(ctl, clock, tmp_path):
    ctl.add("0", "もとの伝言")
    path = tmp_path / "board.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["messages"][0]["text"] = "直した伝言"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    import os
    os.utime(path, (clock.now.timestamp() + 5, clock.now.timestamp() + 5))
    ctl.tick()
    assert texts(ctl) == ["直した伝言"]


def test_a_broken_board_file_is_reported_and_does_not_crash(tmp_path, clock):
    (tmp_path / "board.json").write_text("{", encoding="utf-8")
    ctl = make(tmp_path, clock)
    assert ctl.board.messages == ()
    assert any("伝言を読めませんでした" in p for p in ctl.take_problems())


def test_key_codes_are_what_the_design_says():
    assert bc.DIGIT_KEYS[2] == "1" and bc.DIGIT_KEYS[10] == "9" and bc.DIGIT_KEYS[11] == "0"
    assert bc.KEYPAD_NUMBERS == {79: 1, 80: 2, 81: 3, 75: 4, 76: 5}
    assert bc.KEY_DELETE == 111 and bc.KEY_INSERT == 110
    assert {bc.KEY_ESC, bc.KEY_LEFT, bc.KEY_RIGHT, bc.KEY_PAGEUP, bc.KEY_PAGEDOWN, bc.KEY_UP, bc.KEY_DOWN} <= bc.BOARD_CODES
    assert (bc.KEY_UP, bc.KEY_DOWN) == (103, 108)


# ---------- 上下の矢印で選ぶ（テンキーの無いキーボード向け）----------


def test_down_arrow_selects_the_first_card_then_moves_down(ctl, clock):
    fill(ctl, clock, 3)
    ids = [m.id for m in ctl.board.messages]     # 画面の 1 番、2 番、…の順
    ctl.handle_key(bc.KEY_DOWN)
    assert ctl.view.selected == ids[0]
    ctl.handle_key(bc.KEY_DOWN)
    assert ctl.view.selected == ids[1]
    ctl.handle_key(bc.KEY_UP)
    assert ctl.view.selected == ids[0]


def test_up_arrow_with_nothing_selected_selects_the_first_card(ctl, clock):
    fill(ctl, clock, 3)
    ctl.handle_key(bc.KEY_UP)
    assert ctl.view.selected == ctl.board.messages[0].id


def test_arrows_stop_at_the_ends_of_the_page(ctl, clock):
    fill(ctl, clock, 2)
    for _ in range(4):
        ctl.handle_key(bc.KEY_DOWN)
    assert ctl.view.selected == ctl.board.messages[1].id      # 一番下の 2 番
    for _ in range(4):
        ctl.handle_key(bc.KEY_UP)
    assert ctl.view.selected == ctl.board.messages[0].id


def test_arrows_then_delete_removes_the_selected_card(ctl, clock):
    fill(ctl, clock, 3)
    ctl.handle_key(bc.KEY_DOWN)
    ctl.handle_key(bc.KEY_DOWN)
    assert ctl.handle_key(bc.KEY_DELETE) == bc.DELETED
    assert texts(ctl) == ["伝言2", "伝言0"]   # 2 番（伝言1）が消える


def test_arrow_after_the_selection_expired_starts_again_from_the_first_card(ctl, clock):
    fill(ctl, clock, 3)
    ctl.handle_key(bc.KEY_DOWN)
    ctl.handle_key(bc.KEY_DOWN)
    clock.advance(bc.SELECT_SECONDS + 1)
    ctl.handle_key(bc.KEY_DOWN)
    assert ctl.view.selected == ctl.board.messages[0].id


def test_each_arrow_press_extends_the_time_to_press_delete(ctl, clock):
    fill(ctl, clock, 3)
    ctl.handle_key(bc.KEY_DOWN)
    clock.advance(bc.SELECT_SECONDS - 1)
    ctl.handle_key(bc.KEY_DOWN)
    clock.advance(bc.SELECT_SECONDS - 1)
    assert ctl.handle_key(bc.KEY_DELETE) == bc.DELETED


def test_arrows_do_nothing_while_a_voice_confirmation_is_waiting(ctl, clock):
    fill(ctl, clock, 3)
    ctl.request_delete(1)
    target = ctl.view.confirming
    ctl.handle_key(bc.KEY_DOWN)
    assert ctl.view.confirming == target and ctl.view.selected == target


def test_arrows_with_an_empty_board_do_nothing(ctl, clock):
    ctl.handle_key(bc.KEY_DOWN)
    assert ctl.view.selected is None


# ---------- 全部消す（Ctrl+Delete と声）----------


def ctrl_delete(ctl):
    return ctl.handle_key(bc.KEY_DELETE, ctrl=True)


def test_ctrl_delete_asks_first_and_deletes_nothing_yet(ctl, clock):
    fill(ctl, clock, 3)
    assert ctrl_delete(ctl) is None
    assert len(ctl.board.messages) == 3
    assert ctl.view.clear_all_until is not None
    assert "全部で 3 件を消します。もう一度 Delete で実行します。" in ctl.view.banner
    assert ctl.view.banner.endswith("（中止したい場合は Esc）")
    assert ctl.confirming is False        # 声の返事を待つ状態にはならない


def test_delete_within_five_seconds_deletes_everything(ctl, clock):
    fill(ctl, clock, 3)
    ctrl_delete(ctl)
    clock.advance(bc.CLEAR_ALL_SECONDS - 1)
    assert ctl.handle_key(bc.KEY_DELETE) == bc.DELETED_ALL
    assert ctl.board.messages == () and ctl.view.restorable == 3
    assert ctl.view.clear_all_until is None and ctl.view.banner == bc.BANNER_DELETED_ALL


def test_letting_five_seconds_pass_deletes_nothing(ctl, clock):
    fill(ctl, clock, 3)
    ctrl_delete(ctl)
    clock.advance(bc.CLEAR_ALL_SECONDS + 1)
    ctl.tick()
    assert ctl.view.clear_all_until is None and ctl.view.banner == ""
    assert ctl.handle_key(bc.KEY_DELETE) is None          # 期限後の Delete は、何も消さない
    assert len(ctl.board.messages) == 3


def test_delete_pressed_after_the_time_is_up_even_without_a_tick_deletes_nothing(ctl, clock):
    fill(ctl, clock, 3)
    ctrl_delete(ctl)
    clock.advance(bc.CLEAR_ALL_SECONDS + 1)
    assert ctl.handle_key(bc.KEY_DELETE) is None
    assert len(ctl.board.messages) == 3


def test_escape_cancels_clearing_everything(ctl, clock):
    fill(ctl, clock, 3)
    ctrl_delete(ctl)
    assert ctl.handle_key(bc.KEY_ESC) is None
    assert ctl.view.clear_all_until is None and ctl.view.banner == ""
    assert ctl.handle_key(bc.KEY_DELETE) is None
    assert len(ctl.board.messages) == 3


@pytest.mark.parametrize("code", [bc.KEY_DOWN, bc.KEY_UP, bc.KEY_RIGHT, bc.KEY_INSERT, 79])
def test_any_other_key_cancels_clearing_everything_without_doing_its_own_job(ctl, clock, code):
    fill(ctl, clock, 3)
    ctrl_delete(ctl)
    ctl.handle_key(code)
    assert ctl.view.clear_all_until is None and ctl.view.selected is None
    assert len(ctl.board.messages) == 3


def test_pressing_ctrl_alone_does_not_cancel_it(ctl, clock):
    fill(ctl, clock, 3)
    ctrl_delete(ctl)
    ctl.handle_key(bc.KEY_LEFTCTRL)
    ctl.handle_key(bc.KEY_RIGHTCTRL)
    assert ctl.view.clear_all_until is not None


def test_ctrl_delete_twice_also_confirms(ctl, clock):
    fill(ctl, clock, 2)
    ctrl_delete(ctl)
    assert ctrl_delete(ctl) == bc.DELETED_ALL


def test_plain_delete_without_ctrl_never_deletes_everything(ctl, clock):
    fill(ctl, clock, 3)
    assert ctl.handle_key(bc.KEY_DELETE) is None
    assert ctl.view.clear_all_until is None and len(ctl.board.messages) == 3


def test_ctrl_delete_with_no_messages_says_so(ctl):
    assert ctrl_delete(ctl) == "消す伝言はありません"
    assert ctl.view.clear_all_until is None


def test_ctrl_delete_is_ignored_while_a_voice_confirmation_waits(ctl, clock):
    fill(ctl, clock, 3)
    ctl.request_delete(1)
    assert ctrl_delete(ctl) is None
    assert ctl.view.clear_all_until is None and ctl.confirming is True


def test_ctrl_delete_clears_a_card_selection(ctl, clock):
    fill(ctl, clock, 3)
    ctl.handle_key(bc.KEY_DOWN)
    ctrl_delete(ctl)
    assert ctl.view.selected is None


def test_new_message_cancels_clearing_everything(ctl, clock):
    fill(ctl, clock, 2)
    ctrl_delete(ctl)
    ctl.add("0", "新着")
    assert ctl.view.clear_all_until is None and ctl.handle_key(bc.KEY_DELETE) is None
    assert len(ctl.board.messages) == 3


def test_voice_delete_all_asks_with_the_count_then_deletes_after_yes(ctl, clock):
    fill(ctl, clock, 4)
    assert ctl.request_delete_all() == "全部で4件を削除します。よろしいですか"
    assert ctl.confirming is True and ctl.view.confirming_all is True
    assert len(ctl.board.messages) == 4
    assert ctl.answer_confirmation(True) == bc.DELETED_ALL
    assert ctl.board.messages == () and ctl.confirming is False


def test_voice_delete_all_is_cancelled_by_no(ctl, clock):
    fill(ctl, clock, 4)
    ctl.request_delete_all()
    assert ctl.answer_confirmation(False) == bc.CANCELED
    assert len(ctl.board.messages) == 4 and ctl.confirming is False


def test_voice_delete_all_is_dropped_when_no_answer_comes(ctl, clock):
    fill(ctl, clock, 4)
    ctl.request_delete_all()
    ctl.cancel_confirmation()
    assert ctl.confirming is False and len(ctl.board.messages) == 4


def test_voice_delete_all_expires_with_the_other_confirmations(ctl, clock):
    fill(ctl, clock, 4)
    ctl.request_delete_all()
    clock.advance(bc.CONFIRM_SECONDS + 1)
    ctl.tick()
    assert ctl.confirming is False and len(ctl.board.messages) == 4


def test_delete_key_does_not_delete_everything_during_a_voice_confirmation(ctl, clock):
    fill(ctl, clock, 3)
    ctl.request_delete_all()
    assert ctl.handle_key(bc.KEY_DELETE) is None
    assert len(ctl.board.messages) == 3 and ctl.confirming is True


def test_voice_delete_all_with_no_messages(ctl):
    assert ctl.request_delete_all() == "消す伝言はありません"
    assert ctl.confirming is False


def test_undo_after_delete_all_restores_everything_and_says_how_many(ctl, clock):
    fill(ctl, clock, 3)
    ctrl_delete(ctl)
    ctl.handle_key(bc.KEY_DELETE)
    assert ctl.handle_key(bc.KEY_INSERT) == "3件戻しました"
    assert texts(ctl) == ["伝言2", "伝言1", "伝言0"] and ctl.view.restorable == 0


def test_undo_of_a_single_deletion_still_says_the_short_phrase(ctl, clock):
    fill(ctl, clock, 3)
    ctl.handle_key(bc.KEY_DOWN)
    ctl.handle_key(bc.KEY_DELETE)
    assert ctl.undo() == bc.RESTORED


def test_ctrl_keys_are_read_for_the_board():
    assert {bc.KEY_LEFTCTRL, bc.KEY_RIGHTCTRL} <= bc.BOARD_CODES
    assert (bc.KEY_LEFTCTRL, bc.KEY_RIGHTCTRL) == (29, 97)
