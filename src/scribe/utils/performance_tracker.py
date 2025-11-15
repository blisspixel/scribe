"""
Performance tracking for adaptive progress estimation.

Tracks actual processing times per machine to improve progress estimates.
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass, asdict

from scribe.utils.logging import get_logger
import os

logger = get_logger(__name__)


def get_provider_speedup() -> float:
    """
    Get speedup factor based on configured AI provider.
    
    XAI/Grok is typically 2-3x faster than OpenAI for jokes/notes/memes.
    
    Returns:
        Speedup multiplier (1.0 = baseline OpenAI speed)
    """
    # Check which providers are configured
    joke_provider = os.getenv("SCRIBE_JOKE_PROVIDER", "xai").lower()
    notes_provider = os.getenv("SCRIBE_NOTES_PROVIDER", "xai").lower()
    meme_provider = os.getenv("SCRIBE_MEME_PROVIDER", "xai").lower()
    
    # If majority are XAI, use XAI speedup
    xai_count = sum([
        joke_provider == "xai",
        notes_provider == "xai",
        meme_provider == "xai"
    ])
    
    if xai_count >= 2:
        return 2.5  # XAI is ~2.5x faster on average
    else:
        return 1.0  # OpenAI baseline


@dataclass
class PerformanceMetrics:
    """Performance metrics for a specific operation."""
    
    # Conversion metrics (seconds per minute of audio)
    analysis_speed: float = 1.0  # Default: 1x real-time
    conversion_speed: float = 1.0  # Default: 1x real-time
    
    # Transcription metrics (real-time multiplier)
    transcription_speed: float = 11.0  # Default: 11x for large-v3
    
    # Post-processing metrics (fixed times in seconds)
    # Note: Times vary by provider (XAI/Grok is typically faster than OpenAI)
    docx_time: float = 1.0
    notes_time: float = 30.0  # ~15s with XAI, ~30s with OpenAI
    joke_time: float = 10.0   # ~2s with XAI, ~10s with OpenAI
    meme_time: float = 180.0  # ~60s with XAI, ~180s with OpenAI
    
    # Sample count for averaging
    sample_count: int = 0
    
    def update_from_actual(self, phase: str, audio_duration: float, actual_time: float):
        """
        Update metrics based on actual performance.
        
        Args:
            phase: Phase name (analysis, conversion, transcription, etc.)
            audio_duration: Audio duration in seconds
            actual_time: Actual processing time in seconds
        """
        if phase == "analysis":
            # Calculate speed as ratio of actual time to audio duration
            new_speed = actual_time / audio_duration if audio_duration > 0 else 1.0
            self.analysis_speed = self._weighted_average(self.analysis_speed, new_speed)
        elif phase == "conversion":
            new_speed = actual_time / audio_duration if audio_duration > 0 else 1.0
            self.conversion_speed = self._weighted_average(self.conversion_speed, new_speed)
        elif phase == "transcription":
            # Calculate as real-time multiplier (audio_duration / actual_time)
            new_speed = audio_duration / actual_time if actual_time > 0 else 11.0
            self.transcription_speed = self._weighted_average(self.transcription_speed, new_speed)
        elif phase in ["docx", "notes", "joke", "meme"]:
            # Fixed time operations
            attr_name = f"{phase}_time"
            current_value = getattr(self, attr_name)
            setattr(self, attr_name, self._weighted_average(current_value, actual_time))
        
        self.sample_count += 1
    
    def _weighted_average(self, current: float, new: float, weight: float = 0.3) -> float:
        """
        Calculate weighted average favoring recent measurements.
        
        Args:
            current: Current average value
            new: New measurement
            weight: Weight for new measurement (0-1)
        
        Returns:
            Updated average
        """
        return current * (1 - weight) + new * weight
    
    def estimate_total_time(
        self, 
        audio_duration: float, 
        include_post: bool = True,
        provider_speedup: float = 1.0
    ) -> float:
        """
        Estimate total processing time for given audio duration.
        
        Args:
            audio_duration: Audio duration in seconds
            include_post: Include post-processing time
            provider_speedup: Speedup factor for AI provider (e.g., 3.0 for XAI being 3x faster)
        
        Returns:
            Estimated total time in seconds
        """
        analysis_time = audio_duration * self.analysis_speed
        conversion_time = audio_duration * self.conversion_speed
        transcription_time = audio_duration / self.transcription_speed
        
        total = analysis_time + conversion_time + transcription_time
        
        if include_post:
            # Apply provider speedup to AI-dependent tasks
            total += self.docx_time  # Not AI-dependent
            total += (self.notes_time / provider_speedup)
            total += (self.joke_time / provider_speedup)
            total += (self.meme_time / provider_speedup)
        
        return total
    
    def get_phase_percentages(self, audio_duration: float, include_api_features: bool = True) -> Dict[str, tuple]:
        """
        Calculate phase percentages based on estimated times.
        
        Args:
            audio_duration: Audio duration in seconds
            include_api_features: Whether to include API features (notes, joke, meme)
        
        Returns:
            Dict mapping phase names to (start%, end%, time_multiplier) tuples
        """
        analysis_time = audio_duration * self.analysis_speed
        conversion_time = audio_duration * self.conversion_speed
        transcription_time = audio_duration / self.transcription_speed
        
        if include_api_features:
            post_time = self.docx_time + self.notes_time + self.joke_time + self.meme_time
        else:
            post_time = self.docx_time  # Just DOCX, no API features
        
        total_time = analysis_time + conversion_time + transcription_time + post_time
        
        # Calculate percentages
        preparing_pct = ((analysis_time + conversion_time) / total_time) * 100
        transcribing_pct = (transcription_time / total_time) * 100
        
        return {
            "preparing": (0, preparing_pct, (analysis_time + conversion_time) / audio_duration),
            "transcribing": (preparing_pct, preparing_pct + transcribing_pct, transcription_time / audio_duration),
            "finishing": (preparing_pct + transcribing_pct, 100, post_time / audio_duration)
        }


class PerformanceTracker:
    """Tracks and persists performance metrics per machine."""
    
    def __init__(self, machine_id: str, config_dir: Optional[Path] = None):
        """
        Initialize performance tracker.
        
        Args:
            machine_id: Unique machine identifier
            config_dir: Directory to store performance data (default: ~/.scribe)
        """
        self.machine_id = machine_id
        
        if config_dir is None:
            config_dir = Path.home() / ".scribe"
        
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.metrics_file = self.config_dir / f"performance_{machine_id}.json"
        self.metrics = self._load_metrics()
    
    def _load_metrics(self) -> PerformanceMetrics:
        """Load metrics from disk or create defaults."""
        if self.metrics_file.exists():
            try:
                with open(self.metrics_file, 'r') as f:
                    data = json.load(f)
                return PerformanceMetrics(**data)
            except Exception as e:
                logger.warning(f"Failed to load performance metrics: {e}")
        
        return PerformanceMetrics()
    
    def _save_metrics(self):
        """Save metrics to disk."""
        try:
            with open(self.metrics_file, 'w') as f:
                json.dump(asdict(self.metrics), f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save performance metrics: {e}")
    
    def record_phase(self, phase: str, audio_duration: float, actual_time: float):
        """
        Record actual performance for a phase.
        
        Args:
            phase: Phase name
            audio_duration: Audio duration in seconds
            actual_time: Actual processing time in seconds
        """
        self.metrics.update_from_actual(phase, audio_duration, actual_time)
        self._save_metrics()
        
        logger.debug(
            f"Updated {phase} performance: "
            f"audio={audio_duration:.0f}s, actual={actual_time:.1f}s, "
            f"samples={self.metrics.sample_count}"
        )
    
    def get_metrics(self) -> PerformanceMetrics:
        """Get current performance metrics."""
        return self.metrics
    
    def estimate_total_time(self, audio_duration: float) -> float:
        """Estimate total processing time."""
        return self.metrics.estimate_total_time(audio_duration)
    
    def get_phase_percentages(self, audio_duration: float) -> Dict[str, tuple]:
        """Get adaptive phase percentages."""
        return self.metrics.get_phase_percentages(audio_duration)


def get_performance_tracker(machine_id: str) -> PerformanceTracker:
    """
    Get or create performance tracker for machine.
    
    Args:
        machine_id: Unique machine identifier
    
    Returns:
        PerformanceTracker instance
    """
    return PerformanceTracker(machine_id)
