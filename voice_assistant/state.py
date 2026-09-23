"""いまの様子を小さなファイルに書く（モニターの画面に渡すため）。

$XDG_RUNTIME_DIR の下（メモリ上）に置くので、遅い SD カードには書かない。再起動で消えてよい。
**書き込みに失敗しても本体は止めない。** 画面のための情報であり、音声アシスタントの動作には要らない。

画面側は tools/display.py が読む。仕様は docs/display-spec.md を参照。
"""

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# 画面が扱う状態の名前（docs/display-spec.md と合わせる）
STARTING = "starting"
WAITING = "waiting"
LISTENING = "listening"
THINKING = "thinking"
SPEAKING = "speaking"
FOLLOWUP = "followup"


def default_path() -> Path | None:
    """状態ファイルの置き場所。$XDG_RUNTIME_DIR が無ければ None（書かない）。"""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return Path(runtime) / "voice-assistant" / "state.json" if runtime else None


class StateFile:
    """いまの様子を書き出す。失敗しても例外を投げない。"""

    def __init__(self, path: Path | None = None, clock=datetime.now):
        self._path = path if path is not None else default_path()
        self._clock = clock
        self._warned = False

    @property
    def path(self) -> Path | None:
        return self._path

    def write(self, state: str, history_seconds_left: float = 0.0,
              model: str | None = None, fallback: bool = False) -> None:
        """いまの様子を書く。

        history_seconds_left は会話履歴が消えるまでの秒数。
        model は使用中の AI のモデル名、fallback は予備のモデルに切り替わっているか（画面に出すため）。
        """
        if self._path is None:
            return
        now = self._clock()
        payload = {"state": state, "updated": now.isoformat(timespec="seconds"), "pid": os.getpid()}
        if model:
            payload["model"] = model
            payload["fallback"] = fallback
        if history_seconds_left > 0:
            payload["history_alive_until"] = (
                now + timedelta(seconds=history_seconds_left)).isoformat(timespec="seconds")
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # 画面が読みかけのファイルを見ないよう、別名で書いてから置き換える
            temporary = self._path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(temporary, self._path)
        except OSError as e:
            if not self._warned:  # 毎回記録すると技術ログが埋まるため、最初の 1 回だけ
                logger.warning("状態ファイルを書けません（%s）。画面の状態表示は会話ログから推定されます", e)
                self._warned = True

    def remove(self) -> None:
        """終了時に消す（画面が「動いていない」と分かるように）。"""
        if self._path is None:
            return
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass
