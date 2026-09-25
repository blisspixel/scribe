"""Diarization post-processing, speaker-aware transcript rendering, and naming wiring."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from scribe.core.diarization.postprocess import BinarizeParams, binarize
from scribe.core.local_whisper import rewrite_clean_transcript, write_clean_transcript
from scribe.models.transcript import Transcript, TranscriptSegment
from scribe.utils.transcript_writers import write_srt, write_vtt


def _probs(frames: int, speakers: int = 8) -> np.ndarray:
    return np.zeros((frames, speakers), dtype=np.float32)


def test_hysteresis_bridges_dips_between_onset_and_offset() -> None:
    probs = _probs(300)
    probs[0:100, 0] = 0.9
    probs[100:150, 0] = 0.55  # above offset, below onset: speech continues
    probs[150:200, 0] = 0.9
    turns = binarize(probs, 0.01)
    assert [(t.speaker, t.start, t.end) for t in turns] == [("SPEAKER_00", 0.0, 2.05)]


def test_speech_that_never_reaches_onset_is_ignored() -> None:
    probs = _probs(500)
    probs[:, 0] = 0.9
    probs[100:400, 1] = 0.58  # hovers above offset but never above onset
    assert {t.speaker for t in binarize(probs, 0.01)} == {"SPEAKER_00"}


def test_short_bursts_removed_short_gaps_filled_and_labels_renumbered() -> None:
    probs = _probs(1000)
    probs[0:400, 3] = 0.9  # channel 3 speaks first
    probs[420:600, 3] = 0.9  # 0.2 s gap: filled
    probs[600:1000, 5] = 0.9
    probs[800:810, 6] = 0.9  # 0.1 s burst: removed
    turns = binarize(probs, 0.01)
    assert [(t.speaker, t.start, t.end) for t in turns] == [
        ("SPEAKER_00", 0.0, 6.05),
        ("SPEAKER_01", 5.9, 10.0),
    ]


def test_speaker_with_too_little_speech_is_dropped_unless_alone() -> None:
    probs = _probs(1000)
    probs[:, 0] = 0.9
    probs[500:600, 1] = 0.9  # 1 s total: below min_speaker_seconds
    assert {t.speaker for t in binarize(probs, 0.01)} == {"SPEAKER_00"}

    alone = _probs(100)
    alone[:, 2] = 0.9
    assert [t.speaker for t in binarize(alone, 0.01)] == ["SPEAKER_00"]


def test_binarize_handles_empty_input_and_custom_params() -> None:
    assert binarize(np.zeros((0, 8), dtype=np.float32), 0.01) == []
    probs = _probs(100)
    probs[:, 0] = 0.45
    assert binarize(probs, 0.01, BinarizeParams(onset=0.4, offset=0.3))[0].speaker == "SPEAKER_00"


def _labeled_transcript() -> Transcript:
    parts = [
        ("SPEAKER_00", "Good morning."),
        ("SPEAKER_00", "Let's start."),
        ("SPEAKER_01", "Sounds good."),
        ("SPEAKER_00", "Great."),
    ]
    return Transcript(
        segments=[
            TranscriptSegment(start=float(i * 2), end=float(i * 2 + 1.5), text=f" {t}", speaker=s)
            for i, (s, t) in enumerate(parts)
        ],
        duration=10.0,
    )


def test_speaker_paragraphs_group_consecutive_segments(tmp_path: Path) -> None:
    out = tmp_path / "t.txt"
    write_clean_transcript(_labeled_transcript(), out, tmp_path / "meeting.wav", [])
    body = out.read_text(encoding="utf-8")
    assert "Speakers: SPEAKER_00, SPEAKER_01" in body
    assert "SPEAKER_00: Good morning. Let's start.\n\nSPEAKER_01: Sounds good.\n\n" in body
    assert body.rstrip().endswith("SPEAKER_00: Great.")


def test_unlabeled_transcripts_keep_one_paragraph_per_segment(tmp_path: Path) -> None:
    transcript = Transcript(
        segments=[
            TranscriptSegment(start=0.0, end=1.0, text=" One."),
            TranscriptSegment(start=1.0, end=2.0, text=" Two."),
        ]
    )
    out = tmp_path / "t.txt"
    write_clean_transcript(transcript, out, tmp_path / "m.wav", [])
    body = out.read_text(encoding="utf-8")
    assert "Speakers" not in body
    assert body.endswith("One.\n\nTwo.\n\n")


def test_names_render_in_header_body_and_subtitles(tmp_path: Path) -> None:
    transcript = _labeled_transcript()
    transcript.metadata["speaker_names"] = {
        "SPEAKER_00": {"name": "Dana", "alternatives": ["Sam"]},
    }
    out = tmp_path / "t.txt"
    write_clean_transcript(transcript, out, tmp_path / "meeting.wav", [(100.0, 400.0)])
    body = out.read_text(encoding="utf-8")
    assert "Dana = SPEAKER_00 (possibly also: Sam)" in body
    assert "SPEAKER_01 = unidentified" in body
    assert "Dana: Good morning. Let's start." in body
    assert "<v Dana>" in write_vtt(transcript, tmp_path / "t.vtt").read_text(encoding="utf-8")
    assert "Dana: Good morning." in write_srt(transcript, tmp_path / "t.srt").read_text(
        encoding="utf-8"
    )
    assert transcript.metadata["silence_periods"] == [[100.0, 400.0]]


def test_rewrite_reuses_recorded_silence_periods(tmp_path: Path) -> None:
    transcript = Transcript(
        segments=[
            TranscriptSegment(start=0.0, end=1.0, text=" Before.", speaker="SPEAKER_00"),
            TranscriptSegment(start=400.0, end=401.0, text=" After.", speaker="SPEAKER_00"),
        ],
        duration=401.0,
        metadata={"silence_periods": [[10.0, 390.0]]},
    )
    out = tmp_path / "t.txt"
    rewrite_clean_transcript(transcript, out, tmp_path / "meeting.wav")
    body = out.read_text(encoding="utf-8")
    assert "[NO AUDIO FOR 6 MINUTES" in body
    assert "SPEAKER_00: Before.\n\n[NO AUDIO" in body


def test_transcriber_names_speakers_after_release_and_rewrites_txt(tmp_path: Path) -> None:
    from scribe.core.transcriber import Transcriber
    from scribe.models.config import ScribeConfig
    from scribe.models.gpu import GPUConfig

    transcriber = object.__new__(Transcriber)
    transcriber.config = ScribeConfig(output_folder=tmp_path, name_speakers=True)
    transcriber.gpu_config = GPUConfig(has_gpu=False)
    transcriber._cached_diarizer = None
    transcript = _labeled_transcript()
    transcript.metadata["silence_periods"] = []
    transcriber.last_transcript = transcript
    out = tmp_path / "meeting_transcription.txt"
    order: list[str] = []

    def fake_transcribe(*_args, **_kwargs):
        order.append("transcribe")
        return out

    names = {"SPEAKER_01": {"name": "Priya", "confidence": "high", "evidence": "x"}}
    with (
        patch.object(transcriber, "_transcribe", side_effect=fake_transcribe),
        patch.object(transcriber, "release_resources", side_effect=lambda: order.append("release")),
        patch(
            "scribe.core.speaker_naming.name_speakers",
            side_effect=lambda _t: order.append("name") or names,
        ),
    ):
        transcriber.transcribe(tmp_path / "meeting.wav")

    assert order == ["transcribe", "release", "name"]
    assert "Priya: Sounds good." in out.read_text(encoding="utf-8")
    assert transcriber.last_transcript.speaker_name("SPEAKER_01") == "Priya"


def test_naming_is_skipped_when_disabled_or_music(tmp_path: Path) -> None:
    from scribe.core.transcriber import Transcriber
    from scribe.models.config import ScribeConfig
    from scribe.models.gpu import GPUConfig

    transcriber = object.__new__(Transcriber)
    transcriber.config = ScribeConfig(output_folder=tmp_path, name_speakers=False)
    transcriber.gpu_config = GPUConfig(has_gpu=False)
    transcriber._cached_diarizer = None
    transcriber.last_transcript = _labeled_transcript()
    with (
        patch.object(transcriber, "_transcribe", return_value=tmp_path / "t.txt"),
        patch("scribe.core.speaker_naming.name_speakers") as namer,
    ):
        transcriber.transcribe(tmp_path / "m.wav")
        transcriber.config.name_speakers = True
        transcriber.transcribe(tmp_path / "m.wav", music_mode=True)
    namer.assert_not_called()


def test_ollama_provider_passes_think_switch() -> None:
    from scribe.providers.base import ProviderConfig
    from scribe.providers.ollama_provider import OllamaProvider

    provider = OllamaProvider(ProviderConfig(provider_name="ollama", api_key="x", model="m"))
    with patch.object(provider, "_post_chat", return_value={"message": {"content": "{}"}}) as post:
        provider.chat_completion_with_json([{"role": "user", "content": "hi"}], think=False)
    assert post.call_args.args[0]["think"] is False


def test_openrouter_chat_provider_uses_openai_compatible_endpoint(monkeypatch) -> None:
    from scribe.providers import factory

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("SCRIBE_LOCAL_ONLY", raising=False)
    with (
        patch.object(factory, "_local_only_enabled", return_value=False),
        patch.object(factory, "OpenAIProvider", MagicMock()) as provider_cls,
    ):
        factory.get_provider("speakers", provider_name="openrouter")
    config = provider_cls.call_args.args[0]
    assert config.base_url == factory.OPENROUTER_CHAT_BASE_URL
    assert config.model == "google/gemini-3.8-flash"
    assert config.api_key == "sk-or-test"
