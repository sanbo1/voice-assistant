from tools.evdev_keys import (
    EV_KEY,
    EVENT,
    KEY_SPACE,
    SpaceTracker,
    SpaceWatcher,
    find_keyboards,
    parse_event,
    supports_key,
)

DEV = "keyboard-0"


def event_bytes(code, value, kind=EV_KEY):
    return EVENT.pack(0, 0, kind, code, value)


# ---------- イベントの読み取り ----------


def test_parse_event():
    assert parse_event(event_bytes(KEY_SPACE, 1)) == (EV_KEY, KEY_SPACE, 1)


def test_parse_event_rejects_wrong_length():
    assert parse_event(b"\x00" * 5) is None
    assert parse_event(b"") is None


# ---------- 装置がスペースキーを送れるか ----------

# capabilities/key は、16 進の語を空白で区切ったもの（上位の語が先）。64 ビットの語では、
# KEY_SPACE（57）は、いちばん下位の語の 57 ビット目
SPACE_ONLY = format(1 << KEY_SPACE, "x")


def test_supports_key_in_the_lowest_word():
    assert supports_key(SPACE_ONLY, KEY_SPACE, word_bits=64) is True
    assert supports_key("0", KEY_SPACE, word_bits=64) is False


def test_supports_key_reads_the_lowest_word_even_with_higher_words():
    assert supports_key(f"10000 0 {SPACE_ONLY}", KEY_SPACE, word_bits=64) is True
    assert supports_key("10000 0 0", KEY_SPACE, word_bits=64) is False


def test_supports_key_in_a_higher_word():
    """語が 2 つのとき、先頭の語は 64〜127 番のキー。"1 0" なら 64 番だけ。"""
    assert supports_key("1 0", 64, word_bits=64) is True
    assert supports_key("1 0", 65, word_bits=64) is False
    assert supports_key("1 0", KEY_SPACE, word_bits=64) is False


def test_supports_key_beyond_the_listed_words():
    assert supports_key(SPACE_ONLY, 100, word_bits=64) is False
    assert supports_key("", KEY_SPACE, word_bits=64) is False


def test_supports_key_with_32_bit_words():
    """32 ビットの語（32 ビットの OS）でも、読み方が合う。57 番は、下位から 2 つ目の語の 25 ビット目。"""
    assert supports_key(f"{1 << 25:x} 0", KEY_SPACE, word_bits=32) is True
    assert supports_key("0 0", KEY_SPACE, word_bits=32) is False


def make_input_tree(tmp_path, devices):
    """sysfs の入力装置を模した、フォルダを作る。devices は {名前: capabilities/key の中身}。"""
    sys_input = tmp_path / "sys"
    for name, capabilities in devices.items():
        folder = sys_input / name / "device" / "capabilities"
        folder.mkdir(parents=True)
        (folder / "key").write_text(capabilities + "\n")
    return sys_input


def test_find_keyboards_lists_devices_that_have_space(tmp_path):
    sys_input = make_input_tree(tmp_path, {
        "event0": SPACE_ONLY,   # キーボード
        "event1": "0",          # マウス（キーなし）
        "event2": "1f0000 0 0",  # スペースを持たない（メディアキーなど）
        "event3": SPACE_ONLY,   # もう 1 台
    })
    got = find_keyboards(sys_input, tmp_path / "dev", word_bits=64)
    assert got == [tmp_path / "dev" / "event0", tmp_path / "dev" / "event3"]


def test_find_keyboards_skips_devices_without_a_readable_capability(tmp_path):
    sys_input = make_input_tree(tmp_path, {"event0": SPACE_ONLY})
    (sys_input / "event5").mkdir()   # capabilities が無い（読めない）装置
    (sys_input / "mouse0").mkdir()   # event ではない名前
    assert find_keyboards(sys_input, tmp_path / "dev", word_bits=64) == [tmp_path / "dev" / "event0"]


def test_find_keyboards_with_an_empty_tree(tmp_path):
    assert find_keyboards(tmp_path / "ない", tmp_path / "dev", word_bits=64) == []


