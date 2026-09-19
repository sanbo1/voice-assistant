"""音量の計算。int16 のフルスケールを 0 dBFS とする。"""

import math

import numpy as np

FULL_SCALE = 32768.0


def peak_dbfs(samples: np.ndarray) -> float:
    """最大振幅（dBFS）。無音なら -inf。"""
    samples = np.asarray(samples)
    if samples.size == 0:
        return -math.inf
    peak = float(np.max(np.abs(samples.astype(np.float64))))
    return 20 * math.log10(peak / FULL_SCALE) if peak > 0 else -math.inf


def normalize_peak(samples: np.ndarray, target_dbfs: float = -1.0) -> np.ndarray:
    """最大振幅が target_dbfs になるように音量をそろえる（int16）。無音はそのまま返す。"""
    samples = np.asarray(samples)
    peak = float(np.max(np.abs(samples.astype(np.float64)))) if samples.size else 0.0
    if peak == 0:
        return samples.astype(np.int16)
    gain = FULL_SCALE * 10 ** (target_dbfs / 20) / peak
    scaled = np.round(samples.astype(np.float64) * gain)
    return np.clip(scaled, -32768, 32767).astype(np.int16)


def rms_dbfs(samples: np.ndarray) -> float:
    """実効値（dBFS）。無音なら -inf。"""
    samples = np.asarray(samples)
    if samples.size == 0:
        return -math.inf
    rms = math.sqrt(float(np.mean(np.square(samples.astype(np.float64)))))
    return 20 * math.log10(rms / FULL_SCALE) if rms > 0 else -math.inf
