"""AI の呼び出しの共通部分。"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    text: str


class AiError(Exception):
    """AI の呼び出しに失敗した。メッセージはそのまま利用者に見せられる文言にする。"""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


class ChatClient(Protocol):
    def reply(self, user_text: str, history: Sequence[Message] = ()) -> str:
        """これまでのやり取り（history）を踏まえて、user_text への返答を返す。失敗したら AiError。"""
        ...
