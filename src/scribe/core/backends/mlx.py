"""mlx-whisper backend for Apple Silicon (Metal via Apple's MLX).

mlx-whisper is the fast local path on Apple Silicon: it runs Whisper on the Metal
GPU through MLX, well ahead of faster-whisper's CPU fallback there. Word-level
timestamps are left optional for this engine; ``mlx_whisper.transcribe`` returns
segment-level timing, which is what the writers and the ``.txt`` need.

Install Scribe with its ``mlx`` extra on an Apple Silicon Mac. The result
mapping is kept as a pure function so it is unit-testable without the dependency
or a Mac present.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from scribe.core.backends.base import TranscriptionBackend
from scribe.models.transcript import Transcript, TranscriptSegment

# Whisper size -> mlx-community model repo on Hugging Face. mlx-whisper downloads
# and caches the converted weights on first use.
_MODEL_REPOS = {
    "tiny": "mlx-community/whisper-tiny-mlx",
    "base": "mlx-community/whisper-base-mlx",
    "small": "mlx-community/whisper-small-mlx",
    "medium": "mlx-community/whisper-medium-mlx",
    "large": "mlx-community/whisper-large-v3-mlx",
    "large-v2": "mlx-community/whisper-large-v2-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "turbo": "mlx-community/whisper-large-v3-turbo",
}
_DEFAULT_REPO = "mlx-community/whisper-large-v3-mlx"


def _result_to_transcript(result: dict[str, Any], model_size: str) -> Transcript:
    """Map an ``mlx_whisper.transcribe`` result dict into a Transcript."""
    segments: list[TranscriptSegment] = []
    for seg in result.get("segments") or []:
        start = max(0.0, float(seg.get("start", 0.0)))
        end = float(seg.get("end", start))
        if end < start:
            end = start
        segments.append(TranscriptSegment(start=start, end=end, text=str(seg.get("text", ""))))
    duration = segments[-1].end if segments else None
    return Transcript(
        segments=segments,
        language=result.get("language"),
        duration=duration,
        backend="mlx-whisper",
        model=model_size,
    )


class MLXWhisperBackend(TranscriptionBackend):
    name = "mlx"

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("mlx_whisper") is not None

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None,
        model_size: str,
        beam_size: int,
        initial_prompt: str | None,
    ) -> Transcript:
        import mlx_whisper

        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=_MODEL_REPOS.get(model_size, _DEFAULT_REPO),
            language=language,
            initial_prompt=initial_prompt,
        )
        return _result_to_transcript(dict(result), model_size)
