import datetime

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
from voice_assistant import board_control as bc
from voice_assistant.board import BoardSettings
from voice_assistant.board_control import BoardController
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


class NoBoard:
    """伝言板を使わないテスト用（確認中ではなく、宛先は「みんな」だけ）。"""

    confirming = False
    settings = BoardSettings()


def turns_taken(by_key, config):
    """最初の質問のあと、続けて聞き取りに進んだ回数を返す（聞き取りと AI は差し替える）。"""
    assistant = Assistant.__new__(Assistant)
    assistant._config = config
    assistant._by_key = False
    assistant._board = NoBoard()
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


# ---------- AI を使わない回答（今日のごみ。2026-10-04）----------


class LocalLog(StatusLog):
    def reply(self, text, model=None):
        self.lines.append(("reply", text, model))


def make_local_assistant(log):
    assistant = Assistant.__new__(Assistant)
    assistant._log = log
    assistant._history = ConversationHistory()
    assistant._board = NoBoard()
    return assistant


def test_local_answer_is_logged_with_its_source_and_kept_in_history(monkeypatch):
    from voice_assistant import garbage

    monkeypatch.setattr(garbage, "answer", lambda text, day: garbage.Answer("今日は月曜日です。燃えるごみの日です。"))
    log = LocalLog()
    assistant = make_local_assistant(log)
    assert assistant._answer_locally("今日のごみは") == "今日は月曜日です。燃えるごみの日です。"
    assert log.lines == [("reply", "今日は月曜日です。燃えるごみの日です。", "予定表")]
    assert [m.text for m in assistant._history.messages()] == ["今日のごみは", "今日は月曜日です。燃えるごみの日です。"]


def test_local_answer_returns_none_for_other_questions(monkeypatch):
    from voice_assistant import garbage

    monkeypatch.setattr(garbage, "answer", lambda text, day: None)
    log = LocalLog()
    assistant = make_local_assistant(log)
    assert assistant._answer_locally("今日の天気は") is None
    assert log.lines == []
    assert assistant._history.messages() == []


def test_unusable_schedule_is_answered_and_reported_without_asking_ai(monkeypatch):
    """予定表が使えないときも、定型の質問には答える（AI には送らない）。理由はエラーに、答えは返答に残す。"""
    from voice_assistant import garbage

    monkeypatch.setattr(garbage, "answer", lambda text, day: garbage.Answer(
        garbage.MISSING_MESSAGE, "garbage.json がありません"))
    log = LocalLog()
    assistant = make_local_assistant(log)
    assert assistant._answer_locally("今日のごみは") == garbage.MISSING_MESSAGE
    assert log.lines == [("error", "ごみの予定表を使えませんでした（garbage.json がありません）"),
                         ("reply", garbage.MISSING_MESSAGE, "予定表")]
    assert assistant._history.messages() == []  # 失敗の文言を、AI が前の答えとして踏まえないように


# ---------- 伝言板（2026-10-08）----------

START = datetime.datetime(2026, 10, 8, 18, 0, 0)


class FakeKeys:
    """入力装置を読むスレッドの代わり（取り込んだキーを、順に返す）。"""

    def __init__(self, *codes):
        import queue

        self.events = queue.SimpleQueue()
        for code in codes:
            self.events.put(("press", code))

    def is_down(self, code):
        return False


def make_board_assistant(tmp_path, log=None, settings=None):
    import json

    if settings is not None:
        (tmp_path / "board-settings.json").write_text(json.dumps(settings, ensure_ascii=False), encoding="utf-8")
    assistant = Assistant.__new__(Assistant)
    assistant._log = log or LocalLog()
    assistant._history = ConversationHistory()
    assistant._board = BoardController(tmp_path / "board.json", tmp_path / "board-settings.json",
                                       tmp_path / "view.json", lambda: START)
    assistant._board_keys = FakeKeys()
    assistant.spoken = []
    assistant._speak = lambda text, before_play=None: assistant.spoken.append(text)
    assistant._note_state = lambda state: None
    return assistant


PEOPLE = {"people": [{"key": "1", "name": "お父さん", "color": "#4C9AFF"},
                     {"key": "2", "name": "お母さん", "color": "#FF6B81"}]}


def test_voice_message_is_stored_without_asking_ai_and_not_kept_in_history(tmp_path):
    log = LocalLog()
    assistant = make_board_assistant(tmp_path, log, PEOPLE)
    assert assistant._answer_locally("お母さんに伝言牛乳を買ってきて") == "お母さん宛に預かりました"
    assert [(m.to, m.text) for m in assistant._board.board.messages] == [("2", "牛乳を買ってきて")]
    assert log.lines == [("reply", "お母さん宛に預かりました", "伝言板")]
    assert assistant._history.messages() == []   # 家族の伝言を、AI の会話履歴に入れない


