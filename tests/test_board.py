import json
from datetime import datetime, timedelta

import pytest

from voice_assistant.board import (
    EMPTY,
    FULL_FOR_BATCH,
    FULL,
    MAX_CHARS,
    MAX_MESSAGES,
    NOTHING_TO_RESTORE,
    TOO_LONG,
    UNDO_HOURS,
    Board,
    BoardSettings,
    Person,
    View,
    add_message,
    counts_by_recipient,
    delete_all,
    delete_message,
    load_board,
    load_settings,
    page_count,
    page_of,
    parse_settings,
    purge,
    read_view,
    restore_last,
    save_board,
    write_view,
)

NOW = datetime(2026, 10, 8, 18, 0, 0)


def later(minutes):
    return NOW + timedelta(minutes=minutes)


def board_with(*texts, to="0"):
    board = Board()
    for number, text in enumerate(texts):
        board, error = add_message(board, to, text, later(number))
        assert error is None
    return board


# ---------- 足す ----------


def test_add_keeps_the_newest_first():
    board = board_with("一つめ", "二つめ", "三つめ")
    assert [m.text for m in board.messages] == ["三つめ", "二つめ", "一つめ"]
    assert [m.id for m in board.messages] == [3, 2, 1]


def test_add_records_the_recipient_and_time():
    board, error = add_message(Board(), "2", "牛乳を買ってきてください", NOW)
    assert error is None
    message = board.messages[0]
    assert (message.to, message.created) == ("2", "2026-10-08T18:00:00")


def test_add_cleans_up_whitespace():
    board, _ = add_message(Board(), "0", "  明日は\n早く  帰ります ", NOW)
    assert board.messages[0].text == "明日は 早く 帰ります"


def test_add_rejects_empty_text():
    board, error = add_message(Board(), "0", "   ", NOW)
    assert error == EMPTY
    assert board.messages == ()


def test_add_accepts_exactly_the_limit_and_rejects_one_more():
    board, error = add_message(Board(), "0", "あ" * MAX_CHARS, NOW)
    assert error is None
    board, error = add_message(Board(), "0", "あ" * (MAX_CHARS + 1), NOW)
    assert error == TOO_LONG == "60文字までです"
    assert board.messages == ()


def test_add_rejects_when_full_and_keeps_the_existing_messages():
    board = board_with(*[f"伝言{n}" for n in range(MAX_MESSAGES)])
    assert len(board.messages) == MAX_MESSAGES
    same, error = add_message(board, "0", "21 件目", later(99))
    assert error == FULL
    assert same == board


def test_ids_are_never_reused():
    board = board_with("a", "b")
    board = delete_message(board, 2, NOW)
    board, _ = add_message(board, "0", "c", later(5))
    assert sorted(m.id for m in board.messages) == [1, 3]


# ---------- 消す・戻す ----------


def test_delete_moves_the_message_to_the_undo_list():
    board = delete_message(board_with("a", "b"), 2, later(10))
    assert [m.text for m in board.messages] == ["a"]
    assert [(m.text, m.deleted_at) for m in board.deleted] == [("b", "2026-10-08T18:10:00")]


def test_delete_unknown_id_changes_nothing():
    board = board_with("a")
    assert delete_message(board, 99, NOW) == board


def test_restore_puts_the_message_back_in_its_time_order():
    board = delete_message(board_with("古い", "真ん中", "新しい"), 2, later(10))
    board, restored, error = restore_last(board, later(11))
    assert error is None
    assert [(m.text, m.deleted_at) for m in restored] == [("真ん中", None)]
    assert [m.text for m in board.messages] == ["新しい", "真ん中", "古い"]
    assert board.deleted == ()


def test_restore_returns_the_last_deleted_first():
    board = board_with("a", "b", "c")
    board = delete_message(board, 1, later(10))
    board = delete_message(board, 3, later(11))
    board, first, _ = restore_last(board, later(12))
    board, second, _ = restore_last(board, later(13))
    assert (first[0].text, second[0].text) == ("c", "a")


def test_restore_with_nothing_deleted():
    board, restored, error = restore_last(board_with("a"), NOW)
    assert (restored, error) == ((), NOTHING_TO_RESTORE)


def test_restore_is_refused_when_full():
    board = board_with(*[f"伝言{n}" for n in range(MAX_MESSAGES)])
    board = delete_message(board, 1, later(30))
    board, _ = add_message(board, "0", "穴を埋める", later(31))
    assert len(board.messages) == MAX_MESSAGES
    same, restored, error = restore_last(board, later(32))
    assert (restored, error) == ((), FULL)
    assert len(same.deleted) == 1   # 消した伝言は、残ったまま


def test_deleted_messages_expire_after_24_hours():
    board = delete_message(board_with("a"), 1, NOW)
    assert purge(board, NOW + timedelta(hours=UNDO_HOURS - 1)).deleted == board.deleted
    assert purge(board, NOW + timedelta(hours=UNDO_HOURS + 1)).deleted == ()


