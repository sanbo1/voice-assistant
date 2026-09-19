"""会話ログ。やり取りとエラーを logs/conversation.log に書く（モニターのターミナルに表示するため）。

毎日 0 時に新しいファイルに切り替え、古いものは RETENTION_DAYS 日分だけ残す。
"""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from .config import PROJECT_ROOT

DEFAULT_PATH = PROJECT_ROOT / "logs" / "conversation.log"
RETENTION_DAYS = 7


class ConversationLog:
    def __init__(self, path: Path = DEFAULT_PATH, retention_days: int = RETENTION_DAYS):
        path.parent.mkdir(parents=True, exist_ok=True)
        # 今日の分と、切り替えた古いファイル（retention_days - 1 日分）を残す
        self._handler = TimedRotatingFileHandler(
            path, when="midnight", backupCount=retention_days - 1, encoding="utf-8"
        )
        self._handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%m/%d %H:%M:%S"))
        self._logger = logging.getLogger(f"{__name__}.{id(self)}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        self._logger.addHandler(self._handler)

    def _write(self, label: str, text: str) -> None:
        self._logger.info("%s：%s", label, " ".join(text.split()))

    def status(self, text: str) -> None:
        self._write("状態", text)

    def heard(self, text: str) -> None:
        self._write("聞き取り", text or "（聞き取れませんでした）")

    def reply(self, text: str) -> None:
        self._write("返答", text)

    def error(self, text: str) -> None:
        self._write("エラー", text)

    def close(self) -> None:
        self._logger.removeHandler(self._handler)
        self._handler.close()
