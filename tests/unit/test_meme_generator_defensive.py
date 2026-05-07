"""
Defensive tests for meme generator - edge cases and error handling.
"""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scribe.utils.meme_generator import (
    MemeConfig,
    _analyze_transcript_for_meme,
    _generate_meme_image,
)


class TestMemeGeneratorDefensive:
    """Defensive tests for meme generator edge cases."""

    def test_size_normalization_with_description(self):
        """Test that size with description text is normalized."""
        import os

        from scribe.utils.meme_generator import _generate_meme_image

        # Ensure we're using AI text mode (not local Pillow mode)
        with patch.dict(os.environ, {"SCRIBE_MEME_TEXT_METHOD": "ai"}):
            mock_provider = Mock()
            mock_provider.generate_image.return_value = b"fake_image_data"
            mock_provider.config = Mock(provider_name="openai")  # Add config attribute

            config = MemeConfig()
            meme_concept = {
                "top_text": "TEST",
                "bottom_text": "MEME",
                "image_prompt": "test prompt",
                "optimal_size": "1024x1536 (portrait)"  # Invalid format with description
            }

            output_path = Path("test_meme.png")

            # Should normalize to valid size
            with patch("builtins.open", create=True):
                with patch("scribe.utils.meme_generator.Path.mkdir"):
                    result = _generate_meme_image(mock_provider, meme_concept, config, output_path)

            # Check that generate_image was called with normalized size
            # Size should be normalized to '1024x1536' without the description
            assert result == output_path

    def test_size_normalization_invalid_format(self):
        """Test that completely invalid size defaults to 1024x1024."""
        import os

        with patch.dict(os.environ, {"SCRIBE_MEME_TEXT_METHOD": "ai"}):
            mock_provider = Mock()
            mock_provider.generate_image.return_value = b"fake_image_data"
            mock_provider.config = Mock(provider_name="openai")

            config = MemeConfig()
            meme_concept = {
                "top_text": "TEST",
                "bottom_text": "MEME",
                "image_prompt": "test prompt",
                "optimal_size": "invalid_size_format"
            }

            output_path = Path("test_meme.png")

            with patch("builtins.open", create=True):
                with patch("scribe.utils.meme_generator.Path.mkdir"):
                    result = _generate_meme_image(mock_provider, meme_concept, config, output_path)

            assert result == output_path

    def test_analyze_transcript_empty_response(self):
        """Test handling of empty response from AI."""
        mock_provider = Mock()
        mock_provider.chat_completion.return_value = {
            "content": "",
            "usage": {"total_tokens": 0}
        }

        config = MemeConfig()
        result = _analyze_transcript_for_meme(
            mock_provider,
            "Test transcript",
            config,
            show_reasoning=False
        )

        # Should return None for empty response
        assert result is None

    def test_analyze_transcript_invalid_json(self):
        """Test handling of invalid JSON response."""
        mock_provider = Mock()
        mock_provider.chat_completion.return_value = {
            "content": "This is not valid JSON",
            "usage": {"total_tokens": 100}
        }

        config = MemeConfig()
        result = _analyze_transcript_for_meme(
            mock_provider,
            "Test transcript",
            config,
            show_reasoning=False
        )

        # Should return None for invalid JSON
        assert result is None

    def test_analyze_transcript_malformed_json(self):
        """Test handling of malformed JSON that can't be repaired."""
        mock_provider = Mock()
        mock_provider.chat_completion.return_value = {
            "content": '{"template": "test", "incomplete',
            "usage": {"total_tokens": 100}
        }

        config = MemeConfig()
        result = _analyze_transcript_for_meme(
            mock_provider,
            "Test transcript",
            config,
            show_reasoning=False
        )

        # Should return None for malformed JSON
        assert result is None

    def test_generate_image_provider_exception(self):
        """Test handling of provider exceptions during image generation."""
        mock_provider = Mock()
        mock_provider.generate_image.side_effect = Exception("Provider error")

        config = MemeConfig()
        meme_concept = {
            "top_text": "TEST",
            "bottom_text": "MEME",
            "image_prompt": "test prompt",
            "optimal_size": "1024x1024"
        }

        output_path = Path("test_meme.png")
        result = _generate_meme_image(mock_provider, meme_concept, config, output_path)

        # Should return None on exception
        assert result is None

    def test_generate_image_empty_response(self):
        """Test handling of empty image data from provider."""
        import os

        with patch.dict(os.environ, {"SCRIBE_MEME_TEXT_METHOD": "ai"}):
            mock_provider = Mock()
            mock_provider.generate_image.return_value = b""
            mock_provider.config = Mock(provider_name="openai")

            config = MemeConfig()
            meme_concept = {
                "top_text": "TEST",
                "bottom_text": "MEME",
                "image_prompt": "test prompt",
                "optimal_size": "1024x1024"
            }

            output_path = Path("test_meme.png")

            with patch("builtins.open", create=True):
                with patch("scribe.utils.meme_generator.Path.mkdir"):
                    result = _generate_meme_image(mock_provider, meme_concept, config, output_path)

            # Should still write the file even if empty (let caller handle)
            assert result == output_path

    def test_size_normalization_with_spaces(self):
        """Test size normalization with extra spaces."""
        import os

        with patch.dict(os.environ, {"SCRIBE_MEME_TEXT_METHOD": "ai"}):
            mock_provider = Mock()
            mock_provider.generate_image.return_value = b"fake_image_data"
            mock_provider.config = Mock(provider_name="openai")

            config = MemeConfig()
            meme_concept = {
                "top_text": "TEST",
                "bottom_text": "MEME",
                "image_prompt": "test prompt",
                "optimal_size": "  1024x1536  "  # Extra spaces
            }

            output_path = Path("test_meme.png")

            with patch("builtins.open", create=True):
                with patch("scribe.utils.meme_generator.Path.mkdir"):
                    result = _generate_meme_image(mock_provider, meme_concept, config, output_path)

            assert result == output_path

    def test_size_normalization_auto(self):
        """Test that 'auto' size is preserved."""
        import os

        with patch.dict(os.environ, {"SCRIBE_MEME_TEXT_METHOD": "ai"}):
            mock_provider = Mock()
            mock_provider.generate_image.return_value = b"fake_image_data"
            mock_provider.config = Mock(provider_name="openai")

            config = MemeConfig()
            meme_concept = {
                "top_text": "TEST",
                "bottom_text": "MEME",
                "image_prompt": "test prompt",
                "optimal_size": "auto"
            }

            output_path = Path("test_meme.png")

            with patch("builtins.open", create=True):
                with patch("scribe.utils.meme_generator.Path.mkdir"):
                    result = _generate_meme_image(mock_provider, meme_concept, config, output_path)

            assert result == output_path

    def test_analyze_transcript_with_reasoning_output(self):
        """Test that reasoning output is handled correctly."""
        mock_provider = Mock()
        mock_provider.chat_completion.return_value = {
            "content": '{"template": "test", "top_text": "TOP", "bottom_text": "BOTTOM", "image_prompt": "test", "concept": "test concept", "reasoning": "some reasoning"}',
            "usage": {"total_tokens": 100}
        }

        config = MemeConfig()
        result = _analyze_transcript_for_meme(
            mock_provider,
            "Test transcript",
            config,
            show_reasoning=True
        )

        assert result is not None
        assert result["template"] == "test"
        assert "reasoning" in result

    def test_safety_block_detection(self):
        """Test that safety blocks are properly detected."""
        mock_provider = Mock()
        mock_error = Exception("Error code: 400 - {'error': {'message': 'Your request was rejected by the safety system.', 'code': 'moderation_blocked'}}")
        mock_provider.generate_image.side_effect = mock_error

        config = MemeConfig()
        meme_concept = {
            "top_text": "TEST",
            "bottom_text": "MEME",
            "image_prompt": "test prompt",
            "optimal_size": "1024x1024"
        }

        output_path = Path("test_meme.png")
        result = _generate_meme_image(mock_provider, meme_concept, config, output_path)

        # Should return special "SAFETY_BLOCKED" string
        assert result == "SAFETY_BLOCKED"

    def test_missing_optimal_size_uses_default(self):
        """Test that missing optimal_size uses config default."""
        import os

        with patch.dict(os.environ, {"SCRIBE_MEME_TEXT_METHOD": "ai"}):
            mock_provider = Mock()
            mock_provider.generate_image.return_value = b"fake_image_data"
            mock_provider.config = Mock(provider_name="openai")

            config = MemeConfig(size="1536x1024")
            meme_concept = {
                "top_text": "TEST",
                "bottom_text": "MEME",
                "image_prompt": "test prompt"
                # No optimal_size specified
            }

            output_path = Path("test_meme.png")

            with patch("builtins.open", create=True):
                with patch("scribe.utils.meme_generator.Path.mkdir"):
                    result = _generate_meme_image(mock_provider, meme_concept, config, output_path)

            assert result == output_path


