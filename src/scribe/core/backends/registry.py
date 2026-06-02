"""Backend registry and the hardware-to-engine selection rule.

``select_backend`` is the heart of the hardware-adaptive path: a pure, total
function over ``(vendor, availability, override)`` that names the engine to use.
It is kept free of any import side effects so it can be exhaustively unit-tested
without the optional engines installed.
"""

from __future__ import annotations

from collections.abc import Mapping

from scribe.core.backends.base import TranscriptionBackend
from scribe.core.backends.faster_whisper import FasterWhisperBackend
from scribe.core.backends.hardware import HardwareInfo, Vendor
from scribe.core.backends.mlx import MLXWhisperBackend
from scribe.core.backends.whispercpp import WhisperCppBackend

# Canonical backend names (also accepted as the SCRIBE_LOCAL_BACKEND override).
FASTER_WHISPER = "faster-whisper"
MLX = "mlx"
WHISPERCPP = "whispercpp"
CPU = "cpu"

VALID_BACKENDS: tuple[str, ...] = (FASTER_WHISPER, MLX, WHISPERCPP, CPU)

# Preference order per vendor, most to least preferred. "cpu" is the universal
# floor (faster-whisper on the CPU) and is always reachable, so every list that
# can miss its accelerator ends there.
_PREFERENCE: dict[Vendor, tuple[str, ...]] = {
    "nvidia": (FASTER_WHISPER,),
    "apple": (MLX, WHISPERCPP, CPU),
    "amd": (WHISPERCPP, CPU),
    "intel": (WHISPERCPP, CPU),
    "cpu": (CPU,),
}


def backend_availability() -> dict[str, bool]:
    """Which backends can run right now, by importable dependency."""
    faster = FasterWhisperBackend.is_available()
    return {
        FASTER_WHISPER: faster,
        MLX: MLXWhisperBackend.is_available(),
        WHISPERCPP: WhisperCppBackend.is_available(),
        CPU: faster,  # the CPU floor is faster-whisper running on the CPU
    }


def select_backend(
    hardware: HardwareInfo,
    *,
    override: str | None = None,
    available: Mapping[str, bool] | None = None,
) -> str:
    """Choose a backend name for the given hardware.

    Deterministic and total over every input. A concrete ``override`` (from
    ``SCRIBE_LOCAL_BACKEND`` or ``config.local_backend``) wins when it names a
    valid, available backend. ``auto``/``default``/empty, or an unknown or
    currently unavailable override, fall through to the per-vendor preference
    order, and finally to ``cpu``, which is always reachable.
    """
    avail = dict(available) if available is not None else backend_availability()

    norm = (override or "").strip().lower()
    if norm and norm not in ("auto", "default"):
        if norm in VALID_BACKENDS and avail.get(norm, False):
            return norm
        # Unknown or unavailable override: ignore it and pick automatically.

    for candidate in _PREFERENCE.get(hardware.vendor, (CPU,)):
        if avail.get(candidate, False):
            return candidate

    return CPU


def build_backend(name: str) -> TranscriptionBackend:
    """Instantiate the backend for ``name``.

    ``faster-whisper`` and ``cpu`` are both served by the faster-whisper engine;
    it selects CUDA versus CPU int8 internally from the detected GPU.
    """
    if name == MLX:
        return MLXWhisperBackend()
    if name == WHISPERCPP:
        return WhisperCppBackend()
    return FasterWhisperBackend()
