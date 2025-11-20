"""Spinner progress display utilities for consistent UX across Scribe commands."""

import time
from typing import Optional
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

console = Console()


class SpinnerProgress:
    """Consistent spinner progress display with elapsed time."""
    
    # Consistent color scheme
    COLORS = {
        "process": "cyan",      # For ongoing operations
        "success": "green",     # For completed operations  
        "warning": "yellow",    # For warnings
        "error": "red",        # For errors
        "info": "blue",        # For informational messages
        "dim": "dim"           # For secondary info
    }
    
    def __init__(self, message: str, spinner_style: str = "dots"):
        """Initialize spinner progress display.
        
        Args:
            message: The message to display
            spinner_style: Spinner style (dots, line, etc.)
        """
        self.message = message
        self.start_time = time.time()
        self.progress: Optional[Progress] = None
        self.task_id = None
    
    def __enter__(self):
        """Start the spinner display."""
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn(f"[{self.COLORS['process']}]{self.message}...[/{self.COLORS['process']}]"),
            TimeElapsedColumn(),
            console=console,
            transient=False
        )
        self.progress.start()
        self.task_id = self.progress.add_task(self.message, total=None)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop the spinner display."""
        if self.progress:
            self.progress.stop()
    
    def update(self, message: Optional[str] = None):
        """Update the spinner message.
        
        Args:
            message: New message (or keep current if None)
        """
        if message and self.progress and self.task_id is not None:
            self.message = message
            self.progress.update(
                self.task_id,
                description=f"[{self.COLORS['process']}]{message}...[/{self.COLORS['process']}]"
            )
    
    def success(self, message: str, extra: Optional[str] = None):
        """Display success message and stop spinner.
        
        Args:
            message: Success message
            extra: Optional extra info (like score)
        """
        if self.progress:
            self.progress.stop()
        
        elapsed = time.time() - self.start_time
        elapsed_str = f"{int(elapsed // 60):01d}:{int(elapsed % 60):02d}"
        
        if extra:
            console.print(f"[{self.COLORS['success']}]DONE[/{self.COLORS['success']}] {message} [{self.COLORS['dim']}]({extra}, {elapsed_str})[/{self.COLORS['dim']}]")
        else:
            console.print(f"[{self.COLORS['success']}]DONE[/{self.COLORS['success']}] {message} [{self.COLORS['dim']}]({elapsed_str})[/{self.COLORS['dim']}]")
    
    def error(self, message: str):
        """Display error message and stop spinner.
        
        Args:
            message: Error message
        """
        if self.progress:
            self.progress.stop()
        
        console.print(f"[{self.COLORS['error']}]ERROR[/{self.COLORS['error']}] {message}")
    
    def warning(self, message: str):
        """Display warning message.
        
        Args:
            message: Warning message
        """
        console.print(f"[{self.COLORS['warning']}]WARNING[/{self.COLORS['warning']}] {message}")


def show_spinner(message: str) -> SpinnerProgress:
    """Create a spinner progress display.
    
    Usage:
        with show_spinner("Generating meme") as spinner:
            # do work
            spinner.update("Generating meme (attempt 2)")
            # more work
            spinner.success("Meme generated", extra="score: 8.5/10")
    
    Args:
        message: Initial message to display
        
    Returns:
        SpinnerProgress context manager
    """
    return SpinnerProgress(message)
