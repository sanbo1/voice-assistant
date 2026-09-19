import io

import numpy as np

from voice_assistant.tts import to_speakable
from voice_assistant.wav import read_wav, write_wav


def test_plain_text_unchanged():
    text = "日本で一番高い山は富士山で、標高は3776メートルです。"
    assert to_speakable(text) == text


def test_removes_markdown_and_bullets():
    text = "**富士山**の特徴です。\n- 標高は3776メートル\n- 山梨県と静岡県にまたがる\n# まとめ"
    assert to_speakable(text) == "富士山の特徴です。標高は3776メートル。山梨県と静岡県にまたがる。まとめ。"


def test_removes_url_and_emoji():
    text = "詳しくは https://example.com/page を見てください😊"
    assert to_speakable(text) == "詳しくは を見てください。"


def test_keeps_question_and_exclamation():
    assert to_speakable("本当ですか？\nすごい！") == "本当ですか？すごい！"


def test_numbered_list():
    assert to_speakable("1. 起きる\n2. 顔を洗う") == "起きる。顔を洗う。"


def test_empty():
    assert to_speakable("") == ""
    assert to_speakable("\n  \n") == ""


def test_read_wav_from_bytes(tmp_path):
    samples = np.array([0, 100, -100, 32767], dtype=np.int16)
    path = tmp_path / "x.wav"
    write_wav(path, samples, 48000)
    loaded, rate = read_wav(io.BytesIO(path.read_bytes()))
    assert rate == 48000
    np.testing.assert_array_equal(loaded, samples)


def test_apply_readings_fixes_known_misreading():
    assert to_speakable("お手数ですが、ご確認ください。") == "おてすうですが、ご確認ください。"
