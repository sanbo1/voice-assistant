from collections import deque

from voice_assistant.config import WakeWordConfig
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


def test_confirm_window_delays_the_trigger():
    """確認窓があるときは、立ち上がりのあと confirm_frames ぶん見てから反応する。"""
    gate = TriggerGate(threshold=0.5, cooldown_frames=0, patience_frames=2, confirm_frames=3)
    assert [gate.update(0.9) for _ in range(5)] == [False, False, False, False, True]


def test_confirm_window_without_threshold_always_triggers():
    """確認しきい値が 0 なら見送らない（材料を集める段階の設定）。"""
    gate = TriggerGate(threshold=0.35, cooldown_frames=0, patience_frames=2, confirm_frames=3)
    # 2026-09-20 の誤反応と同じ並び。確認しきい値が 0 のときは、遅れるだけで今までどおり反応する
    assert [gate.update(s) for s in (0.10, 0.48, 0.46, 0.40, 0.38, 0.30)] == [False] * 5 + [True]
    assert gate.peak == 0.48
    assert gate.suppressed == 0


def test_confirm_threshold_suppresses_low_peak():
    """最大スコアが確認しきい値に届かなければ反応しない（誤反応を想定）。"""
    gate = TriggerGate(threshold=0.35, cooldown_frames=25, patience_frames=2,
                       confirm_frames=3, confirm_threshold=0.6)
    assert [gate.update(s) for s in (0.10, 0.48, 0.46, 0.40, 0.38, 0.30)] == [False] * 6
    assert gate.suppressed == 1


def test_confirm_threshold_allows_rising_score():
    """立ち上がりが低くても、確認窓の中で伸びれば反応する（本物を想定）。"""
    gate = TriggerGate(threshold=0.35, cooldown_frames=25, patience_frames=2,
                       confirm_frames=3, confirm_threshold=0.6)
    # 2026-09-20 の本物と同じ並び（0.36 → 0.86 と伸びる）
    assert [gate.update(s) for s in (0.01, 0.36, 0.86, 0.90, 0.70, 0.50)] == [False] * 5 + [True]
    assert gate.peak == 0.90
    assert gate.suppressed == 0


def test_peak_covers_the_rising_frames():
    """確認窓の中で落ちても、立ち上がりで高ければ最大スコアとして残る。"""
    gate = TriggerGate(threshold=0.35, cooldown_frames=0, patience_frames=2,
                       confirm_frames=2, confirm_threshold=0.6)
    assert [gate.update(s) for s in (0.50, 0.79, 0.20, 0.10)] == [False, False, False, True]
    assert gate.peak == 0.79


def test_suppressed_run_can_trigger_later():
    """一度見送っても、そのあと立ち上がり直せばまた確認する。"""
    gate = TriggerGate(threshold=0.35, cooldown_frames=0, patience_frames=2,
                       confirm_frames=1, confirm_threshold=0.6)
    assert [gate.update(s) for s in (0.40, 0.40, 0.40)] == [False, False, False]  # 見送り
    assert [gate.update(s) for s in (0.40, 0.90, 0.90)] == [False, False, True]
    assert gate.suppressed == 1  # 反応するまでに見送った回数が残る


def test_reset_clears_the_confirm_window():
    gate = TriggerGate(threshold=0.5, cooldown_frames=0, patience_frames=2, confirm_frames=3)
    gate.update(0.9)
    gate.update(0.9)  # 確認窓に入ったところで消す
    gate.reset()
    assert [gate.update(0.9) for _ in range(5)] == [False, False, False, False, True]


class FakeGateModel:
    """WakeWordDetector のうち、モデルを使わない部分だけを試すための土台。"""

    def __init__(self, scores):
        self.scores = list(scores)
        self.resets = 0

    def predict(self, frame):
        return {"fake": self.scores.pop(0)}

    def reset(self):
        self.resets += 1


def make_detector(scores, config=WakeWordConfig(confirm_frames=0)):
    """モデルを差し替えた WakeWordDetector を作る（ファイルの読み込みを避けるため __new__ で組み立てる）。"""
    detector = WakeWordDetector.__new__(WakeWordDetector)
    detector._model = FakeGateModel(scores)
    detector.name = "fake"
    detector._gate = TriggerGate(config.threshold, 0, config.patience_frames,
                                 config.confirm_frames, config.confirm_threshold)
    detector.last_score = 0.0
    detector.last_peak = 0.0
    detector.last_suppressed = 0
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
    detector = make_detector([0.0] * 20 + [0.9, 0.9])
    for _ in range(22):
        detector.process(None)
    assert len(detector.last_scores) == SCORE_HISTORY_FRAMES
    assert detector.last_scores[-2:] == [0.9, 0.9]


def test_detector_records_peak_and_window():
    """確認窓があるとき、並びには窓のぶんも入り、最大スコアが残る。"""
    detector = make_detector([0.01, 0.36, 0.86, 0.90, 0.70, 0.50],
                             WakeWordConfig(confirm_frames=3, confirm_threshold=0.6))
    results = [detector.process(None) for _ in range(6)]
    assert results == [False] * 5 + [True]
    assert detector.last_scores == [0.01, 0.36, 0.86, 0.90, 0.70, 0.50]
    assert detector.last_peak == 0.90
    assert detector.last_suppressed == 0


def test_detector_counts_suppressed_detections():
    """見送った回数は、次に反応したときに残り、そこで数え直す。"""
    detector = make_detector([0.40, 0.40, 0.40, 0.40, 0.90, 0.90],
                             WakeWordConfig(confirm_frames=1, confirm_threshold=0.6))
    results = [detector.process(None) for _ in range(6)]
    assert results == [False, False, False, False, False, True]
    assert detector.last_suppressed == 1
    assert detector._gate.suppressed == 0
