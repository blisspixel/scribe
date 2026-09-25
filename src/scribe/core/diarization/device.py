"""Torch device resolution shared by the torch-based diarization backends."""

from __future__ import annotations

from scribe.utils.logging import get_logger

logger = get_logger(__name__)


def resolve_torch_device(requested: str | None) -> str:
    """Pick a torch device that the installed PyTorch build can actually use.

    GPU detection elsewhere in Scribe also counts CTranslate2's own CUDA runtime, so
    an NVIDIA machine can report a GPU while PyTorch is a CPU-only build (the
    default PyPI wheel on Windows). Asking such a build for ``cuda`` raises, so any
    CUDA request degrades to CPU with a clear log line instead of failing.
    """
    want = (requested or "auto").strip().lower()
    if want == "cpu":
        return "cpu"
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
    except Exception:  # noqa: S110 - a broken torch install means CPU
        pass
    if want.startswith("cuda"):
        logger.info(
            "PyTorch cannot use CUDA here (CPU-only build or no driver); "
            "running speaker diarization on CPU"
        )
    return "cpu"
