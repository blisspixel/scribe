"""Backend interface for local transcription engines.

A backend wraps one engine (faster-whisper, mlx-whisper, whisper.cpp) behind a
single ``audio -> Transcript`` method. The registry picks one per hardware. Each
backend degrades gracefully: ``is_available()`` returns False when its optional
runtime dependency is not installed, and the registry falls back to one that is,
ending at the CPU floor that ships with the base install.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from scribe.models.transcript import Transcript


class TranscriptionBackend(ABC):
    """A local transcription engine that turns audio into a structured Transcript."""

    #: Stable identifier used by the registry, config, and diagnostics.
    name: str = "backend"

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """True when this backend's runtime dependency can be imported."""

    @abstractmethod
    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None,
        model_size: str,
        beam_size: int,
        initial_prompt: str | None,
    ) -> Transcript:
        """Transcribe ``audio_path`` into a Transcript with this backend's provenance."""
