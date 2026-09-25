"""Speaker naming: model proposals are assigned only by transcript evidence."""

import json
from unittest.mock import MagicMock, patch

import pytest

from scribe.core import speaker_naming
from scribe.core.speaker_naming import (
    build_messages,
    identify_speakers,
    name_speakers,
    score_name,
    validate_names,
)
from scribe.models.transcript import Transcript, TranscriptSegment


def _meeting() -> Transcript:
    lines = [
        ("A", "Thanks everyone for joining. Dana, can you start with the numbers?"),
        ("B", "Sure. We are four percent under forecast this quarter."),
        ("A", "Great, thanks Dana. Priya, anything on hiring?"),
        ("C", "Hi, I'm Priya. Hiring slipped into October."),
        ("A", "Understood. Let's follow up Friday."),
    ]
    return Transcript(
        segments=[
            TranscriptSegment(start=float(i * 5), end=float(i * 5 + 4), text=text, speaker=label)
            for i, (label, text) in enumerate(lines)
        ]
    )


def _reply(speakers: list[dict], people: list[str] | None = None) -> str:
    return json.dumps({"speakers": speakers, "people": people or []})


def test_score_name_points_to_the_addressed_speaker() -> None:
    transcript = _meeting()
    turns = speaker_naming._turns(transcript)
    scores, quote = score_name("dana", turns, transcript.speakers)
    assert max(scores, key=lambda label: scores[label]) == "B"
    assert scores["A"] < 0  # the speaker who says the name is penalized
    assert quote and "Dana" in quote


def test_self_introduction_counts_for_the_speaker() -> None:
    transcript = _meeting()
    scores, _ = score_name("priya", speaker_naming._turns(transcript), transcript.speakers)
    assert max(scores, key=lambda label: scores[label]) == "C"


def test_model_that_names_whoever_says_a_name_is_overruled() -> None:
    transcript = _meeting()
    # The model wrongly gives speaker A the names A says to others.
    reply = _reply(
        [
            {"label": "A", "name": "Dana", "confidence": "high", "evidence": "thanks Dana"},
            {"label": "B", "name": None, "confidence": "low", "evidence": ""},
            {"label": "C", "name": "Priya", "confidence": "high", "evidence": "I'm Priya"},
        ],
        people=["Dana", "Priya"],
    )
    names = validate_names(reply, transcript)
    assert names["B"]["name"] == "Dana"
    assert names["C"]["name"] == "Priya"
    assert "A" not in names


def test_names_absent_from_the_transcript_are_rejected() -> None:
    transcript = _meeting()
    reply = _reply(
        [{"label": "A", "name": "Robert", "confidence": "high", "evidence": "Robert said"}],
        people=["Robert", "SPEAKER_01", "unknown"],
    )
    assert validate_names(reply, transcript) == {}


def test_ambiguous_single_mention_is_not_assigned() -> None:
    transcript = Transcript(
        segments=[
            TranscriptSegment(start=0.0, end=2.0, text="Hello there.", speaker="A"),
            TranscriptSegment(start=2.0, end=4.0, text="I spoke to Sam yesterday.", speaker="B"),
            TranscriptSegment(start=4.0, end=6.0, text="Okay.", speaker="C"),
        ]
    )
    assert validate_names(_reply([], people=["Sam"]), transcript) == {}


def test_two_names_on_one_speaker_keep_the_stronger_and_list_the_other() -> None:
    lines = [
        ("A", "Morgan, what do you think?"),
        ("B", "I think it works."),
        ("A", "Thanks Morgan. Morgan, one more thing."),
        ("B", "Go ahead."),
        ("A", "Casey, your view?"),
        ("B", "Agreed."),
        ("C", "Nothing from me."),
    ]
    transcript = Transcript(
        segments=[
            TranscriptSegment(start=float(i), end=float(i) + 0.9, text=t, speaker=s)
            for i, (s, t) in enumerate(lines)
        ]
    )
    names = validate_names(_reply([], people=["Morgan", "Casey"]), transcript)
    assert names["B"]["name"] == "Morgan"
    assert names["B"]["alternatives"] == ["Casey"]


@pytest.mark.parametrize("content", ["not json", "{}", '{"speakers": "x"}', ""])
def test_malformed_replies_yield_no_names(content: str) -> None:
    assert validate_names(content, _meeting()) == {}


