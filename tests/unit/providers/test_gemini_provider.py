"""
Unit tests for Gemini provider.
"""

import sys
from unittest.mock import Mock, patch

import pytest

from scribe.providers.base import ProviderConfig


@pytest.fixture
def gemini_config():
    """Create a test Gemini provider config."""
    return ProviderConfig(
        provider_name="gemini",
        api_key="test-gemini-key",
        model="gemini-3-pro-preview",
    )


@pytest.fixture
def mock_google_genai():
    """Mock the google.genai module and its dependencies."""
    mock_genai = Mock()
    mock_types = Mock()
    mock_genai.types = mock_types

    # Mock the google module structure
    mock_google = Mock()
    mock_google.genai = mock_genai

    with patch.dict(sys.modules, {
        "google": mock_google,
        "google.genai": mock_genai,
        "google.genai.types": mock_types,
    }):
        yield mock_genai, mock_types


class TestGeminiProvider:
    """Test suite for GeminiProvider."""

    def test_size_to_aspect_ratio(self, gemini_config, mock_google_genai):
        """Test size to aspect ratio conversion."""
        mock_genai, mock_types = mock_google_genai

        # Force reimport to use mocked modules
        if "scribe.providers.gemini_provider" in sys.modules:
            del sys.modules["scribe.providers.gemini_provider"]

        from scribe.providers.gemini_provider import GeminiProvider

        # Create mock client
        mock_client = Mock()
        mock_genai.Client.return_value = mock_client

        provider = GeminiProvider(gemini_config)

        assert provider._size_to_aspect_ratio("1024x1024") == "1:1"
        assert provider._size_to_aspect_ratio("1024x1536") == "3:4"
        assert provider._size_to_aspect_ratio("1536x1024") == "4:3"
        assert provider._size_to_aspect_ratio("1024x1792") == "9:16"
        assert provider._size_to_aspect_ratio("1792x1024") == "16:9"
        assert provider._size_to_aspect_ratio("unknown") == "1:1"  # Default

    def test_transcribe_audio_not_supported(self, gemini_config, mock_google_genai):
        """Test that audio transcription is not supported."""
        mock_genai, mock_types = mock_google_genai

        if "scribe.providers.gemini_provider" in sys.modules:
            del sys.modules["scribe.providers.gemini_provider"]

        from scribe.providers.gemini_provider import GeminiProvider

        mock_client = Mock()
        mock_genai.Client.return_value = mock_client

        provider = GeminiProvider(gemini_config)

        with pytest.raises(NotImplementedError, match="does not currently support"):
            provider.transcribe_audio("test.mp3")

    def test_chat_completion_converts_messages(self, gemini_config, mock_google_genai):
        """Test that chat completion converts OpenAI-style messages."""
        mock_genai, mock_types = mock_google_genai

        if "scribe.providers.gemini_provider" in sys.modules:
            del sys.modules["scribe.providers.gemini_provider"]

        from scribe.providers.gemini_provider import GeminiProvider

        # Setup mocks
        mock_client = Mock()
        mock_genai.Client.return_value = mock_client

        mock_response = Mock()
        mock_response.text = "Test response"
        mock_response.usage_metadata = Mock(
            prompt_token_count=10,
            candidates_token_count=20,
            total_token_count=30
        )
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiProvider(gemini_config)

        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"}
        ]

        result = provider.chat_completion(messages)

        assert result["content"] == "Test response"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 20
        assert result["model"] == "gemini-3-pro-preview"

    def test_generate_image_converts_size(self, gemini_config, mock_google_genai):
        """Test that image generation converts size to aspect ratio."""
        mock_genai, mock_types = mock_google_genai

        if "scribe.providers.gemini_provider" in sys.modules:
            del sys.modules["scribe.providers.gemini_provider"]

        from scribe.providers.gemini_provider import GeminiProvider

        # Setup mocks
        mock_client = Mock()
        mock_genai.Client.return_value = mock_client

        # Mock PIL Image
        mock_pil_image = Mock()
        mock_pil_image.save = Mock()

        mock_generated = Mock()
        mock_generated.image = mock_pil_image

        mock_response = Mock()
        mock_response.generated_images = [mock_generated]

        mock_client.models.generate_images.return_value = mock_response

        provider = GeminiProvider(gemini_config)

        # Test with square size
        result = provider.generate_image("A robot", size="1024x1024")

        assert result is not None
        mock_pil_image.save.assert_called_once()

        # Verify aspect ratio was set
        call_kwargs = mock_client.models.generate_images.call_args[1]
        assert "config" in call_kwargs

    def test_generate_image_no_images_error(self, gemini_config, mock_google_genai):
        """Test error when no images are returned."""
        mock_genai, mock_types = mock_google_genai

        if "scribe.providers.gemini_provider" in sys.modules:
            del sys.modules["scribe.providers.gemini_provider"]

        from scribe.providers.gemini_provider import GeminiProvider

        mock_client = Mock()
        mock_genai.Client.return_value = mock_client

        mock_response = Mock()
        mock_response.generated_images = []

        mock_client.models.generate_images.return_value = mock_response

        provider = GeminiProvider(gemini_config)

        with pytest.raises(ValueError, match="returned no images"):
            provider.generate_image("A robot")
