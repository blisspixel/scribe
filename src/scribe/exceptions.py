"""
Custom exception hierarchy for Scribe transcription system.

This module defines a comprehensive exception hierarchy that provides
clear, actionable error messages with context for debugging and user feedback.
"""

from typing import Optional


class ScribeError(Exception):
    """
    Base exception for all Scribe-related errors.
    
    All custom exceptions in the Scribe system inherit from this base class,
    allowing for easy catching of any Scribe-specific error.
    
    Attributes:
        message: Human-readable error message
        context: Optional dictionary with additional error context
    """
    
    def __init__(self, message: str, context: Optional[dict] = None):
        """
        Initialize ScribeError with message and optional context.
        
        Args:
            message: Human-readable error description
            context: Optional dictionary with additional debugging information
        """
        self.message = message
        self.context = context or {}
        super().__init__(self.message)
    
    def __str__(self) -> str:
        """Return formatted error message with context."""
        if self.context:
            context_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            return f"{self.message} ({context_str})"
        return self.message


class ValidationError(ScribeError):
    """
    Configuration or environment validation failed.
    
    Raised when:
    - Required environment variables are missing
    - Configuration values are invalid
    - File paths don't exist or aren't accessible
    - Dependencies are missing or incompatible
    
    Example:
        raise ValidationError(
            "CUDA not available",
            context={"torch_version": "2.0.0", "cuda_available": False}
        )
    """
    pass


class ProcessError(ScribeError):
    """
    Subprocess execution failed.
    
    Raised when:
    - External process (ffmpeg, OBS) fails
    - Process times out
    - Process returns non-zero exit code
    - Process output indicates error
    
    Example:
        raise ProcessError(
            "FFmpeg conversion failed",
            context={"command": "ffmpeg -i input.mp4", "exit_code": 1}
        )
    """
    pass


class TranscriptionError(ScribeError):
    """
    Transcription process failed.
    
    Raised when:
    - GPU transcription fails (CUDA errors, OOM)
    - OpenAI API call fails
    - Model loading fails
    - Audio processing fails
    - All fallback methods exhausted
    
    Example:
        raise TranscriptionError(
            "GPU out of memory",
            context={"vram_used_gb": 22.5, "vram_total_gb": 24.0, "model": "large-v3"}
        )
    """
    pass


class FileOperationError(ScribeError):
    """
    File operation failed.
    
    Raised when:
    - File read/write fails
    - File doesn't exist
    - Insufficient permissions
    - Disk space exhausted
    - File corruption detected
    
    Example:
        raise FileOperationError(
            "Cannot write to output directory",
            context={"path": "/output", "error": "Permission denied"}
        )
    """
    pass


class CircuitBreakerOpen(ScribeError):
    """
    Circuit breaker is open due to repeated failures.
    
    Raised when:
    - Too many consecutive failures detected
    - System enters protective mode
    - Prevents cascading failures
    
    This is used in the circuit breaker pattern to prevent overwhelming
    external services (like OpenAI API) with requests when they're failing.
    
    Example:
        raise CircuitBreakerOpen(
            "Too many API failures, circuit open for 60 seconds",
            context={"failure_count": 5, "timeout_seconds": 60}
        )
    """
    pass


class ConversionError(ScribeError):
    """
    Audio/video conversion failed.
    
    Raised when:
    - FFmpeg conversion fails
    - Input file is invalid
    - Output path is not writable
    - Conversion process times out
    
    Example:
        raise ConversionError(
            "Failed to convert MP4 to WAV",
            context={"input": "video.mp4", "error": "Invalid codec"}
        )
    """
    pass


class AudioFormatError(ScribeError):
    """
    Audio file format is invalid or unsupported.
    
    Raised when:
    - Audio file is corrupted
    - Format is not supported
    - Audio has no valid stream
    - Sample rate or channels are invalid
    
    Example:
        raise AudioFormatError(
            "Unsupported audio format",
            context={"file": "audio.xyz", "format": "unknown"}
        )
    """
    pass


class GPUError(ScribeError):
    """
    GPU-related error occurred.
    
    Raised when:
    - CUDA initialization fails
    - GPU memory allocation fails
    - GPU driver issues detected
    - Incompatible GPU detected
    
    Example:
        raise GPUError(
            "CUDA out of memory",
            context={"requested_gb": 12, "available_gb": 8}
        )
    """
    pass


class APIError(ScribeError):
    """
    External API call failed.
    
    Raised when:
    - OpenAI API returns error
    - API authentication fails
    - Rate limit exceeded
    - Network connectivity issues
    
    Example:
        raise APIError(
            "OpenAI API rate limit exceeded",
            context={"status_code": 429, "retry_after": 60}
        )
    """
    pass
