from voice_assistant.config import AudioConfig, load_audio_config, parse_device


def test_parse_device_empty_means_default():
    assert parse_device(None) is None
    assert parse_device("") is None
    assert parse_device("   ") is None


def test_parse_device_digits_are_index():
    assert parse_device("2") == 2
    assert parse_device(" 10 ") == 10


def test_parse_device_other_is_name():
    assert parse_device("USB PnP Audio Device") == "USB PnP Audio Device"
    assert parse_device(" pipewire ") == "pipewire"


def test_load_audio_config_defaults():
    assert load_audio_config({}) == AudioConfig(input_device=None, output_device=None)


def test_load_audio_config_from_env():
    env = {"AUDIO_INPUT_DEVICE": "USB PnP", "AUDIO_OUTPUT_DEVICE": "3"}
    assert load_audio_config(env) == AudioConfig(input_device="USB PnP", output_device=3)
