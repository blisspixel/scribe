"""Spinner progress display utilities for consistent UX across Scribe commands."""

import threading
import time

from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from scribe.utils.logging import console
from scribe.utils.shimmer import shimmer_markup
from scribe.utils.terminal_ui import get_terminal_ui_config
from scribe.utils.theme import ScribeTheme


class SpinnerProgress:
    """Consistent spinner progress display with elapsed time."""

    # Modern color scheme using ScribeTheme
    COLORS = {
        "process": ScribeTheme.PRIMARY,       # Sophisticated teal for ongoing ops
        "success": ScribeTheme.SUCCESS,       # Soft green for completion
        "warning": ScribeTheme.WARNING,       # Amber for warnings
        "error": ScribeTheme.ERROR,           # Soft red for errors
        "info": ScribeTheme.INFO,             # Soft blue for info
        "dim": ScribeTheme.TEXT_MUTED,        # Muted for secondary info
        "ai": ScribeTheme.AI_ACCENT,          # Purple for AI features
    }

    def __init__(self, message: str, spinner_style: str = "dots"):
        """Initialize spinner progress display.
        
        Args:
            message: The message to display
            spinner_style: Spinner style (dots, line, etc.)
        """
        self.message = message
        self.start_time = time.time()
        self.progress: Progress | None = None
        self.task_id = None
        self.ui_config = get_terminal_ui_config()
        self._lock = threading.Lock()
        self._shimmer_stop: threading.Event | None = None
        self._shimmer_thread: threading.Thread | None = None
        self._shimmer_cycle_seconds = 3.2
        self._shimmer_width = 0.25 if self.ui_config.capabilities.is_windows else 0.35

    def __enter__(self):
        """Start the spinner display."""
        if self.ui_config.animation_mode == "off":
            console.print(f"[{self.COLORS['process']}]{self.message}...[/{self.COLORS['process']}]")
            return self

        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
            auto_refresh=False,
            refresh_per_second=max(2, self.ui_config.fps),
        )
        self.progress.start()
        self.task_id = self.progress.add_task(self._render_description(), total=None)
        self.progress.refresh()
        self._start_shimmer_if_enabled()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Stop the spinner display."""
        self._stop_shimmer()
        if self.progress:
            self.progress.stop()

    def _shimmer_enabled(self) -> bool:
        return (
            self.ui_config.animation_mode == "full"
            and self.ui_config.capabilities.supports_advanced_effects
        )

    def _render_description(self, phase: float | None = None) -> str:
        if self._shimmer_enabled() and phase is not None:
            return (
                shimmer_markup(
                    self.message,
                    phase=phase,
                    base_color=ScribeTheme.TEXT_MUTED,
                    highlight_color="#d0d0ff",
                    width=self._shimmer_width,
                )
                + "..."
            )
        return f"[{self.COLORS['process']}]{self.message}...[/{self.COLORS['process']}]"

    def _start_shimmer_if_enabled(self) -> None:
        if not self._shimmer_enabled() or not self.progress or self.task_id is None:
            return
        self._shimmer_stop = threading.Event()

        def _run() -> None:
            while self._shimmer_stop and not self._shimmer_stop.is_set():
                elapsed = time.time() - self.start_time
                phase = (elapsed % self._shimmer_cycle_seconds) / self._shimmer_cycle_seconds
                with self._lock:
                    if not self.progress or self.task_id is None:
                        return
                    self.progress.update(self.task_id, description=self._render_description(phase))
                    self.progress.refresh()
                if self._shimmer_stop.wait(self.ui_config.frame_delay):
                    return

        self._shimmer_thread = threading.Thread(target=_run, daemon=True)
        self._shimmer_thread.start()

    def _stop_shimmer(self) -> None:
        if self._shimmer_stop:
            self._shimmer_stop.set()
        if self._shimmer_thread:
            self._shimmer_thread.join(timeout=1.0)
        self._shimmer_stop = None
        self._shimmer_thread = None

    def update(self, message: str | None = None) -> None:
        """Update the spinner message.
        
        Args:
            message: New message (or keep current if None)
        """
        if message:
            self.message = message
        if self.progress and self.task_id is not None and not self._shimmer_enabled():
            with self._lock:
                self.progress.update(self.task_id, description=self._render_description())
                self.progress.refresh()

    def success(self, message: str, extra: str | None = None) -> None:
        """Display success message and stop spinner.
        
        Args:
            message: Success message
            extra: Optional extra info (like score)
        """
        self._stop_shimmer()
        if self.progress:
            self.progress.stop()

        elapsed = time.time() - self.start_time
        elapsed_str = f"{int(elapsed // 60):01d}:{int(elapsed % 60):02d}"

        if extra:
            console.print(f"[{self.COLORS['success']}]DONE[/{self.COLORS['success']}] {message} [{self.COLORS['dim']}]({extra}, {elapsed_str})[/{self.COLORS['dim']}]")
        else:
            console.print(f"[{self.COLORS['success']}]DONE[/{self.COLORS['success']}] {message} [{self.COLORS['dim']}]({elapsed_str})[/{self.COLORS['dim']}]")

    def complete(self) -> None:
        """Stop spinner silently without printing a message.
        
        Use this when the calling code will handle the success message itself.
        """
        self._stop_shimmer()
        if self.progress:
            self.progress.stop()

    def error(self, message: str) -> None:
        """Display error message and stop spinner.
        
        Args:
            message: Error message
        """
        self._stop_shimmer()
        if self.progress:
            self.progress.stop()

        console.print(f"[{self.COLORS['error']}]ERROR[/{self.COLORS['error']}] {message}")

    def warning(self, message: str) -> None:
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
