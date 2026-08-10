"""faster-whisper backend (NVIDIA CUDA, and the CPU int8 floor).

This wraps the production ``LocalWhisperTranscriber`` engine so the CUDA and CPU
code paths stay byte-for-byte identical to what shipped before backends existed.
The registry routes NVIDIA and plain-CPU hardware here; device and compute-type
selection happen inside the engine via ``GPUConfig``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from scribe.core.backends.base import TranscriptionBackend
from scribe.models.transcript import Transcript


class FasterWhisperBackend(TranscriptionBackend):
    name = "faster-whisper"

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("faster_whisper") is not None

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None,
        model_size: str,
        beam_size: int,
        initial_prompt: str | None,
    ) -> Transcript:
        # Reuse the production engine rather than re-implementing the model.transcribe
        # call, so beam/VAD/compute behavior cannot drift from the main path. The
        # beam width is taken from the engine's GPUConfig, matching that path.
        from scribe.core.local_whisper import LocalWhisperTranscriber

        transcriber = LocalWhisperTranscriber(model_size=model_size, language=language)
        transcriber._load_model()
        return transcriber._execute_transcription(audio_path, None, initial_prompt or "")
