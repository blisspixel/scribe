"""Vendor-general hardware detection for backend selection.

``models/gpu.py`` owns the NVIDIA/CUDA specifics (it maps VRAM tiers to a model
size and beam width). This module sits one level above it and answers a simpler
question for the registry: what kind of accelerator is this machine, expressed as
a ``(vendor, memory_gb)`` pair. NVIDIA detection reuses ``GPUConfig`` so there is
one source of truth for CUDA rather than two that can disagree.

Detection is best effort. Every probe is wrapped so a missing or misbehaving
driver, library, or platform tool degrades to a less specific answer instead of
raising. The CPU result is the universal floor.
"""

from __future__ import annotations

import platform
import subprocess
from dataclasses import dataclass
from typing import Literal

from scribe.models.gpu import GPUConfig

Vendor = Literal["nvidia", "apple", "amd", "intel", "cpu"]


@dataclass(frozen=True)
class HardwareInfo:
    """The detected local accelerator: its vendor, memory, and display name."""

    vendor: Vendor
    memory_gb: float = 0.0
    accelerator_name: str | None = None

    @property
    def has_accelerator(self) -> bool:
        """True for anything other than a plain CPU."""
        return self.vendor != "cpu"


def _detect_amd() -> HardwareInfo | None:
    """Detect an AMD GPU exposed through a ROCm build of PyTorch.

    ROCm presents itself through the same ``torch.cuda`` API as NVIDIA, so this
    must run before the NVIDIA probe: a HIP version is the reliable AMD tell.
    """
    try:
        import torch

        if not getattr(torch.version, "hip", None):
            return None

        memory_gb = 0.0
        name = "AMD GPU"
        try:
            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                memory_gb = props.total_memory / (1024**3)
                name = torch.cuda.get_device_name(0)
        except Exception:
            pass
        return HardwareInfo(vendor="amd", memory_gb=memory_gb, accelerator_name=name)
    except Exception:
        return None


def _detect_nvidia() -> HardwareInfo | None:
    """Detect an NVIDIA GPU, reusing the CUDA detection in ``GPUConfig``."""
    try:
        gpu = GPUConfig.detect()
        if gpu.has_gpu:
            return HardwareInfo(
                vendor="nvidia",
                memory_gb=gpu.gpu_memory_gb,
                accelerator_name=gpu.gpu_name,
            )
    except Exception:
        pass
    return None


def _detect_apple() -> HardwareInfo | None:
    """Detect Apple Silicon (unified-memory Metal) on arm64 macOS."""
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        return None

    memory_gb = 0.0
    try:
        result = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True,
            check=False,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            memory_gb = int(result.stdout.strip()) / (1024**3)
    except (OSError, subprocess.SubprocessError, ValueError):
        memory_gb = 0.0

    return HardwareInfo(
        vendor="apple",
        memory_gb=memory_gb,
        accelerator_name=platform.processor() or "Apple Silicon",
    )


def detect_hardware() -> HardwareInfo:
    """Best-effort detection of the local accelerator vendor and memory.

    Order matters: AMD (ROCm) before NVIDIA because ROCm masquerades as CUDA, then
    Apple Silicon, then a plain-CPU floor.
    """
    for probe in (_detect_amd, _detect_nvidia, _detect_apple):
        info = probe()
        if info is not None:
            return info
    return HardwareInfo(vendor="cpu", memory_gb=0.0, accelerator_name=None)
