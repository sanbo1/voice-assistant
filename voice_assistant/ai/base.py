"""AI の呼び出しの共通部分。"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    text: str


class AiError(Exception):
    """AI の呼び出しに失敗した。メッセージはそのまま利用者に見せられる文言にする。

    status は HTTP の状態コード（時間切れ・接続失敗では None）。
    quota は回数上限（429）の種類："day"（1 日あたり）、"minute"（1 分あたり）、不明なら None。
    """

    def __init__(self, message: str, *, status: int | None = None, quota: str | None = None):
        super().__init__(message)
        self.status = status
        self.quota = quota


class ChatClient(Protocol):
    def reply(self, user_text: str, history: Sequence[Message] = ()) -> str:
        """これまでのやり取り（history）を踏まえて、user_text への返答を返す。失敗したら AiError。"""
        ...
