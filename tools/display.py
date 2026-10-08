#!/usr/bin/env python3
"""会話ログと伝言板をモニターに大きく表示する画面（音声アシスタント本体とは別プロセス）。

本体の venv ではなく**システムの python3** で動かす（tkinter を使うため。本体の依存は増やさない）。
画面が落ちても音声アシスタントは動き続ける。仕様は docs/display-spec.md を参照。

画面は左右に分かれる：左が今までの表示（状態・質問・返答・過去のやり取り）、右が伝言板
（宛先ごとの件数のチップ、伝言のカード、お知らせ、常時表示の凡例）。伝言の中身は tools/board_model.py が決める。

使い方（Pi のデスクトップ上で）：
    python3 tools/display.py

キー操作：
    スペース（押しっぱなし）… 押している間だけ聞き取る（うるさいときに近くで話すため）
    c … 見切れ調整モードの入り切り（テレビ側のオーバースキャンで端が切れる場合に使う）
        調整中：Tab で辺を選ぶ／矢印で動かす／Enter で保存／Esc で取り消し
    q … 終了（デスクトップのアイコンから開き直せる）
伝言板のキー（数字キー、矢印、Delete、Insert。あればテンキー）は、本体が入力装置から直接読む（画面は関与しない）。
"""

import json
import queue
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import font as tkfont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.board_model import CONFIRMING, SELECTED, build_model, dim, page_note, text_color_for  # noqa: E402
from tools.display_log import (  # noqa: E402
    STATE_LABELS,
    confidence_mark,
    current_state,
    default_state_path,
    default_talk_path,
    history_alive,
    latest_exchange,
    past_exchanges,
    read_entries,
    read_state,
    statistics,
)
from voice_assistant.board import DEFAULT_PATH as BOARD_PATH  # noqa: E402
from voice_assistant.board import SETTINGS_PATH as BOARD_SETTINGS_PATH  # noqa: E402
from voice_assistant.board import (  # noqa: E402
    Board,
    BoardSettings,
    default_view_path,
    load_board,
    read_view,
)
from voice_assistant.board import load_settings as load_board_settings  # noqa: E402
from voice_assistant.evdev_keys import KEY_SPACE, KeyWatcher  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = PROJECT_ROOT / "logs" / "conversation.log"
# 見切れの調整値などの保存先。tools/deploy.sh の対象外なので、配置し直しても消えない
SETTINGS_PATH = PROJECT_ROOT / "display-settings.json"
REFRESH_MS = 500
# 画面に出す過去のやり取りの数（多いと返答の行と重なる）
PAST_ON_SCREEN = 3
# ボタンの合図を送る間隔と、キーの自動リピートを見分けるための待ち時間
TALK_TOUCH_MS = 200
KEY_REPEAT_MS = 60
# /dev/input から読んだスペースキーの押下を、画面側で取り込む間隔
KEY_POLL_MS = 50
# 伝言のある宛先のチップを、ゆっくり明滅させる間隔（自分宛てに気づけるように）
PULSE_MS = 800
# 全画面になっているかを確かめる間隔（起動の直後に、全画面にならず小さなウィンドウになることがあるため）
FULLSCREEN_CHECK_MS = 3000
# 画面の左側（今までの表示）の幅の割合と、左右のすき間（ピクセル）
LEFT_RATIO = 0.52
COLUMN_GAP = 24

# テレビは内部で画面を引き伸ばし、端を切り落とすことがある（オーバースキャン）。
# 既定で上下左右に 4% の余白を取り、実機を見ながら c キーで調整する
DEFAULT_SETTINGS = {"margin_top": 0.04, "margin_bottom": 0.04, "margin_left": 0.04,
                    "margin_right": 0.04, "font_scale": 1.0}

