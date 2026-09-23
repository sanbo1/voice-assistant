"""`.env` の変更を見張り、動作中の設定を入れ替える。

調整のたびに再起動していると、音声認識の大きなモデルを読み直すため約 85 秒使えなくなる。
待ち受け中に `.env` の更新時刻を見て、変わっていれば読み直す（実測で 1 回 2.6 マイクロ秒。
読み直し自体も 0.33 ミリ秒で、変更があったときだけ行う）。

反映は**待ち受け中だけ**に限る。聞き取りや読み上げの途中で値が変わると、
会話の途中で挙動が変わってしまうため。

音声認識のモデル（`VOSK_MODEL_DIR`）だけは入れ替えられない（1.6GB の読み直しに数十秒かかる）。
変更を見つけたら、再起動が必要だと会話ログに出す。
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

from dotenv import dotenv_values

from .config import (
    PROJECT_ROOT,
    AssistantConfig,
    AudioConfig,
    GeminiConfig,
    SttConfig,
    WakeWordConfig,
    load_assistant_config,
    load_audio_config,
    load_gemini_config,
    load_stt_config,
    load_wakeword_config,
)

ENV_PATH = PROJECT_ROOT / ".env"

# 会話ログに出すときの言い方（変数名のままでは分かりにくいため）
LABELS = {
    "assistant.followup_seconds": "続けて話せる秒数",
    "assistant.followup_max_turns": "続けて話せる回数",
    "wakeword.threshold": "ウェイクワードのしきい値",
    "wakeword.patience_frames": "ウェイクワードの連続フレーム数",
    "wakeword.confirm_frames": "ウェイクワードの確認窓",
    "wakeword.confirm_threshold": "ウェイクワードの確認しきい値",
    "stt.model_dir": "音声認識のモデル",
    "stt.min_confidence": "聞き取りの確信度の下限",
    "audio.input_device": "マイク",
    "audio.output_device": "スピーカー",
    "gemini.model": "AI のモデル",
    "gemini.thinking_level": "AI の思考の量",
    "gemini.fallback_models": "予備のモデル",
    "gemini.api_key": "API キー",
}
# 値を会話ログに出してはいけない項目
SECRET = {"gemini.api_key"}
# 入れ替えられず、再起動が必要な項目
NEEDS_RESTART = {"stt.model_dir"}


@dataclass(frozen=True)
class Settings:
    assistant: AssistantConfig
    wakeword: WakeWordConfig
    stt: SttConfig
    audio: AudioConfig
    gemini: GeminiConfig


def load_settings(env: Mapping[str, str]) -> Settings:
    return Settings(
        assistant=load_assistant_config(env),
        wakeword=load_wakeword_config(env),
        stt=load_stt_config(env),
        audio=load_audio_config(env),
        gemini=load_gemini_config(env),
    )


def read_env(path: Path = ENV_PATH) -> Mapping[str, str]:
    """`.env` と環境変数を合わせる。**読み直しでは `.env` を優先する**。

    起動時は「すでにある環境変数 > `.env`」だが、読み直しでは逆にする。
    利用者が編集するのは `.env` であり、そちらが効かないと分かりにくいため。
    サービスが設定しているのは PYTHONUNBUFFERED と ORT_DISABLE_TELEMETRY だけで、
    `.env` に書く項目とは重ならない。
    """
    return {**os.environ, **{k: v for k, v in dotenv_values(path).items() if v is not None}}


def changes(old: Settings, new: Settings) -> list[str]:
    """変わった項目を、会話ログに出せる言い方で返す。"""
    found = []
    for group in fields(Settings):
        before, after = getattr(old, group.name), getattr(new, group.name)
        for item in fields(before):
            key = f"{group.name}.{item.name}"
            was, now = getattr(before, item.name), getattr(after, item.name)
            if was == now:
                continue
            label = LABELS.get(key, key)
            found.append(f"{label}を変更しました" if key in SECRET else f"{label} {was} → {now}")
    return found


def needs_restart(old: Settings, new: Settings) -> list[str]:
    """入れ替えられず、再起動しないと反映されない項目。"""
    return [LABELS[key] for key in NEEDS_RESTART
            if getattr(getattr(old, key.split(".")[0]), key.split(".")[1])
            != getattr(getattr(new, key.split(".")[0]), key.split(".")[1])]


class SettingsWatcher:
    """`.env` の更新時刻を見て、変わっていれば読み直す。"""

    def __init__(self, settings: Settings, path: Path = ENV_PATH):
        self._path = path
        self._settings = settings
        self._mtime = self._current_mtime()

    @property
    def settings(self) -> Settings:
        return self._settings

    def _current_mtime(self) -> float | None:
        try:
            return self._path.stat().st_mtime
        except OSError:
            return None

    def reload_if_changed(self) -> Settings | None:
        """`.env` が変わっていれば新しい設定を返す。変わっていなければ None。

        読み込みに失敗した場合も None を返す（直前の設定のまま動き続ける）。
        """
        mtime = self._current_mtime()
        if mtime == self._mtime:
            return None
        self._mtime = mtime
        try:
            settings = load_settings(read_env(self._path))
        except Exception:  # 壊れた .env でも本体を止めない
            return None
        if settings == self._settings:
            return None
        self._settings = settings
        return settings
