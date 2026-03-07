"""
GPU configuration models with hardware-specific optimizations.

This module provides GPU detection and configuration with optimized
settings for different GPU models, especially RTX 4090.
"""

from dataclasses import dataclass
from typing import Any, Literal

from scribe.models.config import ModelSize


@dataclass
class GPUConfig:
    """
    GPU-specific configuration with optimized settings.

    This class stores GPU detection results and provides optimized
    transcription settings based on the detected hardware.

    Attributes:
        has_gpu: Whether a GPU was detected
        gpu_name: Name of the GPU (e.g., "NVIDIA GeForce RTX 4090")
        gpu_memory_gb: Total GPU memory in GB
        cuda_available: Whether CUDA is available
        cuda_version: CUDA version string
        model_size: Recommended Whisper model size
        beam_size: Recommended beam search size
        batch_size: Recommended batch size
        use_fp16: Whether to use FP16 precision
        enable_tensor_cores: Whether to enable Tensor Core acceleration
        recommendation: Recommended transcription method
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
        - Provides transcription method recommendation

        Returns:
            GPUConfig with detection results and optimized settings
        """
        config = cls(has_gpu=False)

        try:
            import torch

            if not torch.cuda.is_available():
                config.reason = "CUDA not available"
                return config

            # GPU detected
            config.has_gpu = True
            config.cuda_available = True
            config.cuda_version = torch.version.cuda

            # Get GPU details
            config.gpu_name = torch.cuda.get_device_name(0)
            gpu_memory_bytes = torch.cuda.get_device_properties(0).total_memory
            config.gpu_memory_gb = gpu_memory_bytes / (1024**3)

            # Configure based on GPU
            config._configure_for_gpu()

        except ImportError:
            config.reason = "PyTorch not available for GPU detection"
        except Exception as e:
            config.reason = f"GPU detection error: {e}"

        return config

    def _configure_for_gpu(self) -> None:
        """Configure optimal settings based on detected GPU."""
        if not self.gpu_name:
            return

        gpu_name_upper = self.gpu_name.upper()
        vram = self.gpu_memory_gb

        # RTX 4090 - Maximum quality
        if "RTX 4090" in gpu_name_upper or vram >= 22:
            self.model_size = "large-v3"
            self.beam_size = 10
            self.batch_size = 16
            self.use_fp16 = True
            self.enable_tensor_cores = True
            self.recommendation = "local"
            self.reason = f"High-end GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - optimal for local transcription"

        # RTX 4080 - High performance
        elif "RTX 4080" in gpu_name_upper or (16 <= vram < 22):
            self.model_size = "large-v3"
            self.beam_size = 8
            self.batch_size = 12
            self.use_fp16 = True
            self.enable_tensor_cores = True
            self.recommendation = "local"
            self.reason = f"High-end GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - excellent for local transcription"

        # RTX 4070 Ti / 4070 Ti Super - Good performance
        elif "RTX 4070" in gpu_name_upper and "TI" in gpu_name_upper:
            self.model_size = "large-v3"
            self.beam_size = 5
            self.batch_size = 10
            self.use_fp16 = True
            self.enable_tensor_cores = True
            self.recommendation = "local"
            self.reason = f"Mid-high GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - good for local transcription"

        # RTX 4070 / 4060 Ti - Balanced
        elif "RTX 40" in gpu_name_upper or (10 <= vram < 16):
            self.model_size = "large-v2"
            self.beam_size = 5
            self.batch_size = 8
            self.use_fp16 = True
            self.enable_tensor_cores = False
            self.recommendation = "local"
            self.reason = f"Mid-range GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - suitable for local transcription"

        # RTX 30 series - Good performance
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
            self.beam_size = 10
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
            self.recommendation = "openai"
            self.reason = f"Low VRAM GPU ({self.gpu_name}, {vram:.1f}GB VRAM) - OpenAI API recommended for quality"

        else:
            # Very low VRAM
            self.model_size = "base"
            self.beam_size = 5
            self.batch_size = 2
            self.use_fp16 = False
            self.enable_tensor_cores = False
            self.recommendation = "openai"
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
            Speed description (e.g., "8-12x real-time")
        """
        if not self.has_gpu or self.recommendation == "openai":
            return "1-2x real-time (API)"

        if self.model_size in ("large-v3", "large-v3-turbo"):
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
            True if high-end GPU (RTX 4090, A100, etc.)
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
