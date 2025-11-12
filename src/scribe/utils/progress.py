"""
Progress tracking utilities with Rich integration.

This module provides progress tracking with dynamic time estimation,
speed calculation, and beautiful Rich progress bars.
"""

import time
from typing import Optional, List
from dataclasses import dataclass, field

from rich.progress import (
    Progress,
    SpinnerColumn,
    BarColumn,
    TextColumn,
    TimeRemainingColumn,
    TimeElapsedColumn,
    MofNCompleteColumn,
)
from rich.console import Console

from scribe.utils.logging import console


@dataclass
class ProgressMeasurement:
    """Single progress measurement."""
    progress: float  # 0.0 to 1.0
    elapsed: float   # seconds since start
    timestamp: float # absolute timestamp


class ProgressTracker:
    """
    Track progress and estimate completion time using Kalman filter.
    
    This class provides:
    - Dynamic time estimates that improve over time
    - Speed ratio calculation (e.g., 8.5x realtime)
    - Smooth progress updates
    - No emoji output
    
    Example:
        tracker = ProgressTracker(total_duration=3600, operation="Transcribing")
        tracker.start()
        
        for segment in segments:
            tracker.update(segment.end)
            # Progress bar updates automatically
        
        tracker.complete()
    """
    
    def __init__(self, total_duration: float, operation: str = "Processing"):
        """
        Initialize progress tracker.
        
        Args:
            total_duration: Total duration to process (seconds)
            operation: Operation description
        """
        self.total_duration = total_duration
        self.operation = operation
        self.start_time: Optional[float] = None
        self.measurements: List[ProgressMeasurement] = []
        
        # Kalman filter state
        self.speed_estimate: Optional[float] = None
        self.variance: float = 1.0
        
    def start(self) -> None:
        """Start tracking."""
        self.start_time = time.time()
        self.measurements = []
        self.speed_estimate = None
        self.variance = 1.0
    
    def update(self, current_position: float) -> None:
        """
        Update progress with new measurement.
        
        Args:
            current_position: Current position in total duration
        """
        if self.start_time is None:
            return
        
        elapsed = time.time() - self.start_time
        progress = min(1.0, current_position / self.total_duration)
        
        measurement = ProgressMeasurement(
            progress=progress,
            elapsed=elapsed,
            timestamp=time.time()
        )
        self.measurements.append(measurement)
        
        # Update Kalman filter
        self._update_kalman_filter(progress, elapsed)
    
    def _update_kalman_filter(self, progress: float, elapsed: float) -> None:
        """Update speed estimate using Kalman filter."""
        if progress <= 0 or elapsed <= 0:
            return
        
        # Current speed (progress per second)
        speed = progress / elapsed
        
        if self.speed_estimate is None:
            self.speed_estimate = speed
        else:
            # Prediction
            prediction = self.speed_estimate
            prediction_variance = self.variance + 0.1
            
            # Update
            kalman_gain = prediction_variance / (prediction_variance + 0.5)
            self.speed_estimate = prediction + kalman_gain * (speed - prediction)
            self.variance = (1 - kalman_gain) * prediction_variance
    
    def get_eta(self, current_progress: float) -> float:
        """
        Get estimated time to completion.
        
        Args:
            current_progress: Current progress (0.0 to 1.0)
            
        Returns:
            Estimated seconds remaining
        """
        if self.speed_estimate is None or self.speed_estimate <= 0:
            return float('inf')
        
        remaining = 1.0 - current_progress
        return remaining / self.speed_estimate
    
    def get_speed_ratio(self) -> float:
        """
        Get processing speed ratio (e.g., 8.5x realtime).
        
        Returns:
            Speed ratio
        """
        if not self.measurements or self.start_time is None:
            return 0.0
        
        latest = self.measurements[-1]
        if latest.elapsed <= 0:
            return 0.0
        
        processed_duration = latest.progress * self.total_duration
        return processed_duration / latest.elapsed
    
    def complete(self) -> None:
        """Mark tracking as complete."""
        if self.start_time is not None:
            elapsed = time.time() - self.start_time
            speed_ratio = self.get_speed_ratio()
            
            # Log completion (will be picked up by logger)
            import logging
            logger = logging.getLogger("scribe")
            logger.info(
                f"{self.operation} completed in {elapsed:.1f}s "
                f"({speed_ratio:.1f}x realtime)"
            )


def create_progress_bar(description: str = "Processing") -> Progress:
    """
    Create a Rich progress bar with standard configuration.
    
    Args:
        description: Progress bar description
        
    Returns:
        Configured Progress instance
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(complete_style="green", finished_style="bold green"),
        TextColumn("[progress.percentage]{task.percentage:>3.1f}%"),
        TimeElapsedColumn(),
        TextColumn("•"),
        TimeRemainingColumn(),
        console=console,
        transient=False  # Keep progress visible after completion
    )


def format_speed_ratio(ratio: float) -> str:
    """
    Format speed ratio for display.
    
    Args:
        ratio: Speed ratio (e.g., 8.5)
        
    Returns:
        Formatted string (e.g., "8.5x realtime")
    """
    if ratio <= 0:
        return "calculating..."
    elif ratio < 1:
        return f"{ratio:.2f}x realtime"
    else:
        return f"{ratio:.1f}x realtime"


def format_eta(seconds: float) -> str:
    """
    Format ETA for display.
    
    Args:
        seconds: Seconds remaining
        
    Returns:
        Formatted string (e.g., "2m 30s", "1h 15m")
    """
    if seconds == float('inf') or seconds < 0:
        return "calculating..."
    
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds / 3600)
        minutes = int((seconds % 3600) / 60)
        return f"{hours}h {minutes}m"
