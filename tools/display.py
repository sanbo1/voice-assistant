#!/usr/bin/env python3
"""会話ログをモニターに大きく表示する画面（音声アシスタント本体とは別プロセス）。

本体の venv ではなく**システムの python3** で動かす（tkinter を使うため。本体の依存は増やさない）。
画面が落ちても音声アシスタントは動き続ける。仕様は docs/display-spec.md を参照。

使い方（Pi のデスクトップ上で）：
    python3 tools/display.py

キー操作：
    c … 見切れ調整モードの入り切り（テレビ側のオーバースキャンで端が切れる場合に使う）
    q … 終了
"""

import json
import sys
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.display_log import (  # noqa: E402
    STATE_LABELS,
    confidence_mark,
    current_state,
    latest_exchange,
    past_exchanges,
    read_entries,
    statistics,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = PROJECT_ROOT / "logs" / "conversation.log"
# 見切れの調整値などの保存先。tools/deploy.sh の対象外なので、配置し直しても消えない
SETTINGS_PATH = PROJECT_ROOT / "display-settings.json"
REFRESH_MS = 1000

# テレビは内部で画面を引き伸ばし、端を切り落とすことがある（オーバースキャン）。
# 既定で上下左右に 4% の余白を取り、実機を見ながら c キーで調整する
DEFAULT_SETTINGS = {"margin_top": 0.04, "margin_bottom": 0.04, "margin_left": 0.04,
                    "margin_right": 0.04, "font_scale": 1.0}

BACKGROUND = "#101418"
TEXT = "#e8eaed"
DIM = "#8b9299"
STATE_COLORS = {"starting": "#9aa0a6", "waiting": "#57d977", "listening": "#5aa9ff",
                "thinking": "#f2c14e", "speaking": "#5aa9ff", "followup": "#57d977",
                "error": "#ff6b6b", "unknown": "#9aa0a6"}
# 会話履歴が生きている（直前のやり取りから 5 分以内）ときの背景。「前の話が続いている」ことを示す
ALIVE_BACKGROUND = "#17212b"

FONT_CANDIDATES = ("Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic", "IPAGothic",
                   "VL Gothic", "DejaVu Sans")
# 余白を除いた高さに対する文字の大きさ
SIZES = {"state": 0.075, "state_sub": 0.034, "heard": 0.047, "reply": 0.040,
         "past": 0.026, "stats": 0.024}

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
        self.family = pick_font()

        root.title("音声アシスタント")
        root.configure(bg=BACKGROUND)
        root.attributes("-fullscreen", True)
        root.config(cursor="none")

        # 画面の端が切れるテレビでも中身が見えるよう、余白の内側にだけ描く
        self.safe = tk.Frame(root, bg=BACKGROUND, highlightthickness=0,
                             highlightbackground="#ff6b6b")
        self.labels = {
            "state": self._label("state", TEXT),
            "state_sub": self._label("state_sub", DIM),
            "heard": self._label("heard", TEXT),
            "mark": self._label("state_sub", DIM),
            "reply": self._label("reply", TEXT),
            "past": self._label("past", DIM),
            "stats": self._label("stats", DIM),
            "guide": self._label("state_sub", "#ff6b6b"),
        }
        for key in ("state", "state_sub", "heard", "mark", "reply", "past", "stats"):
            self.labels[key].configure(justify="left", anchor="nw")
        # 位置を固定すると、下の行の背景が上の行の文字を隠してしまう（2026-09-23 に実機で判明）。
        # pack で上から順に積み、高さは文字に合わせて自動で決めさせる
        self.labels["stats"].pack(side="bottom", anchor="w", fill="x")
        self.labels["past"].pack(side="bottom", anchor="w", fill="x")
        for key in ("state", "state_sub", "heard", "mark", "reply"):
            self.labels[key].pack(anchor="w", fill="x")

        root.bind("<Key>", self.on_key)
        self.layout()
        self.refresh()

    def _label(self, size_key: str, color: str) -> tk.Label:
        label = tk.Label(self.safe, bg=BACKGROUND, fg=color, text="")
        label.size_key = size_key  # layout() で大きさを決め直すため覚えておく
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

        scale = self.settings["font_scale"]
        for label in self.labels.values():
            size = max(8, int(safe_h * SIZES[label.size_key] * scale))
            # 行間を少し空ける（文字の上下が詰まって見切れて見えないように）
            label.configure(font=(self.family, size), wraplength=safe_w,
                            pady=max(2, int(size * 0.12)))

    # ---------- 表示の更新 ----------

    def refresh(self) -> None:
        try:
            mtime = LOG_PATH.stat().st_mtime
        except OSError:
            mtime = None
        if mtime != self.log_mtime:
            self.log_mtime = mtime
            self.update_texts()
        self.root.after(REFRESH_MS, self.refresh)

    def update_texts(self) -> None:
        entries = read_entries(LOG_PATH)
        state = current_state(entries)
        title, sub = STATE_LABELS[state]
        if state == "waiting":
            sub += "\nまたはキーボードのスペースキーを押しっぱなしにして質問してください"
        self.labels["state"].configure(text=title, fg=STATE_COLORS[state])
        self.labels["state_sub"].configure(text=sub)

        latest = latest_exchange(entries)
        if latest is None:
            self.labels["heard"].configure(text="")
            self.labels["mark"].configure(text="")
            self.labels["reply"].configure(text="まだ会話がありません")
        else:
            heard, reply = latest
            mark, note = confidence_mark(heard.confidence)
            self.labels["heard"].configure(text=f"あなた： {shorten(heard.body, 60)}")
            self.labels["mark"].configure(text=f"{mark} {note}".strip())
            self.labels["reply"].configure(
                # 送らなかった理由は短すぎた場合と確信度が低い場合があるため、まとめた言い方にする
                text=f"返答　： {shorten(reply.body, 160)}" if reply else "（うまく聞き取れず、AI には送っていません）")

        past = past_exchanges(entries)
        self.labels["past"].configure(
            text="\n".join(f"・{shorten(h.body, 22)} → {shorten(r.body, 26)}　{r.clock}" for h, r in past))

        got = statistics(entries)
        parts = [f"今日の利用 およそ {got.ai_calls} 回", f"誤反応 {got.false_wakes}",
                 f"見送り {got.suppressed}", f"遅い応答 {got.slow_responses}"]
        if got.errors:
            parts.append(f"エラー {got.errors}")
        if got.fallback_model:
            parts.append(f"予備のモデル使用中（{got.fallback_model}）")
        self.labels["stats"].configure(text="　".join(parts))

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
