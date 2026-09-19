"""設定の読み込み。

値は環境変数から取る。Pi 上では ~/voice-assistant/.env に書いておくと起動時に読み込まれる。
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
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
