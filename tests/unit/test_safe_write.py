"""
Unit tests for safe file writing utilities.

Tests atomic writes, safe copies, and backup functionality.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from scribe.utils.safe_write import (
    atomic_write,
    atomic_write_json,
    backup_file,
    safe_copy,
    safe_write_context,
)


class TestAtomicWrite:
    """Test atomic file writing."""

    def test_atomic_write_text(self, tmp_path):
        """Test atomic write with text content."""
        target = tmp_path / "test.txt"
        content = "Hello, World!"

        result = atomic_write(target, content)

        assert result == target
        assert target.exists()
        assert target.read_text() == content

    def test_atomic_write_binary(self, tmp_path):
        """Test atomic write with binary content."""
        target = tmp_path / "test.bin"
        content = b"Binary data"

        result = atomic_write(target, content, mode="wb")

        assert result == target
        assert target.exists()
        assert target.read_bytes() == content

    def test_atomic_write_creates_parent_dirs(self, tmp_path):
        """Test that parent directories are created."""
        target = tmp_path / "subdir" / "nested" / "test.txt"
        content = "Test"

        result = atomic_write(target, content)

        assert result == target
        assert target.exists()
        assert target.read_text() == content

    def test_atomic_write_overwrites_existing(self, tmp_path):
        """Test that existing files are overwritten."""
        target = tmp_path / "test.txt"
        target.write_text("Old content")

        new_content = "New content"
        atomic_write(target, new_content)

        assert target.read_text() == new_content

    def test_atomic_write_no_temp_files_left(self, tmp_path):
        """Test that no temporary files are left behind."""
        target = tmp_path / "test.txt"
        atomic_write(target, "Content")

        # Check for any .tmp files
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0

    def test_atomic_write_with_encoding(self, tmp_path):
        """Test atomic write with specific encoding."""
        target = tmp_path / "test.txt"
        content = "Hello 世界"  # Unicode content

        atomic_write(target, content, encoding="utf-8")

        assert target.read_text(encoding="utf-8") == content


class TestAtomicWriteJSON:
    """Test atomic JSON writing."""

    def test_atomic_write_json(self, tmp_path):
        """Test writing JSON data atomically."""
        target = tmp_path / "data.json"
        data = {"key": "value", "number": 42, "list": [1, 2, 3]}

        result = atomic_write_json(target, data)

        assert result == target
        assert target.exists()

        import json

        loaded = json.loads(target.read_text())
        assert loaded == data

    def test_atomic_write_json_with_unicode(self, tmp_path):
        """Test JSON writing with Unicode characters."""
        target = tmp_path / "data.json"
        data = {"message": "Hello 世界", "emoji": "🎉"}

        atomic_write_json(target, data)

        import json

        loaded = json.loads(target.read_text(encoding="utf-8"))
        assert loaded == data


class TestSafeWriteContext:
    """Test safe write context manager."""

    def test_safe_write_context_text(self, tmp_path):
        """Test context manager with text mode."""
        target = tmp_path / "test.txt"

        with safe_write_context(target) as f:
            f.write("Line 1\n")
            f.write("Line 2\n")

        assert target.exists()
        assert target.read_text() == "Line 1\nLine 2\n"

    def test_safe_write_context_binary(self, tmp_path):
        """Test context manager with binary mode."""
        target = tmp_path / "test.bin"

        with safe_write_context(target, mode="wb") as f:
            f.write(b"Binary")
            f.write(b" data")

        assert target.exists()
        assert target.read_bytes() == b"Binary data"

    def test_safe_write_context_creates_dirs(self, tmp_path):
        """Test that context manager creates parent directories."""
        target = tmp_path / "subdir" / "test.txt"

        with safe_write_context(target) as f:
            f.write("Content")

        assert target.exists()

    def test_safe_write_context_cleans_up_on_error(self, tmp_path):
        """Test that temp files are cleaned up on error."""
        target = tmp_path / "test.txt"

        with pytest.raises(ValueError), safe_write_context(target) as f:
            f.write("Partial")
            raise ValueError("Simulated error")

        # Target should not exist
        assert not target.exists()

        # No temp files should remain
        temp_files = list(tmp_path.glob("*.tmp"))
        assert len(temp_files) == 0


class TestAtomicWriteChaos:
    """Fault-injection tests: originals must survive failed writes."""

    def test_write_failure_preserves_original_content(self, tmp_path) -> None:
        target = tmp_path / "transcript.txt"
        target.write_text("original transcript", encoding="utf-8")

        with patch("os.fdopen", side_effect=OSError("simulated disk full")):
            with pytest.raises(OSError, match="Failed to write file"):
                atomic_write(target, "partial new content")

        assert target.read_text(encoding="utf-8") == "original transcript"
        assert list(tmp_path.glob(".*.tmp")) == []

    def test_rename_failure_preserves_original_on_posix(self, tmp_path) -> None:
        if os.name == "nt":
            pytest.skip("Windows removes the target before rename")

        target = tmp_path / "transcript.txt"
        target.write_text("keep this", encoding="utf-8")

        with patch.object(Path, "rename", side_effect=OSError("simulated rename failure")):
            with pytest.raises(OSError):
                atomic_write(target, "should not land")

        assert target.read_text(encoding="utf-8") == "keep this"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_context_manager_failure_preserves_existing_file(self, tmp_path) -> None:
        target = tmp_path / "transcript.txt"
        target.write_text("stable original", encoding="utf-8")

        with pytest.raises(RuntimeError, match="boom"):
            with safe_write_context(target) as handle:
                handle.write("partial")
                raise RuntimeError("boom")

        assert target.read_text(encoding="utf-8") == "stable original"
        assert list(tmp_path.glob("*.tmp")) == []

    def test_atomic_write_json_chaos_preserves_original(self, tmp_path) -> None:
        target = tmp_path / "transcript.json"
        target.write_text('{"version": 1}', encoding="utf-8")

        with patch("os.fdopen", side_effect=OSError("json write failed")):
            with pytest.raises(OSError):
                atomic_write_json(target, {"version": 2})

        assert target.read_text(encoding="utf-8") == '{"version": 1}'


class TestSafeCopy:
    """Test safe file copying."""

    def test_safe_copy(self, tmp_path):
        """Test safe copy operation."""
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"

        src.write_text("Content to copy")

        result = safe_copy(src, dst)

        assert result == dst
        assert dst.exists()
        assert dst.read_text() == "Content to copy"

    def test_safe_copy_preserves_metadata(self, tmp_path):
        """Test that file metadata is preserved."""
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"

        src.write_text("Content")
        original_mtime = src.stat().st_mtime

        safe_copy(src, dst)

        # Modification time should be preserved
        assert abs(dst.stat().st_mtime - original_mtime) < 1

    def test_safe_copy_creates_parent_dirs(self, tmp_path):
        """Test that parent directories are created."""
        src = tmp_path / "source.txt"
        dst = tmp_path / "subdir" / "dest.txt"

        src.write_text("Content")

        safe_copy(src, dst)

        assert dst.exists()
        assert dst.read_text() == "Content"

    def test_safe_copy_overwrites_existing(self, tmp_path):
        """Test that existing destination is overwritten."""
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"

        src.write_text("New content")
        dst.write_text("Old content")

        safe_copy(src, dst)

        assert dst.read_text() == "New content"

    def test_safe_copy_nonexistent_source(self, tmp_path):
        """Test error when source doesn't exist."""
        src = tmp_path / "nonexistent.txt"
        dst = tmp_path / "dest.txt"

        with pytest.raises(FileNotFoundError):
            safe_copy(src, dst)


