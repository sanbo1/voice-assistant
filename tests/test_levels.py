import math

import numpy as np
import pytest

from voice_assistant.levels import normalize_peak, peak_dbfs, rms_dbfs


def test_silence_is_minus_inf():
    silence = np.zeros(1600, dtype=np.int16)
    assert peak_dbfs(silence) == -math.inf
    assert rms_dbfs(silence) == -math.inf


def test_empty_is_minus_inf():
    empty = np.array([], dtype=np.int16)
    assert peak_dbfs(empty) == -math.inf
    assert rms_dbfs(empty) == -math.inf


def test_full_scale_square_wave_is_0_dbfs():
    square = np.array([-32768, -32768] * 100, dtype=np.int16)
    assert peak_dbfs(square) == pytest.approx(0.0)
    assert rms_dbfs(square) == pytest.approx(0.0)


def test_half_scale_sine():
    t = np.arange(16000) / 16000
    sine = (16384 * np.sin(2 * np.pi * 1000 * t)).astype(np.int16)
    # 振幅が半分なら -6.02 dB、正弦波の実効値はさらに -3.01 dB
    assert peak_dbfs(sine) == pytest.approx(-6.02, abs=0.01)
    assert rms_dbfs(sine) == pytest.approx(-9.03, abs=0.01)


def test_normalize_peak_raises_quiet_audio():
    quiet = (np.array([0, 1000, -2000, 500])).astype(np.int16)
    loud = normalize_peak(quiet, -1.0)
    assert loud.dtype == np.int16
    assert peak_dbfs(loud) == pytest.approx(-1.0, abs=0.01)
    # 形（比率）は変わらない（整数に丸めるため ±1 の誤差は許す）
    assert abs(int(loud[2]) + 2 * int(loud[1])) <= 1


def test_normalize_peak_keeps_silence():
    silence = np.zeros(10, dtype=np.int16)
    np.testing.assert_array_equal(normalize_peak(silence), silence)
