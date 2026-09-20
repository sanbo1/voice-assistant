import numpy as np
import pytest

from voice_assistant.levels import peak_dbfs
from voice_assistant.sounds import listen_chime, ready_chime, tone, wake_chime


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


def test_ready_chime_is_longer_than_wake_chime():
    # 検知の音（上がる 2 音）と、待ち受けに戻る音（下がる 3 音）を、音の数と長さで区別できるようにしている
    wake, ready = wake_chime(16000), ready_chime(16000)
    assert len(wake) / 16000 == pytest.approx(0.18, abs=0.01)
    assert len(ready) / 16000 == pytest.approx(0.28, abs=0.01)
    assert peak_dbfs(ready) == pytest.approx(-6.0, abs=0.1)


def dominant_hz(samples, sample_rate=16000):
    spectrum = np.abs(np.fft.rfft(samples.astype(float)))
    return np.fft.rfftfreq(len(samples), 1 / sample_rate)[np.argmax(spectrum)]


def test_ready_chime_goes_down_in_pitch():
    ready, n = ready_chime(16000), round(0.08 * 16000)
    first, middle, last = ready[:n], ready[n + 320: 2 * n + 320], ready[-n:]
    assert dominant_hz(first) > dominant_hz(middle) > dominant_hz(last)


def test_chimes_at_output_sample_rate():
    # 再生に使う 48kHz でも、同じ長さ・同じ音量で作れる
    for maker in (wake_chime, ready_chime, listen_chime):
        assert len(maker(48000)) == 3 * len(maker(16000))
        assert peak_dbfs(maker(48000)) == pytest.approx(-6.0, abs=0.1)


def test_listen_chime_is_one_short_tone():
    chime = listen_chime(48000)
    assert len(chime) == round(0.08 * 48000)
    assert peak_dbfs(chime) == pytest.approx(-6.0, abs=0.1)
    assert dominant_hz(chime, 48000) == pytest.approx(1100, abs=30)
