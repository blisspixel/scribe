"""
File operation utilities with defensive programming.

This module provides safe file operations including path handling,
cleanup, verification, and date extraction from filenames.
"""

import os
import re
import glob
from pathlib import Path
from typing import List, Optional
from datetime import datetime

from scribe.exceptions import FileOperationError
from scribe.utils.platform import normalize_path


def safe_path(path: str) -> Path:
    """
    Sanitize and validate file path using pathlib.
    
    This function:
    - Strips quotes and whitespace
    - Expands ~ to home directory
    - Expands environment variables
    - Converts to absolute path
    - Validates path is not empty
    
    Args:
        path: Raw path string
        
    Returns:
        Cleaned absolute Path object
        
    Raises:
        FileOperationError: If path is invalid
    """
    if not path or not path.strip():
        raise FileOperationError("Path cannot be empty")
    
    try:
        return normalize_path(path)
    except Exception as e:
        raise FileOperationError(
            f"Invalid path: {path}",
            context={"error": str(e)}
        )


def ensure_directory(path: Path) -> Path:
    """
    Create directory if it doesn't exist.
    
    Args:
        path: Directory path to create
        
    Returns:
        Path object (guaranteed to exist)
        
    Raises:
        FileOperationError: If directory cannot be created
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except Exception as e:
        raise FileOperationError(
            f"Cannot create directory: {path}",
            context={"error": str(e)}
        )


def cleanup_files(
    directory: Path,
    patterns: List[str],
    keep_patterns: Optional[List[str]] = None,
    dry_run: bool = False
) -> List[Path]:
    """
    Clean up files matching patterns.
    
    Args:
        directory: Directory to clean
        patterns: File patterns to delete (e.g., ["*.tmp", "*_temp.*"])
        keep_patterns: Patterns to preserve (e.g., ["*_final.*"])
        dry_run: If True, don't actually delete files
        
    Returns:
        List of files that were (or would be) deleted
        
    Raises:
        FileOperationError: If cleanup fails critically
    """
    if not directory.exists():
        return []
    
    keep_patterns = keep_patterns or []
    deleted_files: List[Path] = []
    
    try:
        # Find all files matching delete patterns
        files_to_delete = set()
        for pattern in patterns:
            for file_path in directory.glob(pattern):
                if file_path.is_file():
                    files_to_delete.add(file_path)
        
        # Remove files matching keep patterns
        files_to_keep = set()
        for pattern in keep_patterns:
            for file_path in directory.glob(pattern):
                if file_path.is_file():
                    files_to_keep.add(file_path)
        
        files_to_delete -= files_to_keep
        
        # Delete files
        for file_path in files_to_delete:
            if dry_run:
                deleted_files.append(file_path)
            else:
                try:
                    file_path.unlink()
                    deleted_files.append(file_path)
                except Exception as e:
                    # Log but don't fail on individual file deletion errors
                    import logging
                    logging.warning(f"Could not delete {file_path}: {e}")
        
        return deleted_files
        
    except Exception as e:
        raise FileOperationError(
            f"Cleanup failed in directory: {directory}",
            context={"error": str(e)}
        )


def verify_file_content(path: Path, min_size: int = 100) -> bool:
    """
    Verify file exists and has minimum content.
    
    Args:
        path: Path to file
        min_size: Minimum file size in bytes
        
    Returns:
        True if file is valid
        
    Raises:
        FileOperationError: If file is invalid
    """
    # Use try/except to avoid race conditions (TOCTOU)
    try:
        file_stat = path.stat()
    except FileNotFoundError:
        raise FileOperationError(
            f"File does not exist: {path}",
            context={"path": str(path)}
        )
    except OSError as e:
        raise FileOperationError(
            f"Cannot access file: {path}",
            context={"path": str(path), "error": str(e)}
        )
    
    if not path.is_file():
        raise FileOperationError(
            f"Path is not a file: {path}",
            context={"path": str(path)}
        )
    
    file_size = file_stat.st_size
    
    if file_size < min_size:
        raise FileOperationError(
            f"File is too small (expected >= {min_size} bytes, got {file_size} bytes): {path}",
            context={"path": str(path), "size": file_size, "min_size": min_size}
        )
    
    return True


def extract_date_from_filename(filename: str) -> Optional[str]:
    """
    Extract date from filename like 'Meeting_2025-11-06_15-31-40.mp4'.
    
    Args:
        filename: Filename to parse
        
    Returns:
        Date string in YYYY-MM-DD format, or None if not found
    """
    # Try to find YYYY-MM-DD pattern
    match = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
    if match:
        return match.group(1)
    
    # Try to find YYYYMMDD pattern
    match = re.search(r'(\d{4})(\d{2})(\d{2})', filename)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}"
    
    return None


def format_date(date_str: str) -> str:
    """
    Convert YYYY-MM-DD to readable format like 'November 6, 2025'.
    
    Args:
        date_str: Date string in YYYY-MM-DD format
        
    Returns:
        Formatted date string
    """
    try:
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.strftime('%B %d, %Y')
    except Exception:
        return date_str


def format_duration_minutes(seconds: float) -> str:
    """
    Convert seconds to readable duration like '58 minutes' or '2 hours 15 minutes'.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted duration string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    
    if hours > 0:
        hour_str = f"{hours} hour" + ("s" if hours != 1 else "")
        if minutes > 0:
            minute_str = f"{minutes} minute" + ("s" if minutes != 1 else "")
            return f"{hour_str} {minute_str}"
        return hour_str
    else:
        return f"{minutes} minute" + ("s" if minutes != 1 else "")


