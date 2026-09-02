"""
Scribe: Local-first speech-to-text transcription system.

A transcription system with local CPU and GPU backends, explicit opt-in cloud
processing, speaker diarization, multiple output formats, and terminal progress.

Author: Nick Seal
License: Apache-2.0
"""

__version__ = "2.9.0"
__author__ = "Nick Seal"
__license__ = "Apache-2.0"

import contextlib as _contextlib
import warnings as _warnings

# pydub (a transitive dependency) emits SyntaxWarning on first import under Python
# 3.12+ because its regex literals use invalid escape sequences, and it imports the
# deprecated audioop module. These are compile-time warnings the import system
# raises before any module-scoped filter applies, so pre-import pydub once under a
# blanket suppression to absorb them. After this its bytecode is cached and it never
# warns again, keeping the CLI's first run clean for everyone.
with _warnings.catch_warnings(), _contextlib.suppress(Exception):
    _warnings.simplefilter("ignore")
    import pydub.utils as _pydub_utils

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
