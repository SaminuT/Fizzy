from fizzy.settings import (
    CONTEXT_SCREEN, CONTEXT_SELECTION_OR_SCREEN, Settings, get_json_secret, get_secret, set_json_secret, set_secret,
)


def test_round_trip():
    s = Settings.load()
    s.provider = "gemini"
    s.set_model("gemini", "gemini-x")
    s.screen_context = CONTEXT_SCREEN
    s.save()
    again = Settings.load()
    assert again.provider == "gemini"
    assert again.model_for("gemini") == "gemini-x"
    assert again.screen_context == CONTEXT_SCREEN


def test_unknown_context_mode_falls_back():
    s = Settings.load()
    s.screen_context = "telepathy"
    s.save()
    assert Settings.load().screen_context == CONTEXT_SELECTION_OR_SCREEN


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("FIZZY_PROVIDER", "ollama")
    monkeypatch.setenv("FIZZY_WAKE_WORD", "yes")
    monkeypatch.setenv("FIZZY_HOLD_THRESHOLD_S", "0.8")
    monkeypatch.setenv("FIZZY_MIC_DEVICE", "3")
    s = Settings.load()
    assert s.provider == "ollama"
    assert s.wake_word is True
    assert s.hold_threshold_s == 0.8
    assert s.mic_device == 3


def test_bad_env_value_is_ignored(monkeypatch):
    monkeypatch.setenv("FIZZY_HOLD_THRESHOLD_S", "soon")
    assert Settings.load().hold_threshold_s == Settings.hold_threshold_s


def test_short_secret(isolated):
    set_secret("openai_api_key", "sk-123")
    assert get_secret("openai_api_key") == "sk-123"
    set_secret("openai_api_key", None)
    assert get_secret("openai_api_key") is None
    assert isolated.items == {}


def test_long_secret_is_split_and_cleaned_up(isolated):
    big = "x" * 4500
    set_secret("chatgpt_session", big)
    assert get_secret("chatgpt_session") == big
    assert len(isolated.items) == 6     # head + 5 parts
    set_secret("chatgpt_session", "short")
    assert get_secret("chatgpt_session") == "short"
    assert len(isolated.items) == 1


def test_env_key_wins(monkeypatch):
    set_secret("anthropic_api_key", "from-store")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    assert get_secret("anthropic_api_key") == "from-env"


def test_json_secret():
    set_json_secret("thing", {"a": 1})
    assert get_json_secret("thing") == {"a": 1}
    set_json_secret("thing", None)
    assert get_json_secret("thing") is None
