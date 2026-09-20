from collections import deque

from voice_assistant.wakeword import (
    SCORE_HISTORY_FRAMES,
    TriggerGate,
    WakeWordDetector,
)


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


def test_patience_requires_consecutive_frames():
    gate = TriggerGate(threshold=0.5, cooldown_frames=3, patience_frames=2)
    assert gate.update(0.9) is False   # 1 フレーム目では反応しない
    assert gate.update(0.9) is True    # 2 フレーム続けて超えたら反応する
    assert gate.run_frames == 2


def test_patience_resets_when_score_drops():
    gate = TriggerGate(threshold=0.5, cooldown_frames=3, patience_frames=2)
    assert [gate.update(s) for s in (0.9, 0.1, 0.9)] == [False, False, False]
    assert gate.update(0.9) is True


def test_patience_three_frames():
    gate = TriggerGate(threshold=0.5, cooldown_frames=0, patience_frames=3)
    assert [gate.update(0.9) for _ in range(4)] == [False, False, True, False]


def test_patience_count_restarts_after_cooldown():
    gate = TriggerGate(threshold=0.5, cooldown_frames=2, patience_frames=2)
    assert [gate.update(0.9) for _ in range(6)] == [False, True, False, False, False, True]


class FakeGateModel:
    """WakeWordDetector のうち、モデルを使わない部分だけを試すための土台。"""

    def __init__(self, scores):
        self.scores = list(scores)
        self.resets = 0

    def predict(self, frame):
        return {"fake": self.scores.pop(0)}

    def reset(self):
        self.resets += 1


def make_detector(scores, patience=2):
    """モデルを差し替えた WakeWordDetector を作る（ファイルの読み込みを避けるため __new__ で組み立てる）。"""
    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector._model = FakeGateModel(scores)
    detector.name = "fake"
    detector._gate = TriggerGate(0.35, cooldown_frames=0, patience_frames=patience)
    detector.last_score = 0.0
    detector.last_scores = []
    detector._recent = deque(maxlen=SCORE_HISTORY_FRAMES)
    return detector


def test_detector_records_recent_scores_on_detection():
    detector = make_detector([0.01, 0.10, 0.40, 0.44])
    results = [detector.process(None) for _ in range(4)]
    assert results == [False, False, False, True]
    # 検知したときに、直前のスコアの並びを残す
    assert detector.last_scores == [0.01, 0.10, 0.40, 0.44]
    assert detector._model.resets == 1


def test_detector_keeps_only_recent_scores():
    detector = make_detector([0.0] * 10 + [0.9, 0.9])
    for _ in range(12):
        detector.process(None)
    assert len(detector.last_scores) == SCORE_HISTORY_FRAMES
    assert detector.last_scores[-2:] == [0.9, 0.9]
