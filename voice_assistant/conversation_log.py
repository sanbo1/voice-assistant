"""会話ログ。やり取りとエラーを logs/conversation.log に書く（モニターのターミナルに表示するため）。

毎日 0 時に新しいファイルに切り替え、古いものは RETENTION_DAYS 日分だけ残す。
"""

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .config import PROJECT_ROOT

DEFAULT_PATH = PROJECT_ROOT / "logs" / "conversation.log"
RETENTION_DAYS = 7


class ConversationLog:
    def __init__(self, path: Path = DEFAULT_PATH, retention_days: int = RETENTION_DAYS, *, echo: bool = False):
        """echo を True にすると、標準出力にも同じ内容を表示する（手動で起動したとき用）。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        formatter = logging.Formatter("%(asctime)s  %(message)s", datefmt="%m/%d %H:%M:%S")
        # 今日の分と、切り替えた古いファイル（retention_days - 1 日分）を残す
        self._handlers: list[logging.Handler] = [
            TimedRotatingFileHandler(path, when="midnight", backupCount=retention_days - 1, encoding="utf-8")
        ]
        if echo:
            self._handlers.append(logging.StreamHandler(sys.stdout))
        self._logger = logging.getLogger(f"{__name__}.{id(self)}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        for handler in self._handlers:
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

    def _write(self, label: str, text: str) -> None:
        self._logger.info("%s：%s", label, " ".join(text.split()))

    def status(self, text: str) -> None:
        self._write("状態", text)

    def heard(self, text: str, confidence: float | None = None) -> None:
        """confidence を渡すと「聞き取り（確信度 0.92）」と書く（しきい値の調整に使う）。"""
        label = "聞き取り" if confidence is None else f"聞き取り（確信度 {confidence:.2f}）"
        self._write(label, text or "（聞き取れませんでした）")

    def reply(self, text: str, model: str | None = None) -> None:
        """model を渡すと「返答（モデル名）」と書く（予備のモデルで答えたとき用）。"""
        self._write(f"返答（{model}）" if model else "返答", text)

    def error(self, text: str) -> None:
        self._write("エラー", text)

    def close(self) -> None:
        for handler in self._handlers:
            self._logger.removeHandler(handler)
            handler.close()
