"""Hardware-adaptive diarizer registry and selection rules.

Analogous to ``scribe.core.backends.registry``, ``select_diarizer`` is a pure,
total function over ``(hardware, availability, override)`` that chooses the best
speaker diarization backend without side effects. ``resolve_diarizer`` walks the
same preference order and returns the first backend that can actually be built,
so a missing token or dependency degrades to the next backend, then to no labels.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING

from scribe.core.backends.hardware import HardwareInfo, Vendor
from scribe.core.diarization.base import SpeakerDiarizer
from scribe.core.diarization.mlx import NemotronMLXDiarizer
from scribe.core.diarization.nemotron import NemotronDiarizer
from scribe.core.diarization.pyannote import PyannoteDiarizer
from scribe.utils.logging import get_logger

if TYPE_CHECKING:
    from scribe.models.config import ScribeConfig

logger = get_logger(__name__)

# Canonical diarizer backend names
NEMOTRON = "nemotron"
PYANNOTE = "pyannote"
MLX = "mlx"
NONE = "none"
AUTO = "auto"

VALID_DIARIZERS: tuple[str, ...] = (NEMOTRON, PYANNOTE, MLX, NONE)
#: Every value accepted by --diarizer and the ``diarization_backend`` setting.
DIARIZER_CHOICES: tuple[str, ...] = (AUTO, *VALID_DIARIZERS)

# Preference order per hardware vendor, most to least preferred. Nemotron needs no
# Hugging Face token and runs well on CPU, so it leads everywhere except Apple
# Silicon, where the native MLX port uses Metal. pyannote is the fallback: it needs
# a token with the gated model licenses accepted.
_PREFERENCE: dict[Vendor, tuple[str, ...]] = {
    "nvidia": (NEMOTRON, PYANNOTE),
    "apple": (MLX, NEMOTRON, PYANNOTE),
    "amd": (NEMOTRON, PYANNOTE),
    "intel": (NEMOTRON, PYANNOTE),
    "cpu": (NEMOTRON, PYANNOTE),
}

#: Install guidance per backend, used in logs and ``scribe info``.
INSTALL_HINTS: dict[str, str] = {
    NEMOTRON: 'install the "diarize-nemotron" extra',
    PYANNOTE: 'install the "diarize" extra and set HF_TOKEN',
    MLX: 'install the "diarize-mlx" extra (Apple Silicon only)',
}


def normalize_diarizer(value: str | None) -> str:
    """Canonical lower-case diarizer name; empty and 'default' mean 'auto'."""
    norm = (value or "").strip().lower()
    return AUTO if norm in ("", "default") else norm


def diarizer_availability() -> dict[str, bool]:
    """Which diarizers can run right now, by importable dependency."""
    return {
        NEMOTRON: NemotronDiarizer.is_available(),
        PYANNOTE: PyannoteDiarizer.is_available(),
        MLX: NemotronMLXDiarizer.is_available(),
        NONE: True,
    }


def hf_token(config: ScribeConfig | None) -> str | None:
    """The Hugging Face token from config or the HF_TOKEN environment variable."""
    token = config.hf_token if config is not None and config.hf_token else None
    return token or os.getenv("HF_TOKEN") or None


def candidate_order(hardware: HardwareInfo, override: str | None = None) -> tuple[str, ...]:
    """The backends to try, in order: a valid explicit override first, then hardware order."""
    norm = normalize_diarizer(override)
    if norm == NONE:
        return ()
    preference = _PREFERENCE.get(hardware.vendor, (NEMOTRON, PYANNOTE))
    if norm in VALID_DIARIZERS:
        return (norm, *(name for name in preference if name != norm))
    return preference


def select_diarizer(
    hardware: HardwareInfo,
    *,
    override: str | None = None,
    available: Mapping[str, bool] | None = None,
) -> str:
    """Choose a diarization backend name for the given hardware.

    Deterministic and total over every input. An explicit override
    (from config or SCRIBE_DIARIZATION_BACKEND) wins when it names a valid,
    available diarizer. 'auto', empty, or unavailable overrides fall through
    to the hardware preference order, and finally to 'none'.
    """
    avail = dict(available) if available is not None else diarizer_availability()
    for candidate in candidate_order(hardware, override):
        if avail.get(candidate, False):
            return candidate
    return NONE


def build_diarizer(
    name: str,
    *,
    config: ScribeConfig | None = None,
    device: str | None = None,
) -> SpeakerDiarizer | None:
    """Instantiate the diarization engine for ``name``.

    Returns None for 'none', an unknown name, or missing mandatory credentials
    (an HF token for pyannote). ``device`` is a request; torch backends fall back
    to CPU when the installed PyTorch build cannot use CUDA.
    """
    if name == NONE:
        return None

    if name == NEMOTRON:
        diarizer = NemotronDiarizer(device=device)
        logger.info(f"Speaker diarization: NVIDIA Nemotron-3 ({diarizer.device})")
        return diarizer

    if name == MLX:
        logger.info("Speaker diarization: Nemotron-3 on Apple Silicon (MLX, Metal)")
        return NemotronMLXDiarizer()

    if name == PYANNOTE:
        token = hf_token(config)
        if not token:
            logger.info(
                "pyannote diarization needs a Hugging Face token (set HF_TOKEN or hf_token "
                "in config)"
            )
            return None
        pipeline_name = (
            getattr(config, "pyannote_pipeline", None) or PyannoteDiarizer.DEFAULT_PIPELINE
        )
        pyannote = PyannoteDiarizer(token, device=device, pipeline_name=pipeline_name)
        logger.info(f"Speaker diarization: pyannote ({pipeline_name}, {pyannote.device})")
        return pyannote

    logger.warning(f"Unknown diarizer backend: '{name}'")
    return None


def resolve_diarizer(
    hardware: HardwareInfo,
    *,
    config: ScribeConfig | None = None,
    device: str | None = None,
    available: Mapping[str, bool] | None = None,
) -> SpeakerDiarizer | None:
    """Build the best diarizer that can run here, or None (with the reason logged).

    Tries an explicit ``diarization_backend`` first, then the hardware preference
    order, skipping backends whose dependencies or credentials are missing.
    """
    override = normalize_diarizer(getattr(config, "diarization_backend", AUTO))
    if override == NONE:
        return None
    if override not in DIARIZER_CHOICES:
        logger.warning(
            f"Unknown diarization backend '{override}'; choose one of "
            f"{', '.join(DIARIZER_CHOICES)}. Selecting automatically."
        )

    avail = dict(available) if available is not None else diarizer_availability()
    if override in VALID_DIARIZERS and not avail.get(override, False):
        logger.warning(
            f"Requested diarizer '{override}' is not installed ({INSTALL_HINTS[override]}); "
            "trying the next available backend"
        )

    for candidate in candidate_order(hardware, override):
        if not avail.get(candidate, False):
            continue
        diarizer = build_diarizer(candidate, config=config, device=device)
        if diarizer is not None:
            return diarizer

    logger.info(
        "Speaker diarization is enabled but no backend can run; "
        f"{INSTALL_HINTS[NEMOTRON]} for token-free local speaker labels. Skipping labels."
    )
    return None
