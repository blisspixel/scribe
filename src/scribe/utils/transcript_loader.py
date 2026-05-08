"""
Transcript loading helpers for text-based downstream commands.
"""

from __future__ import annotations

from pathlib import Path

from docx import Document

SUPPORTED_TRANSCRIPT_EXTENSIONS = {".txt", ".md", ".docx"}


def is_supported_transcript_file(path: Path) -> bool:
    """Return True if transcript extension is supported."""
    return path.suffix.lower() in SUPPORTED_TRANSCRIPT_EXTENSIONS


def _read_text_with_fallback(path: Path) -> str:
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except Exception:
            continue
    raise ValueError(f"Failed to decode text transcript: {path}")


def _read_docx(path: Path) -> str:
    try:
        doc = Document(str(path))
    except Exception as e:
        raise ValueError(f"Failed to read DOCX transcript: {e}") from e

    return "\n".join(paragraph.text for paragraph in doc.paragraphs)


def load_transcript_text(path: Path) -> str:
    """Load transcript text from .txt, .md, or .docx."""
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return _read_text_with_fallback(path)
    if suffix == ".docx":
        return _read_docx(path)

    supported = ", ".join(sorted(SUPPORTED_TRANSCRIPT_EXTENSIONS))
    raise ValueError(f"Unsupported transcript format: {suffix}. Supported: {supported}")
