import os
from unittest.mock import Mock, patch

import pytest

from scribe.utils.meme_bakeoff import run_meme_bakeoff
from scribe.utils.meme_generator import MemeConfig


def test_run_meme_bakeoff_requires_available_providers():
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValueError, match="No providers available with API keys"):
            run_meme_bakeoff("meeting transcript", MemeConfig(), Mock())


def test_run_meme_bakeoff_returns_judged_winner():
    config = MemeConfig(spice_level=6)
    judge_provider = Mock()
    judge_provider.chat_completion.return_value = {
        "content": '{"winner": 2, "reasoning": "Better template fit", "scores": {"1": {}, "2": {}}}',
    }

    concepts = {
        "xai": {
            "top_text": "First",
            "bottom_text": "Concept",
            "template": "Drake",
            "judgment": "pretty good",
        },
        "openai": {
            "top_text": "Second",
            "bottom_text": "Winner",
            "template": "Distracted",
            "judgment": "very funny",
        },
    }

    def analyze_concept(provider, _transcript, _cfg, show_reasoning=False):
        assert show_reasoning is False
        return concepts[provider]

    with (
        patch.dict(
            os.environ,
            {"XAI_API_KEY": "xai-key", "OPENAI_API_KEY": "openai-key"},
            clear=True,
        ),
        patch(
            "scribe.utils.meme_bakeoff.get_provider", side_effect=["xai", "openai", judge_provider]
        ),
    ):
        result = run_meme_bakeoff(
            "meeting transcript",
            config,
            analyze_concept,
            providers=["xai", "openai"],
        )

    assert result["winner"] == "openai"
    assert result["concept"] == concepts["openai"]
    assert result["reasoning"] == "Better template fit"
    assert len(result["all_concepts"]) == 2


def test_run_meme_bakeoff_falls_back_when_judging_fails():
    config = MemeConfig()
    judge_provider = Mock()
    judge_provider.chat_completion.side_effect = RuntimeError("judge unavailable")
    concept = {
        "top_text": "Fallback",
        "bottom_text": "Concept",
        "template": "Drake",
        "judgment": "usable",
    }

    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "openai-key"}, clear=True),
        patch("scribe.utils.meme_bakeoff.get_provider", side_effect=["openai", judge_provider]),
    ):
        result = run_meme_bakeoff(
            "meeting transcript",
            config,
            Mock(return_value=concept),
            providers=["openai"],
        )

    assert result["winner"] == "openai"
    assert result["concept"] == concept
    assert result["reasoning"] == "Judging failed, using first concept"


def test_run_meme_bakeoff_requires_successful_concepts():
    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "openai-key"}, clear=True),
        patch("scribe.utils.meme_bakeoff.get_provider", return_value="openai"),
    ):
        with pytest.raises(ValueError, match="No providers successfully generated concepts"):
            run_meme_bakeoff(
                "meeting transcript",
                MemeConfig(),
                Mock(return_value=None),
                providers=["openai"],
            )
