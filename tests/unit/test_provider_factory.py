from unittest.mock import Mock, patch

import pytest

from scribe.providers.factory import _get_default_model, _get_fallback_provider, get_provider


def test_get_provider_uses_health_check_fallback() -> None:
    monitor = Mock()
    openai_provider = Mock(name="openai-provider")

    def check_provider_health(provider_name: str, api_key: str) -> Mock:
        if provider_name == "xai":
            return Mock(is_healthy=False, error_message="down")
        return Mock(is_healthy=True, error_message=None)

    monitor.check_provider_health.side_effect = check_provider_health

    with (
        patch.dict(
            "os.environ",
            {
                "SCRIBE_ENABLE_HEALTH_CHECKS": "true",
                "XAI_API_KEY": "xai-key",
                "OPENAI_API_KEY": "openai-key",
            },
            clear=True,
        ),
        patch("scribe.providers.health.get_health_monitor", return_value=monitor),
        patch(
            "scribe.providers.factory.OpenAIProvider", return_value=openai_provider
        ) as mock_openai,
        patch("scribe.providers.factory.XAIProvider") as mock_xai,
    ):
        provider = get_provider("joke")

    assert provider is openai_provider
    mock_xai.assert_not_called()
    mock_openai.assert_called_once()


def test_get_provider_uses_meme_image_env_override() -> None:
    xai_provider = Mock(name="xai-provider")

    with (
        patch.dict(
            "os.environ",
            {"SCRIBE_MEME_IMAGE_PROVIDER": "xai", "XAI_API_KEY": "xai-key"},
            clear=True,
        ),
        patch("scribe.providers.factory.XAIProvider", return_value=xai_provider) as mock_xai,
    ):
        provider = get_provider("meme_image")

    assert provider is xai_provider
    mock_xai.assert_called_once()


def test_get_provider_raises_for_missing_anthropic_package() -> None:
    with (
        patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}, clear=True),
        patch("scribe.providers.factory.ANTHROPIC_AVAILABLE", False),
        pytest.raises(ImportError, match="anthropic package not installed"),
    ):
        get_provider("joke", provider_name="anthropic")


def test_get_default_model_rejects_unsupported_feature() -> None:
    with pytest.raises(ValueError, match="does not support feature"):
        _get_default_model("xai", "transcribe")


def test_get_fallback_provider_returns_next_available() -> None:
    with patch.dict(
        "os.environ",
        {"GEMINI_API_KEY": "gemini-key", "OPENAI_API_KEY": "openai-key"},
        clear=True,
    ):
        fallback = _get_fallback_provider("joke", "xai", "original-key")

    assert fallback == "gemini"


def test_get_fallback_provider_returns_none_without_keys() -> None:
    with patch.dict("os.environ", {}, clear=True):
        fallback = _get_fallback_provider("notes", "gemini", "original-key")

    assert fallback is None


def test_config_toml_provider_is_used_when_no_env() -> None:
    # The setup wizard's [providers] choice (here openai for jokes) must override
    # the built-in default (xai) when no SCRIBE_JOKE_PROVIDER env var is set.
    openai_provider = Mock(name="openai-provider")
    with (
        patch.dict("os.environ", {"OPENAI_API_KEY": "openai-key"}, clear=True),
        patch("scribe.providers.factory._config_provider", return_value="openai"),
        patch(
            "scribe.providers.factory.OpenAIProvider", return_value=openai_provider
        ) as mock_openai,
        patch("scribe.providers.factory.XAIProvider") as mock_xai,
    ):
        provider = get_provider("joke")

    assert provider is openai_provider
    mock_xai.assert_not_called()
    mock_openai.assert_called_once()


def test_env_provider_beats_config_toml() -> None:
    # Precedence is env > config.toml: the env var must win even if config differs.
    xai_provider = Mock(name="xai-provider")
    with (
        patch.dict(
            "os.environ", {"SCRIBE_JOKE_PROVIDER": "xai", "XAI_API_KEY": "xai-key"}, clear=True
        ),
        patch("scribe.providers.factory._config_provider", return_value="openai"),
        patch("scribe.providers.factory.XAIProvider", return_value=xai_provider),
        patch("scribe.providers.factory.OpenAIProvider") as mock_openai,
    ):
        provider = get_provider("joke")

    assert provider is xai_provider
    mock_openai.assert_not_called()


def test_local_only_routes_text_feature_to_ollama() -> None:
    """$0 local-only mode forces notes/jokes/meme-concepts to local Ollama."""
    ollama_provider = Mock(name="ollama-provider")
    with (
        patch.dict("os.environ", {"SCRIBE_LOCAL_ONLY": "1"}, clear=True),
        patch(
            "scribe.providers.factory.OllamaProvider", return_value=ollama_provider
        ) as mock_ollama,
    ):
        provider = get_provider("notes", model="llama3.2")

    assert provider is ollama_provider
    mock_ollama.assert_called_once()


def test_local_only_overrides_explicit_cloud_provider() -> None:
    """local-only wins even over an explicit --provider openai (the $0 guarantee)."""
    ollama_provider = Mock(name="ollama-provider")
    with (
        patch.dict("os.environ", {"SCRIBE_LOCAL_ONLY": "true"}, clear=True),
        patch("scribe.providers.factory.OllamaProvider", return_value=ollama_provider),
        patch("scribe.providers.factory.OpenAIProvider") as mock_openai,
    ):
        provider = get_provider("joke", provider_name="openai", model="llama3.2")

    assert provider is ollama_provider
    mock_openai.assert_not_called()


def test_local_only_blocks_meme_image() -> None:
    """Image generation has no local backend, so local-only refuses it clearly."""
    with (
        patch.dict("os.environ", {"SCRIBE_LOCAL_ONLY": "1"}),
        pytest.raises(ValueError, match="no local backend"),
    ):
        get_provider("meme_image")


def test_local_only_enabled_parses_env() -> None:
    from scribe.providers.factory import _local_only_enabled

    for truthy in ("1", "true", "TRUE", "yes", "on"):
        with patch.dict("os.environ", {"SCRIBE_LOCAL_ONLY": truthy}):
            assert _local_only_enabled() is True
    for falsy in ("0", "false", "no", "off", ""):
        with patch.dict("os.environ", {"SCRIBE_LOCAL_ONLY": falsy}):
            assert _local_only_enabled() is False


def test_local_only_off_when_unset() -> None:
    from scribe.providers.factory import _local_only_enabled

    # Ensure the var is removed for this test
    import os
    with (
        patch.dict("os.environ", {}, clear=False),
        patch("scribe.config_file.load_config_file", return_value={}),
    ):
        if "SCRIBE_LOCAL_ONLY" in os.environ:
            del os.environ["SCRIBE_LOCAL_ONLY"]
        assert _local_only_enabled() is False
