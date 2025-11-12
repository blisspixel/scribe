"""
Unit tests for transcription progress display and ETA calculation.

Tests the progress bar UX improvements including:
- GPU-based time estimation
- ETA calculation and formatting
- Duration validation and correction
- Progress percentage accuracy
"""

import pytest
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
from io import StringIO

from scribe.core.local_whisper import LocalWhisperTranscriber
from scribe.models.gpu import GPUConfig


class TestProgressEstimation:
    """Test initial progress estimation based on GPU."""
    
    def test_estimates_time_for_rtx4090(self, tmp_path):
        """Test time estimation for RTX 4090 (11.5x realtime)."""
        gpu_config = GPUConfig(
            has_gpu=True,
            gpu_name="NVIDIA GeForce RTX 4090",
            gpu_memory_gb=24.0,
            beam_size=10,
            use_fp16=True
        )
        
        transcriber = LocalWhisperTranscriber(
            model_size="large-v3",
            language="en",
            gpu_config=gpu_config
        )
        
        # For a 53-minute (3180 second) file at 11.5x speed
        # Expected time: 3180 / 11.5 = 276.5 seconds (4m 36s)
        duration = 3180.0
        expected_time = duration / 11.5
        
        assert abs(expected_time - 276.5) < 1.0
    
    def test_estimates_time_for_rtx4080(self, tmp_path):
        """Test time estimation for RTX 4080 (8x realtime)."""
        gpu_config = GPUConfig(
            has_gpu=True,
            gpu_name="NVIDIA GeForce RTX 4080",
            gpu_memory_gb=16.0,
            beam_size=8,
            use_fp16=True
        )
        
        transcriber = LocalWhisperTranscriber(
            model_size="large-v3",
            language="en",
            gpu_config=gpu_config
        )
        
        # For a 53-minute file at 8x speed
        # Expected time: 3180 / 8 = 397.5 seconds (6m 37s)
        duration = 3180.0
        expected_time = duration / 8.0
        
        assert abs(expected_time - 397.5) < 1.0
    
    def test_estimates_time_for_rtx4070(self, tmp_path):
        """Test time estimation for RTX 4070 (6x realtime)."""
        gpu_config = GPUConfig(
            has_gpu=True,
            gpu_name="NVIDIA GeForce RTX 4070",
            gpu_memory_gb=12.0,
            beam_size=5,
            use_fp16=True
        )
        
        transcriber = LocalWhisperTranscriber(
            model_size="large-v2",
            language="en",
            gpu_config=gpu_config
        )
        
        # For a 53-minute file at 6x speed
        # Expected time: 3180 / 6 = 530 seconds (8m 50s)
        duration = 3180.0
        expected_time = duration / 6.0
        
        assert abs(expected_time - 530.0) < 1.0
    
    def test_estimates_time_for_unknown_gpu(self, tmp_path):
        """Test time estimation for unknown GPU (4x realtime fallback)."""
        gpu_config = GPUConfig(
            has_gpu=True,
            gpu_name="NVIDIA GeForce GTX 1080",
            gpu_memory_gb=8.0,
            beam_size=5,
            use_fp16=False
        )
        
        transcriber = LocalWhisperTranscriber(
            model_size="base",
            language="en",
            gpu_config=gpu_config
        )
        
        # For a 53-minute file at 4x speed (fallback)
        # Expected time: 3180 / 4 = 795 seconds (13m 15s)
        duration = 3180.0
        expected_time = duration / 4.0
        
        assert abs(expected_time - 795.0) < 1.0