def get_file_size_mb(path: Path) -> float:
    """
    Get file size in megabytes.
    
    Args:
        path: Path to file
        
    Returns:
        File size in MB
    """
    try:
        return path.stat().st_size / (1024 * 1024)
    except Exception:
        return 0.0


def get_file_info(path: Path) -> dict:
    """
    Get comprehensive file information.
    
    Args:
        path: Path to file
        
    Returns:
        Dictionary with file metadata
    """
    try:
        stat = path.stat()
        return {
            "path": str(path),
            "name": path.name,
            "size_bytes": stat.st_size,
            "size_mb": stat.st_size / (1024 * 1024),
            "created": datetime.fromtimestamp(stat.st_ctime),
            "modified": datetime.fromtimestamp(stat.st_mtime),
            "is_file": path.is_file(),
            "is_dir": path.is_dir(),
        }
    except Exception as e:
        return {
            "path": str(path),
            "error": str(e)
        }


def find_latest_file(directory: Path, pattern: str, min_size: int = 0) -> Optional[Path]:
    """
    Find the most recently created file matching pattern.
    
    Args:
        directory: Directory to search
        pattern: Glob pattern (e.g., "*.wav")
        min_size: Minimum file size in bytes
        
    Returns:
        Path to latest file, or None if not found
    """
    if not directory.exists():
        return None
    
    matching_files = []
    
    for file_path in directory.glob(pattern):
        if file_path.is_file():
            try:
                stat = file_path.stat()
                if stat.st_size >= min_size:
                    matching_files.append((file_path, stat.st_ctime))
            except Exception:
                continue
    
    if not matching_files:
        return None
    
    # Return file with latest creation time
    latest_file = max(matching_files, key=lambda x: x[1])
    return latest_file[0]


def wait_for_file_stable(
    path: Path,
    stable_duration: float = 2.0,
    max_wait: float = 300.0,
    check_interval: float = 0.5
) -> bool:
    """
    Wait for file to exist and stop growing (stable size).
    
    Args:
        path: Path to file
        stable_duration: How long size must be stable (seconds)
        max_wait: Maximum time to wait (seconds)
        check_interval: How often to check (seconds)
        
    Returns:
        True if file is stable, False if timeout
    """
    import time
    
    start_time = time.time()
    last_size = -1
    stable_time = 0.0
    
    while time.time() - start_time < max_wait:
        if not path.exists():
            time.sleep(check_interval)
            continue
        
        try:
            current_size = path.stat().st_size
            
            if current_size == last_size:
                stable_time += check_interval
                if stable_time >= stable_duration:
                    return True
            else:
                stable_time = 0.0
                last_size = current_size
            
        except Exception:
            pass
        
        time.sleep(check_interval)
    
    return False


def copy_file_safe(source: Path, destination: Path, overwrite: bool = False) -> Path:
    """
    Safely copy file with error handling.
    
    Args:
        source: Source file path
        destination: Destination file path
        overwrite: Whether to overwrite existing file
        
    Returns:
        Destination path
        
    Raises:
        FileOperationError: If copy fails
    """
    if not source.exists():
        raise FileOperationError(
            f"Source file does not exist: {source}",
            context={"source": str(source)}
        )
    
    if destination.exists() and not overwrite:
        raise FileOperationError(
            f"Destination file already exists: {destination}",
            context={"destination": str(destination)}
        )
    
    try:
        import shutil
        shutil.copy2(source, destination)
        return destination
    except Exception as e:
        raise FileOperationError(
            f"Failed to copy file from {source} to {destination}",
            context={"source": str(source), "destination": str(destination), "error": str(e)}
        )


def move_file_safe(source: Path, destination: Path, overwrite: bool = False) -> Path:
    """
    Safely move file with error handling.
    
    Args:
        source: Source file path
        destination: Destination file path
        overwrite: Whether to overwrite existing file
        
    Returns:
        Destination path
        
    Raises:
        FileOperationError: If move fails
    """
    if not source.exists():
        raise FileOperationError(
            f"Source file does not exist: {source}",
            context={"source": str(source)}
        )
    
    if destination.exists() and not overwrite:
        raise FileOperationError(
            f"Destination file already exists: {destination}",
            context={"destination": str(destination)}
        )
    
    try:
        import shutil
        shutil.move(str(source), str(destination))
        return destination
    except Exception as e:
        raise FileOperationError(
            f"Failed to move file from {source} to {destination}",
            context={"source": str(source), "destination": str(destination), "error": str(e)}
        )