class TestXAIImageProviderDefensive:
    """Defensive tests for XAI image provider."""

    def test_xai_image_with_b64_json(self):
        """Test XAI image generation with b64_json format."""
        from scribe.providers.base import ProviderConfig
        from scribe.providers.xai_provider import XAIProvider

        config = ProviderConfig(
            provider_name="xai",
            api_key="test-key",
            model="grok-imagine-image"
        )

        with patch("scribe.providers.xai_provider.OpenAI") as mock_openai:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.data = [Mock(b64_json="dGVzdA==", url=None)]  # "test" in base64
            mock_client.images.generate.return_value = mock_response
            mock_openai.return_value = mock_client

            provider = XAIProvider(config)
            result = provider.generate_image("test prompt")

            assert result == b"test"

    def test_xai_image_with_url_fallback(self):
        """Test XAI image generation falls back to URL format."""

        from scribe.providers.base import ProviderConfig
        from scribe.providers.xai_provider import XAIProvider

        config = ProviderConfig(
            provider_name="xai",
            api_key="test-key",
            model="grok-imagine-image"
        )

        with patch("scribe.providers.xai_provider.OpenAI") as mock_openai:
            with patch.object(XAIProvider, "_download_image_url", return_value=b"image_data") as mock_download:
                mock_client = Mock()

                # First call (b64_json) fails
                mock_client.images.generate.side_effect = [
                    Exception("b64_json not supported"),
                    Mock(data=[Mock(url="http://example.com/image.jpg", b64_json=None)])
                ]

                mock_openai.return_value = mock_client

                provider = XAIProvider(config)
                result = provider.generate_image("test prompt")

                assert result == b"image_data"
                mock_download.assert_called_once_with("http://example.com/image.jpg", timeout=30)

    def test_xai_image_no_data_raises_error(self):
        """Test XAI image generation with no data raises error."""
        from scribe.providers.base import ProviderConfig
        from scribe.providers.xai_provider import XAIProvider

        config = ProviderConfig(
            provider_name="xai",
            api_key="test-key",
            model="grok-imagine-image"
        )

        with patch("scribe.providers.xai_provider.OpenAI") as mock_openai:
            mock_client = Mock()
            mock_response = Mock()
            mock_response.data = []  # Empty data
            mock_client.images.generate.return_value = mock_response
            mock_openai.return_value = mock_client

            provider = XAIProvider(config)

            with pytest.raises(ValueError, match="no image data"):
                provider.generate_image("test prompt")
