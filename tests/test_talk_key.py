import numpy as np

from voice_assistant.talk_key import FRESH_SECONDS, TalkSignal, collect_while_held, default_path
from voice_assistant.vad import EndReason


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def make_signal(tmp_path, age=0.0):
    """age 秒前に更新された合図のファイルを用意する。"""
    clock = FakeClock()
    path = tmp_path / "talk"
    path.touch()
    import os

    os.utime(path, (clock.now - age, clock.now - age))
    return TalkSignal(path, clock=clock), path


def test_fresh_signal_means_held(tmp_path):
    signal, _ = make_signal(tmp_path, age=0.0)
    assert signal.held() is True


def test_stale_signal_means_released(tmp_path):
    """送る側が止まっても、合図が古くなれば自動で離したことになる。"""
    signal, _ = make_signal(tmp_path, age=FRESH_SECONDS + 0.1)
    assert signal.held() is False


def test_missing_file_means_released(tmp_path):
    assert TalkSignal(tmp_path / "ない").held() is False


def test_no_path_means_released():
    assert TalkSignal(None).held() is False
    assert TalkSignal(None).pressed() is False


def test_pressed_is_only_true_at_the_start(tmp_path):
    """押しっぱなしのままでは、続けて聞き取りが始まらない。"""
    signal, path = make_signal(tmp_path, age=0.0)
    assert signal.pressed() is True
    assert signal.pressed() is False  # 押したまま
    path.unlink()
    assert signal.pressed() is False  # 離した
    path.touch()
    import os

    os.utime(path, (signal._clock.now, signal._clock.now))
    assert signal.pressed() is True  # 押し直した


def test_default_path_uses_runtime_dir(monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    assert default_path().as_posix().endswith("/run/user/1000/voice-assistant/talk")
    monkeypatch.delenv("XDG_RUNTIME_DIR")
    assert default_path() is None


# ---------- 押している間の聞き取り ----------


def frames(count):
    return [np.full(4, i, dtype=np.int16) for i in range(count)]


class Recorder:
    def __init__(self):
        self.accepted = 0

    def accept(self, frame):
        self.accepted += 1

    def reset(self):
        pass


def test_collects_until_released():
    held = iter([True, True, True, False])
    utterance = collect_while_held(frames(10), lambda: next(held), max_frames=100)
    assert utterance.reason is EndReason.RELEASED
    assert len(utterance.samples) == 3 * 4  # 3 フレーム分


def test_stops_at_the_limit():
    """押しっぱなしで放置されても打ち切る。"""
    utterance = collect_while_held(frames(10), lambda: True, max_frames=2)
    assert utterance.reason is EndReason.MAX_LENGTH
    assert len(utterance.samples) == 2 * 4


def test_passes_frames_to_the_recognizer():
    recorder = Recorder()
    collect_while_held(frames(10), lambda: True, max_frames=3, listener=recorder)
    assert recorder.accepted == 3


def test_released_immediately_gives_no_audio():
    utterance = collect_while_held(frames(10), lambda: False, max_frames=100)
    assert utterance.samples is None
    assert utterance.reason is EndReason.RELEASED


def test_input_ends_before_release():
    """マイクが止まった場合も、集めた分を返す。"""
    utterance = collect_while_held(frames(2), lambda: True, max_frames=100)
    assert utterance.reason is EndReason.INPUT_ENDED
    assert len(utterance.samples) == 2 * 4
