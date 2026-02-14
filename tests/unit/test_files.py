"""
Unit tests for file operation utilities.

Tests safe file operations, cleanup, verification, and date extraction.
"""

import time
from pathlib import Path

import pytest

from scribe.exceptions import FileOperationError
from scribe.utils.files import (
    cleanup_files,
    copy_file_safe,
    ensure_directory,
    extract_date_from_filename,
    find_latest_file,
    format_date,
    format_duration_minutes,
    get_file_info,
    get_file_size_mb,
    move_file_safe,
    safe_path,
    verify_file_content,
    wait_for_file_stable,
)


class TestSafePath:
    """Test path sanitization and validation."""

    def test_safe_path_basic(self, tmp_path):
        """Test basic path sanitization."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        result = safe_path(str(test_file))

        assert isinstance(result, Path)
        assert result.is_absolute()

    def test_safe_path_with_quotes(self, tmp_path):
        """Test path with quotes."""
        test_file = tmp_path / "test.txt"
        test_file.touch()

        # Path with quotes
        quoted_path = f'"{test_file}"'
        result = safe_path(quoted_path)

        assert result.is_absolute()

    def test_safe_path_empty(self):
        """Test empty path raises error."""
        with pytest.raises(FileOperationError, match="cannot be empty"):
            safe_path("")

    def test_safe_path_whitespace_only(self):
        """Test whitespace-only path raises error."""
        with pytest.raises(FileOperationError, match="cannot be empty"):
            safe_path("   ")


class TestEnsureDirectory:
    """Test directory creation."""

    def test_ensure_directory_creates_new(self, tmp_path):
        """Test creating new directory."""
        new_dir = tmp_path / "new_directory"

        result = ensure_directory(new_dir)

        assert result.exists()
        assert result.is_dir()

    def test_ensure_directory_existing(self, tmp_path):
        """Test with existing directory."""
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()

        result = ensure_directory(existing_dir)

        assert result.exists()
        assert result.is_dir()

    def test_ensure_directory_nested(self, tmp_path):
        """Test creating nested directories."""
        nested_dir = tmp_path / "level1" / "level2" / "level3"

        result = ensure_directory(nested_dir)

        assert result.exists()
        assert result.is_dir()


class TestCleanupFiles:
    """Test file cleanup functionality."""

    def test_cleanup_files_basic(self, tmp_path):
        """Test basic file cleanup."""
        # Create test files
        (tmp_path / "file1.tmp").touch()
        (tmp_path / "file2.tmp").touch()
        (tmp_path / "keep.txt").touch()

        deleted = cleanup_files(tmp_path, ["*.tmp"])

        assert len(deleted) == 2
        assert not (tmp_path / "file1.tmp").exists()
        assert not (tmp_path / "file2.tmp").exists()
        assert (tmp_path / "keep.txt").exists()

    def test_cleanup_files_with_keep_patterns(self, tmp_path):
        """Test cleanup with keep patterns."""
        (tmp_path / "temp1.tmp").touch()
        (tmp_path / "temp2_final.tmp").touch()
        (tmp_path / "temp3.tmp").touch()

        deleted = cleanup_files(
            tmp_path,
            ["*.tmp"],
            keep_patterns=["*_final.*"]
        )

        assert len(deleted) == 2
        assert (tmp_path / "temp2_final.tmp").exists()

    def test_cleanup_files_dry_run(self, tmp_path):
        """Test cleanup in dry run mode."""
        (tmp_path / "file1.tmp").touch()
        (tmp_path / "file2.tmp").touch()

        deleted = cleanup_files(tmp_path, ["*.tmp"], dry_run=True)

        assert len(deleted) == 2
        # Files should still exist
        assert (tmp_path / "file1.tmp").exists()
        assert (tmp_path / "file2.tmp").exists()

    def test_cleanup_files_nonexistent_directory(self, tmp_path):
        """Test cleanup with nonexistent directory."""
        nonexistent = tmp_path / "nonexistent"

        deleted = cleanup_files(nonexistent, ["*.tmp"])

        assert len(deleted) == 0

    def test_cleanup_files_multiple_patterns(self, tmp_path):
        """Test cleanup with multiple patterns."""
        (tmp_path / "file1.tmp").touch()
        (tmp_path / "file2.log").touch()
        (tmp_path / "file3.txt").touch()

        deleted = cleanup_files(tmp_path, ["*.tmp", "*.log"])

        assert len(deleted) == 2
        assert (tmp_path / "file3.txt").exists()


class TestVerifyFileContent:
    """Test file content verification."""

    def test_verify_file_content_valid(self, tmp_path):
        """Test verifying valid file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("x" * 200)

        result = verify_file_content(test_file, min_size=100)

        assert result is True

    def test_verify_file_content_too_small(self, tmp_path):
        """Test file that's too small."""
        test_file = tmp_path / "small.txt"
        test_file.write_text("small")

        with pytest.raises(FileOperationError, match="too small"):
            verify_file_content(test_file, min_size=100)

    def test_verify_file_content_nonexistent(self, tmp_path):
        """Test nonexistent file."""
        nonexistent = tmp_path / "nonexistent.txt"

        with pytest.raises(FileOperationError, match="does not exist"):
            verify_file_content(nonexistent)

    def test_verify_file_content_directory(self, tmp_path):
        """Test with directory instead of file."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        with pytest.raises(FileOperationError, match="not a file"):
            verify_file_content(test_dir)


class TestDateExtraction:
    """Test date extraction from filenames."""

    def test_extract_date_standard_format(self):
        """Test extracting date in YYYY-MM-DD format."""
        filename = "Meeting_2025-11-06_15-31-40.mp4"

        result = extract_date_from_filename(filename)

        assert result == "2025-11-06"

    def test_extract_date_compact_format(self):
        """Test extracting date in YYYYMMDD format."""
        filename = "recording_20251106_153140.wav"

        result = extract_date_from_filename(filename)

        assert result == "2025-11-06"

    def test_extract_date_no_date(self):
        """Test filename without date."""
        filename = "meeting_notes.txt"

        result = extract_date_from_filename(filename)

        assert result is None

    def test_extract_date_multiple_dates(self):
        """Test filename with multiple dates (returns first)."""
        filename = "2025-11-06_backup_2025-11-07.txt"

        result = extract_date_from_filename(filename)

        assert result == "2025-11-06"


class TestFormatDate:
    """Test date formatting."""

    def test_format_date_valid(self):
        """Test formatting valid date."""
        result = format_date("2025-11-06")

        assert result == "November 06, 2025"

    def test_format_date_invalid(self):
        """Test formatting invalid date returns original."""
        invalid_date = "not-a-date"

        result = format_date(invalid_date)

        assert result == invalid_date


class TestFormatDuration:
    """Test duration formatting."""

    def test_format_duration_minutes_only(self):
        """Test formatting duration under 1 hour."""
        result = format_duration_minutes(3480)  # 58 minutes

        assert "58 minute" in result
        assert "hour" not in result

    def test_format_duration_hours_and_minutes(self):
        """Test formatting duration with hours and minutes."""
        result = format_duration_minutes(8100)  # 2 hours 15 minutes

        assert "2 hour" in result
        assert "15 minute" in result

    def test_format_duration_hours_only(self):
        """Test formatting exact hours."""
        result = format_duration_minutes(7200)  # 2 hours

        assert "2 hour" in result
        assert "0 minute" not in result

    def test_format_duration_singular(self):
        """Test singular forms."""
        result = format_duration_minutes(60)  # 1 minute

        assert "1 minute" in result
        assert "minutes" not in result


class TestFileSize:
    """Test file size utilities."""

    def test_get_file_size_mb(self, tmp_path):
        """Test getting file size in MB."""
        test_file = tmp_path / "test.bin"
        test_file.write_bytes(b"x" * (2 * 1024 * 1024))  # 2 MB

        result = get_file_size_mb(test_file)

        assert 1.9 < result < 2.1  # Allow for rounding

    def test_get_file_size_mb_nonexistent(self, tmp_path):
        """Test getting size of nonexistent file."""
        nonexistent = tmp_path / "nonexistent.txt"

        result = get_file_size_mb(nonexistent)

        assert result == 0.0


class TestFileInfo:
    """Test file information retrieval."""

    def test_get_file_info_valid(self, tmp_path):
        """Test getting info for valid file."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        info = get_file_info(test_file)

        assert info["name"] == "test.txt"
        assert info["size_bytes"] > 0
        assert info["is_file"] is True
        assert info["is_dir"] is False
        assert "created" in info
        assert "modified" in info

    def test_get_file_info_directory(self, tmp_path):
        """Test getting info for directory."""
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()

        info = get_file_info(test_dir)

        assert info["is_file"] is False
        assert info["is_dir"] is True

    def test_get_file_info_nonexistent(self, tmp_path):
        """Test getting info for nonexistent file."""
        nonexistent = tmp_path / "nonexistent.txt"

        info = get_file_info(nonexistent)

        assert "error" in info


