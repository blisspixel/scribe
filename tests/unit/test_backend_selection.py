"""Tests for the hardware-to-backend selection rule (core/backends/registry.py)."""

from hypothesis import given
from hypothesis import strategies as st

from scribe.core.backends import (
    CPU,
    FASTER_WHISPER,
    MLX,
    VALID_BACKENDS,
    WHISPERCPP,
    HardwareInfo,
    select_backend,
)

ALL_AVAILABLE = dict.fromkeys(VALID_BACKENDS, True)
NONE_AVAILABLE = dict.fromkeys(VALID_BACKENDS, False)


def _hw(vendor: str) -> HardwareInfo:
    return HardwareInfo(vendor=vendor, memory_gb=16.0, accelerator_name=vendor)


def test_nvidia_uses_faster_whisper():
    assert select_backend(_hw("nvidia"), available=ALL_AVAILABLE) == FASTER_WHISPER


def test_apple_prefers_mlx_then_whispercpp_then_cpu():
    assert select_backend(_hw("apple"), available=ALL_AVAILABLE) == MLX
    assert select_backend(_hw("apple"), available={**ALL_AVAILABLE, MLX: False}) == WHISPERCPP
    assert (
        select_backend(_hw("apple"), available={**ALL_AVAILABLE, MLX: False, WHISPERCPP: False})
        == CPU
    )


def test_amd_and_intel_prefer_whispercpp_then_cpu():
    for vendor in ("amd", "intel"):
        assert select_backend(_hw(vendor), available=ALL_AVAILABLE) == WHISPERCPP
        assert select_backend(_hw(vendor), available={**ALL_AVAILABLE, WHISPERCPP: False}) == CPU


def test_cpu_vendor_always_cpu():
    assert select_backend(_hw("cpu"), available=ALL_AVAILABLE) == CPU


def test_valid_available_override_wins():
    # Force whisper.cpp on an NVIDIA box.
    assert (
        select_backend(_hw("nvidia"), override="whispercpp", available=ALL_AVAILABLE) == WHISPERCPP
    )


def test_override_ignored_when_unavailable_or_unknown():
    # Unavailable override falls back to the vendor preference.
    assert (
        select_backend(_hw("nvidia"), override="mlx", available={**ALL_AVAILABLE, MLX: False})
        == FASTER_WHISPER
    )
    # Unknown override is ignored.
    assert select_backend(_hw("nvidia"), override="banana", available=ALL_AVAILABLE) == (
        FASTER_WHISPER
    )
    # "auto" and empty mean "pick for me".
    assert select_backend(_hw("apple"), override="auto", available=ALL_AVAILABLE) == MLX
    assert select_backend(_hw("apple"), override="", available=ALL_AVAILABLE) == MLX


def test_falls_back_to_cpu_when_nothing_available():
    for vendor in ("nvidia", "apple", "amd", "intel", "cpu"):
        assert select_backend(_hw(vendor), available=NONE_AVAILABLE) == CPU


@given(
    vendor=st.sampled_from(["nvidia", "apple", "amd", "intel", "cpu"]),
    override=st.sampled_from([None, "auto", "mlx", "whispercpp", "faster-whisper", "cpu", "x"]),
    avail=st.fixed_dictionaries({name: st.booleans() for name in VALID_BACKENDS}),
)
def test_selection_is_total_and_deterministic(vendor, override, avail):
    hw = _hw(vendor)
    result = select_backend(hw, override=override, available=avail)
    # Always names a known backend, never raises.
    assert result in VALID_BACKENDS
    # Deterministic for identical inputs.
    assert select_backend(hw, override=override, available=avail) == result
    # If a usable override was given, it is honored.
    norm = (override or "").strip().lower()
    if norm in VALID_BACKENDS and avail.get(norm, False):
        assert result == norm
