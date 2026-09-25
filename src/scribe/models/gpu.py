"""
GPU configuration models with hardware-specific optimizations.

This module provides GPU detection and configuration with settings selected from
the capabilities and memory available on the current machine.
"""

import subprocess
from dataclasses import dataclass
from typing import Any, Literal

from scribe.models.options import ModelSize


@dataclass
class GPUConfig:
    """
    GPU-specific configuration with optimized settings.

    This class stores GPU detection results and provides optimized
    transcription settings based on the detected hardware.

    Attributes:
        has_gpu: Whether a GPU was detected
        gpu_name: Name reported by the installed GPU runtime
        gpu_memory_gb: Total GPU memory in GB
        cuda_available: Whether CUDA is available
        cuda_version: CUDA version string
        model_size: Recommended Whisper model size
        beam_size: Recommended beam search size
        batch_size: Recommended batch size
        use_fp16: Whether to use FP16 precision
        enable_tensor_cores: Whether to enable Tensor Core acceleration
        recommendation: Legacy performance hint; automatic selection remains local
        reason: Explanation for the recommendation
    """

    has_gpu: bool
    gpu_name: str | None = None
    gpu_memory_gb: float = 0.0
    cuda_available: bool = False
    cuda_version: str | None = None

    # Optimized settings
    model_size: ModelSize = "base"
    beam_size: int = 5
    batch_size: int = 8
    use_fp16: bool = False
    enable_tensor_cores: bool = False

    # Recommendation
    recommendation: Literal["local", "openai"] = "openai"
    reason: str = "No GPU detected"

    @classmethod
    def detect(cls) -> "GPUConfig":
        """
        Detect GPU and determine optimal settings.

        This method:
        - Detects CUDA availability
        - Identifies GPU model and VRAM
        - Selects optimal model size and parameters
        - Provides a legacy performance hint used by diagnostics

        Returns:
            GPUConfig with detection results and optimized settings
        """
        config = cls(has_gpu=False)
        torch_reason = "PyTorch not available for GPU detection"
        ctranslate2_reason = "CTranslate2 not available for GPU detection"

        try:
            import torch

            if torch.cuda.is_available():
                config.has_gpu = True
                config.cuda_available = True
                config.cuda_version = torch.version.cuda
                config.gpu_name = torch.cuda.get_device_name(0)
                gpu_memory_bytes = torch.cuda.get_device_properties(0).total_memory
                config.gpu_memory_gb = gpu_memory_bytes / (1024**3)
                config._configure_for_gpu()
                return config

            torch_reason = "PyTorch installed but CUDA not available"
        except ImportError:
            torch_reason = "PyTorch not available for GPU detection"
        except Exception as e:
            torch_reason = f"PyTorch GPU detection error: {e}"

        try:
            import ctranslate2  # type: ignore[import-untyped]

            cuda_device_count = int(ctranslate2.get_cuda_device_count())
            if cuda_device_count > 0:
                config.has_gpu = True
                config.cuda_available = True

                nvidia_info = cls._detect_nvidia_gpu()
                if nvidia_info is not None:
                    config.gpu_name = str(nvidia_info["gpu_name"])
                    config.gpu_memory_gb = float(nvidia_info["gpu_memory_gb"])
                elif config.gpu_name is None:
                    suffix = "" if cuda_device_count == 1 else "s"
                    config.gpu_name = f"NVIDIA GPU ({cuda_device_count} device{suffix})"

                if config.gpu_memory_gb > 0:
                    config._configure_for_gpu()
                else:
                    config.model_size = "medium"
                    config.beam_size = 5
                    config.batch_size = 4
                    config.use_fp16 = True
                    config.enable_tensor_cores = False
                    config.recommendation = "local"

                if config.gpu_name and config.gpu_memory_gb > 0:
                    config.reason = (
                        f"GPU detected via CTranslate2 ({config.gpu_name}, "
                        f"{config.gpu_memory_gb:.1f}GB VRAM) - local faster-whisper transcription available"
                    )
                else:
                    config.reason = "GPU detected via CTranslate2 - local faster-whisper transcription available"
                return config

            ctranslate2_reason = "CTranslate2 CUDA backend reports no devices"
        except ImportError:
            ctranslate2_reason = "CTranslate2 not available for GPU detection"
        except Exception as e:
            ctranslate2_reason = f"CTranslate2 GPU detection error: {e}"

        config.reason = f"No local CUDA backend detected ({torch_reason}; {ctranslate2_reason})"

        return config

    @staticmethod
    def _detect_nvidia_gpu() -> dict[str, float | str] | None:
        """Detect GPU name and VRAM via nvidia-smi when PyTorch CUDA is unavailable."""
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None

        if result.returncode != 0 or not result.stdout.strip():
            return None

        first_gpu = result.stdout.strip().splitlines()[0]
        parts = [part.strip() for part in first_gpu.split(",", maxsplit=1)]
        if len(parts) != 2:
            return None

        try:
            memory_gb = float(parts[1]) / 1024
        except ValueError:
            return None

        return {
            "gpu_name": parts[0],
            "gpu_memory_gb": memory_gb,
        }

    @staticmethod
    def query_free_memory_gb() -> float | None:
        """Currently free VRAM on the first NVIDIA GPU via nvidia-smi, or None if unknown.

        Other processes (a local LLM server, games, other ML jobs) can hold most of a
        card. On Windows the driver then spills CUDA allocations into system RAM,
        which makes transcription dramatically slower rather than failing.
        """
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0 or not result.stdout.strip():
            return None
        try:
            return float(result.stdout.strip().splitlines()[0]) / 1024
        except ValueError:
            return None

    def _configure_for_gpu(self) -> None:
        """Configure optimal settings based on detected GPU."""
        if not self.gpu_name:
            return

        gpu_name_upper = self.gpu_name.upper()
        vram = self.gpu_memory_gb

        # High-memory accelerator
        if "RTX 4090" in gpu_name_upper or vram >= 22:
            self.model_size = "large-v3"
            self.beam_size = 5
            self.batch_size = 16
            self.use_fp16 = True
            self.enable_tensor_cores = True
            self.recommendation = "local"
            self.reason = f"High-end GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - optimal for local transcription"

        # Upper-mid memory accelerator
        elif "RTX 4080" in gpu_name_upper or (16 <= vram < 22):
            self.model_size = "large-v3"
            self.beam_size = 5
            self.batch_size = 12
            self.use_fp16 = True
            self.enable_tensor_cores = True
            self.recommendation = "local"
            self.reason = f"High-end GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - excellent for local transcription"

        # Mid-range accelerator with an explicitly recognized high-tier model
        elif "RTX 4070" in gpu_name_upper and "TI" in gpu_name_upper:
            self.model_size = "large-v3"
            self.beam_size = 5
            self.batch_size = 10
            self.use_fp16 = True
            self.enable_tensor_cores = True
            self.recommendation = "local"
            self.reason = (
                f"Mid-high GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - good for local transcription"
            )

        # General mid-range accelerator
        elif "RTX 40" in gpu_name_upper or (10 <= vram < 16):
            self.model_size = "large-v2"
            self.beam_size = 5
            self.batch_size = 8
            self.use_fp16 = True
            self.enable_tensor_cores = False
            self.recommendation = "local"
            self.reason = f"Mid-range GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - suitable for local transcription"

        # Older accelerator family with adequate memory
        elif "RTX 30" in gpu_name_upper or (8 <= vram < 10):
            self.model_size = "large-v2"
            self.beam_size = 5
            self.batch_size = 8
            self.use_fp16 = True
            self.enable_tensor_cores = True
            self.recommendation = "local"
            self.reason = f"RTX 30 series GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - good for local transcription"

        # Professional GPUs (Quadro, Tesla, A100, etc.)
        elif any(x in gpu_name_upper for x in ["QUADRO", "TESLA", "A100", "V100", "A40"]):
            self.model_size = "large-v3"
            self.beam_size = 5
            self.batch_size = 16
            self.use_fp16 = True
            self.enable_tensor_cores = True
            self.recommendation = "local"
            self.reason = f"Professional GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - excellent for local transcription"

        # Lower-end GPUs
        elif 6 <= vram < 8:
            self.model_size = "medium"
            self.beam_size = 5
            self.batch_size = 4
            self.use_fp16 = True
            self.enable_tensor_cores = False
            self.recommendation = "local"
            self.reason = f"Entry-level GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - can handle local transcription with smaller model"

        elif 4 <= vram < 6:
            self.model_size = "small"
            self.beam_size = 5
            self.batch_size = 4
            self.use_fp16 = True
            self.enable_tensor_cores = False
            self.recommendation = "local"
            self.reason = (
                f"Low VRAM GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - best-fit local model selected"
            )

        else:
            # Very low VRAM
            self.model_size = "base"
            self.beam_size = 5
            self.batch_size = 2
            self.use_fp16 = False
            self.enable_tensor_cores = False
            self.recommendation = "local" if self.has_gpu else "openai"
            if self.has_gpu:
                self.reason = f"Very low VRAM GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - using smallest local model"
            else:
                self.reason = f"Insufficient VRAM ({vram:.1f}GB) - OpenAI API recommended"

    def to_dict(self) -> dict[str, Any]:
        """
        Convert GPU config to dictionary.

        Returns:
            Dictionary representation
        """
        return {
            "has_gpu": self.has_gpu,
            "gpu_name": self.gpu_name,
            "gpu_memory_gb": self.gpu_memory_gb,
            "cuda_available": self.cuda_available,
            "cuda_version": self.cuda_version,
            "model_size": self.model_size,
            "beam_size": self.beam_size,
            "batch_size": self.batch_size,
            "use_fp16": self.use_fp16,
            "enable_tensor_cores": self.enable_tensor_cores,
            "recommendation": self.recommendation,
            "reason": self.reason,
        }

    def get_expected_speed(self) -> str:
        """
        Get expected transcription speed description.

        Returns:
            Approximate tier label for display; actual speed is workload-dependent
        """
        if not self.has_gpu:
            return "hardware-dependent (CPU)"

        if self.model_size in ("large-v3", "large-v3-turbo", "turbo"):
            if self.beam_size >= 10:
                return "8-12x real-time"
            elif self.beam_size >= 8:
                return "6-10x real-time"
            else:
                return "4-6x real-time"
        elif self.model_size == "large-v2":
            return "5-8x real-time"
        elif self.model_size == "medium":
            return "10-15x real-time"
        else:
            return "15-20x real-time"

    def is_high_end(self) -> bool:
        """
        Check if this is a high-end GPU.

        Returns:
            True if the GPU belongs to a recognized high-end tier
        """
        if not self.gpu_name:
            return False

        gpu_upper = self.gpu_name.upper()

        return (
            "RTX 4090" in gpu_upper
            or "RTX 4080" in gpu_upper
            or "A100" in gpu_upper
            or "V100" in gpu_upper
            or self.gpu_memory_gb >= 20
        )
