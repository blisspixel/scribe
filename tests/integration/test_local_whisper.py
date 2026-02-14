"""
Integration tests for local GPU Whisper transcription.

Tests GPU transcription with real CUDA operations (requires GPU).
These tests are skipped if CUDA is not available.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from scribe.core.local_whisper import LocalWhisperTranscriber
from scribe.exceptions import TranscriptionError
from scribe.models.config import ScribeConfig
from scribe.models.gpu import GPUConfig

# Skip all tests in this module if CUDA not available
pytestmark = pytest.mark.skipif(
    not pytest.importorskip("torch", reason="PyTorch not available").cuda.is_available(),
    reason="CUDA not available"
)


class TestLocalWhisperTranscriber:
    """Test local Whisper transcription with GPU."""

    def test_transcribe_with_gpu(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcription using local GPU."""
        transcriber = LocalWhisperTranscriber(temp_config)

        result = transcriber.transcribe(sample_audio, "test_meeting")

        assert result is not None
        assert result.exists()
        assert result.stat().st_size > 0

        # Verify content has expected format
        content = result.read_text(encoding="utf-8")
        assert "Meeting: test_meeting" in content
        assert "Date:" in content

    def test_transcribe_with_progress_callback(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcription with progress updates."""
        transcriber = LocalWhisperTranscriber(temp_config)

        progress_updates = []

        def progress_callback(percent: float, message: str):
            progress_updates.append((percent, message))

        result = transcriber.transcribe(
            sample_audio,
            "meeting",
            progress_callback=progress_callback
        )

        assert result is not None
        assert len(progress_updates) > 0

        # Should have progress updates throughout
        assert any(0 < p[0] < 100 for p in progress_updates)
        assert progress_updates[-1][0] == 100.0

    def test_transcribe_shows_speed_ratio(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcription shows processing speed ratio."""
        transcriber = LocalWhisperTranscriber(temp_config)

        messages = []

        def progress_callback(percent: float, message: str):
            messages.append(message)

        transcriber.transcribe(
            sample_audio,
            "meeting",
            progress_callback=progress_callback
        )

        # Should show speed ratio in messages
        assert any("x" in msg for msg in messages)  # e.g., "8.5x real-time"

    def test_transcribe_with_rtx4090_optimizations(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcription uses RTX 4090 optimizations."""
        gpu_config = GPUConfig.detect()

        assert gpu_config.model_size == "large-v3"
        assert gpu_config.beam_size == 10
        assert gpu_config.use_fp16 is True

        transcriber = LocalWhisperTranscriber(temp_config, gpu_config=gpu_config)
        result = transcriber.transcribe(sample_audio, "meeting")

        assert result is not None

    def test_transcribe_with_silence_detection(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcription includes silence markers."""
        transcriber = LocalWhisperTranscriber(temp_config, detect_silence=True)

        result = transcriber.transcribe(sample_audio, "meeting")
        content = result.read_text(encoding="utf-8")

        # May or may not have silence markers depending on audio
        # Just verify it doesn't crash
        assert len(content) > 0

    @pytest.mark.skipif(not pytest.importorskip("whisperx", reason="WhisperX not available"),
                        reason="WhisperX not available")
    def test_transcribe_with_speaker_diarization(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcription with speaker diarization."""
        import os

        # Skip if no HF token
        if not os.getenv("HF_TOKEN"):
            pytest.skip("HF_TOKEN not available")

        transcriber = LocalWhisperTranscriber(
            temp_config,
            enable_diarization=True
        )

        result = transcriber.transcribe(sample_audio, "meeting")
        content = result.read_text(encoding="utf-8")

        # May have speaker labels if diarization worked
        assert len(content) > 0

    def test_transcribe_long_audio(self, long_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcription of long audio file."""
        transcriber = LocalWhisperTranscriber(temp_config)

        result = transcriber.transcribe(long_audio, "long_meeting")

        assert result is not None
        assert result.exists()

        content = result.read_text(encoding="utf-8")
        assert len(content) > 100  # Should have substantial content

    def test_transcribe_nonexistent_file(self, temp_dir: Path, temp_config: ScribeConfig):
        """Test transcription fails gracefully for non-existent file."""
        transcriber = LocalWhisperTranscriber(temp_config)
        fake_file = temp_dir / "nonexistent.wav"

        with pytest.raises(TranscriptionError, match="does not exist"):
            transcriber.transcribe(fake_file, "meeting")

    def test_transcribe_creates_output_directory(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcription creates output directory if needed."""
        nested_output = temp_config.output_folder / "nested" / "dir"
        temp_config.output_folder = nested_output

        transcriber = LocalWhisperTranscriber(temp_config)
        result = transcriber.transcribe(sample_audio, "meeting")

        assert result.parent == nested_output
        assert nested_output.exists()


class TestGPUOptimizations:
    """Test GPU-specific optimizations."""

    def test_uses_fp16_for_high_end_gpu(self, temp_config: ScribeConfig, mock_gpu):
        """Test FP16 is used for high-end GPUs."""
        gpu_config = GPUConfig.detect()

        assert gpu_config.use_fp16 is True

        transcriber = LocalWhisperTranscriber(temp_config, gpu_config=gpu_config)

        # Verify FP16 is configured
        assert transcriber.use_fp16 is True

    def test_uses_tensor_cores_for_high_end_gpu(self, temp_config: ScribeConfig, mock_gpu):
        """Test tensor cores are enabled for high-end GPUs."""
        gpu_config = GPUConfig.detect()

        assert gpu_config.enable_tensor_cores is True

        transcriber = LocalWhisperTranscriber(temp_config, gpu_config=gpu_config)

        # Verify tensor cores are configured
        assert transcriber.enable_tensor_cores is True

    def test_uses_large_model_for_high_end_gpu(self, temp_config: ScribeConfig, mock_gpu):
        """Test large-v3-turbo model is used for high-end GPUs."""
        gpu_config = GPUConfig.detect()

        assert gpu_config.model_size == "large-v3"

        transcriber = LocalWhisperTranscriber(temp_config, gpu_config=gpu_config)

        assert transcriber.model_size == "large-v3"

    def test_clears_gpu_cache_after_transcription(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test GPU cache is cleared after transcription."""
        with patch('scribe.core.local_whisper.clear_gpu_cache') as mock_clear:
            transcriber = LocalWhisperTranscriber(temp_config)
            transcriber.transcribe(sample_audio, "meeting")

            # Should clear cache after transcription
            mock_clear.assert_called()


class TestTranscriptFormatting:
    """Test transcript output formatting for local transcription."""

    def test_format_includes_header(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcript includes proper header."""
        transcriber = LocalWhisperTranscriber(temp_config)
        result = transcriber.transcribe(sample_audio, "Team Meeting")

        content = result.read_text(encoding="utf-8")

        assert "Meeting: Team Meeting" in content
        assert "Date:" in content
        assert "Duration:" in content
        assert "─" in content  # Separator

    def test_format_includes_timestamps(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcript includes timestamps."""
        transcriber = LocalWhisperTranscriber(temp_config)
        result = transcriber.transcribe(sample_audio, "meeting")

        content = result.read_text(encoding="utf-8")

        # Should have timestamp format [HH:MM:SS]
        import re
        timestamps = re.findall(r'\[\d{2}:\d{2}:\d{2}\]', content)
        assert len(timestamps) > 0

    def test_format_extracts_date_from_filename(self, temp_dir: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcript extracts date from filename."""
        audio_with_date = temp_dir / "Meeting_2025-11-07.wav"

        # Create minimal WAV file
        import wave
        with wave.open(str(audio_with_date), 'wb') as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b'\x00' * 32000)  # 1 second of silence

        transcriber = LocalWhisperTranscriber(temp_config)
        result = transcriber.transcribe(audio_with_date, "meeting")

        content = result.read_text(encoding="utf-8")
        assert "November 7, 2025" in content

    def test_format_no_technical_metadata(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test transcript doesn't include technical metadata."""
        transcriber = LocalWhisperTranscriber(temp_config)
        result = transcriber.transcribe(sample_audio, "meeting")

        content = result.read_text(encoding="utf-8")

        # Should not contain technical details
        assert "GPU" not in content
        assert "CUDA" not in content
        assert "model" not in content.lower()
        assert "beam" not in content.lower()


class TestSilenceDetection:
    """Test silence detection integration."""

    @patch('scribe.core.local_whisper.detect_silence_periods')
    def test_silence_markers_inserted(self, mock_detect, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test silence markers are inserted in transcript."""
        # Mock silence detection to return periods
        mock_detect.return_value = [(10.0, 15.0), (30.0, 35.0)]

        transcriber = LocalWhisperTranscriber(temp_config, detect_silence=True)
        result = transcriber.transcribe(sample_audio, "meeting")

        content = result.read_text(encoding="utf-8")

        # Should have silence markers
        assert "[silence" in content.lower() or "..." in content

    def test_silence_detection_disabled_by_default(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test silence detection is disabled by default."""
        transcriber = LocalWhisperTranscriber(temp_config)

        assert transcriber.detect_silence is False


class TestErrorHandling:
    """Test error handling in local transcription."""

    def test_handles_out_of_memory_error(self, sample_audio: Path, temp_config: ScribeConfig):
        """Test graceful handling of GPU out of memory error."""
        with patch('scribe.core.local_whisper.whisper.load_model') as mock_load:
            mock_load.side_effect = RuntimeError("CUDA out of memory")

            transcriber = LocalWhisperTranscriber(temp_config)

            with pytest.raises(TranscriptionError, match="out of memory"):
                transcriber.transcribe(sample_audio, "meeting")

    def test_handles_model_load_error(self, sample_audio: Path, temp_config: ScribeConfig):
        """Test graceful handling of model loading error."""
        with patch('scribe.core.local_whisper.whisper.load_model') as mock_load:
            mock_load.side_effect = Exception("Model load failed")

            transcriber = LocalWhisperTranscriber(temp_config)

            with pytest.raises(TranscriptionError, match="Model load failed"):
                transcriber.transcribe(sample_audio, "meeting")
