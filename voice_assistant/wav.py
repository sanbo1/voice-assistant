"""16bit PCM の WAV ファイルの読み書き（標準ライブラリの wave を使う）。"""

import wave
from pathlib import Path
from typing import BinaryIO

import numpy as np


def write_wav(path: str | Path, samples: np.ndarray, sample_rate: int) -> None:
    """int16 の音声を WAV に書く。samples は (フレーム数,) か (フレーム数, チャンネル数)。"""
    samples = np.asarray(samples)
    if samples.dtype != np.int16:
        raise ValueError(f"int16 の配列を渡してください（受け取った型：{samples.dtype}）")
    channels = 1 if samples.ndim == 1 else samples.shape[1]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        f.writeframes(samples.astype("<i2").tobytes())


def read_wav(source: str | Path | BinaryIO) -> tuple[np.ndarray, int]:
    """WAV（ファイルのパス、またはバイナリのファイルオブジェクト）を読み、(int16 の配列, サンプリング周波数) を返す。

    モノラルなら 1 次元の配列。
    """
    with wave.open(str(source) if isinstance(source, (str, Path)) else source, "rb") as f:
        if f.getsampwidth() != 2:
            raise ValueError(f"16bit の WAV のみ対応しています（{f.getsampwidth() * 8}bit）")
        channels = f.getnchannels()
        sample_rate = f.getframerate()
        data = f.readframes(f.getnframes())
    samples = np.frombuffer(data, dtype="<i2").astype(np.int16)
    if channels > 1:
        samples = samples.reshape(-1, channels)
    return samples, sample_rate
