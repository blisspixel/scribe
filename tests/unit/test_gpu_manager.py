from unittest.mock import patch

import pytest

from scribe.utils.gpu_manager import GPUResourceManager, get_gpu_manager


@pytest.fixture(autouse=True)
def reset_gpu_manager_singleton():
    GPUResourceManager._instance = None
    GPUResourceManager._initialized = False
    yield
    GPUResourceManager._instance = None
    GPUResourceManager._initialized = False


def test_gpu_manager_is_singleton():
    manager_one = GPUResourceManager.get_instance()
    manager_two = get_gpu_manager()

    assert manager_one is manager_two


def test_acquire_gpu_keeps_same_model_loaded_for_reuse():
    manager = GPUResourceManager()

    with patch("scribe.utils.gpu_manager.clear_gpu_cache") as mock_clear:
        with manager.acquire_gpu("large-v3", model_obj=object()):
            assert manager._current_model == "large-v3"

        with manager.acquire_gpu("large-v3", model_obj=object()):
            assert manager._current_model == "large-v3"

    mock_clear.assert_not_called()
    assert manager.get_current_model() == "large-v3"


def test_acquire_gpu_switches_models_and_clears_cache():
    manager = GPUResourceManager()

    with patch("scribe.utils.gpu_manager.clear_gpu_cache") as mock_clear:
        with manager.acquire_gpu("base", model_obj=object()):
            pass

        with manager.acquire_gpu("large-v3", model_obj=object()):
            assert manager._current_model == "large-v3"

    mock_clear.assert_called_once_with()
    assert manager.get_current_model() == "large-v3"


def test_unload_current_model_resets_manager_state():
    manager = GPUResourceManager()

    with patch("scribe.utils.gpu_manager.clear_gpu_cache") as mock_clear:
        with manager.acquire_gpu("medium", model_obj=object()):
            pass

        manager.unload_current_model()

    mock_clear.assert_called_once_with()
    assert manager.get_current_model() is None


def test_acquire_gpu_preserves_state_when_context_raises():
    manager = GPUResourceManager()

    with pytest.raises(RuntimeError, match="boom"):
        with manager.acquire_gpu("turbo", model_obj=object()):
            raise RuntimeError("boom")

    assert manager.get_current_model() == "turbo"
