"""Tests for the QA round 2 bug fixes and the --version QoL flag."""

import math
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from scribe import __version__
from scribe.cli.main import app


class TestLoudnormFiniteGuard:
    def test_is_finite_number(self):
        from scribe.core.converter import _is_finite_number

        assert _is_finite_number("-16") is True
        assert _is_finite_number("-1.5") is True
        assert _is_finite_number("-inf") is False
        assert _is_finite_number("inf") is False
        assert _is_finite_number("nan") is False
        assert _is_finite_number(float("nan")) is False
        assert _is_finite_number("not a number") is False
        assert _is_finite_number(None) is False


class TestNotesChunkBudget:
    def _generator(self):
        from scribe.utils.notes_generator import NotesGenerator

        with patch(
            "scribe.providers.get_provider", side_effect=RuntimeError("provider unavailable")
        ):
            with patch("scribe.utils.notes_generator.OpenAI", return_value=Mock()):
                return NotesGenerator(api_key="sk-test123")

    def test_cloud_keeps_large_budget(self):
        gen = self._generator()  # provider is None (fell back to OpenAI client)
        assert gen._chunk_token_budget() == 220_000

    def test_ollama_uses_small_budget(self):
        gen = self._generator()
        gen.provider = Mock()
        gen.provider.config.provider_name = "ollama"
        # Must fit a typical ~16K local context, so far below the cloud budget.
        assert gen._chunk_token_budget() == 10_000


class TestOpenAIEmptyChoices:
    def test_empty_choices_raises_clean_error(self):
        from scribe.providers.base import ProviderConfig
        from scribe.providers.openai_provider import OpenAIProvider

        with patch("scribe.providers.openai_provider.OpenAI") as mock_openai:
            client = Mock()
            response = Mock()
            response.choices = []
            client.chat.completions.create.return_value = response
            mock_openai.return_value = client
            provider = OpenAIProvider(
                ProviderConfig(provider_name="openai", api_key="sk-x", model="gpt-5")
            )
            with pytest.raises(ValueError, match="no choices"):
                provider.chat_completion([{"role": "user", "content": "hi"}])


class TestVersionFlag:
    def test_version_flag(self):
        result = CliRunner().invoke(app, ["--version"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_short_version_flag(self):
        result = CliRunner().invoke(app, ["-V"])
        assert result.exit_code == 0


def test_nan_segment_finite_guard():
    # The transcript model rejects non-finite spans (cross-check kept here for the
    # writer-crash class of bug).
    from scribe.models.transcript import TranscriptSegment

    with pytest.raises(ValueError):
        TranscriptSegment(start=0.0, end=math.inf, text="x")