class TestFindLatestFile:
    """Test finding latest file."""

    def test_find_latest_file_basic(self, tmp_path):
        """Test finding latest file."""
        file1 = tmp_path / "file1.txt"
        file1.write_text("content1")
        time.sleep(0.1)

        file2 = tmp_path / "file2.txt"
        file2.write_text("content2")

        result = find_latest_file(tmp_path, "*.txt")

        assert result == file2

    def test_find_latest_file_with_min_size(self, tmp_path):
        """Test finding latest file with minimum size."""
        file1 = tmp_path / "small.txt"
        file1.write_text("x")
        time.sleep(0.1)

        file2 = tmp_path / "large.txt"
        file2.write_text("x" * 1000)

        result = find_latest_file(tmp_path, "*.txt", min_size=100)

        assert result == file2

    def test_find_latest_file_no_match(self, tmp_path):
        """Test when no files match."""
        result = find_latest_file(tmp_path, "*.txt")

        assert result is None

    def test_find_latest_file_nonexistent_directory(self, tmp_path):
        """Test with nonexistent directory."""
        nonexistent = tmp_path / "nonexistent"

        result = find_latest_file(nonexistent, "*.txt")

        assert result is None


class TestWaitForFileStable:
    """Test waiting for file to stabilize."""

    def test_wait_for_file_stable_immediate(self, tmp_path):
        """Test file that's already stable."""
        test_file = tmp_path / "stable.txt"
        test_file.write_text("content")

        result = wait_for_file_stable(test_file, stable_duration=0.5, max_wait=5.0)

        assert result is True

    def test_wait_for_file_stable_timeout(self, tmp_path):
        """Test timeout when file doesn't exist."""
        nonexistent = tmp_path / "nonexistent.txt"

        result = wait_for_file_stable(nonexistent, stable_duration=0.5, max_wait=1.0)

        assert result is False