def test_restore_ignores_expired_deletions():
    board = delete_message(board_with("a"), 1, NOW)
    _, restored, error = restore_last(board, NOW + timedelta(hours=UNDO_HOURS + 1))
    assert (restored, error) == ((), NOTHING_TO_RESTORE)


# ---------- ページ ----------


def test_page_count():
    assert [page_count(n) for n in (0, 1, 5, 6, 10, 11, 20)] == [1, 1, 1, 2, 2, 3, 4]


def test_page_of_slices_by_five_and_clamps():
    board = board_with(*[str(n) for n in range(12)])   # 新しい順に 11, 10, …, 0
    assert [m.text for m in page_of(board, 0)] == ["11", "10", "9", "8", "7"]
    assert [m.text for m in page_of(board, 1)] == ["6", "5", "4", "3", "2"]
    assert [m.text for m in page_of(board, 2)] == ["1", "0"]
    assert page_of(board, 9) == page_of(board, 2)     # 範囲外は、最後のページ
    assert page_of(board, -3) == page_of(board, 0)


def test_counts_cover_all_pages():
    board = Board()
    for number in range(8):
        board, _ = add_message(board, "1" if number < 6 else "2", f"伝言{number}", later(number))
    assert counts_by_recipient(board) == {"1": 6, "2": 2}


# ---------- 保存 ----------


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "board.json"
    board = delete_message(board_with("日本語の伝言", "二つめ"), 1, later(5))
    save_board(path, board)
    assert load_board(path) == board
    assert "日本語の伝言" in path.read_text(encoding="utf-8")   # \u の形にしない（人が読める）


def test_load_missing_file_is_empty(tmp_path):
    assert load_board(tmp_path / "ない.json") == Board()


