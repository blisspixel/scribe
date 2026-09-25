"""
Structured transcript domain model.

This is the single representation every transcription path produces and every
output writer consumes. Before this existed, the local backend returned a
throwaway ``list[dict]`` and the API path built speaker-aware lines as a string,
so segment, speaker, and confidence data was computed and then discarded. Holding
it in one typed model lets the hardware backends, the structured-output writers,
and speaker diarization all share the same shape without re-parsing text.

The dataclasses are frozen and validate their invariants on construction, so an
illegal segment (end before start, confidence out of range) cannot be built.
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import deal


def _check_span(start: float, end: float) -> None:
    # Reject non-finite values (NaN/inf) up front: NaN slips past every ordering
    # comparison below and would later crash the SRT/VTT writers. External engine
    # or provider responses can produce these, so guard at construction.
    if not (math.isfinite(start) and math.isfinite(end)):
        raise ValueError(f"start and end must be finite, got start={start}, end={end}")
    if start < 0:
        raise ValueError(f"start must be non-negative, got {start}")
    if end < start:
        raise ValueError(f"end ({end}) must be >= start ({start})")


def _check_confidence(confidence: float | None) -> None:
    if confidence is not None and not (0.0 <= confidence <= 1.0):
        raise ValueError(f"confidence must be in [0, 1], got {confidence}")


@dataclass(frozen=True)
class TranscriptWord:
    """A single word with its own timing, when a backend provides word timestamps."""

    start: float
    end: float
    text: str
    confidence: float | None = None
    speaker: str | None = None

    def __post_init__(self) -> None:
        _check_span(self.start, self.end)
        _check_confidence(self.confidence)


@dataclass(frozen=True)
class TranscriptSegment:
    """A contiguous span of speech: timing, text, and optional speaker/confidence."""

    start: float
    end: float
    text: str
    speaker: str | None = None
    confidence: float | None = None
    words: tuple[TranscriptWord, ...] | None = None

    def __post_init__(self) -> None:
        _check_span(self.start, self.end)
        _check_confidence(self.confidence)


@dataclass
class Transcript:
    """A full transcript: ordered segments plus provenance metadata.

    ``backend`` records what produced it (for example "faster-whisper", "openai",
    "mlx"), so downstream artifacts can state their provenance honestly.
    """

    segments: list[TranscriptSegment]
    language: str | None = None
    duration: float | None = None
    backend: str | None = None
    model: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def speaker_name(self, label: str | None) -> str | None:
        """Display name for a speaker label: an identified name, else the label itself.

        Names come from ``metadata["speaker_names"]`` (label -> {"name": ...}), which
        speaker naming fills in; labels without an accepted name are shown as-is.
        """
        names = self.metadata.get("speaker_names") or {}
        entry = names.get(label) if label else None
        if isinstance(entry, dict) and entry.get("name"):
            return str(entry["name"])
        return label

    @property
    def speakers(self) -> list[str]:
        """Distinct speaker labels, in first-appearance order."""
        seen: list[str] = []
        for segment in self.segments:
            if segment.speaker and segment.speaker not in seen:
                seen.append(segment.speaker)
        return seen

    @property
    def has_speakers(self) -> bool:
        return any(segment.speaker for segment in self.segments)

    @deal.post(lambda result: isinstance(result, str))
    def text(self) -> str:
        """The full transcript as plain text, one space between segments."""
        return " ".join(s.text.strip() for s in self.segments if s.text.strip())

    def iter_speaker_turns(self) -> Iterator[tuple[str | None, list[TranscriptSegment]]]:
        """Group consecutive segments that share a speaker into turns."""
        turn: list[TranscriptSegment] = []
        current: str | None = None
        for segment in self.segments:
            if turn and segment.speaker != current:
                yield current, turn
                turn = []
            current = segment.speaker
            turn.append(segment)
        if turn:
            yield current, turn