class TestCopyFileSafe:
    """Test safe file copying."""

    def test_copy_file_safe_basic(self, tmp_path):
        """Test basic file copy."""
        source = tmp_path / "source.txt"
        source.write_text("test content")

        dest = tmp_path / "dest.txt"

        result = copy_file_safe(source, dest)

        assert result == dest
        assert dest.exists()
        assert dest.read_text() == "test content"
        assert source.exists()  # Source should still exist

    def test_copy_file_safe_nonexistent_source(self, tmp_path):
        """Test copying nonexistent file."""
        source = tmp_path / "nonexistent.txt"
        dest = tmp_path / "dest.txt"

        with pytest.raises(FileOperationError, match="does not exist"):
            copy_file_safe(source, dest)

    def test_copy_file_safe_existing_dest_no_overwrite(self, tmp_path):
        """Test copying to existing file without overwrite."""
        source = tmp_path / "source.txt"
        source.write_text("source")

        dest = tmp_path / "dest.txt"
        dest.write_text("dest")

        with pytest.raises(FileOperationError, match="already exists"):
            copy_file_safe(source, dest, overwrite=False)

    def test_copy_file_safe_existing_dest_with_overwrite(self, tmp_path):
        """Test copying to existing file with overwrite."""
        source = tmp_path / "source.txt"
        source.write_text("new content")

        dest = tmp_path / "dest.txt"
        dest.write_text("old content")

        result = copy_file_safe(source, dest, overwrite=True)

        assert result == dest
        assert dest.read_text() == "new content"


class TestMoveFileSafe:
    """Test safe file moving."""

    def test_move_file_safe_basic(self, tmp_path):
        """Test basic file move."""
        source = tmp_path / "source.txt"
        source.write_text("test content")

        dest = tmp_path / "dest.txt"

        result = move_file_safe(source, dest)

        assert result == dest
        assert dest.exists()
        assert dest.read_text() == "test content"
        assert not source.exists()  # Source should be gone

    def test_move_file_safe_nonexistent_source(self, tmp_path):
        """Test moving nonexistent file."""
        source = tmp_path / "nonexistent.txt"
        dest = tmp_path / "dest.txt"

        with pytest.raises(FileOperationError, match="does not exist"):
            move_file_safe(source, dest)

    def test_move_file_safe_existing_dest_no_overwrite(self, tmp_path):
        """Test moving to existing file without overwrite."""
        source = tmp_path / "source.txt"
        source.write_text("source")

        dest = tmp_path / "dest.txt"
        dest.write_text("dest")

        with pytest.raises(FileOperationError, match="already exists"):
            move_file_safe(source, dest, overwrite=False)

    def test_move_file_safe_existing_dest_with_overwrite(self, tmp_path):
        """Test moving to existing file with overwrite."""
        source = tmp_path / "source.txt"
        source.write_text("new content")

        dest = tmp_path / "dest.txt"
        dest.write_text("old content")

        result = move_file_safe(source, dest, overwrite=True)

        assert result == dest
        assert dest.read_text() == "new content"
        assert not source.exists()


class TestIntegration:
    """Test integration scenarios."""

    def test_full_file_workflow(self, tmp_path):
        """Test complete file operation workflow."""
        # Create directory structure
        work_dir = tmp_path / "work"
        ensure_directory(work_dir)

        # Create test files
        source = work_dir / "source.txt"
        source.write_text("x" * 500)

        # Verify file
        assert verify_file_content(source, min_size=100)

        # Get file info
        info = get_file_info(source)
        assert info["size_bytes"] == 500

        # Copy file
        backup = work_dir / "backup.txt"
        copy_file_safe(source, backup)
        assert backup.exists()

        # Create temp files
        (work_dir / "temp1.tmp").touch()
        (work_dir / "temp2.tmp").touch()

        # Cleanup
        deleted = cleanup_files(work_dir, ["*.tmp"])
        assert len(deleted) == 2

        # Find latest file
        latest = find_latest_file(work_dir, "*.txt")
        assert latest in [source, backup]
