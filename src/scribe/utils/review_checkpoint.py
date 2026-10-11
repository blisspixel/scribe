"""Resolve complete local verifier checkpoints before constructing an engine."""

from pathlib import Path

from scribe.exceptions import TranscriptionError


def resolve_cached_checkpoint(model: str) -> Path:
    """Require a local tokenizer too; the runtime's tokenizer fallback can download."""
    from faster_whisper.utils import download_model

    candidate = Path(model).expanduser()
    if not candidate.is_dir():
        candidate = Path(
            download_model("turbo" if model == "large-v3-turbo" else model, local_files_only=True)
        )
    required = ("model.bin", "config.json", "tokenizer.json")
    missing = [name for name in required if not (candidate / name).is_file()]
    if missing:
        raise TranscriptionError(
            "Cached verifier checkpoint is incomplete (missing "
            + ", ".join(missing)
            + "). Cache a complete faster-whisper checkpoint explicitly before retrying."
        )
    return candidate.resolve()
