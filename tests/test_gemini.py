from datetime import datetime

import pytest
import requests

from voice_assistant.ai import AiError, Message
from voice_assistant.ai.gemini import API_BASE, GeminiClient, build_request, parse_response
from voice_assistant.ai.prompt import system_instruction


def test_build_request_maps_roles_and_appends_question():
    history = [Message("user", "こんにちは"), Message("assistant", "こんにちは。")]
    body = build_request("今日は何日", history, "指示")
    assert body["systemInstruction"] == {"parts": [{"text": "指示"}]}
    assert body["contents"] == [
        {"role": "user", "parts": [{"text": "こんにちは"}]},
        {"role": "model", "parts": [{"text": "こんにちは。"}]},
        {"role": "user", "parts": [{"text": "今日は何日"}]},
    ]
    assert "generationConfig" not in body


def test_build_request_thinking_budget():
    body = build_request("質問", [], "指示", thinking_budget=0)
    assert body["generationConfig"] == {"thinkingConfig": {"thinkingBudget": 0}}


def test_build_request_thinking_level():
    body = build_request("質問", [], "指示", thinking_level="minimal")
    assert body["generationConfig"] == {"thinkingConfig": {"thinkingLevel": "minimal"}}


def test_parse_response_joins_parts_and_skips_thoughts():
    data = {"candidates": [{"content": {"parts": [
        {"text": "考え中", "thought": True},
        {"text": "富士山です。"},
        {"text": "標高は3776メートルです。"},
    ]}}]}
    assert parse_response(data) == "富士山です。標高は3776メートルです。"


def test_parse_response_blocked():
    with pytest.raises(AiError, match="SAFETY"):
        parse_response({"promptFeedback": {"blockReason": "SAFETY"}})


def test_parse_response_empty_text():
    with pytest.raises(AiError, match="MAX_TOKENS"):
        parse_response({"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]})


def test_system_instruction_contains_date_and_weekday():
    text = system_instruction(datetime(2026, 9, 19, 16, 5))
    assert "2026年9月19日（土）16時05分" in text


def test_system_instruction_states_unavailable_actions():
    # 2026-09-19 の確認で「タイマーでお知らせしますね」と、できない操作を引き受けたため
    text = system_instruction(datetime(2026, 9, 19, 16, 5))
    assert "タイマー" in text and "できない" in text
    assert "\n- あなたにできるのは" in text  # 前の項目と改行で区切られていること


class FakeResponse:
    def __init__(self, status_code, data=None, text=""):
        self.status_code = status_code
        self._data = data
        self.text = text

    def json(self):
        if self._data is None:
            raise ValueError("no json")
        return self._data


class FakeSession:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def make_client(result, **kwargs):
    session = FakeSession(result)
    client = GeminiClient("test-key", "gemini-test", session=session,
                          clock=lambda: datetime(2026, 9, 19, 16, 0), **kwargs)
    return client, session


OK = FakeResponse(200, {"candidates": [{"content": {"parts": [{"text": "令和8年です。"}]}}]})


def test_reply_success_sends_key_in_header_not_url():
    client, session = make_client(OK)
    assert client.reply("今って令和何年") == "令和8年です。"
    url, kwargs = session.calls[0]
    assert url == f"{API_BASE}/models/gemini-test:generateContent"
    assert "test-key" not in url
    assert kwargs["headers"]["x-goog-api-key"] == "test-key"
    assert kwargs["json"]["contents"][-1]["parts"][0]["text"] == "今って令和何年"
    assert "2026年9月19日" in kwargs["json"]["systemInstruction"]["parts"][0]["text"]


def test_reply_rate_limited():
    client, _ = make_client(FakeResponse(429, {"error": {"message": "quota"}}))
    with pytest.raises(AiError) as e:
        client.reply("質問")
    assert e.value.status == 429


def test_reply_http_error_includes_message():
    client, _ = make_client(FakeResponse(400, {"error": {"message": "API key not valid"}}))
    with pytest.raises(AiError, match="API key not valid") as e:
        client.reply("質問")
    assert e.value.status == 400


def test_reply_timeout():
    client, _ = make_client(requests.Timeout())
    with pytest.raises(AiError, match="時間内"):
        client.reply("質問")


def test_reply_connection_error():
    client, _ = make_client(requests.ConnectionError())
    with pytest.raises(AiError, match="接続できません"):
        client.reply("質問")


def test_missing_api_key():
    with pytest.raises(AiError, match="GEMINI_API_KEY"):
        GeminiClient("")
