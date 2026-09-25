"""Backward-compatible re-exports for local speaker diarization.

All core functionality has been refactored into modular components under
``scribe.core.diarization``. This module preserves the legacy interface so existing
imports and tests continue working seamlessly.
"""

from __future__ import annotations

from pathlib import Path

from scribe.core.diarization.alignment import (
    _union_length,
    align_diarization,
    align_words,
    assign_speakers,
    dominant_speaker,
    resegment_by_words,
    resegment_transcript,
)
from scribe.core.diarization.base import (
    DiarizationBackend,
    DiarizationResult,
    SpeakerDiarizer,
    SpeakerTurn,
)
from scribe.core.diarization.pyannote import PyannoteDiarizer
from scribe.models.transcript import Transcript


class LocalDiarizer(PyannoteDiarizer):
    """Backward-compatible subclass of PyannoteDiarizer."""

    PIPELINE = "pyannote/speaker-diarization-3.1"

    def __init__(self, hf_token: str, *, device: str | None = None) -> None:
        super().__init__(hf_token, device=device, pipeline_name=self.PIPELINE)

    def _run_pipeline(self, audio_path: Path) -> list[SpeakerTurn]:
        """Legacy helper returning speaker turns list."""
        res = self.diarize(audio_path)
        return list(res.turns)

    def apply(self, audio_path: Path, transcript: Transcript) -> Transcript:
        """Label ``transcript`` with locally-detected speakers (no-op on failure)."""
        turns = self._run_pipeline(audio_path)
        if not turns:
            return transcript
        return assign_speakers(transcript, turns)


__all__ = [
    "DiarizationBackend",
    "DiarizationResult",
    "LocalDiarizer",
    "PyannoteDiarizer",
    "SpeakerDiarizer",
    "SpeakerTurn",
    "_union_length",
    "align_diarization",
    "align_words",
    "assign_speakers",
    "dominant_speaker",
    "resegment_by_words",
    "resegment_transcript",
]
