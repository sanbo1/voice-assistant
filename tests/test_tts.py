import io
import re

import numpy as np
import pytest

from voice_assistant.tts import (
    MAX_RUN_CHARS,
    READINGS_FILE,
    apply_readings,
    load_readings,
    split_long_runs,
    to_speakable,
)
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


def test_short_run_is_not_split():
    """区切りのない部分が短ければ、そのまま。"""
    assert split_long_runs("今日はよい天気です。") == "今日はよい天気です。"


def test_long_run_is_split_after_a_particle():
    """長く続く部分は、助詞のあと（次が漢字・カタカナのところ）で区切る。"""
    assert split_long_runs("今日は朝からとてもよい天気なので洗濯物がよく乾きそうです。") ==         "今日は朝からとてもよい天気なので 洗濯物がよく乾きそうです。"


def test_split_happens_in_each_part_between_punctuation():
    """句読点で区切られた部分ごとに数える。"""
    text = "戦う時はゴムの実の能力で体を変幻自在に伸ばして動きます。"
    assert split_long_runs(text) == "戦う時はゴムの実の能力で体を変幻自在に 伸ばして動きます。"


def test_not_split_inside_a_word():
    """助詞に見える文字でも、次がひらがなのときは語の途中のおそれがあるので切らない。"""
    # 「はなし」の「は」や「にわ」の「に」で切ってしまわないこと
    text = "はなしのつづきはにわとりのはなしですからきいてくださいね。"
    assert split_long_runs(text) == text


def test_no_safe_break_leaves_the_run_alone():
    """安全な切れ目がなければ、長くてもそのままにする。"""
    text = "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほ。"
    assert split_long_runs(text) == text


def test_each_piece_is_within_the_limit():
    """区切ったあとは、どの部分も上限以下になる（切れ目が見つかる場合）。"""
    text = "ルフィの身長は百七十四センチで、戦う時はゴムゴムの実の能力で体を変幻自在に伸ばして動きます。"
    for piece in re.split(r"[、。\s]+", split_long_runs(text)):
        assert len(piece) <= MAX_RUN_CHARS


def test_to_speakable_inserts_breaks():
    """整える処理の最後に区切りが入る。"""
    assert to_speakable("今日は朝からとてもよい天気なので洗濯物がよく乾きそうです。") ==         "今日は朝からとてもよい天気なので 洗濯物がよく乾きそうです。"


def test_read_wav_from_bytes(tmp_path):
    samples = np.array([0, 100, -100, 32767], dtype=np.int16)
    path = tmp_path / "x.wav"
    write_wav(path, samples, 48000)
    loaded, rate = read_wav(io.BytesIO(path.read_bytes()))
    assert rate == 48000
    np.testing.assert_array_equal(loaded, samples)


def test_apply_readings_fixes_known_misreading():
    assert to_speakable("お手数ですが、ご確認ください。") == "おてすうですが、ご確認ください。"


def test_load_readings(tmp_path):
    path = tmp_path / "readings.tsv"
    path.write_text("# コメント\nお手数\tおてすう\t# 注記\n\n一日\tついたち\n", encoding="utf-8")
    assert load_readings(path) == {"お手数": "おてすう", "一日": "ついたち"}


def test_load_readings_missing_file(tmp_path):
    assert load_readings(tmp_path / "none.tsv") == {}


def test_load_readings_rejects_malformed_line(tmp_path):
    path = tmp_path / "readings.tsv"
    path.write_text("お手数 おてすう\n", encoding="utf-8")  # タブではなく空白
    with pytest.raises(ValueError, match="1 行目"):
        load_readings(path)


def test_apply_readings_longest_first():
    readings = {"手数": "てすう", "お手数料": "おてすうりょう"}
    assert apply_readings("お手数料と手数", readings) == "おてすうりょうとてすう"


def test_repository_readings_file_is_valid():
    # リポジトリの config/readings.tsv が読めること
    assert load_readings(READINGS_FILE)["お手数"] == "おてすう"
