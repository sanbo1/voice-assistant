"""Gemini API（REST）の呼び出し。公式 SDK は使わず、requests で generateContent を呼ぶ。

API キーは URL に含めず、x-goog-api-key ヘッダーで送る。
"""

from collections.abc import Callable, Sequence
from datetime import datetime

import requests

from ..config import GeminiConfig
from .base import AiError, Message
from .prompt import system_instruction

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
# 2026-09-19 時点。gemini-2.5-flash は新規利用者には提供終了（API が gemini-3.6-flash を案内した）
DEFAULT_MODEL = "gemini-3.6-flash"
# 既定のモデルで使う思考の量。応答が速く（確認時 1.6〜3.3 秒）、答えの質も十分だった
DEFAULT_THINKING_LEVEL = "minimal"


def build_request(
    user_text: str,
    history: Sequence[Message],
    system_text: str,
    thinking_budget: int | None = None,
    thinking_level: str | None = None,
) -> dict:
    """generateContent に送る本文を作る。

    思考の量は、Gemini 2.5 系は thinking_budget（トークン数）、Gemini 3 系は thinking_level（minimal など）で指定する。
    """
    contents = [
        {"role": "user" if m.role == "user" else "model", "parts": [{"text": m.text}]} for m in history
    ]
    contents.append({"role": "user", "parts": [{"text": user_text}]})
    body: dict = {"systemInstruction": {"parts": [{"text": system_text}]}, "contents": contents}
    thinking: dict = {}
    if thinking_budget is not None:
        thinking["thinkingBudget"] = thinking_budget
    if thinking_level is not None:
        thinking["thinkingLevel"] = thinking_level
    if thinking:
        body["generationConfig"] = {"thinkingConfig": thinking}
    return body


def parse_response(data: dict) -> str:
    """generateContent の応答から返答の文章を取り出す。思考の過程（thought）は含めない。"""
    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason", "不明")
        raise AiError(f"返答がありませんでした（理由：{reason}）")
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not text:
        raise AiError(f"返答が空でした（理由：{candidate.get('finishReason', '不明')}）")
    return text


def _error_message(response: requests.Response) -> str:
    try:
        return response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return response.text[:200]


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        timeout: float = 20.0,
        thinking_budget: int | None = None,
        thinking_level: str | None = None,
        session: requests.Session | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ):
        if not api_key:
            raise AiError("GEMINI_API_KEY が設定されていません（~/voice-assistant/.env に記入してください）")
        self._api_key = api_key
        self.model = model
        self._timeout = timeout
        self.thinking_budget = thinking_budget
        self.thinking_level = thinking_level
        self._session = session or requests.Session()
        self._clock = clock

    def reply(self, user_text: str, history: Sequence[Message] = ()) -> str:
        body = build_request(
            user_text, history, system_instruction(self._clock()), self.thinking_budget, self.thinking_level
        )
        try:
            response = self._session.post(
                f"{API_BASE}/models/{self.model}:generateContent",
                headers={"x-goog-api-key": self._api_key, "Content-Type": "application/json"},
                json=body,
                timeout=self._timeout,
            )
        except requests.Timeout:
            raise AiError("時間内に返答がありませんでした") from None
        except requests.RequestException as e:
            raise AiError(f"Gemini に接続できませんでした（{type(e).__name__}）") from None

        if response.status_code == 429:
            raise AiError("利用回数の上限に達しました（無料枠の制限）", status=429)
        if response.status_code != 200:
            raise AiError(
                f"Gemini がエラーを返しました（HTTP {response.status_code}：{_error_message(response)}）",
                status=response.status_code,
            )
        try:
            data = response.json()
        except ValueError:
            raise AiError("Gemini の返答を読み取れませんでした") from None
        return parse_response(data)


def client_from_config(
    config: GeminiConfig,
    *,
    model: str | None = None,
    thinking_level: str | None = None,
    thinking_budget: int | None = None,
) -> GeminiClient:
    """設定（.env）から GeminiClient を作る。引数で渡した値は設定より優先する。

    思考の量を指定しないまま既定のモデルを使う場合は、既定の思考の量（DEFAULT_THINKING_LEVEL）にする。
    """
    model = model or config.model or DEFAULT_MODEL
    thinking_level = thinking_level or config.thinking_level
    if thinking_level is None and thinking_budget is None and model == DEFAULT_MODEL:
        thinking_level = DEFAULT_THINKING_LEVEL
    return GeminiClient(config.api_key, model, thinking_level=thinking_level, thinking_budget=thinking_budget)
