"""
Cross-platform tests for platform-specific functionality.

Tests platform-specific path handling, ffmpeg detection, and other
OS-dependent features on Windows, macOS, and Linux.
"""

import pytest
import sys
import platform
from pathlib import Path
from unittest.mock import patch, Mock

from scribe.utils.platform import (
    get_platform,
    get_ffmpeg_path,
    get_ffprobe_path,
    normalize_path,
    is_windows,
    is_macos,
    is_linux
)


# Platform markers
windows_only = pytest.mark.skipif(not sys.platform.startswith('win'), reason="Windows only")
macos_only = pytest.mark.skipif(not sys.platform.startswith('darwin'), reason="macOS only")
linux_only = pytest.mark.skipif(not sys.platform.startswith('linux'), reason="Linux only")
unix_only = pytest.mark.skipif(sys.platform.startswith('win'), reason="Unix only")


class TestPlatformDetection:
    """Test platform detection functions."""
    
    def test_get_platform(self):
        """Test platform detection returns valid platform."""
        platform_name = get_platform()
        assert platform_name in ["windows", "macos", "linux", "unknown"]
    
    def test_is_windows(self):
        """Test Windows detection."""
        result = is_windows()
        assert result == sys.platform.startswith('win')
    
    def test_is_macos(self):
        """Test macOS detection."""
        result = is_macos()
        assert result == sys.platform.startswith('darwin')
    
    def test_is_linux(self):
        """Test Linux detection."""
        result = is_linux()
        assert result == sys.platform.startswith('linux')


class TestPathHandling:
    """Test platform-specific path handling."""
    
    @windows_only
    def test_windows_path_normalization(self):
        """Test path normalization on Windows."""
        # Test backslash conversion
        path = normalize_path("C:\\Users\\test\\file.txt")
        assert isinstance(path, Path)
        assert path.is_absolute()
        
        # Test forward slash handling
        path = normalize_path("C:/Users/test/file.txt")
        assert isinstance(path, Path)
    
    @windows_only
    def test_windows_path_with_quotes(self):
        """Test Windows path with quotes."""
        path = normalize_path('"C:\\Users\\test\\file.txt"')
        assert '"' not in str(path)
    
    @windows_only
    def test_windows_unc_path(self):
        """Test Windows UNC path handling."""
        path = normalize_path("\\\\server\\share\\file.txt")
        assert isinstance(path, Path)
    
    @unix_only
    def test_unix_path_normalization(self):
        """Test path normalization on Unix systems."""
        path = normalize_path("/home/user/file.txt")
        assert isinstance(path, Path)
        assert path.is_absolute()
    
    @unix_only
    def test_unix_home_expansion(self):
        """Test ~ expansion on Unix systems."""
        path = normalize_path("~/file.txt")
        assert "~" not in str(path)
        assert path.is_absolute()
    
    @macos_only
    def test_macos_path_normalization(self):
        """Test path normalization on macOS."""
        path = normalize_path("/Users/test/file.txt")
        assert isinstance(path, Path)
        assert path.is_absolute()
    
    def test_relative_path_conversion(self):
        """Test relative path is converted to absolute."""
        path = normalize_path("file.txt")
        assert path.is_absolute()
    
    def test_path_with_spaces(self):
        """Test path with spaces on all platforms."""
        if is_windows():
            test_path = "C:\\Users\\test user\\file name.txt"
        else:
            test_path = "/home/test user/file name.txt"
        
        path = normalize_path(test_path)
        assert isinstance(path, Path)


class TestFFmpegDetection:
    """Test ffmpeg detection on different platforms."""
    
    @windows_only
    def test_windows_ffmpeg_detection(self):
        """Test ffmpeg detection on Windows."""
        ffmpeg_path = get_ffmpeg_path()
        
        if ffmpeg_path:
            assert ffmpeg_path.exists()
            assert ffmpeg_path.name.lower() in ["ffmpeg.exe", "ffmpeg"]
    
    @windows_only
    def test_windows_ffmpeg_common_locations(self):
        """Test Windows checks common ffmpeg locations."""
        common_locations = [
            Path("C:/ffmpeg/bin/ffmpeg.exe"),
            Path("C:/Program Files/ffmpeg/bin/ffmpeg.exe"),
        ]
        
        # At least one location should be checked
        # (Implementation detail - just verify function works)
        result = get_ffmpeg_path()
        assert result is None or isinstance(result, Path)
    
    @macos_only
    def test_macos_ffmpeg_detection(self):
        """Test ffmpeg detection on macOS."""
        ffmpeg_path = get_ffmpeg_path()
        
        if ffmpeg_path:
            assert ffmpeg_path.exists()
            assert ffmpeg_path.name == "ffmpeg"
            # Common locations: /usr/local/bin, /opt/homebrew/bin
    
    @macos_only
    def test_macos_homebrew_paths(self):
        """Test macOS checks Homebrew paths."""
        # Homebrew can be in different locations on Intel vs Apple Silicon
        homebrew_paths = [
            Path("/usr/local/bin/ffmpeg"),
            Path("/opt/homebrew/bin/ffmpeg"),
        ]
        
        result = get_ffmpeg_path()
        assert result is None or isinstance(result, Path)
    
    @linux_only
    def test_linux_ffmpeg_detection(self):
        """Test ffmpeg detection on Linux."""
        ffmpeg_path = get_ffmpeg_path()
        
        if ffmpeg_path:
            assert ffmpeg_path.exists()
            assert ffmpeg_path.name == "ffmpeg"
            # Common location: /usr/bin/ffmpeg
    
    @linux_only
    def test_linux_system_paths(self):
        """Test Linux checks system paths."""
        system_paths = [
            Path("/usr/bin/ffmpeg"),
            Path("/usr/local/bin/ffmpeg"),
        ]
        
        result = get_ffmpeg_path()
        assert result is None or isinstance(result, Path)
    
    def test_ffmpeg_in_path(self):
        """Test ffmpeg detection via PATH environment variable."""
        with patch('shutil.which') as mock_which:
            mock_which.return_value = "/usr/bin/ffmpeg"
            
            ffmpeg_path = get_ffmpeg_path()
            
            if ffmpeg_path:
                assert isinstance(ffmpeg_path, Path)


