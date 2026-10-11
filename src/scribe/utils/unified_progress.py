"""
Unified progress tracking with adaptive learning.

═══════════════════════════════════════════════════════════════════════════════
ARCHITECTURAL PATTERN: Adaptive Progress Estimation with Machine Learning
═══════════════════════════════════════════════════════════════════════════════

This module implements progress tracking that LEARNS from actual performance
to provide increasingly accurate time estimates.

THE PROBLEM WITH STATIC PROGRESS BARS:
───────────────────────────────────────
Traditional progress bars use fixed percentages:
- "Transcription is 50% of total time"
- Problem: Actual time varies by machine (RTX 4090 vs CPU)
- Result: Inaccurate estimates that frustrate users

Example on fast GPU:
- Estimate: "10 minutes remaining"
- Actual: 2 minutes (way off!)

Example on slow CPU:
- Estimate: "2 minutes remaining"
- Actual: 30 minutes (way off!)

THE SOLUTION - ADAPTIVE LEARNING:
──────────────────────────────────
This module LEARNS from actual performance on YOUR machine:

First run (no data):
- Uses default estimates based on our measurements
- Tracks actual time for each phase
- Saves performance data

Second run (learning):
- Loads previous performance data
- Uses weighted average of past + current
- Updates estimates based on actual speed
- Saves updated data

Nth run (accurate):
- Estimates converge to YOUR machine's actual performance
- Progress bar becomes increasingly accurate
- Users trust the estimates

HOW IT WORKS:
─────────────
1. **Machine ID**: Hash of hostname + processor (stable per machine)
2. **Performance Tracker**: Stores metrics per machine
3. **Weighted Average**: New data weighted 30%, old data 70%
4. **Phase Tracking**: Records actual time for each phase
5. **Adaptive Estimates**: Uses learned metrics for next run

Example learning progression:
```
Run 1: Estimate 10min -> Actual 5min -> Save "5min on this machine"
Run 2: Estimate 5min -> Actual 4.5min -> Update to 4.7min average
Run 3: Estimate 4.7min -> Actual 4.8min -> Update to 4.75min average
```

WHAT WE ACTUALLY MEASURED (DEFAULT VALUES):
────────────────────────────────────────────
These defaults come from actual measurements on RTX 4090:

Test file: 28.9 minutes (1732 seconds) of audio

WITHOUT API features (transcribe only):
- Preparing: 96.8s (41.8% of total)
- Transcribing: 135.2s (58.3% of total)
- Finishing: 0.1s (0.04% of total - just DOCX)
- Total: 232.1s (~4 minutes)

WITH API features (full workflow):
- Preparing: 96.8s (18.9% of total)
- Transcribing: 135.2s (26.4% of total)
- Finishing: 279.7s (54.7% of total - notes+joke+meme)
- Total: 511.7s (~8.5 minutes)

These are REAL measurements, not guesses. Your machine will be different,
which is why adaptive learning matters.

PROVIDER-AWARE ESTIMATES:
─────────────────────────
The system accounts for AI provider speed differences:

XAI/Grok (fast):
- Notes: ~15s
- Joke: ~2s
- Meme: ~60s
- Total: ~77s

OpenAI (slower):
- Notes: ~30s
- Joke: ~10s
- Meme: ~180s
- Total: ~220s

The tracker detects which provider you're using and adjusts estimates
accordingly. This is why XAI is recommended - it's 2-3x faster.

LIMITATIONS (HONEST ASSESSMENT):
─────────────────────────────────
1. **First run inaccurate**: No data yet, uses defaults
2. **Assumes consistency**: If you switch GPUs, estimates are wrong
3. **No validation**: We don't verify the machine ID is stable
4. **Simple averaging**: Could use more sophisticated ML (Kalman filter)
5. **No outlier detection**: One slow run skews the average

POTENTIAL IMPROVEMENTS:
───────────────────────
1. **Detect hardware changes**: Reset metrics if GPU changes
2. **Outlier filtering**: Ignore runs that are 3x slower/faster
3. **Confidence intervals**: Show "4-6 minutes" instead of "5 minutes"
4. **Per-file-size learning**: Different estimates for short vs long files
5. **Kalman filtering**: More sophisticated than weighted average

THE VALUE:
──────────
Despite limitations, this provides MUCH better UX than static progress:
- Estimates improve over time
- Adapts to YOUR machine
- Accounts for provider differences
- Users learn to trust the estimates

Simple adaptive learning beats static estimates every time.
"""

import time
from contextlib import suppress
from typing import TYPE_CHECKING

from rich.progress import BarColumn, Progress, TaskID, TextColumn, TimeElapsedColumn