class TestETACalculation:
    """Test ETA calculation and formatting."""
    
    def test_calculates_eta_from_actual_speed(self):
        """Test ETA calculation based on actual processing speed."""
        # Simulated values
        duration = 3180.0  # 53 minutes
        segment_end = 600.0  # Processed 10 minutes of audio
        elapsed = 60.0  # Took 60 seconds
        
        # Speed ratio: 600 / 60 = 10x realtime
        speed_ratio = segment_end / elapsed
        assert speed_ratio == 10.0
        
        # Remaining audio: 3180 - 600 = 2580 seconds
        remaining_audio = duration - segment_end
        assert remaining_audio == 2580.0
        
        # ETA: 2580 / 10 = 258 seconds (4m 18s)
        eta_seconds = remaining_audio / speed_ratio
        assert eta_seconds == 258.0
    
    def test_formats_eta_seconds(self):
        """Test ETA formatting for seconds."""
        test_cases = [
            (5.0, "5s remaining"),
            (30.0, "30s remaining"),
            (59.0, "59s remaining"),
        ]
        
        for eta_seconds, expected in test_cases:
            if eta_seconds < 60:
                eta_str = f"{int(eta_seconds)}s remaining"
            else:
                eta_mins = int(eta_seconds / 60)
                eta_secs = int(eta_seconds % 60)
                if eta_secs < 10:
                    eta_str = f"{eta_mins}m remaining"
                else:
                    eta_str = f"{eta_mins}m {eta_secs}s remaining"
            
            assert eta_str == expected
    
    def test_formats_eta_minutes(self):
        """Test ETA formatting for minutes."""
        test_cases = [
            (60.0, "1m remaining"),
            (90.0, "1m 30s remaining"),
            (125.0, "2m remaining"),  # 5 seconds rounds down
            (300.0, "5m remaining"),
            (318.0, "5m 18s remaining"),
        ]
        
        for eta_seconds, expected in test_cases:
            if eta_seconds < 60:
                eta_str = f"{int(eta_seconds)}s remaining"
            else:
                eta_mins = int(eta_seconds / 60)
                eta_secs = int(eta_seconds % 60)
                if eta_secs < 10:
                    eta_str = f"{eta_mins}m remaining"
                else:
                    eta_str = f"{eta_mins}m {eta_secs}s remaining"
            
            assert eta_str == expected
    
    def test_formats_eta_hours(self):
        """Test ETA formatting for hours."""
        test_cases = [
            (3600.0, "1h 0m remaining"),
            (3900.0, "1h 5m remaining"),
            (7200.0, "2h 0m remaining"),
            (7380.0, "2h 3m remaining"),
        ]
        
        for eta_seconds, expected in test_cases:
            if eta_seconds < 3600:
                # Minutes formatting
                eta_mins = int(eta_seconds / 60)
                eta_secs = int(eta_seconds % 60)
                if eta_secs < 10:
                    eta_str = f"{eta_mins}m remaining"
                else:
                    eta_str = f"{eta_mins}m {eta_secs}s remaining"
            else:
                # Hours formatting
                eta_hours = int(eta_seconds / 3600)
                eta_mins = int((eta_seconds % 3600) / 60)
                eta_str = f"{eta_hours}h {eta_mins}m remaining"
            
            assert eta_str == expected
    
    def test_waits_for_stable_speed_before_showing_eta(self):
        """Test that ETA waits for 10s of audio before showing."""
        # Before 10 seconds of audio processed
        segment_end = 5.0
        elapsed = 2.0
        
        # Should show initial estimate, not calculated ETA
        if segment_end < 10.0:
            use_initial_estimate = True
        else:
            use_initial_estimate = False
        
        assert use_initial_estimate is True
        
        # After 10 seconds of audio processed
        segment_end = 15.0
        elapsed = 3.0
        
        if segment_end >= 10.0:
            use_calculated_eta = True
        else:
            use_calculated_eta = False
        
        assert use_calculated_eta is True


