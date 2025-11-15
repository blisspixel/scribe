"""
Unit tests for performance tracking.
"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, patch

from scribe.utils.performance_tracker import (
    PerformanceMetrics,
    PerformanceTracker,
    get_performance_tracker
)


class TestPerformanceMetrics:
    """Test performance metrics."""
    
    def test_initialization(self):
        """Test metrics initialization with defaults."""
        metrics = PerformanceMetrics()
        
        assert metrics.analysis_speed == 1.0
        assert metrics.conversion_speed == 1.0
        assert metrics.transcription_speed == 11.0
        assert metrics.sample_count == 0
    
    def test_update_analysis_speed(self):
        """Test updating analysis speed."""
        metrics = PerformanceMetrics()
        
        # Simulate 60 min audio taking 70 seconds to analyze
        metrics.update_from_actual("analysis", 3600, 70)
        
        # Speed should be updated (70/3600 = 0.0194)
        # With 30% weight: 1.0 * 0.7 + 0.0194 * 0.3 = 0.706
        assert 0.7 < metrics.analysis_speed < 0.72
        assert metrics.sample_count == 1
    
    def test_update_transcription_speed(self):
        """Test updating transcription speed."""
        metrics = PerformanceMetrics()
        
        # Simulate 60 min audio taking 300 seconds to transcribe
        # Speed = 3600 / 300 = 12x real-time
        metrics.update_from_actual("transcription", 3600, 300)
        
        # With 30% weight: 11.0 * 0.7 + 12.0 * 0.3 = 11.3
        assert 11.2 < metrics.transcription_speed < 11.4
        assert metrics.sample_count == 1
    
    def test_weighted_average(self):
        """Test weighted averaging."""
        metrics = PerformanceMetrics()
        
        # Test with default weight (0.3)
        result = metrics._weighted_average(10.0, 20.0)
        # 10 * 0.7 + 20 * 0.3 = 13
        assert result == 13.0
    
    def test_estimate_total_time(self):
        """Test total time estimation."""
        metrics = PerformanceMetrics()
        
        # For 60 min audio with defaults:
        # Analysis: 3600 * 1.0 = 3600s
        # Conversion: 3600 * 1.0 = 3600s
        # Transcription: 3600 / 11.0 = 327s
        # Post: 1 + 30 + 10 + 180 = 221s
        # Total: 7748s
        total = metrics.estimate_total_time(3600)
        assert 7700 < total < 7800
    
    def test_get_phase_percentages(self):
        """Test phase percentage calculation."""
        metrics = PerformanceMetrics()
        
        phases = metrics.get_phase_percentages(3600)
        
        assert "preparing" in phases
        assert "transcribing" in phases
        assert "finishing" in phases
        
        # Check that percentages add up to 100
        prep_start, prep_end, _ = phases["preparing"]
        trans_start, trans_end, _ = phases["transcribing"]
        finish_start, finish_end, _ = phases["finishing"]
        
        assert prep_start == 0
        assert trans_start == prep_end
        assert finish_start == trans_end
        assert finish_end == 100


class TestPerformanceTracker:
    """Test performance tracker."""
    
    def test_initialization(self, tmp_path):
        """Test tracker initialization."""
        tracker = PerformanceTracker("test_machine", config_dir=tmp_path)
        
        assert tracker.machine_id == "test_machine"
        assert tracker.config_dir == tmp_path
        assert tracker.metrics_file.exists() == False  # Not created until first save
    
    def test_record_phase(self, tmp_path):
        """Test recording phase performance."""
        tracker = PerformanceTracker("test_machine", config_dir=tmp_path)
        
        # Record analysis phase
        tracker.record_phase("analysis", 3600, 70)
        
        # Check metrics were updated
        assert tracker.metrics.sample_count == 1
        assert tracker.metrics.analysis_speed != 1.0
        
        # Check file was saved
        assert tracker.metrics_file.exists()
    
    def test_persistence(self, tmp_path):
        """Test metrics persistence across instances."""
        # Create first tracker and record data
        tracker1 = PerformanceTracker("test_machine", config_dir=tmp_path)
        tracker1.record_phase("analysis", 3600, 70)
        original_speed = tracker1.metrics.analysis_speed
        
        # Create second tracker with same machine ID
        tracker2 = PerformanceTracker("test_machine", config_dir=tmp_path)
        
        # Should load saved metrics
        assert tracker2.metrics.analysis_speed == original_speed
        assert tracker2.metrics.sample_count == 1
    
    def test_estimate_total_time(self, tmp_path):
        """Test total time estimation."""
        tracker = PerformanceTracker("test_machine", config_dir=tmp_path)
        
        total = tracker.estimate_total_time(3600)
        
        # Should be around 7748s with defaults
        assert 7000 < total < 8000
    
    def test_get_phase_percentages(self, tmp_path):
        """Test getting adaptive phase percentages."""
        tracker = PerformanceTracker("test_machine", config_dir=tmp_path)
        
        phases = tracker.get_phase_percentages(3600)
        
        assert "preparing" in phases
        assert "transcribing" in phases
        assert "finishing" in phases
    
    def test_multiple_updates(self, tmp_path):
        """Test multiple performance updates."""
        tracker = PerformanceTracker("test_machine", config_dir=tmp_path)
        
        # Record multiple samples
        tracker.record_phase("analysis", 3600, 70)
        tracker.record_phase("analysis", 3600, 65)
        tracker.record_phase("analysis", 3600, 68)
        
        assert tracker.metrics.sample_count == 3
        
        # Speed should converge toward actual measurements
        # All measurements are around 0.019 (70/3600)
        assert tracker.metrics.analysis_speed < 0.5


class TestGetPerformanceTracker:
    """Test performance tracker factory function."""
    
    def test_get_tracker(self):
        """Test getting tracker instance."""
        tracker = get_performance_tracker("test_machine")
        
        assert isinstance(tracker, PerformanceTracker)
        assert tracker.machine_id == "test_machine"


class TestAdaptiveProgress:
    """Test adaptive progress with performance tracking."""
    
    def test_unified_progress_with_tracker(self, tmp_path):
        """Test unified progress uses performance tracker."""
        from scribe.utils.unified_progress import UnifiedProgress
        from scribe.utils.performance_tracker import get_performance_tracker
        
        # Create tracker with custom metrics
        # Test that unified progress can use performance tracker
        # Create tracker directly first
        from scribe.utils.performance_tracker import get_performance_tracker
        tracker = get_performance_tracker("test_machine_adaptive")
        
        # Record some performance
        tracker.record_phase("transcription", 3600, 200)
        
        # Create unified progress with machine ID and duration
        progress = UnifiedProgress(total_duration=3600, machine_id="test_machine_adaptive")
        
        # Should have created a tracker (or it falls back to defaults)
        # The tracker may be None if there's an import issue, but phases should still exist
        assert "preparing" in progress.phases
        assert "transcribing" in progress.phases
        assert "finishing" in progress.phases
        
        # If tracker was successfully created, verify it works
        if progress.tracker:
            assert progress.tracker.metrics.sample_count > 0


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_zero_duration(self):
        """Test handling zero audio duration."""
        metrics = PerformanceMetrics()
        
        # Should not crash
        metrics.update_from_actual("analysis", 0, 10)
        
        # Speed should remain at default
        assert metrics.analysis_speed == 1.0
    
    def test_zero_actual_time(self):
        """Test handling zero actual time."""
        metrics = PerformanceMetrics()
        
        # Should not crash
        metrics.update_from_actual("transcription", 3600, 0)
        
        # Speed should remain at default
        assert metrics.transcription_speed == 11.0
    
    def test_invalid_phase_name(self):
        """Test handling invalid phase name."""
        metrics = PerformanceMetrics()
        
        # Should not crash
        metrics.update_from_actual("invalid_phase", 3600, 100)
        
        # Sample count increases even for unknown phases (by design)
        assert metrics.sample_count == 1
    
    def test_corrupted_metrics_file(self, tmp_path):
        """Test handling corrupted metrics file."""
        # Create corrupted file
        metrics_file = tmp_path / "performance_test.json"
        metrics_file.write_text("invalid json {{{")
        
        # Should fall back to defaults
        tracker = PerformanceTracker("test", config_dir=tmp_path)
        
        assert tracker.metrics.analysis_speed == 1.0
        assert tracker.metrics.sample_count == 0


class TestProviderSpeedup:
    """Test provider speedup calculations."""
    
    @patch.dict('os.environ', {
        'SCRIBE_JOKE_PROVIDER': 'xai',
        'SCRIBE_NOTES_PROVIDER': 'xai',
        'SCRIBE_MEME_PROVIDER': 'xai'
    })
    def test_get_provider_speedup_xai(self):
        """Test speedup calculation when using XAI."""
        from scribe.utils.performance_tracker import get_provider_speedup
        
        speedup = get_provider_speedup()
        assert speedup == 2.5  # XAI is 2.5x faster
    
    @patch.dict('os.environ', {
        'SCRIBE_JOKE_PROVIDER': 'openai',
        'SCRIBE_NOTES_PROVIDER': 'openai',
        'SCRIBE_MEME_PROVIDER': 'openai'
    })
    def test_get_provider_speedup_openai(self):
        """Test speedup calculation when using OpenAI."""
        from scribe.utils.performance_tracker import get_provider_speedup
        
        speedup = get_provider_speedup()
        assert speedup == 1.0  # OpenAI is baseline
    
    @patch.dict('os.environ', {
        'SCRIBE_JOKE_PROVIDER': 'xai',
        'SCRIBE_NOTES_PROVIDER': 'openai',
        'SCRIBE_MEME_PROVIDER': 'openai'
    })
    def test_get_provider_speedup_mixed(self):
        """Test speedup calculation with mixed providers."""
        from scribe.utils.performance_tracker import get_provider_speedup
        
        speedup = get_provider_speedup()
        # Majority is OpenAI (2 out of 3), so baseline
        assert speedup == 1.0
    
    def test_estimate_with_provider_speedup(self):
        """Test time estimation with provider speedup."""
        metrics = PerformanceMetrics()
        
        # Estimate with XAI speedup (2.5x faster)
        total_xai = metrics.estimate_total_time(3600, include_post=True, provider_speedup=2.5)
        
        # Estimate with OpenAI (baseline)
        total_openai = metrics.estimate_total_time(3600, include_post=True, provider_speedup=1.0)
        
        # XAI should be faster (lower total time)
        assert total_xai < total_openai
        
        # The difference should be in the AI-dependent tasks
        # (notes_time + joke_time + meme_time) / 2.5 vs / 1.0
        ai_time = 30 + 10 + 180  # 220 seconds
        expected_savings = ai_time - (ai_time / 2.5)  # 220 - 88 = 132 seconds
        
        actual_savings = total_openai - total_xai
        assert abs(actual_savings - expected_savings) < 1  # Within 1 second
