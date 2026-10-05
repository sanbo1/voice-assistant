"""スペースキーの押下を、/dev/input から直接読む（画面のフォーカスに頼らずに、キーを受け取る）。

背景（2026-10-05 の障害）：画面アプリは、Tk のキー入力でスペースキーを受け取っていた。ところが、
ログイン直後の自動起動のときだけ、デスクトップがキー入力を配らず、クリックするまで効かない状態になった
（同じ起動の中で、手動で起動し直すと効いた）。フォーカスに依存しない経路として、カーネルの入力装置を直接読む。

- 標準ライブラリだけで動く（画面アプリは、システムの python3 で動かすため）。
- **スペースキー（KEY_SPACE）のイベントしか見ない。** ほかのキーの内容は、読んでも捨てる。記録もしない。
- 入力装置を読むには、利用者が input グループに入っている必要がある（Raspberry Pi OS の既定の利用者は入っている）。
  読めない装置は黙って飛ばす（Tk のキー入力が、予備として残る）。
- 装置の抜き差しに備えて、一定の間隔で装置の一覧を調べ直す。
"""

import os
import queue
import select
import struct
import threading
import time
from pathlib import Path

EV_KEY = 1
KEY_SPACE = 57
# input_event：時刻（秒、マイクロ秒）、種類、コード、値。64 ビットの Linux では 24 バイト
EVENT = struct.Struct("llHHi")
# capabilities の 16 進の語の幅（ビット）。unsigned long の大きさ
WORD_BITS = struct.calcsize("L") * 8
RESCAN_SECONDS = 5.0
SYS_INPUT = Path("/sys/class/input")
DEV_INPUT = Path("/dev/input")


def parse_event(data: bytes) -> tuple[int, int, int] | None:
    """input_event 1 個分のバイト列から、（種類、コード、値）を取り出す。長さが違えば None。"""
    if len(data) != EVENT.size:
        return None
    _sec, _usec, kind, code, value = EVENT.unpack(data)
    return kind, code, value


def supports_key(capabilities: str, code: int, word_bits: int = WORD_BITS) -> bool:
    """装置の capabilities/key の値（16 進の語を空白で区切ったもの。上位の語が先）に、そのキーが含まれるか。"""
    words = capabilities.split()
    index = code // word_bits
    if index >= len(words):
        return False
    return bool((int(words[-1 - index], 16) >> (code % word_bits)) & 1)


def find_keyboards(sys_input: Path = SYS_INPUT, dev_input: Path = DEV_INPUT,
                   word_bits: int = WORD_BITS) -> list[Path]:
    """スペースキーを送れる入力装置（/dev/input/eventN）の一覧。"""
    found = []
    for node in sorted(sys_input.glob("event*")):
        try:
            capabilities = (node / "device" / "capabilities" / "key").read_text()
            if supports_key(capabilities, KEY_SPACE, word_bits):
                found.append(dev_input / node.name)
        except (OSError, ValueError):
            continue
    return found


class SpaceTracker:
    """複数の入力装置からのイベントを、スペースキーの「押した」「離した」に変える。

    どれか 1 つの装置で押されていれば「押している」。自動リピート（値 2）は、押し続けているだけなので無視する。
    """

    def __init__(self) -> None:
        self._down: set = set()

    def feed(self, device, kind: int, code: int, value: int) -> str | None:
        """イベントを渡す。「押した」なら "press"、「離した」なら "release"、変化がなければ None。"""
        if kind != EV_KEY or code != KEY_SPACE or value not in (0, 1):
            return None
        was_down = bool(self._down)
        if value == 1:
            self._down.add(device)
        else:
            self._down.discard(device)
        return self._change(was_down)

    def forget(self, device) -> str | None:
        """装置が外れたとき。押したまま外れたなら、離したことにする。"""
        was_down = bool(self._down)
        self._down.discard(device)
        return self._change(was_down)

    def _change(self, was_down: bool) -> str | None:
        is_down = bool(self._down)
        if is_down and not was_down:
            return "press"
        if was_down and not is_down:
            return "release"
        return None


class SpaceWatcher:
    """別のスレッドで入力装置を読み、"press" / "release" を events に入れる（受け取る側は get_nowait で取る）。"""

    def __init__(self, find=find_keyboards) -> None:
        self.events: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._find = find
        self._tracker = SpaceTracker()
        self._fds: dict[int, Path] = {}

    def start(self) -> None:
        threading.Thread(target=self._run, name="space-watcher", daemon=True).start()

    # ---------- 読み取りの本体（テストしやすいように、入出力と分けてある）----------

    def handle(self, device, data: bytes) -> None:
        """装置から読んだバイト列（イベント数個分）を処理する。"""
        for start in range(0, len(data) - EVENT.size + 1, EVENT.size):
            event = parse_event(data[start:start + EVENT.size])
            if event is None:
                continue
            change = self._tracker.feed(device, *event)
            if change:
                self.events.put(change)

    def _drop(self, fd: int) -> None:
        device = self._fds.pop(fd, None)
        try:
            os.close(fd)
        except OSError:
            pass
        change = self._tracker.forget(device)
        if change:
            self.events.put(change)

    # ---------- 入出力 ----------

    def _rescan(self) -> None:
        known = set(self._fds.values())
        for path in self._find():
            if path in known:
                continue
            try:
                self._fds[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = path
            except OSError:
                continue  # 権限が無い、または外れた。Tk のキー入力に任せる

    def _run(self) -> None:
        last_scan = float("-inf")
        while True:
            if time.monotonic() - last_scan >= RESCAN_SECONDS:
                self._rescan()
                last_scan = time.monotonic()
            if not self._fds:
                time.sleep(1.0)
                continue
            try:
                ready, _, _ = select.select(list(self._fds), [], [], 0.5)
            except (OSError, ValueError):
                for fd in list(self._fds):
                    self._drop(fd)
                continue
            for fd in ready:
                try:
                    data = os.read(fd, EVENT.size * 32)
                except BlockingIOError:
                    continue
                except OSError:  # 装置が外れた
                    self._drop(fd)
                    continue
                if not data:
                    self._drop(fd)
                    continue
                self.handle(self._fds[fd], data)
