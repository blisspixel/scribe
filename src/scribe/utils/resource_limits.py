"""
Resource limit validation to prevent OOM and runaway processes.

This module provides validation functions to ensure audio files
are within acceptable limits before processing.
"""

from pathlib import Path

from scribe.exceptions import ValidationError
from scribe.utils.audio import get_audio_duration
from scribe.utils.logging import get_logger

logger = get_logger(__name__)


def validate_file_size(file_path: Path, max_size_gb: float = 25.0) -> None:
    """
    Validate file size is within limits.

    Args:
        file_path: Path to file
        max_size_gb: Maximum allowed size in GB

    Raises:
        ValidationError: If file exceeds size limit
    """
    if not file_path.exists():
        raise ValidationError(f"File not found: {file_path}", context={"file_path": str(file_path)})

    size_bytes = file_path.stat().st_size
    size_gb = size_bytes / (1024**3)

    if size_gb > max_size_gb:
        raise ValidationError(
            f"File too large: {size_gb:.2f}GB (limit: {max_size_gb:.1f}GB)",
            context={"file_path": str(file_path), "size_gb": size_gb, "limit_gb": max_size_gb},
        )

    logger.debug(f"File size OK: {size_gb:.2f}GB / {max_size_gb:.1f}GB")


def validate_audio_duration(file_path: Path, max_duration_hours: float = 12.0) -> float | None:
    """
    Validate audio duration is within limits.

    Args:
        file_path: Path to audio file
        max_duration_hours: Maximum allowed duration in hours

    Returns:
        Duration in seconds, or None if duration cannot be determined

    Raises:
        ValidationError: If audio exceeds duration limit
    """
    duration_seconds = get_audio_duration(file_path)

    if duration_seconds is None:
        logger.warning(f"Could not determine duration for: {file_path.name}")
        return None

    duration_hours = duration_seconds / 3600

    if duration_hours > max_duration_hours:
        raise ValidationError(
            f"Audio too long: {duration_hours:.1f}h (limit: {max_duration_hours:.1f}h)",
            context={
                "file_path": str(file_path),
                "duration_hours": duration_hours,
                "limit_hours": max_duration_hours,
            },
        )

    logger.debug(f"Audio duration OK: {duration_hours:.2f}h / {max_duration_hours:.1f}h")
    return duration_seconds


def validate_audio_file(
    file_path: Path, max_size_gb: float = 25.0, max_duration_hours: float = 12.0
) -> float | None:
    """
    Validate audio file meets all resource limits.

    Args:
        file_path: Path to audio file
        max_size_gb: Maximum file size in GB
        max_duration_hours: Maximum duration in hours

    Returns:
        Duration in seconds, or None if duration cannot be determined

    Raises:
        ValidationError: If file exceeds any limit
    """
    # Validate file size
    validate_file_size(file_path, max_size_gb)

    # Validate duration
    duration = validate_audio_duration(file_path, max_duration_hours)

    logger.info(f"Resource validation passed: {file_path.name}")
    return duration
