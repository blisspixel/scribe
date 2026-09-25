"""Experimental Apple Silicon MLX speaker diarization adapter.

Runs mlx-community/Nemotron-3-Diarization through mlx-audio on arm64 macOS, using
Metal and unified memory. Needs an mlx-audio build that ships the
``mlx_audio.vad.models.nemotron_diarization`` model package.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from scribe.core.diarization.alignment import align_diarization
from scribe.core.diarization.base import DiarizationResult, SpeakerTurn, package_has_submodule
from scribe.models.transcript import Transcript
from scribe.utils.logging import get_logger

logger = get_logger(__name__)


class NemotronMLXDiarizer:
    """Runs Nemotron-3 Diarization on Apple Silicon via MLX."""

    name = "mlx"
    MODEL_ID = "mlx-community/Nemotron-3-Diarization"

    def __init__(self, *, model_id: str | None = None) -> None:
        self.model_id = model_id or self.MODEL_ID
        self._model: Any = None

    @classmethod
    def is_available(cls) -> bool:
        """True when running on Apple Silicon and mlx_audio is installed."""
        try:
            import platform

            if platform.system() != "Darwin" or platform.machine() != "arm64":
                return False
            return importlib.util.find_spec("mlx") is not None and package_has_submodule(
                "mlx_audio", "vad", "models", "nemotron_diarization"
            )
        except (ImportError, ValueError):
            return False

    def diarize(self, audio_path: Path) -> DiarizationResult:
        """Execute diarization on Apple Silicon Metal GPU."""
        try:
            from mlx_audio.vad import load

            if self._model is None:
                self._model = load(self.model_id, strict=True)

            # DiarizationOutput.segments: start/end in seconds, integer speaker index.
            result = self._model.generate(str(audio_path))
            turns = [
                SpeakerTurn(
                    start=float(segment.start),
                    end=float(segment.end),
                    speaker=f"SPEAKER_{int(segment.speaker):02d}",
                )
                for segment in getattr(result, "segments", None) or []
                if float(segment.end) > float(segment.start)
            ]

            speakers = {t.speaker for t in turns}
            logger.info(f"MLX diarization found {len(speakers)} speakers ({len(turns)} turns)")

            return DiarizationResult(
                turns=tuple(turns),
                backend=self.name,
                model=self.model_id,
                speaker_count=len(speakers),
                frame_resolution_ms=10,
                supports_overlap=True,
                metadata={"platform": "apple-silicon-metal"},
            )
        except Exception as e:
            logger.warning(f"Nemotron-MLX diarization failed, leaving transcript unlabeled: {e}")
            return DiarizationResult(
                turns=(),
                backend=self.name,
                model=self.model_id,
                speaker_count=0,
                metadata={"error": str(e)},
            )

    def apply(self, audio_path: Path, transcript: Transcript) -> Transcript:
        result = self.diarize(audio_path)
        if not result.turns:
            return transcript
        return align_diarization(transcript, result, prefer_word_alignment=True)
