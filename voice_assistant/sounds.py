"""お知らせ音の生成（正弦波から作る。外部の音声素材は使わない）。"""

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


def wake_chime(sample_rate: int, *, level_dbfs: float = -6.0) -> np.ndarray:
    """ウェイクワードを検知したときの音。低い音から高い音へ上がる 2 音（約 0.17 秒）。"""
    return np.concatenate([
        tone(880.0, 0.07, sample_rate, level_dbfs=level_dbfs),
        np.zeros(round(0.02 * sample_rate), dtype=np.int16),
        tone(1320.0, 0.08, sample_rate, level_dbfs=level_dbfs),
    ])
