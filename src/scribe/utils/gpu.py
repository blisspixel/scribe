"""
GPU detection and configuration utilities.

This module provides GPU detection with graceful handling when
PyTorch or CUDA are unavailable, and returns optimized settings
for different GPU models.
"""

from typing import Any

from scribe.models.gpu import GPUConfig


def detect_gpu_capability() -> dict[str, Any]:
    """
    Comprehensive GPU detection and capability assessment.
    
    This function wraps GPUConfig.detect() and returns a dictionary
    for backward compatibility with existing code.
    
    Returns:
        Dict with GPU info: has_gpu, gpu_name, gpu_memory_gb,
        cuda_available, recommendation, reason
    """
    gpu_config = GPUConfig.detect()
    return gpu_config.to_dict()


def configure_gpu_optimizations(gpu_info: dict[str, Any]) -> dict[str, Any]:
    """
    Configure optimal settings for detected GPU.
    
    Args:
        gpu_info: GPU detection results from detect_gpu_capability()
        
    Returns:
        Dict with optimal settings: model_size, beam_size,
        batch_size, use_fp16, enable_tensor_cores
    """
    return {
        "model_size": gpu_info.get("model_size", "base"),
        "beam_size": gpu_info.get("beam_size", 5),
        "batch_size": gpu_info.get("batch_size", 8),
        "use_fp16": gpu_info.get("use_fp16", False),
        "enable_tensor_cores": gpu_info.get("enable_tensor_cores", False),
    }


def is_high_end_gpu(gpu_name: str, vram_gb: float) -> bool:
    """
    Check if GPU is high-end (RTX 4090, A100, etc.).
    
    Args:
        gpu_name: Name of the GPU
        vram_gb: GPU memory in GB
        
    Returns:
        True if high-end GPU
    """
    if not gpu_name:
        return False

    gpu_upper = gpu_name.upper()

    return (
        "RTX 4090" in gpu_upper
        or "RTX 4080" in gpu_upper
        or "A100" in gpu_upper
        or "V100" in gpu_upper
        or "A40" in gpu_upper
        or vram_gb >= 20
    )


def check_cuda_available() -> bool:
    """
    Check if CUDA is available.
    
    Returns:
        True if CUDA is available
    """
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def get_cuda_version() -> str:
    """
    Get CUDA version string.
    
    Returns:
        CUDA version or "Not available"
    """
    try:
        import torch
        if torch.cuda.is_available():
            return torch.version.cuda or "Unknown"
    except ImportError:
        pass

    return "Not available"


def get_gpu_memory_info() -> dict[str, float]:
    """
    Get GPU memory information.
    
    Returns:
        Dict with total_gb, used_gb, free_gb
    """
    info = {
        "total_gb": 0.0,
        "used_gb": 0.0,
        "free_gb": 0.0,
    }

    try:
        import torch
        if torch.cuda.is_available():
            total = torch.cuda.get_device_properties(0).total_memory
            allocated = torch.cuda.memory_allocated(0)

            info["total_gb"] = total / (1024**3)
            info["used_gb"] = allocated / (1024**3)
            info["free_gb"] = (total - allocated) / (1024**3)
    except Exception:
        pass

    return info


def clear_gpu_cache() -> None:
    """Clear GPU memory cache."""
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
    except Exception:
        pass


def set_gpu_optimizations(enable_tensor_cores: bool = True) -> None:
    """
    Set GPU optimizations for transcription.
    
    Args:
        enable_tensor_cores: Whether to enable Tensor Core acceleration
    """
    try:
        import torch

        if torch.cuda.is_available():
            # Set matrix multiplication precision for Tensor Cores
            if enable_tensor_cores:
                torch.set_float32_matmul_precision("high")

            # Note: cuDNN benchmark can cause issues in some environments
            # torch.backends.cudnn.benchmark = True

    except Exception:
        pass