BACKGROUND = "#101418"
TEXT = "#e8eaed"
DIM = "#8b9299"
# まだ使えない案内に使う色（取り消し線とあわせて「準備中」と分かるようにする）
NOT_READY = "#5b6166"
# 聞き取りの質を質問の文字色で示す（○＝白、△＝黄、×＝赤）。記号や説明文は出さない
HEARD_COLORS = {"○": "#e8eaed", "△": "#f2c14e", "×": "#ff6b6b", "": "#e8eaed"}
STATE_COLORS = {"starting": "#9aa0a6", "waiting": "#57d977", "listening": "#5aa9ff",
                "thinking": "#f2c14e", "speaking": "#5aa9ff", "followup": "#57d977",
                "error": "#ff6b6b", "unknown": "#9aa0a6"}
# 伝言板の色
CARD_BG = "#1a2027"
CARD_SELECTED_BG = "#27323f"
CHIP_EMPTY_BG = "#1a2027"
SELECTED_BORDER = "#f2c14e"
CONFIRMING_BORDER = "#ff6b6b"
BANNER_BG = "#f2c14e"
FONT_CANDIDATES = ("Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic", "IPAGothic",
                   "VL Gothic", "DejaVu Sans")
# 余白を除いた高さに対する文字の大きさ。左側（今までの表示）は、Tk のポイント指定（1 ポイント ＝ 約 1.33 ピクセル）。
# 右側が半分の幅になったので、200 文字の返答が画面の下で切れないよう、質問・返答は小さめにした（2026-10-08 に実機で確認）
SIZES = {"state": 0.075, "state_sub": 0.025, "heard": 0.030, "reply": 0.030,
         "past": 0.021, "stats": 0.024,
         # 伝言板：ピクセル指定（PIXEL_SIZES）。5 件で、60 文字の伝言でも、画面の高さに収まる大きさ
         "board_title": 0.030, "chip": 0.022, "badge": 0.020, "card_name": 0.026,
         "card_text": 0.025, "card_meta": 0.017, "banner": 0.022, "page_note": 0.018, "legend": 0.017}
PIXEL_SIZES = frozenset({"board_title", "chip", "badge", "card_name", "card_text", "card_meta", "banner",
                         "page_note", "legend"})
# 左側（今までの表示）と右側（伝言板）に置くラベルの名前
LEFT_LABELS = ("state", "state_sub", "state_note", "heard", "reply", "past")
RIGHT_LABELS = ("board_title", "page_note", "banner", "banner_sub", "legend_keys", "legend_ops")

EDGES = ("top", "bottom", "left", "right")
EDGE_LABELS = {"top": "上", "bottom": "下", "left": "左", "right": "右"}


def load_settings() -> dict:
    """保存した調整値を読む。無ければ既定値。"""
    settings = dict(DEFAULT_SETTINGS)
    try:
        settings.update(json.loads(SETTINGS_PATH.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict) -> bool:
    try:
        SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def pick_font() -> str:
    """日本語が出せるフォントを選ぶ。"""
    available = set(tkfont.families())
    return next((name for name in FONT_CANDIDATES if name in available), "TkDefaultFont")


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 1] + "…"