def test_reply_wrapped_in_prose_and_fences_is_parsed() -> None:
    reply = "Here you go:\n```json\n" + _reply([], people=["Dana"]) + "\n```"
    assert validate_names(reply, _meeting())["B"]["name"] == "Dana"


def test_build_messages_lists_every_label_and_turn() -> None:
    messages = build_messages(_meeting())
    user = messages[-1]["content"]
    assert "Speakers to identify: A, B, C" in user
    assert "A: Great, thanks Dana." in user


def test_identify_speakers_disables_ollama_thinking_and_records_source() -> None:
    provider = MagicMock()
    provider.config = MagicMock(provider_name="ollama", model="qwen3:30b", timeout=600)
    provider.chat_completion_with_json.return_value = {
        "content": _reply([], people=["Dana", "Priya"])
    }
    names = identify_speakers(_meeting(), provider)
    kwargs = provider.chat_completion_with_json.call_args.kwargs
    assert kwargs["think"] is False
    assert kwargs["temperature"] == 0.0
    assert provider.config.timeout == 180
    assert names["B"]["source"] == "ollama:qwen3:30b"


def test_cloud_providers_do_not_receive_the_ollama_think_switch() -> None:
    provider = MagicMock()
    provider.config = MagicMock(provider_name="openai", model="gpt-5.5", timeout=120)
    provider.chat_completion_with_json.return_value = {"content": _reply([])}
    identify_speakers(_meeting(), provider)
    assert "think" not in provider.chat_completion_with_json.call_args.kwargs


def test_name_speakers_skips_quietly_without_a_local_model(monkeypatch) -> None:
    monkeypatch.delenv("SCRIBE_SPEAKERS_PROVIDER", raising=False)
    monkeypatch.delenv("SCRIBE_LOCAL_ONLY", raising=False)
    with (
        patch("scribe.providers.factory._config_provider", return_value=None),
        patch("scribe.utils.ollama_models.list_installed_models", return_value=[]),
    ):
        assert name_speakers(_meeting()) == {}


def test_name_speakers_never_raises_on_provider_failure() -> None:
    provider = MagicMock()
    provider.config = MagicMock(provider_name="openai", model="m", timeout=60)
    provider.chat_completion_with_json.side_effect = RuntimeError("network down")
    with patch.object(speaker_naming, "resolve_provider", return_value=provider):
        assert name_speakers(_meeting()) == {}


def test_long_transcripts_are_trimmed_to_head_and_tail() -> None:
    segments = [
        TranscriptSegment(start=float(i), end=float(i) + 0.5, text="word " * 40, speaker=label)
        for i, label in enumerate(["A", "B"] * 400)
    ]
    excerpt = speaker_naming.transcript_excerpt(Transcript(segments=segments))
    assert "middle of the meeting omitted" in excerpt
    assert len(excerpt) < 30000


def test_truncated_reply_still_yields_names_from_salvage() -> None:
    truncated = '{"speakers": [{"label": "A", "name": "Dana", "confidence": "high", "evid'
    assert validate_names(truncated, _meeting())["B"]["name"] == "Dana"


def test_ollama_naming_unloads_the_model_after_answering() -> None:
    provider = MagicMock()
    provider.config = MagicMock(provider_name="ollama", model="m", timeout=600)
    provider.chat_completion_with_json.return_value = {"content": _reply([])}
    identify_speakers(_meeting(), provider)
    assert provider.chat_completion_with_json.call_args.kwargs["keep_alive"] == 0


def test_local_naming_model_is_chosen_from_a_capped_budget(monkeypatch) -> None:
    from scribe.utils.ollama_models import OllamaModel

    monkeypatch.delenv("SCRIBE_SPEAKERS_PROVIDER", raising=False)
    monkeypatch.delenv("SCRIBE_SPEAKERS_MODEL", raising=False)
    installed = [OllamaModel(name="big:30b", size_gb=19.0), OllamaModel(name="mid:8b", size_gb=6.0)]
    with (
        patch("scribe.providers.factory._config_provider", return_value=None),
        patch("scribe.providers.factory._local_only_enabled", return_value=False),
        patch("scribe.utils.ollama_models.list_installed_models", return_value=installed),
        patch("scribe.utils.ollama_models.available_model_memory_gb", return_value=24.0),
    ):
        provider = speaker_naming.resolve_provider()
    assert provider is not None
    assert provider.config.model == "mid:8b"
