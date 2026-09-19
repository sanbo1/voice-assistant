"""会話の履歴。直近の数往復をメモリ上に持ち、最後のやり取りから一定時間たったら消す。"""

import time
from collections.abc import Callable

from .ai import Message

DEFAULT_MAX_TURNS = 5
DEFAULT_TTL_SECONDS = 300.0  # 最後のやり取りから 5 分で消す（docs/design.md）


class ConversationHistory:
    def __init__(
        self,
        max_turns: int = DEFAULT_MAX_TURNS,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._max_turns = max_turns
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._turns: list[tuple[Message, Message]] = []
        self._last_time: float | None = None

    def messages(self) -> list[Message]:
        """AI に渡す履歴。時間切れなら消してから返す。"""
        if self._last_time is not None and self._clock() - self._last_time > self._ttl_seconds:
            self.clear()
        return [message for turn in self._turns for message in turn]

    def add(self, user_text: str, assistant_text: str) -> None:
        self.messages()  # 時間切れの古い履歴に続けて追加しないよう、先に確かめる
        self._turns.append((Message("user", user_text), Message("assistant", assistant_text)))
        del self._turns[:-self._max_turns]
        self._last_time = self._clock()

    def clear(self) -> None:
        self._turns.clear()
        self._last_time = None
