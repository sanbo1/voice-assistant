#!/usr/bin/env python3
"""会話ログをモニターに大きく表示する画面（音声アシスタント本体とは別プロセス）。

本体の venv ではなく**システムの python3** で動かす（tkinter を使うため。本体の依存は増やさない）。
画面が落ちても音声アシスタントは動き続ける。仕様は docs/display-spec.md を参照。

使い方（Pi のデスクトップ上で）：
    python3 tools/display.py

キー操作：
    スペース（押しっぱなし）… 押している間だけ聞き取る（うるさいときに近くで話すため）
    c … 見切れ調整モードの入り切り（テレビ側のオーバースキャンで端が切れる場合に使う）
        調整中：Tab で辺を選ぶ／矢印で動かす／Enter で保存／Esc で取り消し
    q … 終了（デスクトップのアイコンから開き直せる）
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
    default_state_path,
    default_talk_path,
    history_alive,
    latest_exchange,
    past_exchanges,
    read_entries,
    read_state,
    statistics,
)

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
FONT_CANDIDATES = ("Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic", "IPAGothic",
                   "VL Gothic", "DejaVu Sans")
# 余白を除いた高さに対する文字の大きさ
SIZES = {"state": 0.075, "state_sub": 0.025, "heard": 0.034, "reply": 0.040,
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
        self.state_mtime: float | None = None
        self.state_path = default_state_path()
        self.talk_path = default_talk_path()
        self.talking = False
        self.release_job = None
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
            "state_note": self._label("state_sub", DIM),
            "heard": self._label("heard", TEXT),
            "reply": self._label("reply", TEXT),
            "past": self._label("past", DIM),
            "guide": self._label("state_sub", "#ff6b6b"),
        }
        # 最下部は「統計（左）」と「キーの案内（右）」に分ける
        self.bottom = tk.Frame(self.safe, bg=BACKGROUND)
        self.labels["stats"] = self._label("stats", DIM, parent=self.bottom)
        self.labels["keys"] = self._label("stats", NOT_READY, parent=self.bottom)
        self.labels["keys"].configure(text="q：終了")
        for key in ("state", "state_sub", "state_note", "heard", "reply", "past", "stats"):
            self.labels[key].configure(justify="left", anchor="nw")
        # 位置を固定すると、下の行の背景が上の行の文字を隠してしまう（2026-09-23 に実機で判明）。
        # pack で上から順に積み、高さは文字に合わせて自動で決めさせる
        self.bottom.pack(side="bottom", fill="x")
        self.labels["keys"].pack(in_=self.bottom, side="right", anchor="e")
        self.labels["stats"].pack(in_=self.bottom, side="left", anchor="w")
        self.labels["past"].pack(side="bottom", anchor="w", fill="x")
        for key in ("state", "state_sub", "state_note", "heard", "reply"):
            self.labels[key].pack(anchor="w", fill="x")

        root.bind("<Key>", self.on_key)
        root.bind("<KeyPress-space>", self.on_talk_press)
        root.bind("<KeyRelease-space>", self.on_talk_release)
        self.layout()
        self.refresh()

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

        scale = self.settings["font_scale"]
        for label in self.labels.values():
            size = max(8, int(safe_h * SIZES[label.size_key] * scale))
            # 行間を少し空ける（文字の上下が詰まって見切れて見えないように）
            font = (self.family, size, label.style) if label.style else (self.family, size)
            wrap = 0 if label is self.labels.get("keys") else safe_w
            label.configure(font=font, wraplength=wrap, pady=max(2, int(size * 0.12)))

    # ---------- 表示の更新 ----------

    def refresh(self) -> None:
        log_mtime = self._mtime(LOG_PATH)
        state_mtime = self._mtime(self.state_path)
        if (log_mtime, state_mtime) != (self.log_mtime, self.state_mtime):
            self.log_mtime, self.state_mtime = log_mtime, state_mtime
            self.update_texts()
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
            self.labels["reply"].configure(
                # 送らなかった理由は短すぎた場合と確信度が低い場合があるため、まとめた言い方にする
                text=f"返答　： {shorten(reply.body, 200)}" if reply else "（うまく聞き取れず、AI には送っていません）")

        past = past_exchanges(entries, limit=PAST_ON_SCREEN)
        # 会話履歴が生きている間は明るく出す（「前の話の続き」を言えると分かるように）
        self.labels["past"].configure(
            fg=DIM if history_alive(reported) else NOT_READY,
            text="\n".join(f"・{shorten(h.body, 14)} → {shorten(r.body, 18)}　{r.clock}" for h, r in past))

        got = statistics(entries)
        # 使用中のモデルは本体が状態ファイルに書く（画面は .env を読まない＝API キーに触れない）
        model = (reported or {}).get("model")
        used = f"（{'予備 ' if (reported or {}).get('fallback') else ''}{model}）" if model else ""
        parts = [f"今日の利用 およそ {got.ai_calls} 回{used}", f"誤反応 {got.false_wakes}",
                 f"見送り {got.suppressed}", f"遅い応答 {got.slow_responses}"]
        if got.errors:
            parts.append(f"エラー {got.errors}")
        self.labels["stats"].configure(text="　".join(parts))

    # ---------- ボタン（スペースキー）----------

    def on_talk_press(self, event: tk.Event) -> str:
        """押している間だけ聞き取ってもらう。合図を短い間隔で送り続ける。"""
        if self.calibrating:
            return "break"  # 調整中は聞き取りを始めない
        if self.release_job is not None:  # 自動リピートによる「離した」を取り消す
            self.root.after_cancel(self.release_job)
            self.release_job = None
        if not self.talking:
            self.talking = True
            self.touch_talk()
        return "break"  # 調整モードのキー処理には渡さない

    def on_talk_release(self, event: tk.Event) -> str:
        """離したことにする。ただし自動リピートの可能性があるので少し待って確かめる。"""
        if self.release_job is not None:
            self.root.after_cancel(self.release_job)
        self.release_job = self.root.after(KEY_REPEAT_MS, self.stop_talk)
        return "break"

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
