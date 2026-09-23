"""Gemini API（REST）の呼び出し。公式 SDK は使わず、requests で generateContent を呼ぶ。

API キーは URL に含めず、x-goog-api-key ヘッダーで送る。
"""

from collections.abc import Callable, Sequence
from datetime import datetime

import requests

from ..config import GeminiConfig
from .base import NETWORK, TIMEOUT, AiError, Message
from .fallback import FallbackChatClient
from .prompt import system_instruction

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
# 2026-09-19 時点。gemini-2.5-flash は新規利用者には提供終了（API が gemini-3.6-flash を案内した）
DEFAULT_MODEL = "gemini-3.6-flash"
# 既定のモデルで使う思考の量。応答が速く（確認時 1.6〜3.3 秒）、答えの質も十分だった
DEFAULT_THINKING_LEVEL = "minimal"
# 既定のモデルが上限などで使えないときに、順に使う予備のモデル（2026-09-19 に 1 回ずつ送信して使えることを確認）。
# 無料枠の 1 日の上限はモデルごと（gemini-3.6-flash は 20 回/日だった）。
# gemini-3.8-flash は混雑（503）、gemini-3.7-flash は時間切れだったため入れていない。
DEFAULT_FALLBACK_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")
# 予備のモデルで使う思考の量。指定しないと質問によって数秒かかることがあったため最小にする。
# 上記 2 つが minimal を受け付けることは確認済み（2026-09-20）。受け付けないモデルを予備にする場合は要変更。
FALLBACK_THINKING_LEVEL = "minimal"


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


def quota_kind(data: dict) -> str | None:
    """回数上限（HTTP 429）の応答から、上限の種類（"day"：1 日あたり、"minute"：1 分あたり）を判断する。"""
    for detail in (data.get("error") or {}).get("details") or []:
        for violation in detail.get("violations") or []:
            quota_id = str(violation.get("quotaId", ""))
            if "PerDay" in quota_id:
                return "day"
            if "PerMinute" in quota_id:
                return "minute"
    return None


def quota_details(data: dict) -> str:
    """回数上限（HTTP 429）の応答から、どの上限か・上限値・再試行までの時間を取り出す（会話ログ用）。"""
    error = data.get("error") or {}
    items = []
    for detail in error.get("details") or []:
        kind = str(detail.get("@type", ""))
        if kind.endswith("QuotaFailure"):
            for violation in detail.get("violations") or []:
                name = violation.get("quotaId") or violation.get("quotaMetric")
                if name:
                    value = violation.get("quotaValue")
                    items.append(f"上限の種類：{name}" + (f"（上限値 {value}）" if value else ""))
        elif kind.endswith("RetryInfo") and detail.get("retryDelay"):
            items.append(f"再試行まで：{detail['retryDelay']}")
    if not items and error.get("message"):
        items.append(" ".join(str(error["message"]).split())[:200])
    return "、".join(items)


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        timeout: float = 10.0,  # 音声で待たせすぎないように（ふだんの応答は 1〜3 秒）。時間切れなら予備のモデルで答え直す
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
            raise AiError("時間内に返答がありませんでした", kind=TIMEOUT) from None
        except requests.RequestException as e:
            raise AiError(f"Gemini に接続できませんでした（{type(e).__name__}）", kind=NETWORK) from None

        if response.status_code == 429:
            try:
                data = response.json()
            except ValueError:
                data = {}
            details = quota_details(data)
            raise AiError(
                "利用回数の上限に達しました（無料枠の制限" + (f"。{details}" if details else "") + "）",
                status=429,
                quota=quota_kind(data),
            )
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


def chat_client_from_config(
    config: GeminiConfig, on_status: Callable[[str], None] = lambda text: None
) -> FallbackChatClient:
    """設定（.env）から、優先のモデルと予備のモデルを順に使う ChatClient を作る。

    予備のモデルの思考の量は FALLBACK_THINKING_LEVEL にそろえる。
    """
    primary = client_from_config(config)
    names = DEFAULT_FALLBACK_MODELS if config.fallback_models is None else config.fallback_models
    models: list[tuple[str, GeminiClient]] = [(primary.model, primary)]
    for name in names:
        if name not in (m for m, _ in models):
            models.append((name, GeminiClient(config.api_key, name, thinking_level=FALLBACK_THINKING_LEVEL)))
    return FallbackChatClient(models, on_status=on_status)