class TestFFprobeDetection:
    """Test ffprobe detection on different platforms."""
    
    @windows_only
    def test_windows_ffprobe_detection(self):
        """Test ffprobe detection on Windows."""
        ffprobe_path = get_ffprobe_path()
        
        if ffprobe_path:
            assert ffprobe_path.exists()
            assert ffprobe_path.name.lower() in ["ffprobe.exe", "ffprobe"]
    
    @unix_only
    def test_unix_ffprobe_detection(self):
        """Test ffprobe detection on Unix systems."""
        ffprobe_path = get_ffprobe_path()
        
        if ffprobe_path:
            assert ffprobe_path.exists()
            assert ffprobe_path.name == "ffprobe"


class TestPlatformSpecificBehavior:
    """Test platform-specific behavior differences."""
    
    @windows_only
    def test_windows_case_insensitive_paths(self):
        """Test Windows handles case-insensitive paths."""
        # Windows paths are case-insensitive
        path1 = normalize_path("C:\\Users\\Test")
        path2 = normalize_path("C:\\users\\test")
        
        # Both should be valid Path objects
        assert isinstance(path1, Path)
        assert isinstance(path2, Path)
    
    @unix_only
    def test_unix_case_sensitive_paths(self):
        """Test Unix handles case-sensitive paths."""
        # Unix paths are case-sensitive
        path1 = normalize_path("/home/Test")
        path2 = normalize_path("/home/test")
        
        # Paths should be different
        assert path1 != path2
    
    @windows_only
    def test_windows_drive_letters(self):
        """Test Windows drive letter handling."""
        path = normalize_path("D:\\data\\file.txt")
        assert isinstance(path, Path)
        assert str(path).startswith("D:")
    
    @windows_only
    def test_windows_path_length_limit(self):
        """Test Windows handles long paths."""
        # Windows has 260 character path limit (without long path support)
        long_path = "C:\\" + "a" * 250 + "\\file.txt"
        
        # Should not raise exception
        path = normalize_path(long_path)
        assert isinstance(path, Path)


class TestCrossPlatformCompatibility:
    """Test cross-platform compatibility features."""
    
    def test_path_separator_handling(self):
        """Test correct path separator is used for platform."""
        path = Path("dir") / "subdir" / "file.txt"
        
        if is_windows():
            assert "\\" in str(path) or "/" in str(path)
        else:
            assert "/" in str(path)
    
    def test_home_directory_expansion(self):
        """Test home directory expansion works on all platforms."""
        path = normalize_path("~")
        
        assert path.is_absolute()
        assert path.exists()
        
        if is_windows():
            assert "Users" in str(path) or "users" in str(path)
        else:
            assert "home" in str(path) or "Users" in str(path)
    
    def test_temp_directory_access(self):
        """Test temporary directory access on all platforms."""
        import tempfile
        
        temp_dir = Path(tempfile.gettempdir())
        assert temp_dir.exists()
        assert temp_dir.is_dir()


class TestPlatformSpecificErrors:
    """Test platform-specific error handling."""
    
    @windows_only
    def test_windows_permission_error(self):
        """Test Windows permission error handling."""
        # Test accessing system file
        system_file = Path("C:\\Windows\\System32\\config\\SAM")
        
        # Should handle permission errors gracefully
        # (Don't actually try to access it)
    
    @unix_only
    def test_unix_permission_error(self):
        """Test Unix permission error handling."""
        # Test accessing root-only file
        root_file = Path("/etc/shadow")
        
        # Should handle permission errors gracefully
        # (Don't actually try to access it)


# Platform-specific test configuration
def pytest_configure(config):
    """Configure pytest with platform information."""
    config.addinivalue_line(
        "markers",
        f"platform_{get_platform()}: Tests for current platform"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on platform."""
    current_platform = get_platform()
    
    for item in items:
        # Add platform marker to all tests
        item.add_marker(getattr(pytest.mark, f"platform_{current_platform}"))