# ---------- 押した・離した ----------


def test_press_and_release():
    tracker = SpaceTracker()
    assert tracker.feed(DEV, EV_KEY, KEY_SPACE, 1) == "press"
    assert tracker.feed(DEV, EV_KEY, KEY_SPACE, 0) == "release"


def test_auto_repeat_is_ignored():
    """押し続けて出る自動リピート（値 2）は、変化として扱わない。"""
    tracker = SpaceTracker()
    tracker.feed(DEV, EV_KEY, KEY_SPACE, 1)
    assert [tracker.feed(DEV, EV_KEY, KEY_SPACE, 2) for _ in range(5)] == [None] * 5
    assert tracker.feed(DEV, EV_KEY, KEY_SPACE, 0) == "release"


def test_other_keys_are_ignored():
    """スペース以外のキーは、押されても何も起こさない（内容も見ない）。"""
    tracker = SpaceTracker()
    assert tracker.feed(DEV, EV_KEY, 30, 1) is None   # a
    assert tracker.feed(DEV, EV_KEY, 28, 1) is None   # Enter
    assert tracker.feed(DEV, 2, KEY_SPACE, 1) is None  # キーではない種類のイベント（マウスの動きなど）


def test_pressing_twice_without_release_is_one_press():
    tracker = SpaceTracker()
    assert tracker.feed(DEV, EV_KEY, KEY_SPACE, 1) == "press"
    assert tracker.feed(DEV, EV_KEY, KEY_SPACE, 1) is None


def test_release_without_press_is_ignored():
    assert SpaceTracker().feed(DEV, EV_KEY, KEY_SPACE, 0) is None


def test_two_devices_count_as_held_until_both_are_released():
    tracker = SpaceTracker()
    assert tracker.feed("a", EV_KEY, KEY_SPACE, 1) == "press"
    assert tracker.feed("b", EV_KEY, KEY_SPACE, 1) is None
    assert tracker.feed("a", EV_KEY, KEY_SPACE, 0) is None
    assert tracker.feed("b", EV_KEY, KEY_SPACE, 0) == "release"


def test_unplugging_while_held_releases():
    tracker = SpaceTracker()
    tracker.feed(DEV, EV_KEY, KEY_SPACE, 1)
    assert tracker.forget(DEV) == "release"
    assert tracker.forget(DEV) is None


def test_unplugging_while_not_held_does_nothing():
    assert SpaceTracker().forget(DEV) is None


# ---------- 読んだバイト列の処理 ----------


def drain(watcher):
    got = []
    while not watcher.events.empty():
        got.append(watcher.events.get_nowait())
    return got


def test_watcher_turns_events_into_press_and_release():
    watcher = SpaceWatcher(find=lambda: [])
    watcher.handle(DEV, event_bytes(KEY_SPACE, 1) + event_bytes(KEY_SPACE, 0))
    assert drain(watcher) == ["press", "release"]


def test_watcher_handles_several_events_in_one_read():
    """1 回の読み取りに、複数のイベント（同期イベントなどを含む）が入っていても、順に処理する。"""
    watcher = SpaceWatcher(find=lambda: [])
    syn = event_bytes(0, 0, kind=0)
    data = syn + event_bytes(30, 1) + event_bytes(KEY_SPACE, 1) + syn + event_bytes(KEY_SPACE, 2) \
        + event_bytes(KEY_SPACE, 0) + syn
    watcher.handle(DEV, data)
    assert drain(watcher) == ["press", "release"]


def test_watcher_ignores_a_truncated_tail():
    watcher = SpaceWatcher(find=lambda: [])
    watcher.handle(DEV, event_bytes(KEY_SPACE, 1) + b"\x01\x02\x03")
    assert drain(watcher) == ["press"]


def test_watcher_never_reports_other_keys():
    watcher = SpaceWatcher(find=lambda: [])
    watcher.handle(DEV, b"".join(event_bytes(code, 1) for code in (16, 17, 18, 28, 29)))
    assert drain(watcher) == []
