"""
Scribe: Professional GPU-accelerated speech-to-text transcription system.

A production-grade transcription system optimized for NVIDIA RTX GPUs with
automatic fallback to OpenAI API. Features include speaker diarization,
silence detection, multiple output formats, and beautiful terminal progress tracking.

Author: blissplixel
License: MIT
"""

__version__ = "2.4.3"
__author__ = "Nick Seal"
__license__ = "MIT"

from scribe.exceptions import (
    FileOperationError,
    ProcessError,
    ScribeError,
    TranscriptionError,
    ValidationError,
)

__all__ = [
    "FileOperationError",
    "ProcessError",
    "ScribeError",
    "TranscriptionError",
    "ValidationError",
    "__author__",
    "__license__",
    "__version__",
]
