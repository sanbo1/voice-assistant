"""設定の読み込み。

値は環境変数から取る。Pi 上では ~/voice-assistant/.env に書いておくと起動時に読み込まれる。
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

Device = int | str | None


def load_env_file(path: Path = PROJECT_ROOT / ".env") -> bool:
    """.env を環境変数に読み込む。すでに設定されている環境変数は上書きしない。"""
    return load_dotenv(path)


def parse_device(value: str | None) -> Device:
    """デバイス指定を sounddevice に渡せる形にする。

    空なら None（既定のデバイス）、数字だけならデバイス番号、それ以外はデバイス名（部分一致）。
    """
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    return value


@dataclass(frozen=True)
class AudioConfig:
    input_device: Device = None
    output_device: Device = None


def load_audio_config(env: Mapping[str, str] = os.environ) -> AudioConfig:
    return AudioConfig(
        input_device=parse_device(env.get("AUDIO_INPUT_DEVICE")),
        output_device=parse_device(env.get("AUDIO_OUTPUT_DEVICE")),
    )


@dataclass(frozen=True)
class AssistantConfig:
    # 返答のあと、ウェイクワードなしで続けて話せる秒数（0 なら続けて話す機能を使わない）
    followup_seconds: float = 3.0
    # 続けて話せる回数の上限（1 回のウェイクワードにつき）
    followup_max_turns: int = 3


def parse_number(value: str | None, default: float | int) -> float | int:
    """数値の設定を読む。空や数値でない場合は既定値。"""
    value = (value or "").strip()
    if not value:
        return default
    try:
        return type(default)(value)
    except ValueError:
        return default


def load_assistant_config(env: Mapping[str, str] = os.environ) -> AssistantConfig:
    return AssistantConfig(
        followup_seconds=parse_number(env.get("FOLLOWUP_SECONDS"), AssistantConfig.followup_seconds),
        followup_max_turns=parse_number(env.get("FOLLOWUP_MAX_TURNS"), AssistantConfig.followup_max_turns),
    )


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str = field(default="", repr=False)  # 表示やログに API キーが出ないようにする
    model: str | None = None  # None なら既定のモデル
    thinking_level: str | None = None  # None なら、既定のモデルのときだけ既定の思考の量を使う
    fallback_models: tuple[str, ...] | None = None  # None なら既定の予備のモデル、() なら予備を使わない


def parse_model_list(value: str | None) -> tuple[str, ...] | None:
    """カンマ区切りのモデル名。空なら None（既定を使う）、"none" なら予備を使わない（空のタプル）。"""
    value = (value or "").strip()
    if not value:
        return None
    if value.lower() == "none":
        return ()
    return tuple(name.strip() for name in value.split(",") if name.strip())


def load_gemini_config(env: Mapping[str, str] = os.environ) -> GeminiConfig:
    return GeminiConfig(
        api_key=(env.get("GEMINI_API_KEY") or "").strip(),
        model=(env.get("GEMINI_MODEL") or "").strip() or None,
        thinking_level=(env.get("GEMINI_THINKING_LEVEL") or "").strip() or None,
        fallback_models=parse_model_list(env.get("GEMINI_FALLBACK_MODELS")),
    )
