import numpy as np
import pytest

from voice_assistant.levels import peak_dbfs
from voice_assistant.sounds import tone, wake_chime


def test_tone_length_and_level():
    samples = tone(1000.0, 0.1, 16000, level_dbfs=-12.0)
    assert samples.dtype == np.int16
    assert len(samples) == 1600
    assert peak_dbfs(samples) == pytest.approx(-12.0, abs=0.1)


def test_tone_fades_in_and_out():
    samples = tone(1000.0, 0.1, 16000)
    assert samples[0] == 0
    assert abs(int(samples[-1])) < 50


def test_wake_chime_is_short():
    samples = wake_chime(16000)
    assert samples.dtype == np.int16
    # 発話とみなさない長さ（0.25 秒）より短くしておく
    assert len(samples) / 16000 < 0.25


def test_wake_chime_level():
    assert peak_dbfs(wake_chime(16000)) == pytest.approx(-6.0, abs=0.1)
    assert peak_dbfs(wake_chime(16000, level_dbfs=-3.0)) == pytest.approx(-3.0, abs=0.1)
