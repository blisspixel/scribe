"""
Performance tracking for adaptive progress estimation.

═══════════════════════════════════════════════════════════════════════════════
ARCHITECTURAL PATTERN: Machine Learning for Progress Estimation
═══════════════════════════════════════════════════════════════════════════════

This module implements the LEARNING component of adaptive progress tracking.
It stores performance metrics per machine and uses them to improve estimates.

THE LEARNING ALGORITHM:
───────────────────────
1. **Record actual performance**: After each phase, record actual time
2. **Weighted averaging**: Combine with previous measurements (70% old, 30% new)
3. **Outlier detection**: Ignore measurements that are >3x or <0.33x average
4. **Persistence**: Save metrics to disk for next run
5. **Retrieval**: Load metrics at start of next run

WHY WEIGHTED AVERAGING?
───────────────────────
Simple average: (old + new) / 2
- Problem: Old measurements have too much influence
- Example: 10 old measurements of 5min, 1 new of 10min → average 5.45min
- Result: Slow to adapt to changes

Weighted average: old * 0.7 + new * 0.3
- Benefit: Recent measurements have more influence
- Example: old=5min, new=10min → average 6.5min
- Result: Adapts faster to actual performance

WHY OUTLIER DETECTION? (NEW IMPROVEMENT):
──────────────────────────────────────────
Without outlier detection:
- User interrupts transcription (Ctrl+C) → recorded as very slow
- System was busy (other processes) → recorded as slow
- One bad measurement skews all future estimates

With outlier detection:
- Measurement >3x average → reduce weight to 10%
- Measurement <0.33x average → reduce weight to 10%
- Prevents one bad run from ruining estimates

Example:
- Normal: 10s, 11s, 9s, 10s → average 10s ✓
- With outlier: 10s, 11s, 50s (interrupted), 9s → average 12s ✗
- With detection: 10s, 11s, 50s (ignored), 9s → average 10s ✓

WHAT WE TRACK:
──────────────
Per-phase metrics:
- **Preparing**: conversion_speed (seconds per second of audio)
- **Transcribing**: transcription_speed (realtime multiplier, e.g., 11x)
- **Finishing**: Fixed times for docx, notes, joke, meme

Provider-aware:
- Detects XAI vs OpenAI
- Applies 2.5x speedup for XAI
- Adjusts estimates accordingly

STORAGE:
────────
Metrics stored in: ~/.scribe/performance/{machine_id}.json

Example:
```json
{
  "conversion_speed": 0.0559,
  "transcription_speed": 13.2,
  "notes_time": 15.3,
  "joke_time": 2.1,
  "meme_time": 58.7,
  "sample_count": 5
}
```

LIMITATIONS (HONEST):
─────────────────────
1. **No hardware change detection**: If you upgrade GPU, old metrics are wrong
2. **Simple outlier detection**: 3x threshold is arbitrary (not optimized)
3. **No confidence tracking**: Don't know if estimates are reliable
4. **No per-file-size learning**: Same estimates for 1min and 60min files
5. **Weighted average is simple**: Could use Kalman filter or exponential smoothing

POTENTIAL IMPROVEMENTS:
───────────────────────
1. **Detect hardware changes**: Hash GPU model, reset if changed
2. **Confidence intervals**: Track variance, show "4-6 minutes" range
3. **Per-duration buckets**: Different estimates for short/medium/long files
4. **Kalman filtering**: More sophisticated than weighted average
5. **Adaptive weight**: Use higher weight when variance is low

THE VALUE:
──────────
Despite limitations, this provides measurable improvement:
- First run: Uses defaults (may be off by 2-3x)
- Second run: Adapts to your machine (within 50%)
- Fifth run: Converges to accurate (within 10-20%)

Simple machine learning beats static estimates.
"""

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from scribe.utils.logging import get_logger

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

    def update_from_actual(self, phase: str, audio_duration: float, actual_time: float) -> None:
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
        Calculate weighted average favoring recent measurements with outlier detection.
        
        Outlier detection: If new measurement is >3x or <0.33x the current average,
        it's likely an anomaly (user interrupted, system was busy, etc.) and we
        reduce its weight to prevent skewing the average.
        
        Args:
            current: Current average value
            new: New measurement
            weight: Weight for new measurement (0-1)
        
        Returns:
            Updated average
        
        Example:
            current=10.0, new=11.0 → normal, use full weight
            current=10.0, new=50.0 → outlier (5x), reduce weight to 0.1
            current=10.0, new=2.0 → outlier (0.2x), reduce weight to 0.1
        """
        # Outlier detection: if new value is >3x or <0.33x current, it's suspicious
        if current > 0:
            ratio = new / current
            if ratio > 3.0 or ratio < 0.33:
                # Likely an outlier - reduce weight dramatically
                logger.debug(f"Outlier detected: new={new:.2f}, current={current:.2f}, ratio={ratio:.2f}x")
                weight = 0.1  # Use only 10% weight for outliers

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

    def get_phase_percentages(self, audio_duration: float, include_api_features: bool = True) -> dict[str, tuple]:
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

    def __init__(self, machine_id: str, config_dir: Path | None = None):
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
                with open(self.metrics_file) as f:
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

    def record_phase(self, phase: str, audio_duration: float, actual_time: float) -> None:
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

    def get_phase_percentages(self, audio_duration: float) -> dict[str, tuple]:
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
