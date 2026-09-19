import numpy as np
import pytest

from voice_assistant.wav import read_wav, write_wav


def test_mono_roundtrip(tmp_path):
    samples = np.array([0, 1, -1, 32767, -32768, 1234], dtype=np.int16)
    path = tmp_path / "sub" / "mono.wav"
    write_wav(path, samples, 16000)

    loaded, rate = read_wav(path)
    assert rate == 16000
    assert loaded.dtype == np.int16
    np.testing.assert_array_equal(loaded, samples)


def test_stereo_roundtrip(tmp_path):
    samples = np.array([[1, -1], [100, -100], [32767, -32768]], dtype=np.int16)
    path = tmp_path / "stereo.wav"
    write_wav(path, samples, 48000)

    loaded, rate = read_wav(path)
    assert rate == 48000
    assert loaded.shape == (3, 2)
    np.testing.assert_array_equal(loaded, samples)


def test_write_rejects_non_int16(tmp_path):
    with pytest.raises(ValueError):
        write_wav(tmp_path / "x.wav", np.zeros(10, dtype=np.float32), 16000)