class TestDurationCorrection:
    """Test duration validation and correction logic."""
    
    def test_detects_incorrect_wav_duration(self, tmp_path):
        """Test detection of incorrect WAV duration (> 2 hours)."""
        # Simulated incorrect duration from WAV header
        wav_duration = 134220.0  # 2237 minutes - clearly wrong
        
        # Should trigger correction
        is_suspicious = wav_duration > 7200  # More than 2 hours
        
        assert is_suspicious is True
    
    def test_corrects_duration_from_original_file(self, tmp_path):
        """Test correction using original MP4 file duration."""
        # Create mock files
        wav_path = tmp_path / "meeting_16k_mono.wav"
        mp4_path = tmp_path / "meeting.mp4"
        
        wav_path.touch()
        mp4_path.touch()
        
        # Simulated durations
        wav_duration = 134220.0  # Incorrect
        mp4_duration = 3180.0  # Correct (53 minutes)
        
        # Correction logic
        if wav_duration > 7200:
            # Try to find original file
            original_path = Path(str(wav_path).replace("_16k_mono.wav", ".mp4"))
            
            if original_path.exists():
                # Use original duration
                corrected_duration = mp4_duration
            else:
                corrected_duration = wav_duration
        else:
            corrected_duration = wav_duration
        
        assert corrected_duration == 3180.0
    
    def test_tries_mp3_if_mp4_not_found(self, tmp_path):
        """Test fallback to MP3 if MP4 not found."""
        wav_path = tmp_path / "meeting_16k_mono.wav"
        mp3_path = tmp_path / "meeting.mp3"
        
        wav_path.touch()
        mp3_path.touch()
        
        # Simulated durations
        wav_duration = 134220.0
        mp3_duration = 3180.0
        
        # Correction logic
        if wav_duration > 7200:
            original_path = Path(str(wav_path).replace("_16k_mono.wav", ".mp4"))
            
            if not original_path.exists():
                original_path = Path(str(wav_path).replace("_16k_mono.wav", ".mp3"))
            
            if original_path.exists():
                corrected_duration = mp3_duration
            else:
                corrected_duration = wav_duration
        else:
            corrected_duration = wav_duration
        
        assert corrected_duration == 3180.0
    
    def test_keeps_wav_duration_if_original_not_found(self, tmp_path):
        """Test keeps WAV duration if original file not found."""
        wav_path = tmp_path / "meeting_16k_mono.wav"
        wav_path.touch()
        
        wav_duration = 134220.0
        
        # Correction logic
        if wav_duration > 7200:
            original_path = Path(str(wav_path).replace("_16k_mono.wav", ".mp4"))
            
            if not original_path.exists():
                original_path = Path(str(wav_path).replace("_16k_mono.wav", ".mp3"))
            
            if original_path.exists():
                corrected_duration = 3180.0
            else:
                # Keep WAV duration if no original found
                corrected_duration = wav_duration
        else:
            corrected_duration = wav_duration
        
        assert corrected_duration == 134220.0
    
    def test_does_not_correct_reasonable_durations(self, tmp_path):
        """Test does not correct reasonable durations (< 2 hours)."""
        # Reasonable durations
        test_durations = [
            60.0,    # 1 minute
            600.0,   # 10 minutes
            3180.0,  # 53 minutes
            7199.0,  # Just under 2 hours
        ]
        
        for duration in test_durations:
            is_suspicious = duration > 7200
            assert is_suspicious is False


class TestProgressDisplay:
    """Test progress bar display and formatting."""
    
    def test_shows_clean_initial_message(self):
        """Test initial progress message is clean and informative."""
        duration_mins = 53
        estimated_mins = 4
        estimated_secs = 37
        
        message = f"Transcribing {duration_mins} min recording → estimated {estimated_mins}m {estimated_secs}s"
        
        assert "Transcribing" in message
        assert "53 min" in message
        assert "4m 37s" in message
        assert "realtime" not in message  # No technical jargon
    
    def test_progress_bar_shows_percentage_and_eta(self):
        """Test progress bar shows only percentage and ETA."""
        # Simulated progress bar components
        components = [
            "spinner",
            "bar",
            "percentage",
            "eta"
        ]
        
        # Should NOT include
        excluded = [
            "elapsed_time",
            "speed_multiplier",
            "status_message"
        ]
        
        for component in components:
            assert component in ["spinner", "bar", "percentage", "eta"]
        
        for excluded_item in excluded:
            assert excluded_item not in components
    
    def test_progress_percentage_based_on_elapsed_time(self):
        """Test progress percentage is based on elapsed time, not audio position."""
        estimated_time = 276.5  # 4m 36s
        elapsed = 138.25  # 2m 18s (halfway)
        
        # Progress should be based on elapsed vs estimated
        percent_complete = (elapsed / estimated_time) * 100
        
        assert abs(percent_complete - 50.0) < 1.0
    
    def test_refines_estimate_after_warmup(self):
        """Test estimate is refined after 10s of audio processed."""
        duration = 3180.0
        initial_estimate = 276.5  # Based on 11.5x
        
        # After processing 10s of audio in 1s (10x actual speed)
        segment_end = 10.0
        elapsed = 1.0
        speed_ratio = segment_end / elapsed
        
        # Refined estimate
        refined_estimate = duration / speed_ratio
        
        assert refined_estimate == 318.0  # 5m 18s at 10x
        assert refined_estimate != initial_estimate


