"""Base protocols and data models for local speaker diarization."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from scribe.models.transcript import Transcript


@dataclass(frozen=True)
class SpeakerTurn:
    """A span of audio attributed to one speaker by the diarizer."""

    start: float
    end: float
    speaker: str
    confidence: float | None = None


@dataclass(frozen=True)
class DiarizationResult:
    """Complete, normalized output from any diarization backend."""

    turns: tuple[SpeakerTurn, ...]
    backend: str
    model: str
    speaker_count: int
    frame_resolution_ms: int = 10
    supports_overlap: bool = False
    speaker_limit_reached: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class DiarizationBackend(Protocol):
    """Protocol implemented by every diarizer backend provider."""

    name: str

    @classmethod
    def is_available(cls) -> bool: ...

    def diarize(self, audio_path: Path) -> DiarizationResult: ...


@runtime_checkable
class SpeakerDiarizer(Protocol):
    """The interface transcription engines depend on to attach speaker labels."""

    name: str

    def apply(self, audio_path: Path, transcript: Transcript) -> Transcript: ...


def package_has_submodule(package: str, *parts: str) -> bool:
    """True when ``package`` is installed and ships the given subpackage or module.

    Checks the filesystem instead of calling ``find_spec`` on a dotted name, which
    would import the (heavy) parent package just to answer an availability probe.
    """
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, ValueError):
        return False
    if spec is None or not spec.submodule_search_locations:
        return False
    for location in spec.submodule_search_locations:
        target = Path(location).joinpath(*parts)
        if target.is_dir() or target.with_suffix(".py").is_file():
            return True
    return False
