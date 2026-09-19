from voice_assistant.ai import Message
from voice_assistant.history import ConversationHistory


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_empty_history():
    assert ConversationHistory().messages() == []


def test_keeps_turns_in_order():
    history = ConversationHistory(clock=FakeClock())
    history.add("富士山の高さは", "3776メートルです。")
    history.add("何県にある？", "静岡県と山梨県です。")
    assert history.messages() == [
        Message("user", "富士山の高さは"),
        Message("assistant", "3776メートルです。"),
        Message("user", "何県にある？"),
        Message("assistant", "静岡県と山梨県です。"),
    ]


def test_keeps_only_recent_turns():
    history = ConversationHistory(max_turns=2, clock=FakeClock())
    for i in range(4):
        history.add(f"質問{i}", f"返答{i}")
    assert [m.text for m in history.messages()] == ["質問2", "返答2", "質問3", "返答3"]


def test_expires_after_ttl_since_last_turn():
    clock = FakeClock()
    history = ConversationHistory(ttl_seconds=300, clock=clock)
    history.add("質問1", "返答1")
    clock.now = 200
    history.add("質問2", "返答2")
    clock.now = 499  # 最後のやり取りから 299 秒
    assert len(history.messages()) == 4
    clock.now = 501  # 最後のやり取りから 301 秒
    assert history.messages() == []


def test_add_after_expiry_starts_fresh():
    clock = FakeClock()
    history = ConversationHistory(ttl_seconds=300, clock=clock)
    history.add("古い質問", "古い返答")
    clock.now = 1000
    history.add("新しい質問", "新しい返答")
    assert [m.text for m in history.messages()] == ["新しい質問", "新しい返答"]


def test_clear():
    history = ConversationHistory(clock=FakeClock())
    history.add("質問", "返答")
    history.clear()
    assert history.messages() == []
