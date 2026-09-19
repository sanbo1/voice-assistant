"""マイクからの録音とスピーカーでの再生（sounddevice を使う）。

device に None を渡すと既定のデバイスを使う。Pi 上では PipeWire の既定の入出力になる。
"""

import logging
from collections.abc import Iterator

import numpy as np
import sounddevice as sd

from .config import Device

SAMPLE_RATE = 16000
DTYPE = "int16"

logger = logging.getLogger(__name__)


def list_devices() -> str:
    """認識している入出力デバイスの一覧（表示用の文字列）。"""
    return str(sd.query_devices())


def record(seconds: float, *, device: Device = None, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """指定した秒数だけモノラルで録音し、int16 の 1 次元配列を返す。"""
    frames = int(seconds * sample_rate)
    data = sd.rec(frames, samplerate=sample_rate, channels=1, dtype=DTYPE, device=device)
    sd.wait()
    return data[:, 0].copy()


def play(samples: np.ndarray, sample_rate: int, *, device: Device = None) -> None:
    """音声を再生し、終わるまで待つ。"""
    sd.play(samples, samplerate=sample_rate, device=device)
    sd.wait()


def play_nowait(samples: np.ndarray, sample_rate: int, *, device: Device = None) -> None:
    """音声の再生を始め、終わるのを待たずに戻る（録音を続けながら鳴らす用）。"""
    sd.play(samples, samplerate=sample_rate, device=device)


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
