import numpy as np

from voice_assistant.frames import rechunk


def test_rechunk_splits_and_carries_remainder():
    frames = [np.arange(0, 5, dtype=np.int16), np.arange(5, 12, dtype=np.int16)]
    chunks = list(rechunk(frames, 4))
    assert [c.tolist() for c in chunks] == [[0, 1, 2, 3], [4, 5, 6, 7], [8, 9, 10, 11]]
    assert all(c.dtype == np.int16 for c in chunks)


def test_rechunk_drops_incomplete_tail():
    chunks = list(rechunk([np.arange(10, dtype=np.int16)], 4))
    assert [c.tolist() for c in chunks] == [[0, 1, 2, 3], [4, 5, 6, 7]]


def test_rechunk_1280_to_512_keeps_all_samples():
    frames = [np.full(1280, i, dtype=np.int16) for i in range(4)]  # 5120 サンプル = 512 × 10
    chunks = list(rechunk(frames, 512))
    assert len(chunks) == 10
    np.testing.assert_array_equal(np.concatenate(chunks), np.concatenate(frames))
