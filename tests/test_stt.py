import numpy as np

from voice_assistant.stt import RecognitionStream, join_japanese_words


def test_joins_japanese_words():
    assert join_japanese_words("今日 の 天気 を 教え て") == "今日の天気を教えて"


def test_keeps_space_between_ascii_words():
    assert join_japanese_words("hey jarvis") == "hey jarvis"


def test_removes_space_next_to_japanese():
    assert join_japanese_words("hey jarvis 今日 の 天気") == "hey jarvis今日の天気"
    assert join_japanese_words("明日 は ok です") == "明日はokです"


def test_empty_and_extra_spaces():
    assert join_japanese_words("") == ""
    assert join_japanese_words("  今日   は  ") == "今日は"


class FakeKaldi:
    """AcceptWaveform の戻り値（区切りが来たか）を順に返す偽物。"""

    def __init__(self, endpoints, results, final):
        self._endpoints = list(endpoints)
        self._results = list(results)
        self._final = final
        self.accepted = 0
        self.resets = 0

    def AcceptWaveform(self, data):
        self.accepted += 1
        return self._endpoints.pop(0) if self._endpoints else False

    def Result(self):
        return '{"text": "%s"}' % self._results.pop(0)

    def FinalResult(self):
        return '{"text": "%s"}' % self._final

    def Reset(self):
        self.resets += 1


def frame():
    return np.zeros(512, dtype=np.int16)


def test_stream_joins_segments_split_by_vosk():
    # 途中の間で区切られた前半も失わずにつなげる
    kaldi = FakeKaldi(endpoints=[False, True, False], results=["今日 の"], final="天気 は")
    stream = RecognitionStream(kaldi)
    for _ in range(3):
        stream.accept(frame())
    assert stream.finish() == "今日の天気は"


def test_stream_reset_discards_segments():
    kaldi = FakeKaldi(endpoints=[True], results=["えー"], final="明日 の 天気")
    stream = RecognitionStream(kaldi)
    stream.accept(frame())
    stream.reset()
    assert kaldi.resets == 1
    assert stream.finish() == "明日の天気"


def test_stream_nothing_heard():
    assert RecognitionStream(FakeKaldi([], [], "")).finish() == ""


def test_model_dir_from_config():
    """.env の設定で、使うモデルのフォルダが決まる。"""
    from voice_assistant.config import SttConfig
    from voice_assistant.stt import MODELS_DIR, model_dir_from_config

    assert model_dir_from_config(SttConfig()) == MODELS_DIR / "vosk-model-ja-0.22"
    assert model_dir_from_config(SttConfig(model_dir="x")) == MODELS_DIR / "x"
