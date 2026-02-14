"""
Tests for Anthropic provider.
"""

from unittest.mock import Mock, patch

import pytest


class TestAnthropicProvider:
    """Test Anthropic provider implementation."""

    @pytest.fixture
    def mock_anthropic_client(self):
        """Mock Anthropic client."""
        with patch("scribe.providers.anthropic_provider.Anthropic") as mock:
            yield mock

    def test_init_with_api_key(self, mock_anthropic_client):
        """Test initialization with API key."""
        try:
            from scribe.providers.anthropic_provider import AnthropicProvider
        except ImportError:
            pytest.skip("anthropic package not installed")

        provider = AnthropicProvider(
            api_key="test-key", model="claude-3-5-sonnet-20241022"
        )

        assert provider.api_key == "test-key"
        assert provider.model == "claude-3-5-sonnet-20241022"
        mock_anthropic_client.assert_called_once_with(api_key="test-key")

    def test_init_without_api_key_raises_error(self, mock_anthropic_client):
        """Test initialization without API key raises error."""
        try:
            from scribe.providers.anthropic_provider import AnthropicProvider
        except ImportError:
            pytest.skip("anthropic package not installed")

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="Anthropic API key required"):
                AnthropicProvider()

    def test_chat_completion(self, mock_anthropic_client):
        """Test chat completion."""
        try:
            from scribe.providers.anthropic_provider import AnthropicProvider
        except ImportError:
            pytest.skip("anthropic package not installed")

        # Mock response
        mock_response = Mock()
        mock_response.content = [Mock(text="Test response")]
        mock_response.usage = Mock(input_tokens=10, output_tokens=20)

        mock_client_instance = Mock()
        mock_client_instance.messages.create.return_value = mock_response
        mock_anthropic_client.return_value = mock_client_instance

        provider = AnthropicProvider(api_key="test-key")

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
        ]

        result = provider.chat_completion(messages, max_tokens=100)

        assert result["content"] == "Test response"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 20
        assert result["usage"]["total_tokens"] == 30

        # Verify API call
        mock_client_instance.messages.create.assert_called_once()
        call_args = mock_client_instance.messages.create.call_args[1]
        assert call_args["model"] == "claude-3-5-sonnet-20241022"
        assert call_args["max_tokens"] == 100
        assert call_args["system"] == "You are helpful"
        assert len(call_args["messages"]) == 1
        assert call_args["messages"][0]["role"] == "user"
        assert call_args["messages"][0]["content"] == "Hello"

    def test_chat_completion_without_system_message(self, mock_anthropic_client):
        """Test chat completion without system message."""
        try:
            from scribe.providers.anthropic_provider import AnthropicProvider
        except ImportError:
            pytest.skip("anthropic package not installed")

        # Mock response
        mock_response = Mock()
        mock_response.content = [Mock(text="Test response")]
        mock_response.usage = Mock(input_tokens=10, output_tokens=20)

        mock_client_instance = Mock()
        mock_client_instance.messages.create.return_value = mock_response
        mock_anthropic_client.return_value = mock_client_instance

        provider = AnthropicProvider(api_key="test-key")

        messages = [{"role": "user", "content": "Hello"}]

        result = provider.chat_completion(messages, max_tokens=100)

        assert result["content"] == "Test response"

        # Verify no system parameter was passed
        call_args = mock_client_instance.messages.create.call_args[1]
        assert "system" not in call_args

    def test_generate_image_not_supported(self, mock_anthropic_client):
        """Test that image generation raises NotImplementedError."""
        try:
            from scribe.providers.anthropic_provider import AnthropicProvider
        except ImportError:
            pytest.skip("anthropic package not installed")

        provider = AnthropicProvider(api_key="test-key")

        with pytest.raises(
            NotImplementedError, match="Anthropic Claude does not support image generation"
        ):
            provider.generate_image("test prompt")

    def test_chat_completion_with_developer_role(self, mock_anthropic_client):
        """Test that developer role is converted to user role."""
        try:
            from scribe.providers.anthropic_provider import AnthropicProvider
        except ImportError:
            pytest.skip("anthropic package not installed")

        # Mock response
        mock_response = Mock()
        mock_response.content = [Mock(text="Test response")]
        mock_response.usage = Mock(input_tokens=10, output_tokens=20)

        mock_client_instance = Mock()
        mock_client_instance.messages.create.return_value = mock_response
        mock_anthropic_client.return_value = mock_client_instance

        provider = AnthropicProvider(api_key="test-key")

        messages = [
            {"role": "developer", "content": "System instructions"},
            {"role": "user", "content": "Hello"},
        ]

        result = provider.chat_completion(messages, max_tokens=100)

        # Verify developer role was converted to user
        call_args = mock_client_instance.messages.create.call_args[1]
        assert call_args["messages"][0]["role"] == "user"
        assert call_args["messages"][0]["content"] == "System instructions"


class TestAnthropicProviderFactory:
    """Test Anthropic provider via factory."""

    def test_get_anthropic_provider_from_factory(self):
        """Test getting Anthropic provider from factory."""
        try:
            from scribe.providers.factory import get_provider
        except ImportError:
            pytest.skip("anthropic package not installed")

        with patch.dict(
            "os.environ", {"ANTHROPIC_API_KEY": "test-key"}, clear=False
        ):
            with patch("scribe.providers.anthropic_provider.Anthropic"):
                provider = get_provider(
                    feature="joke", provider_name="anthropic", api_key="test-key"
                )

                assert provider is not None
                assert provider.model == "claude-3-5-sonnet-20241022"

    def test_anthropic_provider_not_available_raises_error(self):
        """Test that missing anthropic package raises ImportError."""
        from scribe.providers.factory import get_provider

        with patch.dict(
            "os.environ", {"ANTHROPIC_API_KEY": "test-key"}, clear=False
        ):
            with patch(
                "scribe.providers.factory.ANTHROPIC_AVAILABLE", False
            ):
                with pytest.raises(
                    ImportError, match="anthropic package not installed"
                ):
                    get_provider(
                        feature="joke",
                        provider_name="anthropic",
                        api_key="test-key",
                    )
