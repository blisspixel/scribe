"""
Logging configuration utilities.

This module provides centralized logging setup with dual output
(console and file) and Rich-based colored console formatting.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler


# Global console instance
console = Console()


def setup_logging(
    session_name: str,
    log_dir: Path,
    console_level: int = logging.WARNING,
    file_level: int = logging.DEBUG
) -> logging.Logger:
    """
    Configure dual-output logging (console + file).
    
    This function sets up:
    - File handler with detailed format and DEBUG level
    - Console handler with Rich formatting and INFO level
    - No emoji in any output
    - Proper encoding for Unicode characters
    
    Args:
        session_name: Name for log file
        log_dir: Directory for log files
        console_level: Console logging level
        file_level: File logging level
        
    Returns:
        Configured logger instance
    """
    # Create log directory
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate log filename
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"scribe_{session_name}_{timestamp}.log"
    
    # Get root logger
    logger = logging.getLogger("scribe")
    logger.setLevel(logging.DEBUG)
    
    # Clear existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # File handler with detailed format
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(file_level)
    file_formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    file_handler.setFormatter(file_formatter)
    
    # Console handler with Rich formatting
    console_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
    )
    console_handler.setLevel(console_level)
    
    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    # Log startup info
    logger.info(f"Logging initialized for session: {session_name}")
    logger.debug(f"Log file: {log_file}")
    
    return logger


def get_logger(name: str = "scribe") -> logging.Logger:
    """
    Get logger instance.
    
    Args:
        name: Logger name
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def log_system_info(logger: logging.Logger) -> None:
    """
    Log system information for debugging.
    
    Args:
        logger: Logger instance
    """
    import platform
    from scribe.utils.platform import get_platform_info
    from scribe.utils.gpu import detect_gpu_capability
    
    logger.debug("System Information:")
    logger.debug(f"  Platform: {platform.system()} {platform.release()}")
    logger.debug(f"  Python: {platform.python_version()}")
    logger.debug(f"  Machine: {platform.machine()}")
    
    # GPU info
    try:
        gpu_info = detect_gpu_capability()
        if gpu_info.get("has_gpu"):
            logger.debug(f"  GPU: {gpu_info.get('gpu_name')}")
            logger.debug(f"  VRAM: {gpu_info.get('gpu_memory_gb', 0):.1f}GB")
            logger.debug(f"  CUDA: {gpu_info.get('cuda_version', 'N/A')}")
        else:
            logger.debug("  GPU: Not available")
    except Exception as e:
        logger.debug(f"  GPU: Detection failed ({e})")


def log_exception(logger: logging.Logger, exc: Exception, context: Optional[dict] = None) -> None:
    """
    Log exception with context.
    
    Args:
        logger: Logger instance
        exc: Exception to log
        context: Optional context dictionary
    """
    logger.error(f"Exception: {type(exc).__name__}: {exc}")
    
    if context:
        logger.error(f"Context: {context}")
    
    logger.debug("Exception details:", exc_info=True)


def set_log_level(logger: logging.Logger, level: int) -> None:
    """
    Set logging level for all handlers.
    
    Args:
        logger: Logger instance
        level: Logging level (logging.DEBUG, INFO, WARNING, ERROR)
    """
    logger.setLevel(level)
    for handler in logger.handlers:
        if isinstance(handler, RichHandler):
            handler.setLevel(level)
