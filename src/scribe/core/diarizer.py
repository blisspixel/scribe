"""Local speaker diarization: "who said what", entirely on-device.

The cloud path already returns speaker-labeled segments (the OpenAI diarize model).
This brings the same capability to local transcription using pyannote.audio, so a
``Transcript`` produced by faster-whisper, mlx-whisper, or whisper.cpp can carry the
same ``speaker`` field that the structured writers and the ``.txt`` already render.

The design keeps the model run and the alignment math separate. ``LocalDiarizer``
owns the pyannote pipeline (which needs a Hugging Face token and is optional via the
``scribe[diarize]`` extra); ``assign_speakers`` is a pure function that maps speaker
turns onto transcript segments and is exhaustively unit-tested without any model.
Diarization degrades gracefully: a missing dependency, missing token, or pipeline
failure leaves the transcript unlabeled rather than failing the transcription.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from scribe.models.transcript import Transcript, TranscriptSegment
from scribe.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SpeakerTurn:
    """A span of audio attributed to one speaker by the diarizer."""

    start: float
    end: float
    speaker: str


@runtime_checkable
class SpeakerDiarizer(Protocol):
    """The minimal interface the transcription engines depend on."""

    def apply(self, audio_path: Path, transcript: Transcript) -> Transcript: ...


def dominant_speaker(start: float, end: float, turns: list[SpeakerTurn]) -> str | None:
    """The speaker whose turns overlap [start, end] the most, or None.

    Overlap is summed per speaker so a segment that spans a short interjection is
    still attributed to whoever holds most of it. Ties keep the earliest turn's
    speaker, which makes the result deterministic given sorted turns.
    """
    totals: dict[str, float] = {}
    order: dict[str, int] = {}
    for index, turn in enumerate(turns):
        overlap = min(end, turn.end) - max(start, turn.start)
        if overlap > 0:
            totals[turn.speaker] = totals.get(turn.speaker, 0.0) + overlap
            order.setdefault(turn.speaker, index)
    if not totals:
        return None
    # Most overlap wins; earliest-appearing speaker breaks ties.
    return min(totals, key=lambda s: (-totals[s], order[s]))


def assign_speakers(transcript: Transcript, turns: list[SpeakerTurn]) -> Transcript:
    """Return a copy of ``transcript`` with each segment's dominant speaker set.

    Pure and total: every segment is reassigned (to a label or None), segment order
    and all other fields are preserved, and an empty turn list yields a transcript
    whose segments are simply unlabeled.
    """
    ordered = sorted(turns, key=lambda t: (t.start, t.end))
    labeled: list[TranscriptSegment] = [
        replace(segment, speaker=dominant_speaker(segment.start, segment.end, ordered))
        for segment in transcript.segments
    ]
    return replace(transcript, segments=labeled)


class LocalDiarizer:
    """Runs pyannote.audio locally and aligns its turns onto a Transcript."""

    #: Default pretrained pipeline. Gated on Hugging Face for license acceptance.
    PIPELINE = "pyannote/speaker-diarization-3.1"

    def __init__(self, hf_token: str, *, device: str | None = None) -> None:
        self.hf_token = hf_token
        self.device = device

    @classmethod
    def is_available(cls) -> bool:
        """True when pyannote.audio can be imported."""
        try:
            return importlib.util.find_spec("pyannote.audio") is not None
        except (ImportError, ValueError):
            return False

    def _run_pipeline(self, audio_path: Path) -> list[SpeakerTurn]:
        """Run pyannote and return its speaker turns (empty on any failure)."""
        try:
            from pyannote.audio import Pipeline

            pipeline = Pipeline.from_pretrained(self.PIPELINE, use_auth_token=self.hf_token)
            if pipeline is None:
                logger.warning(
                    "pyannote pipeline could not be loaded (check HF token and license acceptance)"
                )
                return []
            if self.device:
                import torch

                pipeline.to(torch.device(self.device))

            diarization: Any = pipeline(str(audio_path))
            turns = [
                SpeakerTurn(start=float(segment.start), end=float(segment.end), speaker=str(label))
                for segment, _, label in diarization.itertracks(yield_label=True)
            ]
            logger.info(f"Diarization found {len({t.speaker for t in turns})} speakers")
            return turns
        except Exception as e:
            logger.warning(f"Speaker diarization failed, leaving transcript unlabeled: {e}")
            return []

    def apply(self, audio_path: Path, transcript: Transcript) -> Transcript:
        """Label ``transcript`` with locally-detected speakers (no-op on failure)."""
        turns = self._run_pipeline(audio_path)
        if not turns:
            return transcript
        return assign_speakers(transcript, turns)