class Display:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = load_settings()
        self.calibrating = False
        self.edge_index = 0
        self.log_mtime: float | None = None
        self.state_mtime: float | None = None
        self.state_path = default_state_path()
        self.talk_path = default_talk_path()
        self.talking = False
        self.release_job = None
        self.family = pick_font()
        # 伝言板（ファイルを読み直すのは、変わったときだけ）
        self.board_path = BOARD_PATH
        self.board_settings_path = BOARD_SETTINGS_PATH
        self.view_path = default_view_path()
        self.board_mtimes: tuple | None = None
        self.board_data = Board()
        self.board_settings = BoardSettings()
        self.board_view: dict = {}
        self.board_problem: str | None = None
        self.board_model = None
        self.chip_widgets: list[tuple[tk.Label, object]] = []
        self.pulse_on = False
        self.safe_h = 1000
        self.left_w = self.right_w = 800

        root.title("音声アシスタント")
        root.configure(bg=BACKGROUND)
        root.attributes("-fullscreen", True)
        root.config(cursor="none")

        # 画面の端が切れるテレビでも中身が見えるよう、余白の内側にだけ描く
        self.safe = tk.Frame(root, bg=BACKGROUND, highlightthickness=0,
                             highlightbackground="#ff6b6b")
        # 最下部は「統計（左）」と「キーの案内（右）」に分ける。その上が、左右に分かれた本体
        self.bottom = tk.Frame(self.safe, bg=BACKGROUND)
        self.main = tk.Frame(self.safe, bg=BACKGROUND)
        self.left = tk.Frame(self.main, bg=BACKGROUND)
        self.right = tk.Frame(self.main, bg=BACKGROUND)
        self.title_row = tk.Frame(self.right, bg=BACKGROUND)
        self.chips_frame = tk.Frame(self.right, bg=BACKGROUND)
        self.cards_frame = tk.Frame(self.right, bg=BACKGROUND)
        self.banner_box = tk.Frame(self.right, bg=BACKGROUND)  # お知らせ（1 行目と、小さな 2 行目）

        self.labels = {
            "state": self._label("state", TEXT, parent=self.left),
            "state_sub": self._label("state_sub", DIM, parent=self.left),
            "state_note": self._label("state_sub", DIM, parent=self.left),
            "heard": self._label("heard", TEXT, parent=self.left),
            "reply": self._label("reply", TEXT, parent=self.left),
            "past": self._label("past", DIM, parent=self.left),
            "guide": self._label("state_sub", "#ff6b6b", parent=self.safe),
            "stats": self._label("stats", DIM, parent=self.bottom),
            "keys": self._label("stats", NOT_READY, parent=self.bottom),
            "board_title": self._label("board_title", TEXT, parent=self.title_row),
            "page_note": self._label("page_note", DIM, parent=self.title_row),
            "banner": self._label("banner", "#101418", parent=self.banner_box),
            "banner_sub": self._label("page_note", "#101418", parent=self.banner_box),
            "legend_keys": self._label("legend", NOT_READY, parent=self.right),
            "legend_ops": self._label("legend", NOT_READY, parent=self.right),
        }
        self.labels["keys"].configure(text="q：終了")
        self.labels["board_title"].configure(text="伝言板")
        for key in (*LEFT_LABELS, "stats", "board_title", "page_note", "banner", "banner_sub", "legend_keys", "legend_ops"):
            self.labels[key].configure(justify="left", anchor="nw")
        # 位置を固定すると、下の行の背景が上の行の文字を隠してしまう（2026-09-23 に実機で判明）。
        # pack で上から順に積み、高さは文字に合わせて自動で決めさせる
        self.bottom.pack(side="bottom", fill="x")
        self.labels["keys"].pack(in_=self.bottom, side="right", anchor="e")
        self.labels["stats"].pack(in_=self.bottom, side="left", anchor="w")
        self.main.pack(side="top", fill="both", expand=True)
        self.left.pack(side="left", fill="y")
        self.left.pack_propagate(False)
        self.right.pack(side="left", fill="both", expand=True, padx=(COLUMN_GAP, 0))
        # 左：past は下に寄せ、そのほかは上から順に積む
        self.labels["past"].pack(side="bottom", anchor="w", fill="x")
        for key in ("state", "state_sub", "state_note", "heard", "reply"):
            self.labels[key].pack(anchor="w", fill="x")
        # 右：下から、凡例、お知らせの順に確保する（カードが多くても、これらが隠れないように、
        # 先に場所を取っておく）。そのあと、上から、題（右端にページの案内）、チップ、カードを積む
        self.labels["legend_ops"].pack(side="bottom", anchor="w", fill="x")
        self.labels["legend_keys"].pack(side="bottom", anchor="w", fill="x")
        self.banner_box.pack(side="bottom", anchor="w", fill="x", pady=(0, 4))
        self.labels["banner"].pack(anchor="w", fill="x")
        self.title_row.pack(anchor="w", fill="x")
        self.labels["board_title"].pack(side="left", anchor="w")
        self.labels["page_note"].pack(side="right", anchor="e")
        self.chips_frame.pack(anchor="w", fill="x")
        self.cards_frame.pack(anchor="w", fill="x", pady=(8, 0))

        root.bind("<Key>", self.on_key)
        root.bind("<KeyPress-space>", self.on_talk_press)
        root.bind("<KeyRelease-space>", self.on_talk_release)
        # スペースキーは、画面のフォーカスに頼らず、入力装置からも直接読む（2026-10-05。
        # ログイン直後の自動起動のときだけ、Tk がキーを受け取れず、クリックするまで効かない障害があったため）。
        # Tk のキー入力は、予備として残す。どちらから来ても同じ処理
        self.keys = KeyWatcher({KEY_SPACE})
        self.keys.start()
        self.layout()
        self.refresh()
        self.root.after(KEY_POLL_MS, self.poll_keys)
        self.root.after(PULSE_MS, self.pulse)
        self.root.after(FULLSCREEN_CHECK_MS, self.keep_fullscreen)

    def _label(self, size_key: str, color: str, style: str = "", parent=None) -> tk.Label:
        label = tk.Label(parent if parent is not None else self.safe, bg=BACKGROUND, fg=color, text="")
        label.size_key = size_key  # layout() で大きさを決め直すため覚えておく
        label.style = style  # "overstrike"（取り消し線）など
        return label

    # ---------- 配置 ----------

    def layout(self) -> None:
        """画面の大きさと余白から、位置と文字の大きさを決める。"""
        width, height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        left = int(width * self.settings["margin_left"])
        right = int(width * self.settings["margin_right"])
        top = int(height * self.settings["margin_top"])
        bottom = int(height * self.settings["margin_bottom"])
        safe_w, safe_h = width - left - right, height - top - bottom
        self.safe.place(x=left, y=top, width=safe_w, height=safe_h)
        self.safe_h = safe_h
        self.left_w = int(safe_w * LEFT_RATIO)
        self.right_w = safe_w - self.left_w - COLUMN_GAP
        self.left.configure(width=self.left_w)

        scale = self.settings["font_scale"]
        for key, label in self.labels.items():
            size = max(8, int(safe_h * SIZES[label.size_key] * scale))
            # 行間を少し空ける（文字の上下が詰まって見切れて見えないように）
            # Tk の文字サイズは、負の値ならピクセル、正の値ならポイント
            shown = -size if label.size_key in PIXEL_SIZES else size
            font = (self.family, shown, label.style) if label.style else (self.family, shown)
            if key == "keys":
                wrap = 0
            elif key in LEFT_LABELS:
                wrap = self.left_w
            elif key in RIGHT_LABELS:
                wrap = self.right_w
            else:
                wrap = safe_w
            label.configure(font=font, wraplength=wrap, pady=max(2, int(size * 0.12)))
        self.board_model = None  # 文字の大きさが変わったので、伝言板を描き直す
        self.update_board()

    def font(self, key: str, bold: bool = False) -> tuple:
        """伝言板の文字（ピクセル指定）。"""
        size = -max(8, int(self.safe_h * SIZES[key] * self.settings["font_scale"]))
        return (self.family, size, "bold") if bold else (self.family, size)

    def keep_fullscreen(self) -> None:
        """全画面になっていなければ、全画面にし直す。

        起動の直後に、全画面の指定が効かず、小さなウィンドウ（200×200）になることがある
        （2026-10-05 と 2026-10-08 に実機で見た。再現は稀）。家族が使う画面なので、自分で直す。
        """
        try:
            width, height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            if self.root.winfo_ismapped() and (self.root.winfo_width() < width * 0.9
                                               or self.root.winfo_height() < height * 0.9):
                self.root.attributes("-fullscreen", False)
                self.root.update_idletasks()
                self.root.attributes("-fullscreen", True)
        except tk.TclError:
            pass  # 画面を閉じている途中など。次の機会にやり直す
        self.root.after(FULLSCREEN_CHECK_MS, self.keep_fullscreen)

    # ---------- 表示の更新 ----------

    def refresh(self) -> None:
        log_mtime = self._mtime(LOG_PATH)
        state_mtime = self._mtime(self.state_path)
        if (log_mtime, state_mtime) != (self.log_mtime, self.state_mtime):
            self.log_mtime, self.state_mtime = log_mtime, state_mtime
            self.update_texts()
        self.update_board()
        self.root.after(REFRESH_MS, self.refresh)

    @staticmethod
    def _mtime(path) -> float | None:
        try:
            return path.stat().st_mtime if path is not None else None
        except OSError:
            return None

    def update_texts(self) -> None:
        entries = read_entries(LOG_PATH)
        reported = read_state(self.state_path)
        state = current_state(entries, reported)
        title, sub = STATE_LABELS[state]
        self.labels["state"].configure(text=title, fg=STATE_COLORS[state])
        self.labels["state_sub"].configure(text=sub)
        self.labels["state_note"].configure(
            text="またはキーボードのスペースキーを押しっぱなしにして質問してください"
            if state == "waiting" else "")

        latest = latest_exchange(entries)
        if latest is None:
            self.labels["heard"].configure(text="")
            self.labels["reply"].configure(text="まだ会話がありません")
        else:
            heard, reply = latest
            mark, _ = confidence_mark(heard.confidence)
            self.labels["heard"].configure(text=f"質問　： {shorten(heard.body, 40)}",
                                           fg=HEARD_COLORS[mark])
            # 返答がまだ無い間は空欄にする。質問欄は認識直後に切り替わるが、返答は AI の応答を
            # 待つ必要があるため、考え中の間に前回の文言を出したままだと「今回も聞き取れなかったのか」と
            # 誤解されるため（2026-09-24 に利用者から指摘）。送らなかった理由（雑音・短すぎ）も含めて
            # 空欄にする（理由は確信度の記号と状態表示から読み取れる）
            self.labels["reply"].configure(text=f"返答　： {shorten(reply.body, 200)}" if reply else "")

        past = past_exchanges(entries, limit=PAST_ON_SCREEN)
        # 会話履歴が生きている間は明るく出す（「前の話の続き」を言えると分かるように）
        self.labels["past"].configure(
            fg=DIM if history_alive(reported) else NOT_READY,
            text="\n".join(f"・{shorten(h.body, 10)} → {shorten(r.body, 12)}　{r.clock}" for h, r in past))

        got = statistics(entries)
        # 使用中のモデルは本体が状態ファイルに書く（画面は .env を読まない＝API キーに触れない）
        model = (reported or {}).get("model")
        used = f"（{'予備 ' if (reported or {}).get('fallback') else ''}{model}）" if model else ""
        parts = [f"今日の利用 およそ {got.ai_calls} 回{used}", f"誤反応 {got.false_wakes}",
                 f"見送り {got.suppressed}", f"遅い応答 {got.slow_responses}"]
        if got.errors:
            parts.append(f"エラー {got.errors}")
        self.labels["stats"].configure(text="　".join(parts))

    # ---------- 伝言板 ----------

    def load_board_files(self) -> None:
        """伝言・宛先の設定・表示の状態を、ファイルが変わっていれば読み直す（画面は読むだけで、書かない）。"""
        mtimes = (self._mtime(self.board_path), self._mtime(self.board_settings_path), self._mtime(self.view_path))
        if mtimes == self.board_mtimes:
            return
        self.board_mtimes = mtimes
        self.board_problem = None
        try:
            self.board_data = load_board(self.board_path)
        except (OSError, ValueError):
            self.board_data, self.board_problem = Board(), "伝言を読めません"
        try:
            self.board_settings = load_board_settings(self.board_settings_path)
        except (OSError, ValueError):
            self.board_settings, self.board_problem = BoardSettings(), "宛先の設定を読めません"
        self.board_view = read_view(self.view_path)

    def update_board(self) -> None:
        """伝言板の内容が変わっていれば、描き直す（期限で消えるお知らせや新着の印も、ここで反映される）。"""
        self.load_board_files()
        model = build_model(self.board_data, self.board_settings, self.board_view, datetime.now(),
                            self.board_problem)
        if model != self.board_model:
            self.board_model = model
            self.draw_board(model)

    def draw_board(self, model) -> None:
        for frame in (self.chips_frame, self.cards_frame):
            for child in frame.winfo_children():
                child.destroy()
        self.chip_widgets = []
        self.draw_chips(model)
        if model.cards:
            for card in model.cards:
                self.draw_card(card)
        else:
            tk.Label(self.cards_frame, text="伝言はありません", bg=BACKGROUND, fg=DIM,
                     font=self.font("card_text"), anchor="w").pack(anchor="w", pady=12)
        self.labels["page_note"].configure(text=page_note(model))
        # お知らせの帯は、常に場所を取っておき、無いときは背景色にして目立たせない
        # 「\n」があれば、2 行目は小さな文字で別に出す（全部消す確認で、実行のキーと中止のキーを分けて見せるため）
        banner, _, sub = (model.problem or model.banner).partition(chr(10))
        color = "#ff6b6b" if model.problem or model.danger else BANNER_BG
        if banner:
            self.labels["banner"].configure(text=f"  {banner}  ", bg=color)
        else:
            self.labels["banner"].configure(text=" ", bg=BACKGROUND)
        if sub:
            self.labels["banner_sub"].configure(text=f"  {sub}  ", bg=color)
            self.labels["banner_sub"].pack(anchor="w", fill="x")
        else:
            self.labels["banner_sub"].pack_forget()
        self.labels["legend_keys"].configure(text=model.legend[0])
        self.labels["legend_ops"].configure(text=model.legend[1])

    def draw_chips(self, model) -> None:
        """宛先ごとのチップ。伝言のある宛先は、宛先の色で塗り、ゆっくり明滅させる。"""
        columns = 5
        for index, chip in enumerate(model.chips):
            active = chip.count > 0
            background = chip.color if active else CHIP_EMPTY_BG
            foreground = text_color_for(chip.color) if active else NOT_READY
            label = tk.Label(self.chips_frame, text=f"{chip.name}　{chip.count}", bg=background, fg=foreground,
                             font=self.font("chip", bold=active), padx=10, pady=4)
            label.grid(row=index // columns, column=index % columns, sticky="ew", padx=3, pady=3)
            self.chips_frame.grid_columnconfigure(index % columns, weight=1, uniform="chip")
            if active:
                self.chip_widgets.append((label, chip))

    def draw_card(self, card) -> None:
        """伝言 1 件のカード。宛名を宛先の色で大きく出し、選んでいる・確認中のカードは枠で強調する。"""
        border = {CONFIRMING: CONFIRMING_BORDER, SELECTED: SELECTED_BORDER}.get(card.state)
        background = CARD_SELECTED_BG if card.state else CARD_BG
        # 枠は常に同じ太さにして、状態が変わっても、カードの大きさが変わらないようにする
        outer = tk.Frame(self.cards_frame, bg=background, highlightthickness=4,
                         highlightbackground=border or background, highlightcolor=border or background)
        outer.pack(fill="x", pady=3)
        tk.Frame(outer, bg=card.color, width=12).pack(side="left", fill="y")
        body = tk.Frame(outer, bg=background)
        body.pack(side="left", fill="both", expand=True, padx=12, pady=5)
        head = tk.Frame(body, bg=background)
        head.pack(fill="x")
        tk.Label(head, text=f" {card.number} ", bg=card.color, fg=text_color_for(card.color),
                 font=self.font("badge", bold=True)).pack(side="left")
        tk.Label(head, text=f"{card.name}へ", bg=background, fg=card.color,
                 font=self.font("card_name", bold=True)).pack(side="left", padx=10)
        if card.is_new:
            tk.Label(head, text=" 新着 ", bg=BANNER_BG, fg="#101418",
                     font=self.font("card_meta", bold=True)).pack(side="left")
        tk.Label(head, text=card.time, bg=background, fg=DIM, font=self.font("card_meta")).pack(side="right")
        tk.Label(body, text=card.text, bg=background, fg=TEXT, font=self.font("card_text"),
                 justify="left", anchor="w", wraplength=self.right_w - 60).pack(fill="x", anchor="w")

    def pulse(self) -> None:
        """伝言のある宛先のチップを、ゆっくり明滅させる（色を、元の色と、少し暗い色で入れ替える）。"""
        self.pulse_on = not self.pulse_on
        for label, chip in self.chip_widgets:
            try:
                label.configure(bg=dim(chip.color, 0.6) if self.pulse_on else chip.color)
            except tk.TclError:
                pass  # 描き直しで、すでに無い
        self.root.after(PULSE_MS, self.pulse)

    # ---------- ボタン（スペースキー）----------

    def on_talk_press(self, event: tk.Event) -> str:
        self.press_talk()
        return "break"  # 調整モードのキー処理には渡さない

    def on_talk_release(self, event: tk.Event) -> str:
        self.release_talk()
        return "break"

    def poll_keys(self) -> None:
        """/dev/input から読んだスペースキーの押下・解放を取り込む（別スレッドが貯めたものを取り出す）。"""
        while True:
            try:
                change, _code = self.keys.events.get_nowait()
            except queue.Empty:
                break
            if change == "press":
                self.press_talk()
            else:
                self.release_talk()
        self.root.after(KEY_POLL_MS, self.poll_keys)

    def press_talk(self) -> None:
        """押している間だけ聞き取ってもらう。合図を短い間隔で送り続ける。"""
        if self.calibrating:
            return  # 調整中は聞き取りを始めない
        if self.release_job is not None:  # 自動リピートによる「離した」を取り消す
            self.root.after_cancel(self.release_job)
            self.release_job = None
        if not self.talking:
            self.talking = True
            self.touch_talk()

    def release_talk(self) -> None:
        """離したことにする。ただし自動リピートの可能性があるので少し待って確かめる。"""
        if self.release_job is not None:
            self.root.after_cancel(self.release_job)
        self.release_job = self.root.after(KEY_REPEAT_MS, self.stop_talk)

    def touch_talk(self) -> None:
        """押している間、合図のファイルを更新し続ける（止まれば本体が自動で解除する）。"""
        if not self.talking or self.talk_path is None:
            return
        try:
            self.talk_path.parent.mkdir(parents=True, exist_ok=True)
            self.talk_path.touch()
        except OSError:
            pass
        self.root.after(TALK_TOUCH_MS, self.touch_talk)

    def stop_talk(self) -> None:
        self.release_job = None
        self.talking = False
        if self.talk_path is not None:
            try:
                self.talk_path.unlink(missing_ok=True)
            except OSError:
                pass

    # ---------- 見切れの調整 ----------

    def on_key(self, event: tk.Event) -> None:
        key = event.keysym
        if not self.calibrating:
            if key in ("c", "C"):
                self.start_calibration()
            elif key in ("q", "Q"):
                self.root.destroy()
            return
        if key == "Tab":
            self.edge_index = (self.edge_index + 1) % len(EDGES)
        elif key in ("Return", "KP_Enter"):
            self.end_calibration(save=True)
            return
        elif key == "Escape":
            self.end_calibration(save=False)
            return
        elif key in ("Up", "Down", "Left", "Right"):
            self.move_edge(key)
        self.layout()
        self.show_guide()

    def move_edge(self, key: str) -> None:
        """選んでいる辺の余白を 0.5% ずつ増減する。"""
        edge = EDGES[self.edge_index]
        step = 0.005
        grow = key in ("Down", "Right") if edge in ("top", "left") else key in ("Up", "Left")
        name = f"margin_{edge}"
        self.settings[name] = min(0.2, max(0.0, self.settings[name] + (step if grow else -step)))

    def start_calibration(self) -> None:
        self.calibrating = True
        self.saved = dict(self.settings)
        self.safe.configure(highlightthickness=4)
        self.show_guide()

    def end_calibration(self, save: bool) -> None:
        self.calibrating = False
        if not save:
            self.settings = self.saved
        self.safe.configure(highlightthickness=0)
        self.labels["guide"].place_forget()
        self.layout()
        if save:
            save_settings(self.settings)

    def show_guide(self) -> None:
        edge = EDGES[self.edge_index]
        percent = self.settings[f"margin_{edge}"] * 100
        self.labels["guide"].configure(
            text=f"見切れ調整中：赤い枠が画面に収まるように調整してください\n"
                 f"Tab で辺を選ぶ（いま：{EDGE_LABELS[edge]} {percent:.1f}%）／矢印で動かす／"
                 f"Enter で保存／Esc で取り消し")
        self.labels["guide"].place(relx=0, rely=0.60, relwidth=1.0)


def main() -> int:
    root = tk.Tk()
    Display(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
