"""AI の呼び出しの共通部分。"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    text: str


# 失敗の種類（利用者に伝える文言を選ぶために使う）
BUSY = "busy"  # AI 側が混み合っている（5xx）
TIMEOUT = "timeout"  # 時間内に返事が来なかった
NETWORK = "network"  # つながらなかった


class AiError(Exception):
    """AI の呼び出しに失敗した。メッセージはそのまま利用者に見せられる文言にする。

    status は HTTP の状態コード（時間切れ・接続失敗では None）。
    quota は回数上限（429）の種類："day"（1 日あたり）、"minute"（1 分あたり）、不明なら None。
    kind は失敗の種類（BUSY・TIMEOUT・NETWORK）。時間切れと接続失敗は status がどちらも None で
    区別できないため、別に持つ（2026-09-23）。
    """

    def __init__(self, message: str, *, status: int | None = None, quota: str | None = None,
                 kind: str | None = None):
        super().__init__(message)
        self.status = status
        self.quota = quota
        self.kind = kind if kind is not None else (BUSY if status and status >= 500 else None)


class ChatClient(Protocol):
    def reply(self, user_text: str, history: Sequence[Message] = ()) -> str:
        """これまでのやり取り（history）を踏まえて、user_text への返答を返す。失敗したら AiError。"""
        ...
