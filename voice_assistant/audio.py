"""マイクからの録音とスピーカーでの再生（sounddevice を使う）。

device に None を渡すと既定のデバイスを使う。Pi 上では PipeWire の既定の入出力になる。
"""

import logging
import subprocess
from collections.abc import Iterator

import numpy as np
import sounddevice as sd

from .config import Device

SAMPLE_RATE = 16000
# 再生に使う周波数。PipeWire と HDMI が 48kHz で動いているため、そろえて変換をなくす
OUTPUT_SAMPLE_RATE = 48000
DTYPE = "int16"
# 再生時の待ち行列の長さ。"high" にすると余裕ができ、音が途切れたり遅くなったりしにくい
# （そのぶん鳴り始めが 0.2 秒ほど遅くなる）
PLAYBACK_LATENCY = "high"

logger = logging.getLogger(__name__)


def list_devices() -> str:
    """認識している入出力デバイスの一覧（表示用の文字列）。"""
    return str(sd.query_devices())


def parse_sinks(text: str) -> str:
    """`pactl list sinks short` の出力を「名前（状態）」の並びにする。

    1 行は「番号<タブ>名前<タブ>ドライバ<タブ>形式<タブ>状態」。
    """
    sinks = [f"{f[1]}（{f[-1]}）" for f in (line.split("\t") for line in text.splitlines()) if len(f) >= 5]
    return "、".join(sinks) if sinks else "なし"


def sink_summary() -> str:
    """PipeWire の出力先（シンク）の一覧と状態。取れないときはその理由を返す。"""
    try:
        result = subprocess.run(["pactl", "list", "sinks", "short"], capture_output=True, timeout=5, check=False)
    except (OSError, subprocess.SubprocessError) as e:
        return f"取得できず（{type(e).__name__}）"
    if result.returncode != 0:
        return f"取得できず（pactl の終了コード {result.returncode}）"
    return parse_sinks(result.stdout.decode("utf-8", errors="replace"))


def output_summary(device: Device = None) -> str:
    """いまの出力先の様子を 1 行にまとめる。

    起動直後の読み上げが聞こえないことがあるため、そのときの出力先を記録して原因を調べる
    （2026-09-21。技術ログは再起動で消えるので、会話ログに残す）。
    """
    try:
        name = sd.query_devices(device, "output")["name"]
    except Exception as e:  # デバイスが無い・開けないなど。記録が目的なので起動は止めない
        name = f"不明（{type(e).__name__}）"
    return f"デバイス「{name}」／シンク {sink_summary()}"


def record(seconds: float, *, device: Device = None, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """指定した秒数だけモノラルで録音し、int16 の 1 次元配列を返す。"""
    frames = int(seconds * sample_rate)
    data = sd.rec(frames, samplerate=sample_rate, channels=1, dtype=DTYPE, device=device)
    sd.wait()
    return data[:, 0].copy()


def play(samples: np.ndarray, sample_rate: int, *, device: Device = None) -> bool:
    """音声を再生し、終わるまで待つ。再生中に音が途切れていたら True を返す。

    途切れ（バッファ不足）は、波形はそのままで時間だけ伸びる形で聞こえるため、
    「間延びして聞こえる」現象の原因かどうかを調べる材料にする（2026-09-21）。
    再生のしかたは変えていない（sounddevice が記録している結果を読むだけ）。
    """
    sd.play(samples, samplerate=sample_rate, device=device, latency=PLAYBACK_LATENCY)
    sd.wait()
    try:
        return bool(sd.get_status().output_underflow)
    except RuntimeError:  # 直前の再生の記録がない場合（判断できないので、途切れなしとして扱う）
        return False


def play_nowait(samples: np.ndarray, sample_rate: int, *, device: Device = None) -> None:
    """音声の再生を始め、終わるのを待たずに戻る（録音を続けながら鳴らす用）。"""
    sd.play(samples, samplerate=sample_rate, device=device, latency=PLAYBACK_LATENCY)


def stream_frames(
    frame_samples: int, *, device: Device = None, sample_rate: int = SAMPLE_RATE
) -> Iterator[np.ndarray]:
    """マイクの音声を frame_samples ずつ（int16 の 1 次元配列で）返し続ける。"""
    with sd.InputStream(
        samplerate=sample_rate,
        channels=1,
        dtype=DTYPE,
        blocksize=frame_samples,
        device=device,
    ) as stream:
        while True:
            data, overflowed = stream.read(frame_samples)
            if overflowed:
                logger.warning("録音バッファがあふれました（処理が追いついていません）")
            yield data[:, 0].copy()
