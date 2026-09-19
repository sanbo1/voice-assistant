from voice_assistant.config import AudioConfig, GeminiConfig, load_audio_config, load_gemini_config, parse_device


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


def test_load_gemini_config():
    config = load_gemini_config({"GEMINI_API_KEY": " secret-key ", "GEMINI_MODEL": "gemini-3.8-flash",
                                 "GEMINI_THINKING_LEVEL": "low"})
    assert config == GeminiConfig(api_key="secret-key", model="gemini-3.8-flash", thinking_level="low")


def test_load_gemini_config_defaults():
    assert load_gemini_config({}) == GeminiConfig(api_key="", model=None, thinking_level=None)
    assert load_gemini_config({"GEMINI_MODEL": " "}).model is None


def test_gemini_config_repr_hides_api_key():
    assert "secret-key" not in repr(GeminiConfig(api_key="secret-key", model="m"))


def test_load_gemini_fallback_models():
    assert load_gemini_config({}).fallback_models is None
    assert load_gemini_config({"GEMINI_FALLBACK_MODELS": " a , b ,"}).fallback_models == ("a", "b")
    assert load_gemini_config({"GEMINI_FALLBACK_MODELS": "none"}).fallback_models == ()
