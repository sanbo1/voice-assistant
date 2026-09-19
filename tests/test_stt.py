from voice_assistant.stt import join_japanese_words


def test_joins_japanese_words():
    assert join_japanese_words("今日 の 天気 を 教え て") == "今日の天気を教えて"


def test_keeps_space_between_ascii_words():
    assert join_japanese_words("hey jarvis") == "hey jarvis"


def test_removes_space_next_to_japanese():
    assert join_japanese_words("hey jarvis 今日 の 天気") == "hey jarvis今日の天気"
    assert join_japanese_words("明日 は ok です") == "明日はokです"


def test_empty_and_extra_spaces():
    assert join_japanese_words("") == ""
    assert join_japanese_words("  今日   は  ") == "今日は"
