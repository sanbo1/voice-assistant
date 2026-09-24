from voice_assistant.ai import AiError
from voice_assistant.assistant import (
    AI_ERROR_MESSAGE,
    BUSY_MESSAGE,
    DAILY_LIMIT_MESSAGE,
    NETWORK_MESSAGE,
    RATE_LIMIT_MESSAGE,
    TIMEOUT_MESSAGE,
    Assistant,
    is_slow_playback,
    reply_or_error_message,
)
from voice_assistant.config import AssistantConfig
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

    def reply(self, text, model=None):
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


def test_daily_limit_message():
    answer = reply_or_error_message(FakeAi(AiError("上限", status=429, quota="day")), ConversationHistory(), "質問", FakeLog())
    assert answer == DAILY_LIMIT_MESSAGE


class FakeFallbackAi(FakeAi):
    primary = "main-model"

    def __init__(self, result, last_model):
        super().__init__(result)
        self.last_model = last_model


class LabelLog(FakeLog):
    def reply(self, text, model=None):
        self.lines.append(("reply", text, model))


def test_reply_is_labeled_only_when_fallback_model_answered():
    log = LabelLog()
    reply_or_error_message(FakeFallbackAi("A", "main-model"), ConversationHistory(), "q", log)
    reply_or_error_message(FakeFallbackAi("B", "lite-model"), ConversationHistory(), "q", log)
    assert log.lines == [("reply", "A", None), ("reply", "B", "lite-model")]


def test_is_slow_playback():
    assert is_slow_playback(10.0, 11.0) is True     # 1.1 倍（2026-09-20 に実際に起きた遅さ）
    assert is_slow_playback(10.0, 10.5) is False    # 1.05 倍（再生開始の待ち時間の分）
    assert is_slow_playback(0.0, 5.0) is False      # 長さが 0 の音声は判定しない


class StatusLog(FakeLog):
    def status(self, text):
        self.lines.append(("status", text))


def make_assistant(log, min_confidence=0.52):
    """会話ログだけを使う部分を試すための Assistant（音声の準備を避けるため __new__ で組み立てる）。"""
    from voice_assistant.config import SttConfig

    assistant = Assistant.__new__(Assistant)
    assistant._log = log
    assistant._wake_note = "最大 0.48、並び 0.10 0.48 0.46"
    assistant._stt_config = SttConfig(min_confidence=min_confidence)
    return assistant


def test_empty_wake_is_recorded_with_the_scores():
    """空振りの 1 行に、検知したときのスコアも入れる（あとから誤反応を数えるため）。"""
    log = StatusLog()
    make_assistant(log)._log_empty_wake("聞き取りが短い")
    assert log.lines == [("status", "ウェイクワードは空振りでした（聞き取りが短い、最大 0.48、並び 0.10 0.48 0.46）")]


def test_low_confidence_is_treated_as_noise():
    """しきい値を下回る聞き取りは雑音とみなす。"""
    assert make_assistant(StatusLog())._is_noise(0.46) is True


def test_confidence_at_the_threshold_is_kept():
    assert make_assistant(StatusLog())._is_noise(0.52) is False
    assert make_assistant(StatusLog())._is_noise(0.58) is False


def test_missing_confidence_is_not_noise():
    """確信度が取れなかった回は足切りしない（誤って捨てないため）。"""
    assert make_assistant(StatusLog())._is_noise(None) is False


def test_threshold_zero_disables_the_check():
    assert make_assistant(StatusLog(), min_confidence=0.0)._is_noise(0.01) is False


# ---------- 失敗の種類ごとの文言（2026-09-23 追加）----------


def answer_for(error):
    return reply_or_error_message(FakeAi(error), ConversationHistory(), "質問", FakeLog())


def test_busy_message_for_server_errors():
    """Gemini が混み合っている（5xx）ときは、そうと分かる文言にする。"""
    assert answer_for(AiError("HTTP 503", status=503)) == BUSY_MESSAGE
    assert answer_for(AiError("HTTP 500", status=500)) == BUSY_MESSAGE


def test_timeout_message():
    """時間切れと接続失敗は status がどちらも None なので、種類で見分ける。"""
    from voice_assistant.ai.base import TIMEOUT

    assert answer_for(AiError("時間内に返答がありませんでした", kind=TIMEOUT)) == TIMEOUT_MESSAGE


def test_network_message():
    from voice_assistant.ai.base import NETWORK

    assert answer_for(AiError("接続できません", kind=NETWORK)) == NETWORK_MESSAGE


def test_other_errors_keep_the_general_message():
    assert answer_for(AiError("読み取れません")) == AI_ERROR_MESSAGE
    assert answer_for(AiError("HTTP 400", status=400)) == AI_ERROR_MESSAGE


def test_quota_messages_are_unchanged():
    assert answer_for(AiError("上限", status=429, quota="day")) == DAILY_LIMIT_MESSAGE
    assert answer_for(AiError("上限", status=429)) == RATE_LIMIT_MESSAGE


# ---------- 続けて話せる回数：ウェイクワードとスペースキーで分ける（2026-09-24）----------


def turns_taken(by_key, config):
    """最初の質問のあと、続けて聞き取りに進んだ回数を返す（聞き取りと AI は差し替える）。"""
    assistant = Assistant.__new__(Assistant)
    assistant._config = config
    assistant._by_key = False
    calls = []

    def answer_once(listen, *, after_wake=False):
        calls.append(after_wake)
        if after_wake:
            assistant._by_key = by_key  # 本物は _wake_and_listen の中で決まる
        return True

    assistant._answer_once = answer_once
    assistant.handle_one_turn()
    return len(calls) - 1


def test_wake_word_allows_the_configured_followups():
    assert turns_taken(False, AssistantConfig(followup_max_turns=3, followup_max_turns_key=0)) == 3


def test_space_key_does_not_listen_again_by_default():
    assert turns_taken(True, AssistantConfig(followup_max_turns=3)) == 0


def test_space_key_has_its_own_count():
    assert turns_taken(True, AssistantConfig(followup_max_turns=3, followup_max_turns_key=2)) == 2


def test_followup_seconds_zero_disables_it_for_both():
    config = AssistantConfig(followup_seconds=0, followup_max_turns=3, followup_max_turns_key=2)
    assert turns_taken(False, config) == 0
    assert turns_taken(True, config) == 0
