from voice_assistant.wakeword import TriggerGate


def test_below_threshold_never_triggers():
    gate = TriggerGate(threshold=0.5, cooldown_frames=3)
    assert [gate.update(s) for s in (0.0, 0.2, 0.49, 0.1)] == [False] * 4


def test_triggers_at_threshold():
    gate = TriggerGate(threshold=0.5, cooldown_frames=3)
    assert gate.update(0.5) is True


def test_cooldown_suppresses_following_frames():
    gate = TriggerGate(threshold=0.5, cooldown_frames=3)
    results = [gate.update(s) for s in (0.9, 0.9, 0.9, 0.9, 0.9)]
    # 1 回反応したあと 3 フレームは反応せず、その次にまた反応する
    assert results == [True, False, False, False, True]


def test_zero_cooldown_triggers_every_frame():
    gate = TriggerGate(threshold=0.5, cooldown_frames=0)
    assert [gate.update(s) for s in (0.9, 0.9, 0.1, 0.9)] == [True, True, False, True]
