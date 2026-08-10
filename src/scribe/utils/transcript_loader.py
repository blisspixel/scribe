"""
Transcript loading helpers for text-based downstream commands.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

SUPPORTED_TRANSCRIPT_EXTENSIONS = {".txt", ".md", ".docx"}
MAX_TRANSCRIPT_BYTES = 50 * 1024 * 1024
MAX_DOCX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_DOCX_ENTRY_BYTES = 25 * 1024 * 1024
MAX_DOCX_ENTRIES = 2_048
MAX_DOCX_COMPRESSION_RATIO = 100
MAX_TRANSCRIPT_CHARS = 50_000_000


def is_supported_transcript_file(path: Path) -> bool:
    """Return True if transcript extension is supported."""
    return path.suffix.lower() in SUPPORTED_TRANSCRIPT_EXTENSIONS


def _read_text_with_fallback(path: Path) -> str:
    if path.stat().st_size > MAX_TRANSCRIPT_BYTES:
        raise ValueError("Text transcript exceeds the 50 MB input limit")
    with path.open("rb") as stream:
        data = stream.read(MAX_TRANSCRIPT_BYTES + 1)
    if len(data) > MAX_TRANSCRIPT_BYTES:
        raise ValueError("Text transcript exceeds the 50 MB input limit")
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            text = data.decode(encoding)
            if len(text) > MAX_TRANSCRIPT_CHARS:
                raise ValueError("Decoded transcript exceeds the character limit")
            return text
        except UnicodeError:
            continue
    raise ValueError(f"Failed to decode text transcript: {path}")


def _validate_docx_archive(path: Path) -> None:
    """Reject oversized, encrypted, or suspicious DOCX archives before parsing."""
    if path.stat().st_size > MAX_TRANSCRIPT_BYTES:
        raise ValueError("DOCX transcript exceeds the 50 MB input limit")
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_DOCX_ENTRIES:
                raise ValueError("DOCX transcript contains too many archive entries")
            expanded_total = 0
            for entry in entries:
                if entry.flag_bits & 0x1:
                    raise ValueError("Encrypted DOCX transcripts are not supported")
                if entry.file_size > MAX_DOCX_ENTRY_BYTES:
                    raise ValueError("DOCX transcript contains an oversized entry")
                expanded_total += entry.file_size
                if expanded_total > MAX_DOCX_EXPANDED_BYTES:
                    raise ValueError("DOCX transcript expands beyond the safety limit")
                if entry.file_size and (
                    entry.compress_size == 0
                    or entry.file_size / entry.compress_size > MAX_DOCX_COMPRESSION_RATIO
                ):
                    raise ValueError("DOCX transcript has a suspicious compression ratio")
    except zipfile.BadZipFile as error:
        raise ValueError("DOCX transcript is not a valid ZIP package") from error


def _read_docx(path: Path) -> str:
    # Imported lazily so .txt/.md loading never depends on python-docx being present.
    from docx import Document

    _validate_docx_archive(path)
    try:
        doc = Document(str(path))
    except Exception as e:
        raise ValueError(f"Failed to read DOCX transcript: {e}") from e

    paragraphs: list[str] = []
    character_count = 0
    for paragraph in doc.paragraphs:
        character_count += len(paragraph.text) + 1
        if character_count > MAX_TRANSCRIPT_CHARS:
            raise ValueError("DOCX transcript exceeds the character limit")
        paragraphs.append(paragraph.text)
    return "\n".join(paragraphs)


def load_transcript_text(path: Path) -> str:
    """Load transcript text from .txt, .md, or .docx."""
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return _read_text_with_fallback(path)
    if suffix == ".docx":
        return _read_docx(path)

    supported = ", ".join(sorted(SUPPORTED_TRANSCRIPT_EXTENSIONS))
    raise ValueError(f"Unsupported transcript format: {suffix}. Supported: {supported}")
