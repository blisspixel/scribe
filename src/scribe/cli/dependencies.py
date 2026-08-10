"""Lazy construction seams for heavyweight optional CLI dependencies.

Tests patch these names through ``scribe.cli.main`` for compatibility. Keeping
the imports behind functions prevents trivial commands such as ``--version``
from importing provider SDKs, OBS, and document-generation libraries.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scribe.core.recorder import OBSRecorder as OBSRecorderType
    from scribe.core.transcriber import Transcriber as TranscriberType
    from scribe.models.config import ScribeConfig as ScribeConfigType
    from scribe.models.gpu import GPUConfig as GPUConfigType
    from scribe.models.session import TranscriptionSession as TranscriptionSessionType
    from scribe.utils.joke_generator import HumorConfig


def Transcriber(*args: Any, **kwargs: Any) -> TranscriberType:
    """Construct the transcription service only when a command needs it."""
    from scribe.core.transcriber import Transcriber as TranscriberImplementation

    return TranscriberImplementation(*args, **kwargs)


def OBSRecorder(*args: Any, **kwargs: Any) -> OBSRecorderType:
    """Construct the OBS service only for commands that actually record."""
    from scribe.core.recorder import OBSRecorder as OBSRecorderImplementation

    return OBSRecorderImplementation(*args, **kwargs)


def ScribeConfig(*args: Any, **kwargs: Any) -> ScribeConfigType:
    """Load Pydantic settings only for commands that read configuration."""
    from scribe.models.config import ScribeConfig as ScribeConfigImplementation

    return ScribeConfigImplementation(*args, **kwargs)


class GPUConfig:
    """Lazy facade for the GPU detector used by the information command."""

    @staticmethod
    def detect() -> GPUConfigType:
        from scribe.models.gpu import GPUConfig as GPUConfigImplementation

        return GPUConfigImplementation.detect()


class TranscriptionSession:
    """Lazy facade for creating durable transcription sessions."""

    @staticmethod
    def create(*args: Any, **kwargs: Any) -> TranscriptionSessionType:
        from scribe.models.session import TranscriptionSession as SessionImplementation

        return SessionImplementation.create(*args, **kwargs)


def txt_to_docx(txt_path: Path, docx_path: Path | None = None, title: str | None = None) -> Path:
    """Load DOCX support only when a document output is requested."""
    from scribe.utils.docx_converter import txt_to_docx as convert

    return convert(txt_path, docx_path, title)


def generate_transcript_joke(
    transcript_path: str | Path,
    api_key_or_cfg: str | HumorConfig | None = None,
    provider_name: str | None = None,
) -> tuple[str, str] | None:
    """Load provider-backed humor support only when explicitly requested."""
    from scribe.utils.joke_generator import generate_transcript_joke as generate

    return generate(transcript_path, api_key_or_cfg, provider_name)