def test_load_broken_file_reports_it(tmp_path):
    path = tmp_path / "board.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_board(path)
    path.write_text(json.dumps({"messages": [{"id": 1}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="形が違います"):
        load_board(path)


def test_save_leaves_no_temporary_file(tmp_path):
    save_board(tmp_path / "board.json", board_with("a"))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["board.json"]


def test_next_id_never_goes_backwards_after_loading(tmp_path):
    path = tmp_path / "board.json"
    path.write_text(json.dumps({"next_id": 1, "messages": [{"id": 7, "to": "0", "text": "a",
                                                            "created": "2026-10-08T18:00:00"}]}), encoding="utf-8")
    board, _ = add_message(load_board(path), "0", "b", later(1))
    assert max(m.id for m in board.messages) == 8


# ---------- 宛先の設定 ----------

SETTINGS = {
    "people": [
        {"key": "1", "name": "お父さん", "color": "#4C9AFF", "aliases": ["父", "パパ"]},
        {"key": "2", "name": "お母さん", "color": "#FF6B81", "aliases": ["母", "ママ"]},
        {"key": "3", "name": "たろう", "color": "#57D977"},
    ],
    "everyone": {"key": "0", "name": "みんな", "color": "#C0C4C8"},
}


def test_parse_settings():
    settings = parse_settings(SETTINGS)
    assert [p.name for p in settings.people] == ["お父さん", "お母さん", "たろう"]
    assert settings.person("2").color == "#FF6B81"
    assert settings.person("0").name == "みんな"
    assert settings.person("9") is None


def test_settings_default_has_only_everyone():
    settings = BoardSettings()
    assert settings.people == ()
    assert settings.person("0").name == "みんな"


def test_people_can_be_added_up_to_nine():
    data = {"people": [{"key": str(n), "name": f"人{n}", "color": "#112233"} for n in range(1, 10)]}
    assert len(parse_settings(data).people) == 9


@pytest.mark.parametrize("people, message", [
    ([{"key": "0", "name": "a", "color": "#112233"}], "key"),                      # 0 は、みんな宛に予約
    ([{"key": "10", "name": "a", "color": "#112233"}], "key"),
    ([{"key": "1", "name": "", "color": "#112233"}], "name"),
    ([{"key": "1", "name": "a", "color": "red"}], "color"),
    ([{"key": "1", "name": "a", "color": "#112233", "aliases": "x"}], "aliases"),
    ([{"key": "1", "name": "a", "color": "#112233"}, {"key": "1", "name": "b", "color": "#112233"}], "key が重なって"),
    ([{"key": "1", "name": "a", "color": "#112233"}, {"key": "2", "name": "a", "color": "#112233"}], "重なって"),
    (["a"], "形が違います"),
])
def test_parse_settings_rejects_bad_people(people, message):
    with pytest.raises(ValueError, match=message):
        parse_settings({"people": people})


def test_find_by_name_uses_aliases_and_prefers_longer_names():
    settings = parse_settings({"people": [
        {"key": "1", "name": "お父さん", "color": "#112233", "aliases": ["父"]},
        {"key": "2", "name": "お父さんの妹", "color": "#112233"},
    ]})
    assert settings.find_by_name("父に伝言").key == "1"
    assert settings.find_by_name("お父さんの妹に伝言").key == "2"   # 長い名前を優先
    assert settings.find_by_name("誰もいない") is None


def test_load_settings_missing_file_gives_the_default(tmp_path):
    assert load_settings(tmp_path / "ない.json") == BoardSettings()


def test_load_settings_reports_a_broken_file(tmp_path):
    path = tmp_path / "board-settings.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON"):
        load_settings(path)


def test_example_settings_file_is_valid():
    from voice_assistant.board import PROJECT_ROOT

    example = PROJECT_ROOT / "config" / "board-settings.example.json"
    settings = load_settings(example)
    assert len(settings.people) >= 2


# ---------- 画面に渡す表示の状態 ----------


def test_view_round_trip(tmp_path):
    path = tmp_path / "run" / "board-view.json"
    write_view(path, View(page=2, selected=5, banner="消しました", restorable=1))
    got = read_view(path)
    assert (got["page"], got["selected"], got["banner"], got["restorable"]) == (2, 5, "消しました", 1)


def test_read_view_defaults_when_missing_or_broken(tmp_path):
    assert read_view(tmp_path / "ない.json")["page"] == 0
    assert read_view(None)["page"] == 0
    path = tmp_path / "broken.json"
    path.write_text("[1, 2]", encoding="utf-8")
    assert read_view(path)["page"] == 0


def test_write_view_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    write_view(blocker / "board-view.json", View())   # 親がファイルで、作れない。例外にならない
    write_view(None, View())


def test_person_names_include_aliases():
    assert Person("1", "お父さん", "#112233", ("父",)).names == ("お父さん", "父")


# ---------- 全部消す・まとめて戻す（2026-10-08）----------


def test_delete_all_moves_everything_to_the_undo_list():
    board = delete_all(board_with("a", "b", "c"), later(10))
    assert board.messages == ()
    assert sorted(m.text for m in board.deleted) == ["a", "b", "c"]
    assert {m.deleted_at for m in board.deleted} == {"2026-10-08T18:10:00"}


def test_delete_all_on_an_empty_board_changes_nothing():
    board = Board()
    assert delete_all(board, NOW) is board


def test_restore_after_delete_all_brings_everything_back_at_once():
    board = delete_all(board_with("古い", "真ん中", "新しい"), later(10))
    board, restored, error = restore_last(board, later(11))
    assert error is None and len(restored) == 3
    assert [m.text for m in board.messages] == ["新しい", "真ん中", "古い"]
    assert board.deleted == () and all(m.batch is None and m.deleted_at is None for m in board.messages)


def test_restore_after_delete_all_does_not_take_the_earlier_single_deletions():
    board = delete_message(board_with("a", "b", "c"), 1, later(5))
    board = delete_all(board, later(10))
    board, restored, _ = restore_last(board, later(11))
    assert sorted(m.text for m in restored) == ["b", "c"]
    assert [m.text for m in board.deleted] == ["a"]       # 先に 1 件だけ消した分は、そのまま


def test_single_deletions_in_the_same_second_are_still_restored_one_by_one():
    board = board_with("a", "b")
    board = delete_message(board, 1, later(10))
    board = delete_message(board, 2, later(10))
    board, restored, _ = restore_last(board, later(11))
    assert len(restored) == 1


def test_batch_restore_is_all_or_nothing_when_it_would_not_fit():
    board = delete_all(board_with(*[f"伝言{n}" for n in range(5)]), later(10))
    for n in range(MAX_MESSAGES - 3):
        board, _ = add_message(board, "0", f"新しい{n}", later(11))
    same, restored, error = restore_last(board, later(12))
    assert (restored, error) == ((), FULL_FOR_BATCH)
    assert len(same.messages) == MAX_MESSAGES - 3 and len(same.deleted) == 5


def test_batch_mark_survives_saving_and_loading(tmp_path):
    board = delete_all(board_with("a", "b"), later(10))
    save_board(tmp_path / "board.json", board)
    loaded = load_board(tmp_path / "board.json")
    assert {m.batch for m in loaded.deleted} == {"2026-10-08T18:10:00"}
    assert len(restore_last(loaded, later(11))[1]) == 2


def test_old_files_without_a_batch_mark_still_load(tmp_path):
    old = {"version": 1, "next_id": 2, "messages": [],
           "deleted": [{"id": 1, "to": "0", "text": "a", "created": "2026-10-08T18:00:00",
                        "deleted_at": "2026-10-08T18:05:00"}]}
    (tmp_path / "board.json").write_text(json.dumps(old), encoding="utf-8")
    assert load_board(tmp_path / "board.json").deleted[0].batch is None
