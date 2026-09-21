from voice_assistant.audio import parse_sinks


def test_parse_sinks_reads_name_and_state():
    """pactl の出力から、出力先の名前と状態を取り出す。"""
    text = (
        "67\talsa_output.platform-107c706400.hdmi.hdmi-stereo\tPipeWire\ts32le 2ch 48000Hz\tIDLE\n"
        "68\talsa_output.usb-speaker\tPipeWire\ts16le 2ch 48000Hz\tRUNNING\n"
    )
    assert parse_sinks(text) == (
        "alsa_output.platform-107c706400.hdmi.hdmi-stereo（IDLE）、alsa_output.usb-speaker（RUNNING）"
    )


def test_parse_sinks_without_any_sink():
    """出力先がないときは「なし」。起動直後に音が出ない原因を見分ける材料になる。"""
    assert parse_sinks("") == "なし"


def test_parse_sinks_ignores_broken_lines():
    assert parse_sinks("こわれた行\n67\tname\tPipeWire\ts32le\tIDLE\n") == "name（IDLE）"
