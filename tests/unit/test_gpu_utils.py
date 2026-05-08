import builtins
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scribe.utils.gpu import (
    check_cuda_available,
    clear_gpu_cache,
    configure_gpu_optimizations,
    detect_gpu_capability,
    get_cuda_version,
    get_gpu_memory_info,
    is_high_end_gpu,
    set_gpu_optimizations,
)


def _make_fake_torch(
    *,
    cuda_available=True,
    total_memory=24 * 1024**3,
    allocated_memory=8 * 1024**3,
    cuda_version="12.4",
):
    cuda = SimpleNamespace(
        is_available=Mock(return_value=cuda_available),
        get_device_properties=Mock(return_value=SimpleNamespace(total_memory=total_memory)),
        memory_allocated=Mock(return_value=allocated_memory),
        empty_cache=Mock(),
        synchronize=Mock(),
    )
    return SimpleNamespace(
        cuda=cuda,
        version=SimpleNamespace(cuda=cuda_version),
        set_float32_matmul_precision=Mock(),
    )


def test_detect_gpu_capability_delegates_to_gpu_config():
    fake_config = Mock()
    fake_config.to_dict.return_value = {"has_gpu": True, "gpu_name": "RTX 4090"}

    with patch("scribe.utils.gpu.GPUConfig.detect", return_value=fake_config):
        result = detect_gpu_capability()

    assert result == {"has_gpu": True, "gpu_name": "RTX 4090"}
    fake_config.to_dict.assert_called_once_with()


def test_configure_gpu_optimizations_uses_defaults_and_overrides():
    assert configure_gpu_optimizations({}) == {
        "model_size": "base",
        "beam_size": 5,
        "batch_size": 8,
        "use_fp16": False,
        "enable_tensor_cores": False,
    }

    assert configure_gpu_optimizations(
        {
            "model_size": "large-v3",
            "beam_size": 10,
            "batch_size": 16,
            "use_fp16": True,
            "enable_tensor_cores": True,
        }
    ) == {
        "model_size": "large-v3",
        "beam_size": 10,
        "batch_size": 16,
        "use_fp16": True,
        "enable_tensor_cores": True,
    }


def test_is_high_end_gpu_matches_name_and_vram():
    assert is_high_end_gpu("NVIDIA GeForce RTX 4090", 24.0) is True
    assert is_high_end_gpu("NVIDIA A100", 40.0) is True
    assert is_high_end_gpu("Generic GPU", 21.0) is True
    assert is_high_end_gpu("", 24.0) is False
    assert is_high_end_gpu("GTX 1660", 6.0) is False


def test_check_cuda_available_and_get_cuda_version_use_torch_module():
    fake_torch = _make_fake_torch(cuda_available=True, cuda_version="12.1")

    with patch.dict(sys.modules, {"torch": fake_torch}):
        assert check_cuda_available() is True
        assert get_cuda_version() == "12.1"


def test_check_cuda_available_returns_false_when_torch_import_fails():
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("torch unavailable")
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        assert check_cuda_available() is False
        assert get_cuda_version() == "Not available"


def test_get_cuda_version_returns_unknown_when_cuda_version_missing():
    fake_torch = _make_fake_torch(cuda_available=True, cuda_version=None)

    with patch.dict(sys.modules, {"torch": fake_torch}):
        assert get_cuda_version() == "Unknown"


def test_get_gpu_memory_info_reads_device_properties():
    fake_torch = _make_fake_torch(
        cuda_available=True,
        total_memory=12 * 1024**3,
        allocated_memory=3 * 1024**3,
    )

    with patch.dict(sys.modules, {"torch": fake_torch}):
        info = get_gpu_memory_info()

    assert info == {
        "total_gb": 12.0,
        "used_gb": 3.0,
        "free_gb": 9.0,
    }


def test_clear_gpu_cache_and_set_gpu_optimizations_call_torch_helpers():
    fake_torch = _make_fake_torch(cuda_available=True)

    with patch.dict(sys.modules, {"torch": fake_torch}):
        clear_gpu_cache()
        set_gpu_optimizations()
        set_gpu_optimizations(enable_tensor_cores=False)

    fake_torch.cuda.empty_cache.assert_called_once_with()
    fake_torch.cuda.synchronize.assert_called_once_with()
    fake_torch.set_float32_matmul_precision.assert_called_once_with("high")


def test_get_gpu_memory_info_and_clear_gpu_cache_handle_runtime_errors():
    broken_torch = SimpleNamespace(
        cuda=SimpleNamespace(is_available=Mock(side_effect=RuntimeError("bad cuda")))
    )

    with patch.dict(sys.modules, {"torch": broken_torch}):
        assert get_gpu_memory_info() == {"total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0}
        clear_gpu_cache()
        set_gpu_optimizations()
