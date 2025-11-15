"""
Unified progress tracking for S-tier UX.

Provides a single progress bar that updates through workflow phases.
"""

import time
from typing import Optional
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
from rich.console import Console

console = Console()


class UnifiedProgress:
    """
    Unified progress tracker for entire transcription workflow.
    
    Shows single progress bar that updates through phases:
    - Preparing audio (0-15%)
    - Transcribing (15-85%)
    - Finishing (85-100%)
    """
    
    def __init__(self, total_duration: Optional[float] = None, machine_id: Optional[str] = None, 
                 include_api_features: bool = False):
        """
        Initialize unified progress.
        
        Args:
            total_duration: Audio duration in seconds (for time estimates)
            machine_id: Machine ID for adaptive performance tracking
            include_api_features: Whether this workflow includes API features (notes, joke, meme)
        """
        self.total_duration = total_duration
        self.start_time = time.time()
        self.progress = None
        self.task = None
        self.current_phase = None
        self.phase_start_times = {}
        self.include_api_features = include_api_features
        
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
    
    def _set_default_phases(self):
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
                "preparing": (0, 19, 0.0559),      # 96.8s / 1732s
                "transcribing": (19, 45, 0.0780),  # 135.2s / 1732s
                "finishing": (45, 100, 0.1615)     # 279.7s / 1732s (notes+joke+meme)
            }
        else:
            # Transcribe only (no API features)
            self.phases = {
                "preparing": (0, 42, 0.0559),      # 96.8s / 1732s = 41.8%
                "transcribing": (42, 99, 0.0780),  # 135.2s / 1732s = 58.3%
                "finishing": (99, 100, 0.0001)     # 0.1s / 1732s = 0.04% (just DOCX)
            }
    
    def start(self):
        """Start the unified progress display."""
        self.progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            TimeElapsedColumn(),
            console=console,
            transient=False
        )
        self.progress.start()
        self.task = self.progress.add_task("Starting...", total=100)
    
    def update_phase(self, phase: str, progress_in_phase: float = 0.0, step_description: str = None):
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
        if progress_in_phase >= 1.0 and phase in self.phase_start_times and self.tracker and self.total_duration:
            actual_time = time.time() - self.phase_start_times[phase]
            self.tracker.record_phase(phase, self.total_duration, actual_time)
        
        # Calculate overall progress
        phase_range = end_pct - start_pct
        overall_progress = start_pct + (progress_in_phase * phase_range)
        
        # Build description with step if provided
        if step_description:
            description = step_description
        else:
            # Default descriptions
            descriptions = {
                "preparing": "Preparing audio",
                "transcribing": "Transcribing",
                "finishing": "Finishing"
            }
            description = descriptions.get(phase, "Processing")
        
        if self.progress and self.task is not None:
            self.progress.update(
                self.task,
                completed=overall_progress,
                description=description
            )
    
    def refresh(self):
        """Refresh progress based on elapsed time in current phase."""
        if self.current_phase:
            self.update_phase(self.current_phase, 0.0)
    
    def complete(self):
        """Mark workflow as complete."""
        if self.progress and self.task is not None:
            elapsed = time.time() - self.start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            
            self.progress.update(
                self.task,
                completed=100,
                description=f"[green]Complete ({minutes}m {seconds}s)[/green]"
            )
            self.progress.stop()
    
    def stop(self):
        """Stop progress display."""
        if self.progress:
            self.progress.stop()
