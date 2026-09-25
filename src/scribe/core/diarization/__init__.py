"""Local speaker diarization: hardware-adaptive, decoupled, and word-aligned."""

from scribe.core.diarization.alignment import (
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
from scribe.core.diarization.mlx import NemotronMLXDiarizer
from scribe.core.diarization.nemotron import NemotronDiarizer
from scribe.core.diarization.pyannote import PyannoteDiarizer
from scribe.core.diarization.registry import (
    AUTO,
    DIARIZER_CHOICES,
    MLX,
    NEMOTRON,
    NONE,
    PYANNOTE,
    VALID_DIARIZERS,
    build_diarizer,
    diarizer_availability,
    resolve_diarizer,
    select_diarizer,
)

__all__ = [
    "AUTO",
    "DIARIZER_CHOICES",
    "MLX",
    "NEMOTRON",
    "NONE",
    "PYANNOTE",
    "VALID_DIARIZERS",
    "DiarizationBackend",
    "DiarizationResult",
    "NemotronDiarizer",
    "NemotronMLXDiarizer",
    "PyannoteDiarizer",
    "SpeakerDiarizer",
    "SpeakerTurn",
    "align_diarization",
    "align_words",
    "assign_speakers",
    "build_diarizer",
    "diarizer_availability",
    "dominant_speaker",
    "resegment_by_words",
    "resegment_transcript",
    "resolve_diarizer",
    "select_diarizer",
]
