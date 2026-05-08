import os
from unittest.mock import Mock, patch

import pytest

from scribe.utils.joke_bakeoff import run_joke_bakeoff
from scribe.utils.joke_generator import HumorConfig


def test_run_joke_bakeoff_requires_available_providers():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="No providers available with API keys"):
            run_joke_bakeoff("meeting transcript", HumorConfig())


def test_run_joke_bakeoff_returns_judged_winner():
    config = HumorConfig(spice_level=7)
    judge_provider = Mock()
    judge_provider.chat_completion.return_value = {
        "content": 'Result: {"winner": 2, "reasoning": "Sharper punchline", "scores": {"1": {}, "2": {}}}',
    }

    def fake_generate_transcript_joke(*, transcript_path, api_key_or_cfg, provider_name):
        assert transcript_path.exists()
        assert api_key_or_cfg is config
        return (f"{provider_name} joke",)

    with (
        patch.dict(
            os.environ,
            {"XAI_API_KEY": "xai-key", "OPENAI_API_KEY": "openai-key"},
            clear=True,
        ),
        patch(
            "scribe.utils.joke_bakeoff.generate_transcript_joke",
            side_effect=fake_generate_transcript_joke,
        ),
        patch("scribe.utils.joke_bakeoff.get_provider", return_value=judge_provider),
    ):
        result = run_joke_bakeoff("meeting transcript", config, providers=["xai", "openai"])

    assert result["winner"] == "openai"
    assert result["joke"] == "openai joke"
    assert result["reasoning"] == "Sharper punchline"
    assert [item["provider"] for item in result["all_jokes"]] == ["xai", "openai"]


def test_run_joke_bakeoff_falls_back_when_judging_fails():
    config = HumorConfig()
    judge_provider = Mock()
    judge_provider.chat_completion.side_effect = RuntimeError("judge unavailable")

    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "openai-key"}, clear=True),
        patch(
            "scribe.utils.joke_bakeoff.generate_transcript_joke",
            return_value=("fallback joke",),
        ),
        patch("scribe.utils.joke_bakeoff.get_provider", return_value=judge_provider),
    ):
        result = run_joke_bakeoff("meeting transcript", config, providers=["openai"])

    assert result["winner"] == "openai"
    assert result["joke"] == "fallback joke"
    assert result["reasoning"] == "Judging failed, using first joke"


def test_run_joke_bakeoff_requires_successful_jokes():
    config = HumorConfig()

    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "openai-key"}, clear=True),
        patch("scribe.utils.joke_bakeoff.generate_transcript_joke", return_value=None),
    ):
        with pytest.raises(ValueError, match="No providers successfully generated jokes"):
            run_joke_bakeoff("meeting transcript", config, providers=["openai"])
