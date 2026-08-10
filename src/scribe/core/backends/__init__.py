"""Hardware-adaptive local transcription backends.

The local path is no longer CUDA-only. ``detect_hardware`` classifies the machine
by vendor, ``select_backend`` maps that to an engine, and ``build_backend``
instantiates it. faster-whisper covers NVIDIA and the CPU floor; mlx-whisper and
whisper.cpp cover Apple Silicon, AMD, and Intel through optional extras.
"""

from scribe.core.backends.base import TranscriptionBackend
from scribe.core.backends.hardware import HardwareInfo, Vendor, detect_hardware
from scribe.core.backends.registry import (
    CPU,
    FASTER_WHISPER,
    MLX,
    VALID_BACKENDS,
    WHISPERCPP,
    backend_availability,
    build_backend,
    select_backend,
)

__all__ = [
    "CPU",
    "FASTER_WHISPER",
    "MLX",
    "VALID_BACKENDS",
    "WHISPERCPP",
    "HardwareInfo",
    "TranscriptionBackend",
    "Vendor",
    "backend_availability",
    "build_backend",
    "detect_hardware",
    "select_backend",
]
