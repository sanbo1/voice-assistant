"""伝言板の動作（伝言を預かる、選ぶ、消す、元に戻す、ページを送る）をまとめる。標準ライブラリだけで動く。

声の命令（board_commands.py）と、キー操作（evdev_keys.py）の、どちらからでも同じ動作になるようにする。
データの書き込みは、ここだけが行う（board.py）。画面は、書かれたファイルを読んで描く。

キーの割り当て：
- 上段の数字キー 1〜9、0：押している間、宛先つきの伝言を話す（0 はみんな宛）。録音は assistant.py が行う
- 上下の矢印：いま画面に出ているカードを選ぶ（1 つずつ動かす）→ 5 秒以内に Delete で消す
  （テンキー 1〜5 でも選べる。テンキーの無いキーボードがあるので、上下の矢印を基本にした）
- Insert：最後に消した伝言を元に戻す
- 右矢印／PageDown、左矢印／PageUp：ページを送る
- Ctrl+Delete：全部消す（画面に確認が出る。5 秒以内にもう一度 Delete で実行。Esc・ほかのキー・時間切れは、何も消さない）
- Esc：選択や確認をやめる
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from .board import (
    DEFAULT_PATH,
    SETTINGS_PATH,
    NOTHING_TO_DELETE,
    Board,
    BoardSettings,
    View,
    add_message,
    default_view_path,
    delete_all,
    delete_message,
    load_board,
    load_settings,
    page_count,
    page_of,
    purge,
    restore_last,
    save_board,
    write_view,
)

# ---------- キー（Linux の入力コード）----------
KEY_ESC = 1
KEY_INSERT = 110
KEY_DELETE = 111
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_PAGEUP = 104
KEY_PAGEDOWN = 109
KEY_UP = 103
KEY_LEFTCTRL = 29
KEY_RIGHTCTRL = 97
CTRL_KEYS = (KEY_LEFTCTRL, KEY_RIGHTCTRL)
KEY_DOWN = 108
# 上段の数字キー：コード 2〜10 が 1〜9、11 が 0
DIGIT_KEYS = {code: str((code - 1) % 10) for code in range(2, 12)}
# テンキー 1〜5（NumLock の状態に関係なく、入力装置はこのコードを送る）
KEYPAD_NUMBERS = {79: 1, 80: 2, 81: 3, 75: 4, 76: 5}
BOARD_CODES = frozenset({*DIGIT_KEYS, *KEYPAD_NUMBERS, KEY_ESC, KEY_INSERT, KEY_DELETE,
                         KEY_LEFT, KEY_RIGHT, KEY_PAGEUP, KEY_PAGEDOWN, KEY_UP, KEY_DOWN, *CTRL_KEYS})

SELECT_SECONDS = 5  # カードを選んでから（最後に選ぶ操作をしてから）、Delete で消せる時間
CLEAR_ALL_SECONDS = 5  # Ctrl+Delete のあと、もう一度 Delete で全部消せる時間
CONFIRM_SECONDS = 15  # 声で「消してよいですか」と聞いてから、返事を待つ時間
BANNER_SECONDS = 10  # 画面のお知らせを出しておく時間
IDLE_SECONDS = 60  # 操作がなければ、1 ページ目に戻る時間

# 読み上げる短い応答（内容は読み上げない。2026-10-08 に利用者が指定）
CONFIRM = "{number}番を削除します。よろしいですか"
DELETED = "削除しました"
CANCELED = "やめました"
RESTORED = "戻しました"
RESTORED_MANY = "{count}件戻しました"
CONFIRM_ALL = "全部で{count}件を削除します。よろしいですか"
DELETED_ALL = "全部削除しました"
STORED = "預かりました"
STORED_FOR = "{name}宛に預かりました"
NO_NUMBER = "番号を言ってください"
NO_SUCH_NUMBER = "その番号の伝言はありません"
SAVE_FAILED = "伝言を保存できませんでした"
BANNER_DELETED = "消しました（Insert で元に戻せます）"
BANNER_RESTORED = "元に戻しました"
# 全部消す確認。1 行目に「実行」、2 行目に「中止」を分けて出す（実行と中止のキーを取り違えないため。画面は改行で 2 段にする）
BANNER_CLEAR_ALL = "全部で {count} 件を消します。もう一度 Delete で実行します。\n（中止したい場合は Esc）"
BANNER_CONFIRM_ALL = "全部で {count} 件を消しますか？（はい／いいえ）"
BANNER_DELETED_ALL = "全部消しました（Insert で元に戻せます）"
BANNER_CONFIRM = "{number}番を削除しますか？（はい／いいえ）"


def _stamp(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S")


def _later(moment: datetime, seconds: int) -> str:
    return _stamp(moment + timedelta(seconds=seconds))


class BoardController:
    def __init__(self, board_path: Path = DEFAULT_PATH, settings_path: Path = SETTINGS_PATH,
                 view_path: Path | None = None, clock: Callable[[], datetime] = datetime.now):
        self._board_path = board_path
        self._settings_path = settings_path
        self._view_path = view_path if view_path is not None else default_view_path()
        self._clock = clock
        self._problems: list[str] = []  # 伝言や設定を読めなかった理由（本体が取り出して、会話ログに残す）
        self._board = Board()
        self._board_mtime: float | None = None
        self._settings = BoardSettings()
        self._settings_mtime: float | None = None
        self.view = View()
        self._written: dict | None = None
        self._last_activity = clock()
        self._reload_board()
        self._reload_settings()
        self._refresh_view()

    # ---------- 読み込み ----------

    @staticmethod
    def _mtime(path: Path) -> float | None:
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    def _reload_board(self) -> None:
        try:
            self._board = purge(load_board(self._board_path), self._clock())
        except (OSError, ValueError) as e:
            self._problems.append(f"伝言を読めませんでした（{e}）")
        self._board_mtime = self._mtime(self._board_path)

    def _reload_settings(self) -> None:
        try:
            self._settings = load_settings(self._settings_path)
        except (OSError, ValueError) as e:
            self._problems.append(f"伝言板の宛先の設定を読めませんでした（{e}）")
        self._settings_mtime = self._mtime(self._settings_path)

    def take_problems(self) -> list[str]:
        """たまった「読めなかった・保存できなかった」理由を、取り出して空にする。"""
        problems, self._problems = self._problems, []
        return problems

    @property
    def board(self) -> Board:
        return self._board

    @property
    def settings(self) -> BoardSettings:
        if self._mtime(self._settings_path) != self._settings_mtime:
            self._reload_settings()
        return self._settings

    # ---------- 状態 ----------

    @property
    def confirming(self) -> bool:
        """声で「消してよいですか」と聞いて、返事を待っているか（全部消す確認も含む）。"""
        return self.view.confirming is not None or self.view.confirming_all

    def _clear_all_alive(self, now: datetime) -> bool:
        until = self.view.clear_all_until
        return bool(until) and _stamp(now) < until

    def _page_items(self):
        return page_of(self._board, self.view.page)

    def _refresh_view(self) -> None:
        """画面に渡す状態を、変わっていれば書く。"""
        pages = page_count(len(self._board.messages))
        self.view.page = min(max(self.view.page, 0), pages - 1)
        self.view.restorable = len(self._board.deleted)
        self.view.updated = _stamp(self._clock())
        snapshot = {key: value for key, value in self.view.as_json().items() if key != "updated"}
        if snapshot != self._written:
            write_view(self._view_path, self.view)
            self._written = snapshot

    def _selection_alive(self, now: datetime) -> bool:
        until = self.view.selected_until
        return bool(until) and _stamp(now) < until

    def _touch(self) -> None:
        self._last_activity = self._clock()

    def _notice(self, text: str) -> None:
        self.view.banner = text
        self.view.banner_until = _later(self._clock(), BANNER_SECONDS)

    def _clear_selection(self) -> None:
        if self.view.clear_all_until is not None:  # 全部消す確認の表示も、一緒に消す
            self.view.banner, self.view.banner_until = "", None
        self.view.selected = None
        self.view.selected_until = None
        self.view.confirming = None
        self.view.confirming_all = False
        self.view.clear_all_until = None

    def tick(self) -> None:
        """時間で消えるもの（選択、確認、お知らせ、2 ページ目以降の表示）を、期限が来たら消す。繰り返し呼ぶ。"""
        now = self._clock()
        stamp = _stamp(now)
        if self._mtime(self._board_path) != self._board_mtime:
            self._reload_board()  # 手で直されたとき
        if self.view.selected_until and stamp >= self.view.selected_until:
            self.view.selected, self.view.selected_until = None, None
        if self.view.banner_until and stamp >= self.view.banner_until:
            self.view.banner, self.view.banner_until = "", None
        if self.view.clear_all_until and stamp >= self.view.clear_all_until:
            self._clear_selection()  # 5 秒たったら、何も消さずにやめる
        if self.confirming and (now - self._last_activity).total_seconds() >= CONFIRM_SECONDS:
            self.view.banner, self.view.banner_until = "", None
            self._clear_selection()
        if self.view.page and (now - self._last_activity).total_seconds() >= IDLE_SECONDS:
            self.view.page = 0
            self._clear_selection()
        purged = purge(self._board, now)
        if purged is not self._board:
            self._board = purged
            self._save()
        self._refresh_view()

    def _save(self) -> bool:
        try:
            save_board(self._board_path, self._board)
        except OSError as e:
            self._problems.append(f"伝言を保存できませんでした（{type(e).__name__}）")
            return False
        self._board_mtime = self._mtime(self._board_path)
        return True

    # ---------- 声の操作 ----------

    def knows_recipient(self, key: str) -> bool:
        return self.settings.person(key) is not None

    def add(self, to: str, text: str) -> str:
        """伝言を預かる。読み上げる短い応答を返す（足せなければ、その理由）。"""
        board, error = add_message(self._board, to, text, self._clock())
        if error:
            return error
        previous, self._board = self._board, board
        if not self._save():
            self._board = previous
            return SAVE_FAILED
        self.view.page = 0
        self._clear_selection()
        self._touch()
        self._refresh_view()
        person = self.settings.person(to)
        return STORED_FOR.format(name=person.name) if person and to != self.settings.everyone.key else STORED

    def request_delete(self, number: int | None) -> str:
        """声で「N 番を消して」と言われた。対象を強調して、確認する。"""
        if number is None:
            return NO_NUMBER
        items = self._page_items()
        if not 1 <= number <= len(items):
            return NO_SUCH_NUMBER
        self._clear_selection()
        self.view.confirming = items[number - 1].id
        self.view.selected, self.view.selected_until = items[number - 1].id, None
        self.view.banner = BANNER_CONFIRM.format(number=number)
        self.view.banner_until = None  # 確認が終わるまで出す
        self._touch()
        self._refresh_view()
        return CONFIRM.format(number=number)

    def request_delete_all(self) -> str:
        """声で「全部消して」と言われた。件数を示して、確認する。"""
        count = len(self._board.messages)
        if count == 0:
            return NOTHING_TO_DELETE
        self._clear_selection()
        self.view.confirming_all = True
        self.view.banner = BANNER_CONFIRM_ALL.format(count=count)
        self.view.banner_until = None  # 確認が終わるまで出す
        self._touch()
        self._refresh_view()
        return CONFIRM_ALL.format(count=count)

    def answer_confirmation(self, yes: bool) -> str:
        """「消してよいですか」への返事。"""
        target, everything = self.view.confirming, self.view.confirming_all
        self.view.banner, self.view.banner_until = "", None
        self._clear_selection()
        if not yes or (target is None and not everything):
            self._refresh_view()
            return CANCELED
        return self._delete_all() if everything else self._delete(target)

    def cancel_confirmation(self) -> None:
        """返事が無かった（聞き取れなかった）とき。消さずに、確認をやめる。"""
        if self.confirming:
            self.view.banner, self.view.banner_until = "", None
            self._clear_selection()
            self._refresh_view()

    def undo(self) -> str:
        """最後に消した伝言を戻す。読み上げる短い応答を返す。"""
        board, restored, error = restore_last(self._board, self._clock())
        if error:
            self._board = board
            return error
        previous, self._board = self._board, board
        if not self._save():
            self._board = previous
            return SAVE_FAILED
        self._clear_selection()
        self._notice(BANNER_RESTORED)
        self._touch()
        self._refresh_view()
        return RESTORED if len(restored) == 1 else RESTORED_MANY.format(count=len(restored))

    def _delete(self, message_id: int) -> str:
        previous = self._board
        self._board = delete_message(self._board, message_id, self._clock())
        if self._board is previous:
            self._refresh_view()
            return NO_SUCH_NUMBER
        if not self._save():
            self._board = previous
            return SAVE_FAILED
        self._notice(BANNER_DELETED)
        self._touch()
        self._refresh_view()
        return DELETED

    def _delete_all(self) -> str:
        previous = self._board
        self._board = delete_all(self._board, self._clock())
        if self._board is previous:
            self._refresh_view()
            return NOTHING_TO_DELETE
        if not self._save():
            self._board = previous
            return SAVE_FAILED
        self._notice(BANNER_DELETED_ALL)
        self._touch()
        self._refresh_view()
        return DELETED_ALL

    # ---------- キー操作 ----------

    def handle_key(self, code: int, ctrl: bool = False) -> str | None:
        """キーが押された。読み上げる短い応答があれば返す（なければ None）。宛先の数字キーは、ここでは扱わない。

        ctrl は、そのとき Ctrl キーを押しているか（Ctrl+Delete で、全部消す確認に入る）。
        """
        now = self._clock()
        if code in CTRL_KEYS:
            return None  # Ctrl だけでは、何も変えない（Ctrl+Delete の途中）
        if self._clear_all_alive(now):  # 全部消す確認の途中。Delete だけが実行、ほかのキーは、何も消さずにやめる
            self._clear_selection()
            self._refresh_view()
            return self._delete_all() if code == KEY_DELETE else None
        if code == KEY_DELETE and ctrl and not self.confirming:
            return self._arm_clear_all(now)
        if code in KEYPAD_NUMBERS:
            items = self._page_items()
            number = KEYPAD_NUMBERS[code]
            if number <= len(items):
                self.view.confirming = None
                self.view.selected = items[number - 1].id
                self.view.selected_until = _later(now, SELECT_SECONDS)
                self._touch()
        elif code in (KEY_UP, KEY_DOWN):
            items = self._page_items()
            if items and not self.confirming:
                ids = [item.id for item in items]
                if self.view.selected in ids and self._selection_alive(now):
                    index = ids.index(self.view.selected) + (1 if code == KEY_DOWN else -1)
                else:
                    index = 0  # 何も選んでいないときは、どちらの矢印でも 1 番のカード
                self.view.selected = ids[min(max(index, 0), len(ids) - 1)]
                self.view.selected_until = _later(now, SELECT_SECONDS)
                self._touch()
        elif code == KEY_DELETE:
            target, until = self.view.selected, self.view.selected_until
            if target is not None and until and _stamp(now) < until and not self.confirming:
                self._clear_selection()
                return self._delete(target)
        elif code == KEY_INSERT:
            return self.undo()
        elif code in (KEY_RIGHT, KEY_PAGEDOWN, KEY_LEFT, KEY_PAGEUP):
            step = 1 if code in (KEY_RIGHT, KEY_PAGEDOWN) else -1
            pages = page_count(len(self._board.messages))
            self.view.page = min(max(self.view.page + step, 0), pages - 1)
            self._clear_selection()
            self._touch()
        elif code == KEY_ESC:
            self.view.banner, self.view.banner_until = "", None
            self._clear_selection()
        self._refresh_view()
        return None

    def _arm_clear_all(self, now: datetime) -> str | None:
        """Ctrl+Delete。件数を画面に出して、5 秒以内にもう一度 Delete が押されるのを待つ。"""
        count = len(self._board.messages)
        if count == 0:
            return NOTHING_TO_DELETE
        self._clear_selection()
        self.view.clear_all_until = _later(now, CLEAR_ALL_SECONDS)
        self.view.banner = BANNER_CLEAR_ALL.format(count=count)
        self.view.banner_until = self.view.clear_all_until
        self._touch()
        self._refresh_view()
        return None
