"""Unit tests for GPU detection behavior."""

import subprocess
from unittest.mock import patch

from scribe.models.gpu import GPUConfig


class TestGPUConfigDetection:
    """Test GPUConfig detection across CUDA backends."""

    @patch.object(GPUConfig, "_detect_nvidia_gpu")
    @patch("ctranslate2.get_cuda_device_count")
    @patch("torch.cuda.is_available")
    def test_detect_uses_ctranslate2_when_torch_cuda_is_unavailable(
        self,
        mock_torch_cuda_available,
        mock_get_cuda_device_count,
        mock_detect_nvidia_gpu,
    ):
        """Local transcription should still use GPU when CTranslate2 can see CUDA."""
        mock_torch_cuda_available.return_value = False
        mock_get_cuda_device_count.return_value = 1
        mock_detect_nvidia_gpu.return_value = {
            "gpu_name": "NVIDIA GeForce RTX 4090",
            "gpu_memory_gb": 24.0,
        }

        config = GPUConfig.detect()

        assert config.has_gpu is True
        assert config.cuda_available is True
        assert config.gpu_name == "NVIDIA GeForce RTX 4090"
        assert config.gpu_memory_gb == 24.0
        assert config.recommendation == "local"
        assert "CTranslate2" in config.reason

    @patch("ctranslate2.get_cuda_device_count")
    @patch("torch.cuda.is_available")
    def test_detect_reports_missing_local_cuda_backend(
        self,
        mock_torch_cuda_available,
        mock_get_cuda_device_count,
    ):
        """Reason should explain why local transcription is unavailable."""
        mock_torch_cuda_available.return_value = False
        mock_get_cuda_device_count.return_value = 0

        config = GPUConfig.detect()

        assert config.has_gpu is False
        assert config.recommendation == "openai"
        assert "No local CUDA backend detected" in config.reason

    def test_low_vram_gpu_uses_best_fit_local_model(self):
        """Older NVIDIA GPUs should still get the best-fitting local model by default."""
        config = GPUConfig(
            has_gpu=True,
            gpu_name="NVIDIA GeForce GTX 1660",
            gpu_memory_gb=6.0,
            cuda_available=True,
        )

        config._configure_for_gpu()

        assert config.model_size == "medium"
        assert config.recommendation == "local"

    @patch("torch.cuda.get_device_properties")
    @patch("torch.cuda.get_device_name")
    @patch("torch.cuda.is_available")
    def test_detect_prefers_torch_cuda_when_available(
        self,
        mock_torch_cuda_available,
        mock_get_device_name,
        mock_get_device_properties,
    ):
        mock_torch_cuda_available.return_value = True
        mock_get_device_name.return_value = "NVIDIA GeForce RTX 4080"
        mock_get_device_properties.return_value.total_memory = 16 * 1024**3

        config = GPUConfig.detect()

        assert config.has_gpu is True
        assert config.gpu_name == "NVIDIA GeForce RTX 4080"
        assert config.model_size == "large-v3"
        assert config.batch_size == 12

    @patch.object(GPUConfig, "_detect_nvidia_gpu", return_value=None)
    @patch("ctranslate2.get_cuda_device_count", return_value=2)
    @patch("torch.cuda.is_available", return_value=False)
    def test_detect_uses_generic_ctranslate2_name_without_nvidia_smi(
        self,
        _mock_torch_cuda_available,
        _mock_get_cuda_device_count,
        _mock_detect_nvidia_gpu,
    ):
        config = GPUConfig.detect()

        assert config.gpu_name == "NVIDIA GPU (2 devices)"
        assert config.model_size == "medium"
        assert (
            config.reason
            == "GPU detected via CTranslate2 - local faster-whisper transcription available"
        )

    @patch("subprocess.run")
    def test_detect_nvidia_gpu_parses_nvidia_smi_output(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "NVIDIA GeForce RTX 4090, 24564\n"

        info = GPUConfig._detect_nvidia_gpu()

        assert info == {"gpu_name": "NVIDIA GeForce RTX 4090", "gpu_memory_gb": 24564 / 1024}

    @patch("subprocess.run", side_effect=subprocess.SubprocessError("boom"))
    def test_detect_nvidia_gpu_handles_subprocess_failure(self, _mock_run):
        assert GPUConfig._detect_nvidia_gpu() is None

    def test_configure_for_multiple_gpu_tiers_and_helpers(self):
        cases = [
            ("NVIDIA GeForce RTX 4070 Ti", 12.0, "large-v3", 10, True),
            ("NVIDIA GeForce RTX 4070", 12.0, "large-v2", 8, False),
            ("NVIDIA GeForce RTX 3080", 8.0, "large-v2", 8, True),
            ("NVIDIA A100", 40.0, "large-v3", 16, True),
            ("NVIDIA GTX 1650", 5.0, "small", 4, False),
            ("NVIDIA GTX 1050", 3.0, "base", 2, False),
        ]

        for gpu_name, vram_gb, expected_model, expected_batch_size, tensor_cores in cases:
            config = GPUConfig(
                has_gpu=True,
                gpu_name=gpu_name,
                gpu_memory_gb=vram_gb,
                cuda_available=True,
            )

            config._configure_for_gpu()

            assert config.model_size == expected_model
            assert config.batch_size == expected_batch_size
            assert config.enable_tensor_cores is tensor_cores
            assert config.recommendation == "local"

        assert GPUConfig(has_gpu=False).get_expected_speed() == "1-2x real-time (API)"
        assert (
            GPUConfig(
                has_gpu=True,
                gpu_name="NVIDIA RTX 4090",
                gpu_memory_gb=24.0,
                model_size="large-v3",
                beam_size=10,
            ).get_expected_speed()
            == "8-12x real-time"
        )
        assert (
            GPUConfig(
                has_gpu=True,
                gpu_name="NVIDIA RTX 4070",
                gpu_memory_gb=12.0,
                model_size="large-v2",
            ).get_expected_speed()
            == "5-8x real-time"
        )
        assert (
            GPUConfig(
                has_gpu=True,
                gpu_name="NVIDIA GTX 1660",
                gpu_memory_gb=6.0,
                model_size="medium",
            ).get_expected_speed()
            == "10-15x real-time"
        )
        assert (
            GPUConfig(
                has_gpu=True,
                gpu_name="NVIDIA GTX 1050",
                gpu_memory_gb=3.0,
                model_size="base",
            ).get_expected_speed()
            == "15-20x real-time"
        )

        high_end = GPUConfig(has_gpu=True, gpu_name="NVIDIA A100", gpu_memory_gb=40.0)
        assert high_end.is_high_end() is True
        assert high_end.to_dict()["gpu_name"] == "NVIDIA A100"
        assert GPUConfig(has_gpu=True, gpu_name=None, gpu_memory_gb=0.0).is_high_end() is False
