"""音声フレームの長さの変換。"""

from collections.abc import Iterable, Iterator

import numpy as np


def rechunk(frames: Iterable[np.ndarray], size: int) -> Iterator[np.ndarray]:
    """長さの違うフレームの並びを、size サンプルずつのフレームに分け直す。端数は次のフレームに回す。"""
    buffer: np.ndarray | None = None
    for frame in frames:
        buffer = frame if buffer is None else np.concatenate([buffer, frame])
        while len(buffer) >= size:
            yield buffer[:size]
            buffer = buffer[size:]
