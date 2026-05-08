"""
Unit tests for audio duration detection and validation.

Tests the get_audio_duration function and its fallback mechanisms.
"""

import wave
from unittest.mock import MagicMock, Mock, patch

import pytest

from scribe.utils.audio import (
    _get_duration_ffprobe,
    _get_duration_torchaudio,
    _get_duration_wave,
    get_audio_duration,
)
from scribe.utils.resource_limits import validate_audio_duration


class TestAudioDurationDetection:
    """Test audio duration detection with multiple methods."""

    def test_get_duration_from_wav_file(self, tmp_path):
        """Test duration detection from WAV file."""
        # Create a 5-second WAV file
        wav_path = tmp_path / "test.wav"
        sample_rate = 16000
        duration_seconds = 5.0
        num_frames = int(sample_rate * duration_seconds)

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"\x00" * (num_frames * 2))

        duration = get_audio_duration(wav_path)

        assert duration is not None
        assert abs(duration - duration_seconds) < 0.01

    def test_get_duration_from_different_sample_rates(self, tmp_path):
        """Test duration detection with different sample rates."""
        test_cases = [
            (8000, 3.0),  # 8kHz, 3 seconds
            (16000, 5.0),  # 16kHz, 5 seconds
            (44100, 2.5),  # 44.1kHz, 2.5 seconds
            (48000, 10.0),  # 48kHz, 10 seconds
        ]

        for sample_rate, duration_seconds in test_cases:
            wav_path = tmp_path / f"test_{sample_rate}.wav"
            num_frames = int(sample_rate * duration_seconds)

            with wave.open(str(wav_path), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sample_rate)
                wav.writeframes(b"\x00" * (num_frames * 2))

            duration = get_audio_duration(wav_path)

            assert duration is not None
            assert abs(duration - duration_seconds) < 0.01

    def test_get_duration_from_stereo_wav(self, tmp_path):
        """Test duration detection from stereo WAV file."""
        wav_path = tmp_path / "stereo.wav"
        sample_rate = 44100
        duration_seconds = 3.0
        num_frames = int(sample_rate * duration_seconds)

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(2)  # Stereo
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"\x00" * (num_frames * 4))  # 2 channels * 2 bytes

        duration = get_audio_duration(wav_path)

        assert duration is not None
        assert abs(duration - duration_seconds) < 0.01

    def test_get_duration_returns_none_for_nonexistent_file(self, tmp_path):
        """Test duration detection returns None for non-existent file."""
        fake_path = tmp_path / "nonexistent.wav"

        duration = get_audio_duration(fake_path)

        assert duration is None

    def test_get_duration_returns_none_for_invalid_wav(self, tmp_path):
        """Test duration detection returns None for invalid WAV file."""
        invalid_path = tmp_path / "invalid.wav"
        invalid_path.write_bytes(b"not a wav file")

        duration = get_audio_duration(invalid_path)

        assert duration is None

    def test_get_duration_handles_corrupted_wav_header(self, tmp_path):
        """Test duration detection handles corrupted WAV header."""
        corrupted_path = tmp_path / "corrupted.wav"

        # Create WAV with corrupted header
        with wave.open(str(corrupted_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00" * 32000)

        # Corrupt the header
        data = corrupted_path.read_bytes()
        corrupted_data = data[:20] + b"\xff\xff\xff\xff" + data[24:]
        corrupted_path.write_bytes(corrupted_data)

        # Should handle gracefully
        duration = get_audio_duration(corrupted_path)

        # May return None or a value depending on corruption
        assert duration is None or isinstance(duration, float)


class TestWavDurationMethod:
    """Test WAV-specific duration detection."""

    def test_wave_method_only_processes_wav_files(self, tmp_path):
        """Test _get_duration_wave only processes .wav files."""
        mp3_path = tmp_path / "test.mp3"
        mp3_path.write_bytes(b"fake mp3")

        duration = _get_duration_wave(mp3_path)

        assert duration is None

    def test_wave_method_handles_zero_framerate(self, tmp_path):
        """Test _get_duration_wave handles zero framerate gracefully."""
        wav_path = tmp_path / "zero_rate.wav"

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00" * 32000)

        # Mock to return zero framerate
        with patch("wave.open") as mock_open:
            mock_wav = MagicMock()
            mock_wav.getnframes.return_value = 16000
            mock_wav.getframerate.return_value = 0
            mock_open.return_value.__enter__.return_value = mock_wav

            duration = _get_duration_wave(wav_path)

            assert duration is None


class TestTorchaudioDurationMethod:
    """Test torchaudio duration detection."""

    def test_torchaudio_method_gets_duration(self, tmp_path):
        """Test _get_duration_torchaudio extracts duration."""
        try:
            import torchaudio as _torchaudio
        except ImportError:
            pytest.skip("torchaudio not available")

        assert _torchaudio is not None
        wav_path = tmp_path / "test.wav"
        sample_rate = 16000
        duration_seconds = 5.0
        num_frames = int(sample_rate * duration_seconds)

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"\x00" * (num_frames * 2))

        duration = _get_duration_torchaudio(wav_path)

        # May return None if torchaudio can't read the file
        if duration is not None:
            assert abs(duration - duration_seconds) < 0.01

    def test_torchaudio_method_returns_none_when_not_available(self, tmp_path):
        """Test _get_duration_torchaudio returns None when torchaudio unavailable."""
        wav_path = tmp_path / "test.wav"

        with patch.dict("sys.modules", {"torchaudio": None}):
            duration = _get_duration_torchaudio(wav_path)

            assert duration is None


class TestFFprobeDurationMethod:
    """Test ffprobe duration detection."""

    def test_ffprobe_method_gets_duration(self, tmp_path):
        """Test _get_duration_ffprobe extracts duration from ffprobe output."""
        wav_path = tmp_path / "test.wav"

        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = '{"format": {"duration": "5.123"}}'

        with patch("subprocess.run", return_value=mock_result):
            with patch("scribe.utils.audio.get_ffprobe_path", return_value="/usr/bin/ffprobe"):
                duration = _get_duration_ffprobe(wav_path)

        assert duration == 5.123

    def test_ffprobe_method_returns_none_when_ffprobe_unavailable(self, tmp_path):
        """Test _get_duration_ffprobe returns None when ffprobe not found."""
        wav_path = tmp_path / "test.wav"

        with patch("scribe.utils.audio.get_ffprobe_path", return_value=None):
            duration = _get_duration_ffprobe(wav_path)

        assert duration is None

    def test_ffprobe_method_handles_stream_duration(self, tmp_path):
        """Test _get_duration_ffprobe extracts duration from stream info."""
        wav_path = tmp_path / "test.wav"

        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = """
        {
            "streams": [
                {"codec_type": "audio", "duration": "10.5"}
            ]
        }
        """

        with patch("subprocess.run", return_value=mock_result):
            with patch("scribe.utils.audio.get_ffprobe_path", return_value="/usr/bin/ffprobe"):
                duration = _get_duration_ffprobe(wav_path)

        assert duration == 10.5

    def test_ffprobe_method_handles_error(self, tmp_path):
        """Test _get_duration_ffprobe handles ffprobe errors."""
        wav_path = tmp_path / "test.wav"

        mock_result = Mock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            with patch("scribe.utils.audio.get_ffprobe_path", return_value="/usr/bin/ffprobe"):
                duration = _get_duration_ffprobe(wav_path)

        assert duration is None


class TestDurationValidation:
    """Test duration validation and correction logic."""

    def test_corrects_suspicious_converted_wav_duration_from_original_media(self, tmp_path):
        """Test converted WAV duration is corrected using the original media file."""
        wav_path = tmp_path / "meeting_16k_mono.wav"
        mp4_path = tmp_path / "meeting.mp4"

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00" * (16000 * 5 * 2))

        mp4_path.write_bytes(b"fake mp4")

        with patch("scribe.utils.audio._get_duration_wave", side_effect=[64801.6, None]):
            with patch("scribe.utils.audio._get_duration_torchaudio", side_effect=[None, 1800.0]):
                with patch("scribe.utils.audio._get_duration_ffprobe", return_value=None):
                    duration = get_audio_duration(wav_path)

        assert duration == 1800.0

    def test_validate_audio_duration_uses_corrected_wav_duration(self, tmp_path):
        """Test resource validation accepts corrected converted WAV duration."""
        wav_path = tmp_path / "meeting_16k_mono.wav"
        mp4_path = tmp_path / "meeting.mp4"

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00" * (16000 * 5 * 2))

        mp4_path.write_bytes(b"fake mp4")

        with patch("scribe.utils.audio._get_duration_wave", side_effect=[64801.6, None]):
            with patch("scribe.utils.audio._get_duration_torchaudio", side_effect=[None, 1800.0]):
                with patch("scribe.utils.audio._get_duration_ffprobe", return_value=None):
                    duration = validate_audio_duration(wav_path, max_duration_hours=12.0)

        assert duration == 1800.0

    def test_prefers_wav_method_over_others(self, tmp_path):
        """Test that WAV method is preferred when available."""
        wav_path = tmp_path / "test.wav"

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"\x00" * 32000)

        with patch("scribe.utils.audio._get_duration_wave", return_value=2.0) as mock_wave:
            with patch(
                "scribe.utils.audio._get_duration_torchaudio", return_value=3.0
            ) as mock_torch:
                with patch(
                    "scribe.utils.audio._get_duration_ffprobe", return_value=4.0
                ) as mock_ffprobe:
                    duration = get_audio_duration(wav_path)

                    # Should use WAV method
                    assert duration == 2.0
                    mock_wave.assert_called_once()
                    mock_torch.assert_not_called()
                    mock_ffprobe.assert_not_called()

    def test_falls_back_to_torchaudio_when_wav_fails(self, tmp_path):
        """Test fallback to torchaudio when WAV method fails."""
        wav_path = tmp_path / "test.wav"

        with patch("scribe.utils.audio._get_duration_wave", return_value=None):
            with patch(
                "scribe.utils.audio._get_duration_torchaudio", return_value=5.0
            ) as mock_torch:
                with patch(
                    "scribe.utils.audio._get_duration_ffprobe", return_value=6.0
                ) as mock_ffprobe:
                    duration = get_audio_duration(wav_path)

                    # Should use torchaudio method
                    assert duration == 5.0
                    mock_torch.assert_called_once()
                    mock_ffprobe.assert_not_called()

    def test_falls_back_to_ffprobe_when_others_fail(self, tmp_path):
        """Test fallback to ffprobe when other methods fail."""
        wav_path = tmp_path / "test.wav"

        with patch("scribe.utils.audio._get_duration_wave", return_value=None):
            with patch("scribe.utils.audio._get_duration_torchaudio", return_value=None):
                with patch(
                    "scribe.utils.audio._get_duration_ffprobe", return_value=7.0
                ) as mock_ffprobe:
                    duration = get_audio_duration(wav_path)

                    # Should use ffprobe method
                    assert duration == 7.0
                    mock_ffprobe.assert_called_once()


