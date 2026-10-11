"""Tests for vendor-general hardware detection (core/backends/hardware.py)."""

from unittest.mock import patch

import pytest

from scribe.core.backends.hardware import HardwareInfo, detect_hardware


def test_hardware_info_has_accelerator():
    assert HardwareInfo(vendor="nvidia", memory_gb=24.0).has_accelerator is True
    assert HardwareInfo(vendor="cpu").has_accelerator is False


def test_detect_prefers_amd_over_nvidia():
    # ROCm masquerades as CUDA, so an AMD probe hit must take priority.
    amd = HardwareInfo(vendor="amd", memory_gb=16.0, accelerator_name="AMD GPU")
    with (
        patch("scribe.core.backends.hardware._detect_amd", return_value=amd),
        patch("scribe.core.backends.hardware._detect_nvidia") as nvidia_probe,
    ):
        result = detect_hardware()
    assert result.vendor == "amd"
    nvidia_probe.assert_not_called()


def test_detect_nvidia_when_no_amd():
    nvidia = HardwareInfo(vendor="nvidia", memory_gb=24.0, accelerator_name="RTX 4090")
    with (
        patch("scribe.core.backends.hardware._detect_amd", return_value=None),
        patch("scribe.core.backends.hardware._detect_nvidia", return_value=nvidia),
    ):
        assert detect_hardware().vendor == "nvidia"


def test_detect_apple_when_no_gpu_vendors():
    apple = HardwareInfo(vendor="apple", memory_gb=32.0, accelerator_name="Apple M3")
    with (
        patch("scribe.core.backends.hardware._detect_amd", return_value=None),
        patch("scribe.core.backends.hardware._detect_nvidia", return_value=None),
        patch("scribe.core.backends.hardware._detect_apple", return_value=apple),
    ):
        assert detect_hardware().vendor == "apple"


def test_detect_falls_back_to_cpu():
    with (
        patch("scribe.core.backends.hardware._detect_amd", return_value=None),
        patch("scribe.core.backends.hardware._detect_nvidia", return_value=None),
        patch("scribe.core.backends.hardware._detect_apple", return_value=None),
        patch("scribe.core.backends.hardware._detect_linux_gpu", return_value=None),
    ):
        result = detect_hardware()
    assert result.vendor == "cpu"
    assert result.has_accelerator is False


def test_detect_hardware_real_call_is_well_formed():
    # No mocks: whatever this host is, detection must return a valid vendor and
    # non-negative memory without raising.
    info = detect_hardware()
    assert info.vendor in {"nvidia", "apple", "amd", "intel", "cpu"}
    assert info.memory_gb >= 0.0


@pytest.mark.parametrize(
    ("vendor_id", "vendor"), [("0x1002", "amd"), ("0x8086", "intel"), ("0x10de", "nvidia")]
)
def test_linux_physical_gpu_without_ml_driver(tmp_path, vendor_id, vendor):
    from scribe.core.backends.hardware import _detect_linux_gpu

    device = tmp_path / "0000:04:00.0"
    device.mkdir()
    (device / "class").write_text("0x030000\n")
    (device / "vendor").write_text(vendor_id + "\n")
    (device / "device").write_text("0x15bf\n")
    with patch("scribe.core.backends.hardware.platform.system", return_value="Linux"):
        detected = _detect_linux_gpu(tmp_path)
    assert detected.vendor == vendor
    assert detected.memory_gb == 0  # shared RAM is not dedicated VRAM
    assert "0x15bf" in detected.accelerator_name


def test_linux_does_not_treat_amd_cpu_as_gpu(tmp_path):
    from scribe.core.backends.hardware import _detect_linux_gpu

    device = tmp_path / "0000:04:00.0"
    device.mkdir()
    (device / "class").write_text("0x060000\n")
    (device / "vendor").write_text("0x1002\n")
    with patch("scribe.core.backends.hardware.platform.system", return_value="Linux"):
        assert _detect_linux_gpu(tmp_path) is None
        assert _detect_linux_gpu(tmp_path / "missing") is None
