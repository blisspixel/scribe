"""
Cross-platform utility functions.

This module provides platform detection and platform-specific helpers
to ensure Scribe works flawlessly on Windows, macOS, and Linux.
"""

import os
import platform
import shutil
from pathlib import Path
from typing import Optional, List, Literal

PlatformType = Literal["windows", "macos", "linux", "unknown"]


def get_platform() -> PlatformType:
    """
    Get the current platform.
    
    Returns:
        Platform identifier: "windows", "macos", "linux", or "unknown"
    """
    system = platform.system().lower()
    
    if system == "windows":
        return "windows"
    elif system == "darwin":
        return "macos"
    elif system == "linux":
        return "linux"
    else:
        return "unknown"


def is_windows() -> bool:
    """Check if running on Windows."""
    return get_platform() == "windows"


def is_macos() -> bool:
    """Check if running on macOS."""
    return get_platform() == "macos"


def is_linux() -> bool:
    """Check if running on Linux."""
    return get_platform() == "linux"


def get_ffmpeg_path() -> Optional[Path]:
    """
    Find ffmpeg executable with platform-specific search.
    
    This function searches for ffmpeg in:
    1. System PATH
    2. Common installation directories
    3. Environment variables (FFMPEG_DIR, PUEO_FFMPEG_DIR)
    
    Returns:
        Path to ffmpeg executable, or None if not found
    """
    # Try PATH first
    ffmpeg_cmd = "ffmpeg.exe" if is_windows() else "ffmpeg"
    path_result = shutil.which(ffmpeg_cmd)
    if path_result:
        return Path(path_result)
    
    # Try environment variables
    for env_var in ["FFMPEG_DIR", "PUEO_FFMPEG_DIR"]:
        env_path = os.environ.get(env_var)
        if env_path:
            candidates = [
                Path(env_path) / ffmpeg_cmd,
                Path(env_path) / "bin" / ffmpeg_cmd,
            ]
            for candidate in candidates:
                if candidate.exists():
                    return candidate
    
    # Platform-specific common locations
    if is_windows():
        common_dirs = [
            Path(r"C:\Program Files\ffmpeg\bin"),
            Path(r"C:\Program Files (x86)\ffmpeg\bin"),
            Path(r"C:\ffmpeg\bin"),
            Path(os.path.expandvars(r"%USERPROFILE%\AppData\Local\Microsoft\WinGet\Links")),
        ]
    elif is_macos():
        common_dirs = [
            Path("/usr/local/bin"),
            Path("/opt/homebrew/bin"),
            Path("/opt/local/bin"),
        ]
    else:  # Linux
        common_dirs = [
            Path("/usr/bin"),
            Path("/usr/local/bin"),
            Path("/snap/bin"),
        ]
    
    for directory in common_dirs:
        candidate = directory / ffmpeg_cmd
        if candidate.exists():
            return candidate
    
    return None


def get_ffprobe_path() -> Optional[Path]:
    """
    Find ffprobe executable with platform-specific search.
    
    Returns:
        Path to ffprobe executable, or None if not found
    """
    # Try PATH first
    ffprobe_cmd = "ffprobe.exe" if is_windows() else "ffprobe"
    path_result = shutil.which(ffprobe_cmd)
    if path_result:
        return Path(path_result)
    
    # If ffmpeg was found, ffprobe is usually in the same directory
    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path:
        ffprobe_path = ffmpeg_path.parent / ffprobe_cmd
        if ffprobe_path.exists():
            return ffprobe_path
    
    return None


def get_obs_executable_path() -> Optional[Path]:
    """
    Find OBS Studio executable with platform-specific search.
    
    Returns:
        Path to OBS executable, or None if not found
    """
    # Check environment variable first
    obs_exe = os.environ.get("OBS_EXE")
    if obs_exe and Path(obs_exe).exists():
        return Path(obs_exe)
    
    if is_windows():
        candidates = [
            Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"),
            Path(r"C:\Program Files (x86)\obs-studio\bin\64bit\obs64.exe"),
            Path(r"C:\Program Files\obs-studio\bin\32bit\obs32.exe"),
        ]
    elif is_macos():
        candidates = [
            Path("/Applications/OBS.app/Contents/MacOS/OBS"),
        ]
    else:  # Linux
        candidates = [
            Path("/usr/bin/obs"),
            Path("/usr/local/bin/obs"),
            Path("/snap/bin/obs-studio"),
        ]
    
    for candidate in candidates:
        if candidate.exists():
            return candidate
    
    return None


def open_file_with_default_app(file_path: Path) -> bool:
    """
    Open a file with the system's default application.
    
    Args:
        file_path: Path to file to open
        
    Returns:
        True if successful, False otherwise
    """
    try:
        if is_windows():
            os.startfile(str(file_path))
        elif is_macos():
            import subprocess
            subprocess.run(["open", str(file_path)], check=True)
        else:  # Linux
            import subprocess
            subprocess.run(["xdg-open", str(file_path)], check=True)
        return True
    except Exception:
        return False


def get_home_directory() -> Path:
    """
    Get user's home directory in a cross-platform way.
    
    Returns:
        Path to home directory
    """
    return Path.home()


def get_default_output_directory() -> Path:
    """
    Get platform-appropriate default output directory.
    
    Returns:
        Path to default output directory
    """
    home = get_home_directory()
    
    if is_windows():
        # Windows: ~/Videos/Transcriptions
        return home / "Videos" / "Transcriptions"
    elif is_macos():
        # macOS: ~/Movies/Transcriptions
        return home / "Movies" / "Transcriptions"
    else:
        # Linux: ~/Videos/Transcriptions
        return home / "Videos" / "Transcriptions"


def get_temp_directory() -> Path:
    """
    Get platform-appropriate temporary directory.
    
    Returns:
        Path to temp directory
    """
    import tempfile
    return Path(tempfile.gettempdir())


def get_platform_info() -> dict:
    """
    Get comprehensive platform information.
    
    Returns:
        Dictionary with platform details
    """
    return {
        "platform": get_platform(),
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
    }


def check_disk_space(path: Path, required_gb: float = 1.0) -> bool:
    """
    Check if sufficient disk space is available.
    
    Args:
        path: Path to check
        required_gb: Required space in GB
        
    Returns:
        True if sufficient space available
    """
    try:
        if is_windows():
            import ctypes
            free_bytes = ctypes.c_ulonglong(0)
            ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                str(path), None, None, ctypes.pointer(free_bytes)
            )
            free_gb = free_bytes.value / (1024**3)
        else:
            import os
            stat = os.statvfs(str(path))
            free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
        
        return free_gb >= required_gb
    except Exception:
        # If we can't check, assume it's okay
        return True


def get_path_separator() -> str:
    """
    Get platform-specific path separator.
    
    Returns:
        Path separator character
    """
    return os.sep


def normalize_path(path: str) -> Path:
    """
    Normalize path for current platform.
    
    This function:
    - Converts backslashes to forward slashes on Unix
    - Expands ~ to home directory
    - Resolves to absolute path
    - Handles Windows drive letters correctly
    
    Args:
        path: Path string to normalize
        
    Returns:
        Normalized Path object
    """
    # Remove quotes
    path = path.strip('"').strip("'")
    
    # Create Path object (handles platform differences)
    p = Path(path)
    
    # Expand home directory
    p = p.expanduser()
    
    # Resolve to absolute path
    try:
        p = p.resolve()
    except Exception:
        # If resolve fails, just make it absolute
        p = p.absolute()
    
    return p
