"""
Unit tests for multi-provider AI system.

Tests provider abstraction, factory, and provider implementations.
"""

import os
from unittest.mock import Mock, patch

import pytest

from scribe.providers.base import ProviderConfig
from scribe.providers.factory import _get_default_model, get_provider
from scribe.providers.openai_provider import OpenAIProvider
from scribe.providers.xai_provider import XAIProvider


class TestProviderConfig:
    """Test provider configuration."""

    def test_provider_config_creation(self):
        """Test creating provider config."""
        config = ProviderConfig(
            provider_name="openai",
            api_key="test-key",
            model="gpt-5",
            timeout=120
        )

        assert config.provider_name == "openai"
        assert config.api_key == "test-key"
        assert config.model == "gpt-5"
        assert config.timeout == 120


class TestProviderFactory:
    """Test provider factory."""

    def test_get_default_model_openai(self):
        """Test getting default OpenAI models."""
        assert _get_default_model("openai", "joke") == "gpt-5.2"
        assert _get_default_model("openai", "notes") == "gpt-5.2"
        assert _get_default_model("openai", "meme") == "gpt-5.2"
        assert _get_default_model("openai", "meme_image") == "gpt-image-1"
        assert _get_default_model("openai", "transcribe") == "whisper-1"

    def test_get_default_model_xai(self):
        """Test getting default XAI models."""
        assert _get_default_model("xai", "joke") == "grok-4-1-fast-non-reasoning"
        assert _get_default_model("xai", "notes") == "grok-4-1-fast-reasoning"
        assert _get_default_model("xai", "meme") == "grok-4-1-fast-non-reasoning"
        assert _get_default_model("xai", "meme_image") == "grok-2-image-1212"

    def test_get_default_model_unsupported_feature(self):
        """Test error for unsupported feature."""
        with pytest.raises(ValueError, match="does not support feature"):
            _get_default_model("xai", "transcribe")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-openai-key"})
    def test_get_provider_openai_from_env(self):
        """Test getting OpenAI provider from environment."""
        provider = get_provider(feature="joke", provider_name="openai")

        assert isinstance(provider, OpenAIProvider)
        assert provider.config.provider_name == "openai"
        assert provider.config.api_key == "test-openai-key"

    @patch.dict(os.environ, {"XAI_API_KEY": "test-xai-key"})
    def test_get_provider_xai_from_env(self):
        """Test getting XAI provider from environment."""
        provider = get_provider(feature="joke", provider_name="xai")

        assert isinstance(provider, XAIProvider)
        assert provider.config.provider_name == "xai"
        assert provider.config.api_key == "test-xai-key"

    @patch.dict(os.environ, {"SCRIBE_JOKE_PROVIDER": "xai", "XAI_API_KEY": "test-key"})
    def test_get_provider_from_feature_env(self):
        """Test getting provider from feature-specific env var."""
        provider = get_provider(feature="joke")

        assert isinstance(provider, XAIProvider)
        assert provider.config.provider_name == "xai"

    def test_get_provider_with_explicit_key(self):
        """Test getting provider with explicit API key."""
        provider = get_provider(
            feature="joke",
            api_key="explicit-key",
            provider_name="openai"
        )

        assert provider.config.api_key == "explicit-key"

    def test_get_provider_missing_key(self):
        """Test error when API key is missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="No API key found"):
                get_provider(feature="joke", provider_name="openai")

    def test_get_provider_unknown_provider(self):
        """Test error for unknown provider."""
        with pytest.raises(ValueError, match="does not support feature"):
            get_provider(
                feature="joke",
                api_key="test-key",
                provider_name="unknown"
            )


class TestOpenAIProvider:
    """Test OpenAI provider implementation."""

    @patch('scribe.providers.openai_provider.OpenAI')
    def test_chat_completion(self, mock_openai_class):
        """Test chat completion."""
        config = ProviderConfig(
            provider_name="openai",
            api_key="test-key",
            model="gpt-5"
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Test response"))]
        mock_response.usage = Mock(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30
        )
        mock_response.model = "gpt-5"
        mock_client.chat.completions.create.return_value = mock_response

        provider = OpenAIProvider(config)
        result = provider.chat_completion(
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=100
        )

        assert result["content"] == "Test response"
        assert result["usage"]["total_tokens"] == 30
        assert result["model"] == "gpt-5"

    @patch('scribe.providers.openai_provider.OpenAI')
    def test_generate_image(self, mock_openai_class):
        """Test image generation."""
        config = ProviderConfig(
            provider_name="openai",
            api_key="test-key",
            model="gpt-image-1"
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        # Test with b64_json (gpt-image-1 behavior)
        mock_response = Mock()
        mock_response.data = [Mock(b64_json="dGVzdA==", url=None)]  # "test" in base64
        mock_client.images.generate.return_value = mock_response

        provider = OpenAIProvider(config)
        result = provider.generate_image(prompt="Test image")

        assert result == b"test"

    @patch('scribe.providers.openai_provider.OpenAI')
    def test_generate_image_url_fallback(self, mock_openai_class):
        """Test image generation with URL fallback (dall-e-3 behavior)."""
        config = ProviderConfig(
            provider_name="openai",
            api_key="test-key",
            model="gpt-5"
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        # Test with URL (dall-e-3 behavior)
        mock_response = Mock()
        mock_response.data = [Mock(b64_json=None, url="https://example.com/image.png")]
        mock_client.images.generate.return_value = mock_response

        # Mock requests module as imported inside generate_image
        mock_requests = Mock()
        mock_requests.get.return_value = Mock(content=b"fake_image_data")
        with patch.dict('sys.modules', {'requests': mock_requests}):
            provider = OpenAIProvider(config)
            result = provider.generate_image(prompt="Test image", model="dall-e-3")

            assert result == b"fake_image_data"


class TestXAIProvider:
    """Test XAI provider implementation."""

    @patch('scribe.providers.xai_provider.OpenAI')
    def test_chat_completion(self, mock_openai_class):
        """Test chat completion with XAI."""
        config = ProviderConfig(
            provider_name="xai",
            api_key="test-key",
            model="grok-4-fast-non-reasoning"
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Grok response"))]
        mock_response.usage = Mock(
            prompt_tokens=10,
            completion_tokens=20,
            total_tokens=30
        )
        mock_response.model = "grok-4-fast-non-reasoning"
        mock_client.chat.completions.create.return_value = mock_response

        provider = XAIProvider(config)
        result = provider.chat_completion(
            messages=[{"role": "user", "content": "Test"}],
            max_tokens=100
        )

        assert result["content"] == "Grok response"
        assert result["usage"]["total_tokens"] == 30

    @patch('scribe.providers.xai_provider.OpenAI')
    def test_generate_image(self, mock_openai_class):
        """Test image generation with Grok."""
        config = ProviderConfig(
            provider_name="xai",
            api_key="test-key",
            model="grok-2-image"
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        mock_response = Mock()
        mock_response.data = [Mock(url="https://example.com/grok-image.png")]
        mock_client.images.generate.return_value = mock_response

        with patch('requests.get') as mock_get:
            mock_get.return_value.content = b"fake_grok_image"

            provider = XAIProvider(config)
            result = provider.generate_image(prompt="Test Grok image")

            assert result == b"fake_grok_image"

    def test_transcribe_not_supported(self):
        """Test that XAI doesn't support transcription."""
        config = ProviderConfig(
            provider_name="xai",
            api_key="test-key",
            model="grok-4-fast-non-reasoning"
        )

        provider = XAIProvider(config)

        with pytest.raises(NotImplementedError, match="does not currently support"):
            provider.transcribe_audio("test.wav")


