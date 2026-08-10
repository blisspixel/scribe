"""whisper.cpp backend via pywhispercpp (Metal, Vulkan, ROCm, or CPU).

whisper.cpp is the broadest portable accelerator path: the same GGML model runs
on Apple Metal, Vulkan, ROCm, or plain CPU depending on how the wheel was built.
It is the registry's choice for AMD and Intel GPUs and the second choice on Apple
Silicon behind mlx-whisper. pywhispercpp downloads the GGML weights on first use.

Install Scribe with its ``whispercpp`` extra. The segment mapping is a pure
function so it is unit-testable without the dependency present.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scribe.core.backends.base import TranscriptionBackend
from scribe.models.transcript import Transcript, TranscriptSegment

# Whisper size -> GGML model name that pywhispercpp downloads.
_MODEL_NAMES = {
    "tiny": "tiny",
    "base": "base",
    "small": "small",
    "medium": "medium",
    "large": "large-v3",
    "large-v2": "large-v2",
    "large-v3": "large-v3",
    "large-v3-turbo": "large-v3-turbo",
    "turbo": "large-v3-turbo",
}
_DEFAULT_MODEL = "large-v3"


def _segments_to_transcript(
    raw_segments: Iterable[Any], model_size: str, language: str | None
) -> Transcript:
    """Map pywhispercpp segments into a Transcript.

    pywhispercpp reports ``t0``/``t1`` in centiseconds (hundredths of a second),
    so they are divided by 100 to get seconds.
    """
    segments: list[TranscriptSegment] = []
    for seg in raw_segments:
        start = max(0.0, float(getattr(seg, "t0", 0)) / 100.0)
        end = float(getattr(seg, "t1", 0)) / 100.0
        if end < start:
            end = start
        segments.append(
            TranscriptSegment(start=start, end=end, text=str(getattr(seg, "text", "")).strip())
        )
    duration = segments[-1].end if segments else None
    return Transcript(
        segments=segments,
        language=language,
        duration=duration,
        backend="whisper.cpp",
        model=model_size,
    )


class WhisperCppBackend(TranscriptionBackend):
    name = "whispercpp"

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("pywhispercpp") is not None

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None,
        model_size: str,
        beam_size: int,
        initial_prompt: str | None,
    ) -> Transcript:
        from pywhispercpp.model import Model

        model = Model(_MODEL_NAMES.get(model_size, _DEFAULT_MODEL))
        raw_segments = model.transcribe(str(audio_path), language=language or "")
        return _segments_to_transcript(raw_segments, model_size, language)
