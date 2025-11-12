"""
Safe file writing utilities with atomic operations.

Prevents file corruption by writing to temporary files and atomically
renaming them on success.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Union, Optional
from contextlib import contextmanager

from scribe.utils.logging import get_logger

logger = get_logger(__name__)


def atomic_write(
    path: Union[str, Path],
    content: Union[str, bytes],
    encoding: Optional[str] = "utf-8",
    mode: str = "w"
) -> Path:
    """
    Write content to a file atomically.
    
    Writes to a temporary file first, then atomically renames it to the
    target path. This prevents corruption if the write is interrupted.
    
    Args:
        path: Target file path
        content: Content to write (str or bytes)
        encoding: Text encoding (only used for text mode)
        mode: Write mode ('w' for text, 'wb' for binary)
        
    Returns:
        Path to the written file
        
    Raises:
        IOError: If write fails
    """
    path = Path(path)
    
    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create temporary file in the same directory as target
    # This ensures atomic rename works (same filesystem)
    fd, temp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp"
    )
    
    temp_path = Path(temp_path)
    
    try:
        # Write to temporary file
        if mode == "wb" or isinstance(content, bytes):
            # Binary mode
            with os.fdopen(fd, "wb") as f:
                if isinstance(content, str):
                    content = content.encode(encoding or "utf-8")
                f.write(content)
        else:
            # Text mode
            with os.fdopen(fd, "w", encoding=encoding) as f:
                if isinstance(content, bytes):
                    content = content.decode(encoding or "utf-8")
                f.write(content)
        
        # Atomic rename (overwrites existing file)
        # On Windows, need to remove target first if it exists
        if os.name == "nt" and path.exists():
            path.unlink()
        
        temp_path.rename(path)
        
        logger.debug(f"Atomically wrote file: {path}")
        return path
        
    except Exception as e:
        # Clean up temp file on error
        try:
            temp_path.unlink()
        except Exception:
            pass
        
        logger.error(f"Failed to write file atomically: {path} - {e}")
        raise IOError(f"Failed to write file: {e}") from e


def atomic_write_json(path: Union[str, Path], data: dict, indent: int = 2) -> Path:
    """
    Write JSON data to a file atomically.
    
    Args:
        path: Target file path
        data: Dictionary to serialize as JSON
        indent: JSON indentation level
        
    Returns:
        Path to the written file
    """
    import json
    
    content = json.dumps(data, indent=indent, ensure_ascii=False)
    return atomic_write(path, content, encoding="utf-8", mode="w")


@contextmanager
def safe_write_context(path: Union[str, Path], mode: str = "w", encoding: str = "utf-8"):
    """
    Context manager for safe file writing.
    
    Provides a file handle that writes to a temporary file. On successful
    exit, the temp file is atomically renamed to the target path.
    
    Usage:
        with safe_write_context("output.txt") as f:
            f.write("content")
    
    Args:
        path: Target file path
        mode: Write mode ('w' for text, 'wb' for binary)
        encoding: Text encoding (only used for text mode)
        
    Yields:
        File handle for writing
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    
    # Create temporary file
    fd, temp_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp"
    )
    
    temp_path = Path(temp_path)
    
    try:
        # Open file handle
        if "b" in mode:
            f = os.fdopen(fd, mode)
        else:
            f = os.fdopen(fd, mode, encoding=encoding)
        
        try:
            yield f
        finally:
            f.close()
        
        # Atomic rename on success
        if os.name == "nt" and path.exists():
            path.unlink()
        
        temp_path.rename(path)
        logger.debug(f"Atomically wrote file: {path}")
        
    except Exception as e:
        # Clean up temp file on error
        try:
            temp_path.unlink()
        except Exception:
            pass
        
        logger.error(f"Failed to write file atomically: {path} - {e}")
        raise


def safe_copy(src: Union[str, Path], dst: Union[str, Path]) -> Path:
    """
    Copy a file safely with atomic write.
    
    Copies to a temporary file first, then atomically renames it.
    
    Args:
        src: Source file path
        dst: Destination file path
        
    Returns:
        Path to the destination file
    """
    src = Path(src)
    dst = Path(dst)
    
    if not src.exists():
        raise FileNotFoundError(f"Source file not found: {src}")
    
    dst.parent.mkdir(parents=True, exist_ok=True)
    
    # Create temporary file
    fd, temp_path = tempfile.mkstemp(
        dir=dst.parent,
        prefix=f".{dst.name}.",
        suffix=".tmp"
    )
    
    temp_path = Path(temp_path)
    
    try:
        # Close the file descriptor (shutil.copy2 will open it)
        os.close(fd)
        
        # Copy to temp file
        shutil.copy2(src, temp_path)
        
        # Atomic rename
        if os.name == "nt" and dst.exists():
            dst.unlink()
        
        temp_path.rename(dst)
        
        logger.debug(f"Safely copied: {src} -> {dst}")
        return dst
        
    except Exception as e:
        # Clean up temp file on error
        try:
            temp_path.unlink()
        except Exception:
            pass
        
        logger.error(f"Failed to copy file safely: {src} -> {dst} - {e}")
        raise IOError(f"Failed to copy file: {e}") from e


def backup_file(path: Union[str, Path], suffix: str = ".bak") -> Optional[Path]:
    """
    Create a backup of a file before modifying it.
    
    Args:
        path: File to backup
        suffix: Backup file suffix
        
    Returns:
        Path to backup file, or None if source doesn't exist
    """
    path = Path(path)
    
    if not path.exists():
        return None
    
    backup_path = path.with_suffix(path.suffix + suffix)
    
    # If backup already exists, add a number
    counter = 1
    while backup_path.exists():
        backup_path = path.with_suffix(f"{path.suffix}{suffix}.{counter}")
        counter += 1
    
    try:
        shutil.copy2(path, backup_path)
        logger.debug(f"Created backup: {backup_path}")
        return backup_path
    except Exception as e:
        logger.warning(f"Failed to create backup: {e}")
        return None
