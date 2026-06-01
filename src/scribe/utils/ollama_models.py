"""
Local Ollama model discovery and VRAM-aware default selection.

Mirrors Scribe's existing "quality-first auto model selection based on detected
VRAM" for Whisper (see ``scribe.models.gpu.GPUConfig``), but for the local LLM
used to generate notes. Rather than hardcoding model families, it probes the
running Ollama server for what is actually installed (with on-disk sizes, which
are a good proxy for the memory a model needs) and picks the largest general
model that fits the machine's memory budget.

Cross-platform by design:
- NVIDIA: use detected VRAM.
- Apple Silicon: no CUDA VRAM, so use a fraction of unified system RAM.
- Everything else / unknown: stay conservative and lean on Ollama's own
  CPU offload, exactly as documented.

Everything here degrades gracefully: if the Ollama server is unreachable, model
discovery returns an empty list and selection falls back to a sensible default.
"""

import json
import logging
import os
import platform
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Last-resort default when nothing is installed or discovery fails. Real
# selection always prefers an actually-installed model.
DEFAULT_OLLAMA_MODEL = "llama3.2"

# Memory budget (GB) to assume when the machine's VRAM cannot be determined
# (e.g. AMD/Intel GPUs, or CPU-only). Keeps the default pick runnable on modest
# hardware; Ollama offloads to CPU beyond this.
UNKNOWN_BUDGET_CAP_GB = 9.0

# Fraction of the memory budget a model's *weights* may occupy. The remainder
# is headroom for the KV cache (the context window is capped in the provider so
# it stays small), compute buffers, and the OS — so the chosen model loads
# fully onto the GPU instead of spilling layers to the CPU.
FIT_FRACTION = 0.85

# Substrings that mark a model as specialized (not ideal for general meeting
# notes). Deprioritized, not excluded.
_SPECIALIZED_TOKENS = (
    "coder",
    "-code",
    "code-",
    "embed",
    "uncensored",
    "guard",
    "rerank",
    "-vl",
    "vision",
)

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


@dataclass(frozen=True)
class OllamaModel:
    """An installed Ollama model and its on-disk size in GB."""

    name: str
    size_gb: float

    @property
    def is_general(self) -> bool:
        """True if the model looks suitable for general note generation."""
        lowered = self.name.lower()
        return not any(token in lowered for token in _SPECIALIZED_TOKENS)


def _tags_url(base_url: str | None) -> str:
    """Derive the native ``/api/tags`` URL from an OpenAI-compatible base URL."""
    base = (base_url or DEFAULT_OLLAMA_BASE_URL).rstrip("/")
    # Callers may pass the OpenAI-compatible ".../v1" base; tags lives at the root.
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    return f"{base}/api/tags"


def list_installed_models(base_url: str | None = None, timeout: float = 5.0) -> list[OllamaModel]:
    """
    Return the models installed on the local Ollama server, largest first.

    Returns an empty list if the server is unreachable or returns no models.
    """
    url = _tags_url(base_url)
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - localhost only
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError) as exc:
        logger.debug("Could not list Ollama models from %s: %s", url, exc)
        return []

    models: list[OllamaModel] = []
    for entry in payload.get("models", []):
        name = entry.get("name") or entry.get("model")
        size_bytes = entry.get("size")
        if not name or not isinstance(size_bytes, int | float):
            continue
        models.append(OllamaModel(name=str(name), size_gb=float(size_bytes) / (1024**3)))

    models.sort(key=lambda m: m.size_gb, reverse=True)
    return models


def available_model_memory_gb() -> float:
    """
    Best-effort memory budget (GB) for choosing a local model, cross-platform.

    Returns 0.0 when it cannot be determined, signalling "be conservative."
    """
    # NVIDIA path: reuse Scribe's existing GPU detection.
    try:
        from scribe.models.gpu import GPUConfig

        gpu = GPUConfig.detect()
        if gpu.has_gpu and gpu.gpu_memory_gb > 0:
            return float(gpu.gpu_memory_gb)
    except Exception as exc:  # pragma: no cover - detection is best-effort
        logger.debug("GPU detection unavailable for Ollama sizing: %s", exc)

    # Apple Silicon: no CUDA VRAM, but unified memory can run large models.
    if platform.system() == "Darwin" and platform.machine() in {"arm64", "aarch64"}:
        total = _total_system_ram_gb()
        if total > 0:
            return total * 0.6  # leave headroom for the OS and other apps

    return 0.0


def _total_system_ram_gb() -> float:
    """Total physical RAM in GB via os.sysconf (POSIX); 0.0 if unavailable."""
    # Accessed via getattr because os.sysconf does not exist on Windows; this
    # path is only reached on macOS, where it is always present.
    sysconf = getattr(os, "sysconf", None)
    if sysconf is None:  # pragma: no cover - non-POSIX
        return 0.0
    try:
        page_size = sysconf("SC_PAGE_SIZE")
        phys_pages = sysconf("SC_PHYS_PAGES")
        return float(page_size * phys_pages) / (1024**3)
    except (ValueError, OSError):  # pragma: no cover - platform dependent
        return 0.0


def select_ollama_model(
    installed: list[OllamaModel],
    budget_gb: float,
    override: str | None = None,
) -> str:
    """
    Pick the best installed model for the given memory budget (pure function).

    Strategy:
    - An explicit override always wins.
    - Prefer general (non-specialized) models for notes.
    - With a known budget, choose the largest model that fits; if none fit,
      choose the smallest (Ollama will offload the remainder to CPU).
    - With an unknown budget (0), stay conservative: the largest general model
      under ``UNKNOWN_BUDGET_CAP_GB``, else the smallest installed model.
    """
    if override:
        return override
    if not installed:
        return DEFAULT_OLLAMA_MODEL

    general = [m for m in installed if m.is_general] or installed

    if budget_gb and budget_gb > 0:
        ceiling = budget_gb * FIT_FRACTION
        fitting = [m for m in general if m.size_gb <= ceiling]
        if fitting:
            # Largest that fits = best quality within budget.
            return max(fitting, key=lambda m: m.size_gb).name
        # Nothing fits cleanly: smallest minimizes CPU offload.
        return min(general, key=lambda m: m.size_gb).name

    # Unknown budget: conservative pick that stays runnable on modest hardware.
    under_cap = [m for m in general if m.size_gb <= UNKNOWN_BUDGET_CAP_GB]
    if under_cap:
        return max(under_cap, key=lambda m: m.size_gb).name
    return min(general, key=lambda m: m.size_gb).name


def select_default_ollama_model(base_url: str | None = None, override: str | None = None) -> str:
    """
    Resolve the default local model for this machine (I/O + selection combined).

    Honors ``override`` (or ``SCRIBE_OLLAMA_MODEL``) first, then probes the
    server and the machine's memory budget.
    """
    override = override or os.getenv("SCRIBE_OLLAMA_MODEL") or None
    if override:
        return override

    installed = list_installed_models(base_url)
    budget = available_model_memory_gb()
    choice = select_ollama_model(installed, budget, override=None)
    logger.info(
        "Selected local Ollama model '%s' (budget=%.1fGB, %d installed)",
        choice,
        budget,
        len(installed),
    )
    return choice
