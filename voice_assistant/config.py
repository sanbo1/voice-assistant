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
    # スペースキーで話し始めたときの、続けて話せる回数の上限（0 なら、1 問で待ち受けに戻る）。
    # 押している間だけ聞き取る操作なので、続けて聞き取るとかえって周りの音を拾う（2026-09-24）
    followup_max_turns_key: int = 0


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
        followup_max_turns_key=parse_number(env.get("FOLLOWUP_MAX_TURNS_KEY"), AssistantConfig.followup_max_turns_key),
    )


@dataclass(frozen=True)
class SttConfig:
    """音声認識のモデル（models/ の中のフォルダ名）。

    既定は大型モデル（1.6GB）。2026-09-21 の実測では、小型より精度が高く認識も約 2 倍速い。
    小型（vosk-model-small-ja-0.22、95MB）に戻したいときは .env で指定する。
    """

    model_dir: str = "vosk-model-ja-0.22"
    # 単語ごとの確信度の平均がこれ未満なら、雑音を文字にしただけとみなして AI に送らない。
    # 2026-09-22 の実測：雑音だけ（テレビ）0.465／離れた位置からの質問 0.576〜0.847。
    # 隙間が狭いため余裕は小さい。取りこぼしが出たら下げる。0 にすると足切りをしない
    min_confidence: float = 0.52


def load_stt_config(env: Mapping[str, str] = os.environ) -> SttConfig:
    return SttConfig(
        model_dir=(env.get("VOSK_MODEL_DIR") or "").strip() or SttConfig.model_dir,
        min_confidence=parse_number(env.get("VOSK_MIN_CONFIDENCE"), SttConfig.min_confidence),
    )


@dataclass(frozen=True)
class WakeWordConfig:
    """ウェイクワード検知の調整値。意味は wakeword.TriggerGate を参照。"""

    # スコアがこの値以上のフレームを「立ち上がり」として数える
    threshold: float = 0.35
    # 何フレーム続けてしきい値を超えたら、確認窓に進むか（1 フレーム 80ms）
    patience_frames: int = 2
    # 立ち上がりのあと、何フレームぶんスコアを見てから決めるか（0 なら確認窓なし）
    confirm_frames: int = 3
    # 立ち上がりと確認窓を通した最大スコアがこの値未満なら反応しない。
    # 0 なら見送りが起きない（反応が confirm_frames ぶん遅れるだけ。材料を集める段階の設定）
    confirm_threshold: float = 0.0


def load_wakeword_config(env: Mapping[str, str] = os.environ) -> WakeWordConfig:
    return WakeWordConfig(
        threshold=parse_number(env.get("WAKEWORD_THRESHOLD"), WakeWordConfig.threshold),
        patience_frames=parse_number(env.get("WAKEWORD_PATIENCE_FRAMES"), WakeWordConfig.patience_frames),
        confirm_frames=parse_number(env.get("WAKEWORD_CONFIRM_FRAMES"), WakeWordConfig.confirm_frames),
        confirm_threshold=parse_number(env.get("WAKEWORD_CONFIRM_THRESHOLD"), WakeWordConfig.confirm_threshold),
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
