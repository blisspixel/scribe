"""Tests for the hardware-to-diarizer selection rules and registry."""

from collections.abc import Mapping
from unittest.mock import patch

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scribe.core.backends.hardware import HardwareInfo, Vendor
from scribe.core.diarization.nemotron import NemotronDiarizer
from scribe.core.diarization.registry import (
    MLX,
    NEMOTRON,
    NONE,
    PYANNOTE,
    VALID_DIARIZERS,
    build_diarizer,
    resolve_diarizer,
    select_diarizer,
)
from scribe.models.config import ScribeConfig

ALL_AVAILABLE = dict.fromkeys(VALID_DIARIZERS, True)
NONE_AVAILABLE = {**dict.fromkeys(VALID_DIARIZERS, False), NONE: True}


def _hw(vendor: Vendor) -> HardwareInfo:
    return HardwareInfo(vendor=vendor, memory_gb=16.0, accelerator_name=vendor)


def test_nvidia_prefers_nemotron_then_pyannote() -> None:
    assert select_diarizer(_hw("nvidia"), available=ALL_AVAILABLE) == NEMOTRON
    assert select_diarizer(_hw("nvidia"), available={**ALL_AVAILABLE, NEMOTRON: False}) == PYANNOTE
    assert (
        select_diarizer(
            _hw("nvidia"), available={**ALL_AVAILABLE, NEMOTRON: False, PYANNOTE: False}
        )
        == NONE
    )


def test_apple_prefers_mlx_then_nemotron_then_pyannote() -> None:
    assert select_diarizer(_hw("apple"), available=ALL_AVAILABLE) == MLX
    assert select_diarizer(_hw("apple"), available={**ALL_AVAILABLE, MLX: False}) == NEMOTRON
    assert (
        select_diarizer(_hw("apple"), available={**ALL_AVAILABLE, MLX: False, NEMOTRON: False})
        == PYANNOTE
    )


def test_amd_intel_cpu_prefer_token_free_nemotron_then_pyannote() -> None:
    for vendor in ("amd", "intel", "cpu"):
        assert select_diarizer(_hw(vendor), available=ALL_AVAILABLE) == NEMOTRON
        assert (
            select_diarizer(_hw(vendor), available={**ALL_AVAILABLE, NEMOTRON: False}) == PYANNOTE
        )
        assert select_diarizer(_hw(vendor), available=NONE_AVAILABLE) == NONE


def test_valid_override_wins() -> None:
    # Force pyannote on NVIDIA box
    assert select_diarizer(_hw("nvidia"), override="pyannote", available=ALL_AVAILABLE) == PYANNOTE
    # Force none
    assert select_diarizer(_hw("nvidia"), override="none", available=ALL_AVAILABLE) == NONE


def test_invalid_override_falls_back() -> None:
    assert (
        select_diarizer(
            _hw("nvidia"), override="nemotron", available={**ALL_AVAILABLE, NEMOTRON: False}
        )
        == PYANNOTE
    )
    assert (
        select_diarizer(_hw("nvidia"), override="unknown_diarizer", available=ALL_AVAILABLE)
        == NEMOTRON
    )
    assert select_diarizer(_hw("nvidia"), override="auto", available=ALL_AVAILABLE) == NEMOTRON


def test_build_diarizer_returns_none_for_none() -> None:
    assert build_diarizer("none") is None


def test_build_diarizer_pyannote_requires_token() -> None:
    config = ScribeConfig(hf_token=None)
    # When no token in config or env, pyannote returns None cleanly
    diarizer = build_diarizer("pyannote", config=config)
    # Either None if no HF_TOKEN env var, or PyannoteDiarizer if HF_TOKEN is in env
    assert diarizer is None or diarizer.name == "pyannote"


def test_build_diarizer_nemotron() -> None:
    diarizer = build_diarizer("nemotron", device="cpu")
    assert diarizer is not None
    assert diarizer.name == "nemotron"


def test_build_diarizer_nemotron_degrades_cuda_request_without_cuda_torch() -> None:
    with patch("torch.cuda.is_available", return_value=False):
        diarizer = build_diarizer("nemotron", device="cuda")
    assert isinstance(diarizer, NemotronDiarizer)
    assert diarizer.device == "cpu"


def test_resolve_skips_pyannote_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    config = ScribeConfig(hf_token=None)
    only_pyannote = {**NONE_AVAILABLE, PYANNOTE: True}
    assert resolve_diarizer(_hw("cpu"), config=config, available=only_pyannote) is None


def test_resolve_falls_through_unavailable_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    config = ScribeConfig(hf_token=None, diarization_backend="pyannote")
    diarizer = resolve_diarizer(
        _hw("cpu"), config=config, device="cpu", available={**ALL_AVAILABLE, PYANNOTE: False}
    )
    assert diarizer is not None
    assert diarizer.name == NEMOTRON


def test_resolve_uses_explicit_override_first() -> None:
    config = ScribeConfig(hf_token="hf_test", diarization_backend="pyannote")  # noqa: S106
    diarizer = resolve_diarizer(_hw("nvidia"), config=config, device="cpu", available=ALL_AVAILABLE)
    assert diarizer is not None
    assert diarizer.name == PYANNOTE


def test_resolve_none_backend_disables_labels() -> None:
    config = ScribeConfig(diarization_backend="none")
    assert resolve_diarizer(_hw("nvidia"), config=config, available=ALL_AVAILABLE) is None


def test_config_unknown_diarization_backend_falls_back_to_auto() -> None:
    assert ScribeConfig(diarization_backend="whisperx").diarization_backend == "auto"
    assert ScribeConfig(diarization_backend=" Nemotron ").diarization_backend == "nemotron"
    assert ScribeConfig(diarization_backend="").diarization_backend == "auto"


def test_build_diarizer_mlx() -> None:
    diarizer = build_diarizer("mlx")
    assert diarizer is not None
    assert diarizer.name == "mlx"


@given(
    vendor=st.sampled_from(["nvidia", "apple", "amd", "intel", "cpu"]),
    override=st.sampled_from([None, "auto", "nemotron", "pyannote", "mlx", "none", "bogus"]),
    avail=st.fixed_dictionaries(
        {
            NEMOTRON: st.booleans(),
            PYANNOTE: st.booleans(),
            MLX: st.booleans(),
            NONE: st.just(True),
        }
    ),
)
def test_diarizer_selection_is_total_and_deterministic(
    vendor: Vendor,
    override: str | None,
    avail: Mapping[str, bool],
) -> None:
    hw = _hw(vendor)
    result = select_diarizer(hw, override=override, available=avail)
    assert result in VALID_DIARIZERS
    assert select_diarizer(hw, override=override, available=avail) == result

    norm = (override or "").strip().lower()
    if norm == NONE:
        assert result == NONE
    elif norm in VALID_DIARIZERS and avail.get(norm, False):
        assert result == norm


def test_config_file_diarization_section_maps_to_settings() -> None:
    from scribe.config_file import flatten_for_settings

    flat = flatten_for_settings(
        {"diarization": {"enabled": False, "backend": "pyannote", "pyannote_pipeline": "p"}}
    )
    assert flat["enable_speaker_diarization"] is False
    assert flat["diarization_backend"] == "pyannote"
    assert flat["pyannote_pipeline"] == "p"
