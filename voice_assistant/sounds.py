"""お知らせ音の生成（正弦波から作る。外部の音声素材は使わない）。"""

from collections.abc import Sequence

import numpy as np


def tone(frequency: float, seconds: float, sample_rate: int, *, level_dbfs: float = -12.0,
         fade_seconds: float = 0.005) -> np.ndarray:
    """正弦波の音（int16）。始めと終わりを短くフェードさせて「プツッ」という音を防ぐ。"""
    n = round(seconds * sample_rate)
    t = np.arange(n) / sample_rate
    wave = np.sin(2 * np.pi * frequency * t)
    fade = min(round(fade_seconds * sample_rate), n // 2)
    if fade > 0:
        ramp = np.linspace(0.0, 1.0, fade)
        wave[:fade] *= ramp
        wave[n - fade:] *= ramp[::-1]
    amplitude = 32767 * 10 ** (level_dbfs / 20)
    return (wave * amplitude).astype(np.int16)


GAP_SECONDS = 0.02


def _tones(frequencies: Sequence[float], seconds: float, sample_rate: int, level_dbfs: float) -> np.ndarray:
    """音を少しずつ間を空けて並べる。"""
    gap = np.zeros(round(GAP_SECONDS * sample_rate), dtype=np.int16)
    parts: list[np.ndarray] = []
    for i, hz in enumerate(frequencies):
        if i:
            parts.append(gap)
        parts.append(tone(hz, seconds, sample_rate, level_dbfs=level_dbfs))
    return np.concatenate(parts)


def wake_chime(sample_rate: int, *, level_dbfs: float = -6.0) -> np.ndarray:
    """ウェイクワードを検知したときの音。低い音から高い音へ上がる 2 音（約 0.18 秒）。"""
    return _tones((880.0, 1320.0), 0.08, sample_rate, level_dbfs)


def listen_chime(sample_rate: int, *, level_dbfs: float = -6.0) -> np.ndarray:
    """返答のあと、続けて話せる状態になったことを知らせる音（短い 1 音）。"""
    return tone(1100.0, 0.08, sample_rate, level_dbfs=level_dbfs)


def ready_chime(sample_rate: int, *, level_dbfs: float = -6.0) -> np.ndarray:
    """ウェイクワードの待ち受けに戻ったときの音。

    高い音から低い音へ下がる 3 音（約 0.28 秒）。検知したときの音（上がる 2 音）と、音の数・長さで区別できるようにする。
    """
    return _tones((1320.0, 1100.0, 880.0), 0.08, sample_rate, level_dbfs)
