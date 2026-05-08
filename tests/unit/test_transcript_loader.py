from pathlib import Path
from unittest.mock import patch

import pytest
from docx import Document

from scribe.utils.transcript_loader import (
    _read_docx,
    _read_text_with_fallback,
    is_supported_transcript_file,
    load_transcript_text,
)


def test_is_supported_transcript_file_checks_extensions():
    assert is_supported_transcript_file(Path("meeting.txt")) is True
    assert is_supported_transcript_file(Path("meeting.md")) is True
    assert is_supported_transcript_file(Path("meeting.docx")) is True
    assert is_supported_transcript_file(Path("meeting.pdf")) is False


def test_read_text_with_fallback_handles_utf8_and_utf16(tmp_path):
    utf8_path = tmp_path / "meeting.txt"
    utf8_path.write_text("hello world", encoding="utf-8")
    assert _read_text_with_fallback(utf8_path) == "hello world"

    utf16_path = tmp_path / "meeting-utf16.txt"
    utf16_path.write_text("hello utf16", encoding="utf-16")
    assert _read_text_with_fallback(utf16_path) == "hello utf16"


def test_read_text_with_fallback_raises_when_all_decoders_fail(tmp_path):
    transcript_path = tmp_path / "broken.txt"
    transcript_path.write_bytes(b"\xff\xfe\x00")

    with patch.object(
        Path, "read_text", side_effect=UnicodeDecodeError("utf-8", b"x", 0, 1, "bad")
    ):
        with pytest.raises(ValueError, match="Failed to decode text transcript"):
            _read_text_with_fallback(transcript_path)


def test_read_docx_and_load_transcript_text_support_text_markdown_and_docx(tmp_path):
    docx_path = tmp_path / "meeting.docx"
    document = Document()
    document.add_paragraph("First line")
    document.add_paragraph("Second line")
    document.save(str(docx_path))

    text_path = tmp_path / "meeting.txt"
    text_path.write_text("plain text", encoding="utf-8")
    markdown_path = tmp_path / "meeting.md"
    markdown_path.write_text("# heading", encoding="utf-8")

    assert _read_docx(docx_path) == "First line\nSecond line"
    assert load_transcript_text(text_path) == "plain text"
    assert load_transcript_text(markdown_path) == "# heading"
    assert load_transcript_text(docx_path) == "First line\nSecond line"


def test_read_docx_and_load_transcript_text_raise_clear_errors(tmp_path):
    broken_docx = tmp_path / "broken.docx"
    broken_docx.write_text("not really a docx", encoding="utf-8")

    with pytest.raises(ValueError, match="Failed to read DOCX transcript"):
        _read_docx(broken_docx)

    with pytest.raises(ValueError, match="Unsupported transcript format"):
        load_transcript_text(tmp_path / "meeting.rtf")