class TestProviderIntegration:
    """Test provider integration with features."""

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch('scribe.providers.xai_provider.OpenAI')
    def test_joke_with_xai_provider(self, mock_openai_class):
        """Test joke generation uses XAI provider correctly."""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content="Grok joke"))]
        mock_response.usage = Mock(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        mock_response.model = "grok-4-fast-non-reasoning"
        mock_client.chat.completions.create.return_value = mock_response

        provider = get_provider(feature="joke", provider_name="xai")
        result = provider.chat_completion(
            messages=[{"role": "user", "content": "Tell a joke"}]
        )

        assert result["content"] == "Grok joke"

    @patch.dict(os.environ, {"XAI_API_KEY": "test-key"})
    @patch('scribe.providers.xai_provider.OpenAI')
    def test_notes_with_xai_provider(self, mock_openai_class):
        """Test notes generation uses XAI provider correctly."""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content='{"summary": "test"}'))]
        mock_response.usage = Mock(prompt_tokens=100, completion_tokens=200, total_tokens=300)
        mock_response.model = "grok-4-fast-reasoning"
        mock_client.chat.completions.create.return_value = mock_response

        provider = get_provider(feature="notes", provider_name="xai")
        result = provider.chat_completion_with_json(
            messages=[{"role": "user", "content": "Analyze meeting"}],
            json_schema={"type": "object"}
        )

        assert '{"summary": "test"}' in result["content"]


class TestProviderChatCompletionWithJSON:
    """Test JSON-aware chat completion."""

    @patch('scribe.providers.openai_provider.OpenAI')
    def test_chat_completion_with_json_schema(self, mock_openai_class):
        """Test that JSON schema is added to prompt."""
        config = ProviderConfig(
            provider_name="openai",
            api_key="test-key",
            model="gpt-5"
        )

        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        mock_response = Mock()
        mock_response.choices = [Mock(message=Mock(content='{"key": "value"}'))]
        mock_response.usage = Mock(prompt_tokens=10, completion_tokens=20, total_tokens=30)
        mock_response.model = "gpt-5"
        mock_client.chat.completions.create.return_value = mock_response

        provider = OpenAIProvider(config)
        schema = {"type": "object", "properties": {"key": {"type": "string"}}}

        result = provider.chat_completion_with_json(
            messages=[{"role": "user", "content": "Test"}],
            json_schema=schema
        )

        assert result["content"] == '{"key": "value"}'

        # Verify schema was added to prompt
        call_args = mock_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        last_message = messages[-1]["content"]
        assert "JSON" in last_message or "json" in last_message
