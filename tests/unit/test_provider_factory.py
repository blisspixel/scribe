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
