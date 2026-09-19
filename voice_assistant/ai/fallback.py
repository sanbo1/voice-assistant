"""複数のモデルを優先の順に使う。上限や一時的なエラーのときは、次のモデルで答え直す。

- 1 日の上限に達したモデルは、RETRY_SECONDS（1 時間）ごとに 1 回だけ試す（回復したら自動で優先のモデルに戻る）。
- 1 分あたりの上限・サーバー側の一時的なエラー（5xx）・時間切れ・接続失敗は、その質問だけ次のモデルで答える。
- API キーの誤りなど（401・403 など）は、どのモデルでも直らないため、そのままエラーにする。
"""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .base import AiError, ChatClient, Message

RETRY_SECONDS = 3600.0


def _answer_with_next_model(error: AiError) -> bool:
    """このエラーのとき、次のモデルで答え直すか。"""
    if error.status is None:  # 時間切れ・接続失敗
        return True
    return error.status in (404, 429) or error.status >= 500


@dataclass
class _Model:
    name: str
    client: ChatClient
    unavailable_until: float = 0.0  # これより前は試さない（time.monotonic の値）
    over_daily_limit: bool = False


class FallbackChatClient:
    def __init__(
        self,
        models: Sequence[tuple[str, ChatClient]],
        *,
        on_status: Callable[[str], None] = lambda text: None,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not models:
            raise ValueError("モデルを 1 つ以上渡してください")
        self._models = [_Model(name, client) for name, client in models]
        self._on_status = on_status
        self._clock = clock
        self.primary = self._models[0].name
        self.last_model: str | None = None  # 最後に答えたモデル

    def reply(self, user_text: str, history: Sequence[Message] = ()) -> str:
        now = self._clock()
        last_error: AiError | None = None
        for model in self._models:
            if model.unavailable_until > now:
                continue
            try:
                answer = model.client.reply(user_text, history)
            except AiError as e:
                if not _answer_with_next_model(e):
                    raise
                last_error = e
                if e.quota == "day" or e.status == 404:
                    model.unavailable_until = now + RETRY_SECONDS
                    if not model.over_daily_limit:
                        model.over_daily_limit = True
                        reason = "今日の上限に達しました" if e.status == 429 else "使えませんでした（404）"
                        self._on_status(f"{model.name} が{reason}。1 時間ごとに確認します")
                continue
            model.unavailable_until = 0.0
            model.over_daily_limit = False
            self._note_model(model.name)
            return answer

        if last_error is None or all(m.over_daily_limit for m in self._models):
            raise AiError("すべてのモデルが今日の利用回数の上限に達しています", status=429, quota="day")
        raise last_error

    def _note_model(self, name: str) -> None:
        if name == self.last_model or (self.last_model is None and name == self.primary):
            self.last_model = name
            return
        self._on_status(f"{self.primary} に戻りました" if name == self.primary else f"{name} に切り替えました")
        self.last_model = name
