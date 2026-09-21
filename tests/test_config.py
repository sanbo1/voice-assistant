from voice_assistant.config import (
    AssistantConfig,
    AudioConfig,
    GeminiConfig,
    WakeWordConfig,
    load_assistant_config,
    load_audio_config,
    load_gemini_config,
    load_wakeword_config,
    parse_device,
)


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


def test_load_assistant_config_defaults():
    assert load_assistant_config({}) == AssistantConfig(followup_seconds=3.0, followup_max_turns=3)


def test_load_assistant_config_from_env():
    config = load_assistant_config({"FOLLOWUP_SECONDS": "5", "FOLLOWUP_MAX_TURNS": "1"})
    assert config == AssistantConfig(followup_seconds=5.0, followup_max_turns=1)


def test_load_assistant_config_ignores_invalid_values():
    config = load_assistant_config({"FOLLOWUP_SECONDS": "x", "FOLLOWUP_MAX_TURNS": " "})
    assert config == AssistantConfig()
    assert load_assistant_config({"FOLLOWUP_SECONDS": "0"}).followup_seconds == 0.0


def test_load_wakeword_config_defaults():
    assert load_wakeword_config({}) == WakeWordConfig(
        threshold=0.35, patience_frames=2, confirm_frames=3, confirm_threshold=0.0)


def test_load_wakeword_config_from_env():
    config = load_wakeword_config({
        "WAKEWORD_THRESHOLD": "0.4",
        "WAKEWORD_PATIENCE_FRAMES": "3",
        "WAKEWORD_CONFIRM_FRAMES": "0",
        "WAKEWORD_CONFIRM_THRESHOLD": "0.6",
    })
    assert config == WakeWordConfig(threshold=0.4, patience_frames=3,
                                    confirm_frames=0, confirm_threshold=0.6)


def test_load_wakeword_config_ignores_invalid_values():
    assert load_wakeword_config({"WAKEWORD_THRESHOLD": "x", "WAKEWORD_CONFIRM_FRAMES": " "}) == WakeWordConfig()