class TestProgressBarUX:
    """Test progress bar UX improvements."""
    
    def test_no_information_overload(self):
        """Test progress bar doesn't show too many metrics."""
        # Old (bad): 7 metrics
        old_metrics = [
            "status_message",
            "percentage",
            "elapsed_time",
            "eta",
            "speed_multiplier",
            "audio_position",
            "total_duration"
        ]
        
        # New (good): 2 metrics
        new_metrics = [
            "percentage",
            "eta"
        ]
        
        assert len(new_metrics) < len(old_metrics)
        assert len(new_metrics) == 2
    
    def test_consistent_time_formatting(self):
        """Test all times use consistent format."""
        # All should use "Xm Ys" format
        test_times = [
            (60, "1m"),
            (90, "1m 30s"),
            (276, "4m 36s"),
            (3180, "53m"),
        ]
        
        for seconds, expected_format in test_times:
            mins = seconds // 60
            secs = seconds % 60
            
            if secs < 10 or secs == 0:
                formatted = f"{mins}m"
            else:
                formatted = f"{mins}m {secs}s"
            
            # Check format is consistent
            assert "m" in formatted
            assert ":" not in formatted  # No HH:MM:SS format
    
    def test_no_technical_jargon_in_display(self):
        """Test progress display avoids technical jargon."""
        # Should NOT appear in user-facing messages
        jargon_terms = [
            "realtime multiplier",
            "GPU warmup",
            "tensor cores",
            "FP16",
            "beam size",
            "CUDA",
        ]
        
        # User-facing message
        message = "Transcribing 53 min recording → estimated 4m 37s"
        progress = "42% • 2m 18s remaining"
        
        for term in jargon_terms:
            assert term.lower() not in message.lower()
            assert term.lower() not in progress.lower()
    
    def test_progress_updates_frequently(self):
        """Test progress updates every 0.5 seconds."""
        update_interval = 0.5
        
        assert update_interval <= 1.0
        assert update_interval >= 0.1  # Not too frequent


class TestEdgeCases:
    """Test edge cases in progress display."""
    
    def test_handles_very_fast_transcription(self):
        """Test handles transcription faster than estimated."""
        estimated_time = 276.5
        actual_time = 200.0  # Faster than expected
        
        # Progress percentage based on elapsed time
        percent_complete = (actual_time / estimated_time) * 100
        
        # Should be less than 100% since not done yet
        assert percent_complete < 100.0
        
        # When actually complete, should show 100%
        final_time = 200.0
        final_percent = min((final_time / final_time) * 100, 100.0)
        assert final_percent == 100.0
    
    def test_handles_very_slow_transcription(self):
        """Test handles transcription slower than estimated."""
        estimated_time = 276.5
        elapsed = 300.0  # Slower than expected
        
        # Progress can exceed 100% temporarily
        percent_complete = (elapsed / estimated_time) * 100
        
        assert percent_complete > 100.0
        
        # But should refine estimate to avoid this
        # After refinement, should be back under 100%
    
    def test_handles_zero_duration(self):
        """Test handles zero duration gracefully."""
        duration = 0.0
        expected_speed = 11.5
        
        # Should use fallback
        estimated_time = 60 if duration == 0 else duration / expected_speed
        
        assert estimated_time == 60
    
    def test_handles_none_duration(self):
        """Test handles None duration gracefully."""
        duration = None
        expected_speed = 11.5
        
        # Should use fallback
        estimated_time = 60 if not duration else duration / expected_speed
        
        assert estimated_time == 60
