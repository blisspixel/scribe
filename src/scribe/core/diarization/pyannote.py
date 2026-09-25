"""Pyannote local speaker diarization backend adapter.

Supports pyannote/speaker-diarization-community-1 with fallback to 3.1.
Utilizes exclusive speaker tracks when available for clean ASR timestamp reconciliation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from scribe.core.diarization.alignment import align_diarization
from scribe.core.diarization.base import DiarizationResult, SpeakerTurn
from scribe.core.diarization.device import resolve_torch_device
from scribe.models.transcript import Transcript
from scribe.utils.logging import get_logger

logger = get_logger(__name__)


def _load_pipeline(pipeline_cls: Any, pipe_id: str, token: str) -> Any:
    """Load a pretrained pipeline across pyannote 3.x (use_auth_token) and 4.x (token)."""
    try:
        return pipeline_cls.from_pretrained(pipe_id, token=token)
    except TypeError:
        return pipeline_cls.from_pretrained(pipe_id, use_auth_token=token)


class PyannoteDiarizer:
    """Runs pyannote.audio locally and converts results to DiarizationResult."""

    name = "pyannote"
    DEFAULT_PIPELINE = "pyannote/speaker-diarization-community-1"
    FALLBACK_PIPELINE = "pyannote/speaker-diarization-3.1"

    def __init__(
        self,
        hf_token: str,
        *,
        device: str | None = None,
        pipeline_name: str | None = None,
    ) -> None:
        self.hf_token = hf_token
        self.device = resolve_torch_device(device)
        self.pipeline_name = pipeline_name or self.DEFAULT_PIPELINE
        self._pipeline_instance: Any = None

    @classmethod
    def is_available(cls) -> bool:
        """True when pyannote.audio can be imported."""
        try:
            return importlib.util.find_spec("pyannote.audio") is not None
        except (ImportError, ValueError):
            return False

    def _get_pipeline(self) -> Any:
        if self._pipeline_instance is not None:
            return self._pipeline_instance

        from pyannote.audio import Pipeline

        # Attempt preferred pipeline, falling back to 3.1 if unavailable
        pipelines_to_try = [self.pipeline_name]
        if self.pipeline_name != self.FALLBACK_PIPELINE:
            pipelines_to_try.append(self.FALLBACK_PIPELINE)

        pipeline = None
        for pipe_id in pipelines_to_try:
            try:
                pipeline = _load_pipeline(Pipeline, pipe_id, self.hf_token)
                if pipeline is not None:
                    self.pipeline_name = pipe_id
                    break
            except Exception as e:
                logger.debug(f"Could not load pyannote pipeline '{pipe_id}': {e}")

        if pipeline is None:
            logger.warning(
                "pyannote pipeline could not be loaded (check HF token and model license acceptance)"
            )
            return None

        if self.device != "cpu":
            import torch

            pipeline.to(torch.device(self.device))

        self._pipeline_instance = pipeline
        return self._pipeline_instance

    def diarize(self, audio_path: Path) -> DiarizationResult:
        """Run pyannote inference and return a normalized DiarizationResult."""
        try:
            pipeline = self._get_pipeline()
            if pipeline is None:
                return DiarizationResult(
                    turns=(),
                    backend=self.name,
                    model=self.pipeline_name,
                    speaker_count=0,
                )

            output: Any = pipeline(str(audio_path))

            # pyannote 4 returns a DiarizeOutput; its exclusive (non-overlapping)
            # track is the cleanest to reconcile with ASR timestamps. pyannote 3
            # returns a bare Annotation.
            exclusive = getattr(output, "exclusive_speaker_diarization", None)
            regular = getattr(output, "speaker_diarization", output)
            tracks_source = exclusive if exclusive is not None else regular

            raw_turns: list[SpeakerTurn] = [
                SpeakerTurn(start=float(segment.start), end=float(segment.end), speaker=str(label))
                for segment, _, label in tracks_source.itertracks(yield_label=True)
            ]

            speakers = {t.speaker for t in raw_turns}
            logger.info(
                f"Pyannote diarization found {len(speakers)} speakers ({self.pipeline_name})"
            )

            return DiarizationResult(
                turns=tuple(raw_turns),
                backend=self.name,
                model=self.pipeline_name,
                speaker_count=len(speakers),
                supports_overlap=exclusive is None,
                metadata={"pipeline": self.pipeline_name, "device": self.device},
            )
        except Exception as e:
            logger.warning(f"Pyannote diarization failed: {e}")
            return DiarizationResult(
                turns=(),
                backend=self.name,
                model=self.pipeline_name,
                speaker_count=0,
                metadata={"error": str(e)},
            )

    def apply(self, audio_path: Path, transcript: Transcript) -> Transcript:
        """Label ``transcript`` with locally-detected speakers (no-op on failure)."""
        result = self.diarize(audio_path)
        if not result.turns:
            return transcript
        return align_diarization(transcript, result, prefer_word_alignment=True)