def test_too_long_voice_message_is_refused(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assert assistant._answer_locally("伝言" + "あ" * 61) == "60文字までです"
    assert assistant._board.board.messages == ()


def test_ordinary_questions_still_go_on_to_the_other_handlers(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assert assistant._answer_locally("今日の天気は") is None


def test_voice_delete_asks_and_deletes_after_yes(tmp_path):
    assistant = make_board_assistant(tmp_path)
    for text in ("伝言一つめ", "伝言二つめ"):
        assistant._answer_locally(text)
    assert assistant._answer_locally("伝言の2番を消して") == "2番を削除します。よろしいですか"
    assert assistant._board.confirming is True
    assert assistant._answer_confirmation("はい") is False
    assert assistant.spoken == ["削除しました"]
    assert [m.text for m in assistant._board.board.messages] == ["二つめ"]


def test_voice_delete_is_cancelled_by_no_and_by_an_unclear_reply(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._answer_locally("伝言一つめ")
    for reply in ("いいえ", "さあ"):
        assistant._answer_locally("伝言の1番を消して")
        assistant._answer_confirmation(reply)
        assert assistant.spoken[-1] == "やめました"
        assert len(assistant._board.board.messages) == 1


def test_no_reply_cancels_silently(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._answer_locally("伝言一つめ")
    assistant._answer_locally("伝言の1番を消して")
    assert assistant._answer_confirmation("  ") is False
    assert assistant._board.confirming is False and assistant.spoken == []
    assert len(assistant._board.board.messages) == 1


def test_voice_undo(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._answer_locally("伝言一つめ")
    assistant._answer_locally("伝言の1番を消して")
    assistant._answer_confirmation("はい")
    assert assistant._answer_locally("伝言を元に戻して") == "戻しました"
    assert [m.text for m in assistant._board.board.messages] == ["一つめ"]


def test_key_message_uses_the_key_recipient_even_if_the_words_name_another(tmp_path):
    assistant = make_board_assistant(tmp_path, settings=PEOPLE)
    assert assistant._store_message("1", "お母さんに伝言電気を消してね") == "お父さん宛に預かりました"
    assert [(m.to, m.text) for m in assistant._board.board.messages] == [("1", "電気を消してね")]


def test_key_message_without_the_word_denngon(tmp_path):
    assistant = make_board_assistant(tmp_path, settings=PEOPLE)
    assistant._store_message("2", "今日は遅くなります")
    assert [(m.to, m.text) for m in assistant._board.board.messages] == [("2", "今日は遅くなります")]


def test_confirmation_keeps_listening_even_when_followups_are_off():
    """声で消してよいか聞いたあとは、スペースキーの回（続けて聞かない設定）でも、返事を待つ。"""
    assistant = Assistant.__new__(Assistant)
    assistant._config = AssistantConfig(followup_max_turns=3, followup_max_turns_key=0)
    assistant._by_key = False
    board = NoBoard()
    assistant._board = board
    calls = []

    def answer_once(listen, *, after_wake=False):
        calls.append(after_wake)
        if after_wake:
            assistant._by_key = True
            board.confirming = True   # 1 回目の答えで、「消してよいですか」と聞いた
            return True
        board.confirming = False      # 2 回目（返事）で、決着がつく
        return False

    assistant._answer_once = answer_once
    assistant.handle_one_turn()
    assert calls == [True, False]


def test_a_board_key_only_turn_ends_without_listening_and_skips_the_ready_chime(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._skip_ready_chime = False
    assistant._board_turn_done = True
    assert assistant._answer_once(lambda: (None, None)) is False
    assert assistant._board_turn_done is False
    assert assistant._skip_ready_chime is True   # 応答を言ったばかりなので、続けて待ち受けのお知らせ音は鳴らさない


def test_digit_key_starts_a_message_for_a_known_person_and_ignores_unknown_ones(tmp_path):
    assistant = make_board_assistant(tmp_path, settings=PEOPLE)
    assistant._board_keys = FakeKeys(4, 3, 11)   # 上段の 3、2、0 のキー
    assert assistant._poll_board_keys() == ("talk", ("2", 3))      # 3 は設定にない → 飛ばして 2（お母さん）
    assert assistant._poll_board_keys() == ("talk", ("0", 11))     # 0 は、みんな宛
    assert assistant._poll_board_keys() is None


def test_keypad_and_delete_keys_give_a_short_phrase(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._answer_locally("伝言一つめ")
    assistant._board_keys = FakeKeys(79, bc.KEY_DELETE)
    assert assistant._poll_board_keys() == ("say", "削除しました")
    assert assistant._board.board.messages == ()


def test_insert_key_restores_and_says_so(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._answer_locally("伝言一つめ")
    assistant._board_keys = FakeKeys(79, bc.KEY_DELETE, bc.KEY_INSERT)
    assert assistant._poll_board_keys() == ("say", "削除しました")
    assert assistant._poll_board_keys() == ("say", "戻しました")


def test_arrow_keys_change_the_page_silently(tmp_path):
    assistant = make_board_assistant(tmp_path)
    for number in range(7):
        assistant._answer_locally(f"伝言{number}")
    assistant._board_keys = FakeKeys(bc.KEY_RIGHT)
    assert assistant._poll_board_keys() is None
    assert assistant._board.view.page == 1


# ---------- 伝言板の操作は、会話ログの「聞き取り」にしない（画面の質問欄に出さないため。2026-10-08）----------


def test_board_turns_are_recognized_by_voice_by_key_and_by_confirmation(tmp_path):
    assistant = make_board_assistant(tmp_path, settings=PEOPLE)
    assert assistant._is_board_turn("伝言牛乳を買ってきて", None) is True
    assert assistant._is_board_turn("伝言の2番を消して", None) is True
    assert assistant._is_board_turn("伝言を元に戻して", None) is True
    assert assistant._is_board_turn("牛乳を買ってきて", "2") is True       # 数字キーを押しながら話した
    assistant._board.add("0", "a")
    assistant._board.request_delete(1)
    assert assistant._is_board_turn("はい", None) is True                   # 確認の返事


def test_ordinary_questions_are_not_board_turns(tmp_path):
    assistant = make_board_assistant(tmp_path, settings=PEOPLE)
    for text in ("今日のごみは", "伝言ゲームって何", "日本で一番高い山は"):
        assert assistant._is_board_turn(text, None) is False


# ---------- 伝言を預けた・戻した回のあとは、続けて聞き取らない（2026-10-08）----------


def test_storing_a_message_does_not_allow_listening_again(tmp_path):
    assistant = make_board_assistant(tmp_path, settings=PEOPLE)
    assistant._answer_locally("お母さんに伝言牛乳を買ってきて")
    assert assistant._no_followup is True


def test_a_refused_message_allows_saying_it_again(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._answer_locally("伝言" + "あ" * 61)
    assert assistant._no_followup is False


def test_a_message_by_key_does_not_allow_listening_again(tmp_path):
    assistant = make_board_assistant(tmp_path, settings=PEOPLE)
    assistant._store_message("2", "牛乳を買ってきて")
    assert assistant._no_followup is True


def test_undo_does_not_allow_listening_again_but_nothing_to_undo_does_not_matter(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._answer_locally("伝言あした")
    assistant._board.request_delete(1)
    assistant._board.answer_confirmation(True)
    assistant._answer_locally("伝言を元に戻して")
    assert assistant._no_followup is True


def test_a_delete_request_still_waits_for_the_answer(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._answer_locally("伝言あした")
    assistant._answer_locally("伝言の1番を消して")
    assert assistant._board.confirming is True


def test_handle_one_turn_skips_followups_after_a_stored_message():
    assistant = Assistant.__new__(Assistant)
    assistant._config = AssistantConfig(followup_max_turns=3, followup_max_turns_key=3)
    assistant._by_key = False
    assistant._board = NoBoard()
    calls = []

    def answer_once(listen, *, after_wake=False):
        calls.append(after_wake)
        assistant._no_followup = True   # 本物は、伝言を預けたときにここで決まる
        return True

    assistant._answer_once = answer_once
    assistant.handle_one_turn()
    assert calls == [True]


# ---------- 全部消す（2026-10-08）----------


class CtrlKeys(FakeKeys):
    """Ctrl キーを押している状態を作れる入力装置の代わり。"""

    def __init__(self, *codes, ctrl=False):
        super().__init__(*codes)
        self.ctrl = ctrl

    def is_down(self, code):
        return self.ctrl and code in (29, 97)


def test_ctrl_delete_key_events_start_the_clear_all_confirmation(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._answer_locally("伝言あした")
    assistant._board_keys = CtrlKeys(111, ctrl=True)
    assert assistant._poll_board_keys() is None
    assert assistant._board.view.clear_all_until is not None and len(assistant._board.board.messages) == 1
    assistant._board_keys = CtrlKeys(111)             # もう一度 Delete（Ctrl は離している）
    assert assistant._poll_board_keys() == ("say", "全部削除しました")
    assert assistant._board.board.messages == ()


def test_plain_delete_key_event_does_not_clear_everything(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._answer_locally("伝言あした")
    assistant._board_keys = CtrlKeys(111)
    assert assistant._poll_board_keys() is None
    assert len(assistant._board.board.messages) == 1


def test_voice_delete_all_asks_and_waits_for_the_answer(tmp_path):
    assistant = make_board_assistant(tmp_path)
    assistant._answer_locally("伝言あした")
    assert assistant._answer_locally("伝言を全部消して") == "全部で1件を削除します。よろしいですか"
    assert assistant._board.confirming is True and assistant._is_board_turn("はい", None) is True
    assert assistant._answer_confirmation("はい") is False
    assert assistant._board.board.messages == ()


def test_undo_of_everything_does_not_listen_again(tmp_path):
    assistant = make_board_assistant(tmp_path)
    for text in ("伝言あ", "伝言い"):
        assistant._answer_locally(text)
    assistant._board.request_delete_all()
    assistant._board.answer_confirmation(True)
    assistant._answer_locally("伝言を元に戻して")
    assert assistant._no_followup is True and len(assistant._board.board.messages) == 2
