import numpy as np

from voice_assistant.vad import EndpointConfig, Endpointer, EndReason, collect_utterance

# 1 フレーム 0.1 秒として、秒数がそのままフレーム数の 1/10 になるようにする
FRAME_SECONDS = 0.1
CONFIG = EndpointConfig(
    threshold=0.5,
    end_silence_seconds=0.3,  # 3 フレーム
    start_timeout_seconds=1.0,  # 10 フレーム
    max_seconds=3.0,  # 30 フレーム
    min_speech_seconds=0.2,  # 2 フレーム
    pre_roll_seconds=0.2,  # 2 フレーム
)


def run(probs):
    """確率の並びを順に渡し、終わった位置（1 始まり）と理由を返す。終わらなければ (None, None)。"""
    endpointer = Endpointer(CONFIG, FRAME_SECONDS)
    for i, p in enumerate(probs, start=1):
        reason = endpointer.update(p)
        if reason is not None:
            return i, reason
    return None, None


def test_no_speech_times_out():
    assert run([0.0] * 20) == (10, EndReason.NO_SPEECH)


def test_speech_then_silence_ends():
    # 声 3 フレームのあと、無音 3 フレームで終わる
    assert run([0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.1]) == (6, EndReason.SILENCE)


def test_short_pause_does_not_end():
    probs = [0.9, 0.9, 0.1, 0.1, 0.9, 0.9, 0.1, 0.1, 0.1]
    assert run(probs) == (9, EndReason.SILENCE)


def test_in_between_probability_before_silence_does_not_count():
    # 0.4 は threshold 未満だが neg_threshold（0.35）以上なので、無音を数え始めない
    assert run([0.9, 0.9, 0.4, 0.4, 0.4, 0.4]) == (None, None)


def test_in_between_probability_after_silence_keeps_counting():
    # 無音を数え始めたあとは、0.4 も無音として数え続ける
    assert run([0.9, 0.9, 0.1, 0.4, 0.4]) == (5, EndReason.SILENCE)


def test_too_short_speech_is_ignored():
    # 1 フレームだけの声は取り消し、その後の話し始めを待つ
    probs = [0.9, 0.1, 0.1, 0.1, 0.9, 0.9, 0.1, 0.1, 0.1]
    assert run(probs) == (9, EndReason.SILENCE)


def test_too_short_speech_then_timeout():
    assert run([0.9] + [0.1] * 20) == (10, EndReason.NO_SPEECH)


def test_max_length():
    assert run([0.9] * 40) == (30, EndReason.MAX_LENGTH)


def frames_and_probs(probs):
    """フレーム i の中身をすべて i にしたフレーム列と、確率を返す関数を作る。"""
    frames = [np.full(4, i, dtype=np.int16) for i in range(len(probs))]
    table = {i: p for i, p in enumerate(probs)}
    return frames, lambda frame: table[int(frame[0])]


def collected_ids(utterance):
    return utterance.samples.reshape(-1, 4)[:, 0].tolist()


def test_collect_includes_pre_roll_and_trailing_silence():
    frames, prob = frames_and_probs([0.0, 0.0, 0.0, 0.9, 0.9, 0.1, 0.1, 0.1, 0.0])
    utterance = collect_utterance(frames, prob, Endpointer(CONFIG, FRAME_SECONDS))
    assert utterance.reason is EndReason.SILENCE
    # 話し始め（3）の前の 2 フレーム（1, 2）から、話し終わりの判定（7）まで
    assert collected_ids(utterance) == [1, 2, 3, 4, 5, 6, 7]


def test_collect_no_speech_returns_none():
    frames, prob = frames_and_probs([0.0] * 12)
    utterance = collect_utterance(frames, prob, Endpointer(CONFIG, FRAME_SECONDS))
    assert utterance.reason is EndReason.NO_SPEECH
    assert utterance.samples is None


def test_collect_discards_too_short_speech():
    probs = [0.9, 0.1, 0.1, 0.1, 0.0, 0.9, 0.9, 0.1, 0.1, 0.1]
    frames, prob = frames_and_probs(probs)
    utterance = collect_utterance(frames, prob, Endpointer(CONFIG, FRAME_SECONDS))
    assert utterance.reason is EndReason.SILENCE
    # 取り消された部分（0〜3）は含めず、話し始め（5）の前の 2 フレームから
    assert collected_ids(utterance) == [3, 4, 5, 6, 7, 8, 9]


def test_collect_input_ended_while_speaking():
    frames, prob = frames_and_probs([0.0, 0.9, 0.9])
    utterance = collect_utterance(frames, prob, Endpointer(CONFIG, FRAME_SECONDS))
    assert utterance.reason is EndReason.INPUT_ENDED
    assert collected_ids(utterance) == [0, 1, 2]