from scribe.utils.logging import (
    TERMINAL_OUTPUT_ERRORS,
    console,
    get_logger,
    is_terminal_output_error,
)
from scribe.utils.terminal_ui import get_terminal_ui_config

if TYPE_CHECKING:
    from scribe.utils.performance_tracker import PerformanceTracker

logger = get_logger(__name__)


class UnifiedProgress:
    """
    Unified progress tracker for entire transcription workflow.

    Shows single progress bar that updates through phases:
    - Preparing audio (0-15%)
    - Transcribing (15-85%)
    - Finishing (85-100%)
    """

    def __init__(
        self,
        total_duration: float | None = None,
        machine_id: str | None = None,
        include_api_features: bool = False,
    ):
        """
        Initialize unified progress.

        Args:
            total_duration: Audio duration in seconds (for time estimates)
            machine_id: Machine ID for adaptive performance tracking
            include_api_features: Whether this workflow includes API features (notes, joke, meme)
        """
        self.total_duration = total_duration
        self.start_time = time.time()
        self.progress: Progress | None = None
        self.task: TaskID | None = None
        self.current_phase: str | None = None
        self.phase_start_times: dict[str, float] = {}
        self.phases: dict[str, tuple[float, float, float]] = {}
        self.tracker: PerformanceTracker | None = None
        self.include_api_features = include_api_features
        self.ui_config = get_terminal_ui_config()
        self.frame_delay = self.ui_config.frame_delay
        self._terminal_output_failed = False

        # Try to load adaptive phase percentages based on machine performance
        if machine_id and total_duration:
            try:
                from scribe.utils.performance_tracker import get_performance_tracker

                tracker = get_performance_tracker(machine_id)
                self.phases = tracker.get_phase_percentages(total_duration, include_api_features)
                self.tracker = tracker
            except Exception:
                self.tracker = None
                self._set_default_phases()
        else:
            self.tracker = None
            self._set_default_phases()

    def _set_default_phases(self) -> None:
        """Set default phase definitions based on actual measurements."""
        # Real measurements from 28.9 min (1732s) test file:
        # WITHOUT API features (transcribe only):
        #   - Preparing: 96.8s (41.8%)
        #   - Transcribing: 135.2s (58.3%)
        #   - Finishing: 0.1s (0.04%)
        # WITH API features (full process):
        #   - Preparing: 96.8s (18.9%)
        #   - Transcribing: 135.2s (26.4%)
        #   - Finishing: 279.7s (54.7%) - includes notes, joke, meme

        if self.include_api_features:
            # Full workflow with API features
            self.phases = {
                "preparing": (0, 19, 0.0559),  # 96.8s / 1732s
                "transcribing": (19, 45, 0.0780),  # 135.2s / 1732s
                "finishing": (45, 100, 0.1615),  # 279.7s / 1732s (notes+joke+meme)
            }
        else:
            # Transcribe only (no API features)
            self.phases = {
                "preparing": (0, 42, 0.0559),  # 96.8s / 1732s = 41.8%
                "transcribing": (42, 99, 0.0780),  # 135.2s / 1732s = 58.3%
                "finishing": (99, 100, 0.0001),  # 0.1s / 1732s = 0.04% (just DOCX)
            }

    def start(self) -> None:
        """Start the unified progress display."""
        from scribe.utils.theme import ScribeTheme

        if self._terminal_output_failed:
            return

        progress = Progress(
            TextColumn(
                f"[bold {ScribeTheme.PRIMARY}]{{task.description}}[/bold {ScribeTheme.PRIMARY}]"
            ),
            BarColumn(complete_style=ScribeTheme.PRIMARY, finished_style=ScribeTheme.SUCCESS),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("-"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
            auto_refresh=False,
            refresh_per_second=max(2, self.ui_config.fps),
        )
        self.progress = progress
        try:
            progress.start()
            self.task = progress.add_task("Starting...", total=100)
            progress.refresh()
        except TERMINAL_OUTPUT_ERRORS as error:
            if not is_terminal_output_error(error):
                raise
            self._disable_after_terminal_failure(error)

    def _disable_after_terminal_failure(self, error: BaseException) -> None:
        """Disable this display after one terminal-delivery failure."""
        progress = self.progress
        self.progress = None
        self.task = None
        cleanup_error: Exception | None = None
        if progress is not None:
            try:
                progress.stop()
            except Exception as cleanup_exception:
                cleanup_error = cleanup_exception
        if not self._terminal_output_failed:
            self._terminal_output_failed = True
            with suppress(Exception):
                if cleanup_error is None:
                    logger.warning(
                        "Progress display disabled after terminal output failure: %s", error
                    )
                else:
                    logger.warning(
                        "Progress display disabled after terminal output failure: %s; "
                        "cleanup also failed: %s",
                        error,
                        cleanup_error,
                    )

    def update_phase(
        self, phase: str, progress_in_phase: float = 0.0, step_description: str | None = None
    ) -> None:
        """
        Update progress within a phase.

        Args:
            phase: Phase name ("preparing", "transcribing", "finishing")
            progress_in_phase: Progress within phase (0.0 to 1.0)
                              If None, auto-calculate based on elapsed time
            step_description: Optional specific step description (e.g., "Generating notes")
        """
        if phase not in self.phases:
            return

        # Track phase start time
        if phase != self.current_phase:
            self.phase_start_times[phase] = time.time()
            self.current_phase = phase

        start_pct, end_pct, time_multiplier = self.phases[phase]

        # Auto-calculate progress based on elapsed time if not provided
        if progress_in_phase == 0.0 and phase in self.phase_start_times and self.total_duration:
            elapsed = time.time() - self.phase_start_times[phase]
            expected_time = self.total_duration * time_multiplier
            if expected_time > 0:
                progress_in_phase = min(0.98, elapsed / expected_time)  # Cap at 98%

        # Record phase completion for performance tracking
        if (
            progress_in_phase >= 1.0
            and phase in self.phase_start_times
            and self.tracker
            and self.total_duration
        ):
            actual_time = time.time() - self.phase_start_times[phase]
            self.tracker.record_phase(phase, self.total_duration, actual_time)

        # Calculate overall progress
        phase_range = end_pct - start_pct
        overall_progress = start_pct + (progress_in_phase * phase_range)

        # Cap mid-flight progress so 100% only appears when complete() is called.
        # Without this the time-based extrapolator inside the short "finishing"
        # phase rounds 99.98% to "100%" while DOCX/cleanup is still running.
        if overall_progress > 99.0:
            overall_progress = 99.0

        # Build description with step if provided
        if step_description:
            description = step_description
        else:
            # Default descriptions
            descriptions = {
                "preparing": "Preparing audio",
                "transcribing": "Transcribing",
                "finishing": "Finalizing",
            }
            description = descriptions.get(phase, "Processing")

        if self.progress is not None and self.task is not None:
            try:
                self.progress.update(self.task, completed=overall_progress, description=description)
                self.progress.refresh()
            except TERMINAL_OUTPUT_ERRORS as error:
                if not is_terminal_output_error(error):
                    raise
                self._disable_after_terminal_failure(error)

    def refresh(self) -> None:
        """Refresh progress based on elapsed time in current phase."""
        if self.current_phase is not None:
            self.update_phase(self.current_phase, 0.0)

    def complete(self, *, partial: bool = False) -> None:
        """Mark workflow as complete."""
        from scribe.utils.theme import ScribeTheme

        if self.progress is not None and self.task is not None:
            elapsed = time.time() - self.start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)

            label = "Partial" if partial else "Complete"
            color = "yellow" if partial else ScribeTheme.SUCCESS
            try:
                self.progress.update(
                    self.task,
                    completed=100,
                    description=f"[{color}]{label} ({minutes}m {seconds}s)[/{color}]",
                )
                self.progress.refresh()
            except TERMINAL_OUTPUT_ERRORS as error:
                if not is_terminal_output_error(error):
                    raise
                self._disable_after_terminal_failure(error)
                return
            self.stop()

    def fail(self) -> None:
        """Leave a terminal failed state instead of an unfinished percentage."""
        if self.progress is not None and self.task is not None:
            try:
                self.progress.update(self.task, visible=False)
                self.progress.refresh()
                self.stop()
                elapsed = max(0, int(time.time() - self.start_time))
                console.print(f"[red]Failed[/red] ({elapsed // 60}m {elapsed % 60}s)")
            except TERMINAL_OUTPUT_ERRORS as error:
                if not is_terminal_output_error(error):
                    raise
                self._disable_after_terminal_failure(error)
        self.stop()

    def stop(self) -> None:
        """Stop progress display."""
        progress = self.progress
        if progress is None:
            return
        try:
            progress.stop()
        except TERMINAL_OUTPUT_ERRORS as error:
            if not is_terminal_output_error(error):
                raise
            self.progress = None
            self.task = None
            if not self._terminal_output_failed:
                self._terminal_output_failed = True
                with suppress(Exception):
                    logger.warning(
                        "Progress display disabled after terminal output failure: %s", error
                    )
        else:
            self.progress = None
            self.task = None