class TestEdgeCases:
    """Test edge cases in duration detection."""

    def test_handles_very_short_audio(self, tmp_path):
        """Test duration detection for very short audio (< 1 second)."""
        wav_path = tmp_path / "short.wav"
        sample_rate = 16000
        duration_seconds = 0.1  # 100ms
        num_frames = int(sample_rate * duration_seconds)

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"\x00" * (num_frames * 2))

        duration = get_audio_duration(wav_path)

        assert duration is not None
        assert abs(duration - duration_seconds) < 0.01

    def test_handles_very_long_audio(self, tmp_path):
        """Test duration detection for very long audio (> 1 hour)."""
        sample_rate = 16000
        duration_seconds = 3600.0  # 1 hour
        num_frames = int(sample_rate * duration_seconds)

        wav_path = tmp_path / "long.wav"

        # Mock to return correct frame count
        with patch("scribe.utils.audio.wave.open") as mock_open:
            mock_wav = MagicMock()
            mock_wav.getnframes.return_value = num_frames
            mock_wav.getframerate.return_value = sample_rate
            mock_wav.__enter__ = Mock(return_value=mock_wav)
            mock_wav.__exit__ = Mock(return_value=False)
            mock_open.return_value = mock_wav

            duration = _get_duration_wave(wav_path)

            assert duration is not None
            assert abs(duration - duration_seconds) < 1.0

    def test_handles_empty_wav_file(self, tmp_path):
        """Test duration detection for empty WAV file."""
        wav_path = tmp_path / "empty.wav"

        with wave.open(str(wav_path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(16000)
            wav.writeframes(b"")  # No frames

        duration = get_audio_duration(wav_path)

        assert duration is not None
        assert duration == 0.0
