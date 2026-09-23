"""ボタンを押している間だけ聞き取る（うるさいときに、近くで確実に話すための逃げ道）。

押している側（いまは tools/display.py のスペースキー）が、合図のファイルを短い間隔で更新し続ける。
本体は**そのファイルの更新時刻だけ**を見る（中身は読まない）。

この形にしている理由：

- 押している側が異常終了しても、更新が止まるので FRESH_SECONDS 後に自動で「離した」になる。
  「ファイルがあれば押している」とすると、残ったファイルで録音が止まらなくなる。
- 中身を読まないので、送る側の不具合で本体が想定外の動きをすることがない。
  起こりうるのは「聞き取りが始まる」ことだけで、これはウェイクワードの誤反応と同じ扱いになる
  （短い聞き取りと低い確信度は AI に送らない、という既存の防御がそのまま効く）。
- $XDG_RUNTIME_DIR はメモリ上で、同じ利用者だけが触れる。遅い SD カードに書かず、外部からも触れない。

仕様は docs/display-spec.md を参照。
"""

import os
import time
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np

from .vad import EndReason, Utterance

# 合図がこの秒数より古ければ「離した」とみなす（送る側が止まったときの保険）
FRESH_SECONDS = 1.0


def default_path() -> Path | None:
    """合図のファイル。$XDG_RUNTIME_DIR が無ければ None（ボタンを使わない）。"""
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    return Path(runtime) / "voice-assistant" / "talk" if runtime else None


class TalkSignal:
    """ボタンが押されているかを、合図のファイルの更新時刻から判断する。"""

    def __init__(self, path: Path | None = None, clock: Callable[[], float] = time.time):
        self._path = default_path() if path is None else path
        self._clock = clock
        self._was_held = False

    def held(self) -> bool:
        """いま押されているか。"""
        if self._path is None:
            return False
        try:
            return self._clock() - self._path.stat().st_mtime < FRESH_SECONDS
        except OSError:
            return False

    def pressed(self) -> bool:
        """押し始めたときだけ True。

        押しっぱなしのまま聞き取りが終わった場合に、続けて始まらないようにするため、
        一度離されるまで次の True を返さない。
        """
        now = self.held()
        started = now and not self._was_held
        self._was_held = now
        return started


def collect_while_held(
    frames: Iterable[np.ndarray],
    held: Callable[[], bool],
    max_frames: int,
    listener=None,
) -> Utterance:
    """ボタンを押している間の音声を集める。

    話し終わりの無音判定は使わない。テレビがついていると無音にならず録り続けてしまうため、
    押している範囲をそのまま発話とする。押しっぱなしで放置された場合に備え max_frames で打ち切る。
    """
    collected: list[np.ndarray] = []
    reason = EndReason.INPUT_ENDED
    for frame in frames:
        if not held():
            reason = EndReason.RELEASED
            break
        collected.append(frame)
        if listener is not None:
            listener.accept(frame)
        if len(collected) >= max_frames:
            reason = EndReason.MAX_LENGTH
            break
    if not collected:
        return Utterance(samples=None, reason=reason)
    return Utterance(samples=np.concatenate(collected), reason=reason)
