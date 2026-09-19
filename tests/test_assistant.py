from voice_assistant.ai import AiError
from voice_assistant.assistant import AI_ERROR_MESSAGE, RATE_LIMIT_MESSAGE, reply_or_error_message
from voice_assistant.history import ConversationHistory


class FakeAi:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def reply(self, user_text, history=()):
        self.calls.append((user_text, list(history)))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeLog:
    def __init__(self):
        self.lines = []

    def reply(self, text):
        self.lines.append(("reply", text))

    def error(self, text):
        self.lines.append(("error", text))


def test_success_returns_answer_and_updates_history():
    history = ConversationHistory()
    ai, log = FakeAi("富士山です。"), FakeLog()
    assert reply_or_error_message(ai, history, "一番高い山は", log) == "富士山です。"
    assert [m.text for m in history.messages()] == ["一番高い山は", "富士山です。"]
    assert log.lines == [("reply", "富士山です。")]


def test_history_is_passed_to_ai():
    history = ConversationHistory()
    history.add("富士山の高さは", "3776メートルです。")
    ai = FakeAi("静岡県と山梨県です。")
    reply_or_error_message(ai, history, "何県にある？", FakeLog())
    assert [m.text for m in ai.calls[0][1]] == ["富士山の高さは", "3776メートルです。"]


def test_rate_limit_message_and_history_unchanged():
    history = ConversationHistory()
    log = FakeLog()
    answer = reply_or_error_message(FakeAi(AiError("上限", status=429)), history, "質問", log)
    assert answer == RATE_LIMIT_MESSAGE
    assert history.messages() == []
    assert log.lines == [("error", "上限")]


def test_other_ai_error_message():
    answer = reply_or_error_message(FakeAi(AiError("接続できません")), ConversationHistory(), "質問", FakeLog())
    assert answer == AI_ERROR_MESSAGE