class TestBackupFile:
    """Test file backup functionality."""

    def test_backup_file(self, tmp_path):
        """Test creating a backup."""
        original = tmp_path / "file.txt"
        original.write_text("Original content")

        backup = backup_file(original)

        assert backup is not None
        assert backup.exists()
        assert backup.name == "file.txt.bak"
        assert backup.read_text() == "Original content"

    def test_backup_file_custom_suffix(self, tmp_path):
        """Test backup with custom suffix."""
        original = tmp_path / "file.txt"
        original.write_text("Content")

        backup = backup_file(original, suffix=".backup")

        assert backup is not None
        assert backup.name == "file.txt.backup"

    def test_backup_file_multiple_backups(self, tmp_path):
        """Test creating multiple backups with numbering."""
        original = tmp_path / "file.txt"
        original.write_text("Content 1")

        backup1 = backup_file(original)

        original.write_text("Content 2")
        backup2 = backup_file(original)

        original.write_text("Content 3")
        backup3 = backup_file(original)

        assert backup1.name == "file.txt.bak"
        assert backup2.name == "file.txt.bak.1"
        assert backup3.name == "file.txt.bak.2"

        assert backup1.read_text() == "Content 1"
        assert backup2.read_text() == "Content 2"
        assert backup3.read_text() == "Content 3"

    def test_backup_nonexistent_file(self, tmp_path):
        """Test backup of nonexistent file returns None."""
        nonexistent = tmp_path / "nonexistent.txt"

        backup = backup_file(nonexistent)

        assert backup is None


class TestIntegration:
    """Integration tests for safe write utilities."""

    def test_write_modify_backup_workflow(self, tmp_path):
        """Test a complete write-modify-backup workflow."""
        target = tmp_path / "document.txt"

        # Initial write
        atomic_write(target, "Version 1")
        assert target.read_text() == "Version 1"

        # Create backup before modifying
        backup = backup_file(target)
        assert backup.read_text() == "Version 1"

        # Modify
        atomic_write(target, "Version 2")
        assert target.read_text() == "Version 2"
        assert backup.read_text() == "Version 1"

    def test_concurrent_writes_different_files(self, tmp_path):
        """Test that concurrent writes to different files work."""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"

        atomic_write(file1, "Content 1")
        atomic_write(file2, "Content 2")

        assert file1.read_text() == "Content 1"
        assert file2.read_text() == "Content 2"
