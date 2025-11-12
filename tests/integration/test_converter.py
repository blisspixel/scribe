"""
Integration tests for audio/video conversion.

Tests conversion with real ffmpeg, handling various formats and edge cases.
"""

import pytest
from pathlib import Path
from unittest.mock import patch, Mock
import subprocess

from scribe.core.converter import Converter
from scribe.exceptions import ProcessError, AudioFormatError


class TestConverter:
    """Test Converter with real ffmpeg operations."""
    
    def test_converter_initialization(self):
        """Test converter initializes with ffmpeg."""
        converter = Converter()
        assert converter.ffmpeg_path is not None
    
    @patch('scribe.core.converter.get_ffmpeg_path')
    def test_converter_no_ffmpeg(self, mock_ffmpeg):
        """Test converter fails gracefully when ffmpeg not found."""
        mock_ffmpeg.return_value = None
        
        with pytest.raises(ProcessError, match="ffmpeg not found"):
            Converter()
    
    def test_convert_to_wav_nonexistent_file(self, tmp_path):
        """Test WAV conversion fails for non-existent file."""
        converter = Converter()
        fake_file = tmp_path / "nonexistent.mp4"
        
        with pytest.raises(AudioFormatError, match="does not exist"):
            converter.convert_to_wav(fake_file)
    
    def test_convert_to_wav_empty_file(self, tmp_path):
        """Test WAV conversion fails for empty file."""
        converter = Converter()
        empty_file = tmp_path / "empty.mp4"
        empty_file.write_text("")
        
        # Should fail during conversion or verification
        with pytest.raises((ProcessError, AudioFormatError)):
            converter.convert_to_wav(empty_file)
    
    def test_convert_to_mp3_nonexistent_file(self, tmp_path):
        """Test MP3 conversion fails for non-existent file."""
        converter = Converter()
        fake_file = tmp_path / "nonexistent.wav"
        
        with pytest.raises(AudioFormatError, match="does not exist"):
            converter.convert_to_mp3(fake_file)
    
    @patch('scribe.core.converter.subprocess.Popen')
    @patch('scribe.core.converter.get_audio_duration')
    def test_convert_to_wav_timeout_protection(self, mock_duration, mock_popen, tmp_path):
        """Test WAV conversion has timeout protection."""
        converter = Converter()
        
        # Create a fake input file
        input_file = tmp_path / "test.mp4"
        input_file.write_bytes(b"fake audio data" * 1000)
        
        # Mock duration
        mock_duration.return_value = 60.0  # 1 minute
        
        # Mock process that never completes (simulates hang)
        mock_process = Mock()
        mock_process.poll.return_value = None  # Never completes
        mock_popen.return_value = mock_process
        
        # Should timeout and raise error
        with pytest.raises(ProcessError, match="timed out"):
            converter.convert_to_wav(input_file)
    
    @patch('scribe.core.converter.subprocess.Popen')
    @patch('scribe.core.converter.get_audio_duration')
    def test_convert_to_mp3_timeout_protection(self, mock_duration, mock_popen, tmp_path):
        """Test MP3 conversion has timeout protection."""
        converter = Converter()
        
        # Create a fake input file
        input_file = tmp_path / "test.wav"
        input_file.write_bytes(b"fake audio data" * 1000)
        
        # Mock duration
        mock_duration.return_value = 60.0
        
        # Mock process that never completes
        mock_process = Mock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        
        # Should timeout
        with pytest.raises(ProcessError, match="timed out"):
            converter.convert_to_mp3(input_file)
    
    def test_convert_to_wav_idempotent(self, tmp_path):
        """Test WAV conversion is idempotent (doesn't reconvert if output exists)."""
        converter = Converter()
        
        # Create fake input and output files
        input_file = tmp_path / "input.mp4"
        input_file.write_bytes(b"fake audio")
        
        output_file = tmp_path / "input_16k_mono.wav"
        output_file.write_bytes(b"fake wav data")
        
        # Make output newer than input
        import time
        time.sleep(0.1)
        output_file.touch()
        
        # Should return existing file without conversion
        result = converter.convert_to_wav(input_file, output_file)
        
        assert result == output_file
    
    def test_convert_to_mp3_idempotent(self, tmp_path):
        """Test MP3 conversion is idempotent."""
        converter = Converter()
        
        # Create fake files
        input_file = tmp_path / "input.wav"
        input_file.write_bytes(b"fake audio")
        
        output_file = tmp_path / "input.mp3"
        output_file.write_bytes(b"fake mp3 data")
        
        # Make output newer
        import time
        time.sleep(0.1)
        output_file.touch()
        
        # Should return existing file
        result = converter.convert_to_mp3(input_file, output_file)
        
        assert result == output_file
    
    @patch('scribe.core.converter.subprocess.Popen')
    @patch('scribe.core.converter.get_audio_duration')
    @patch('scribe.core.converter.verify_file_content')
    def test_convert_to_wav_uses_dynaudnorm(self, mock_verify, mock_duration, mock_popen, tmp_path):
        """Test WAV conversion uses dynaudnorm filter."""
        converter = Converter()
        
        # Create input file
        input_file = tmp_path / "test.mp4"
        input_file.write_bytes(b"fake audio data" * 1000)
        
        # Create output file but make it OLDER than input (force reconversion)
        output_file = tmp_path / "custom_output.wav"
        output_file.write_bytes(b"old fake wav" * 100)
        
        # Make input file newer by touching it
        import time
        time.sleep(0.1)
        input_file.touch()
        
        mock_duration.return_value = 10.0
        
        # Mock successful process
        mock_process = Mock()
        mock_process.poll.side_effect = [None, None, 0]  # Running, running, then done
        mock_process.returncode = 0
        mock_process.communicate.return_value = ("", "")
        mock_popen.return_value = mock_process
        
        result = converter.convert_to_wav(input_file, output_file)
        
        # Verify ffmpeg was called with dynaudnorm
        assert mock_popen.called, "Popen was not called"
        call_args = mock_popen.call_args[0][0]
        assert any("dynaudnorm" in str(arg) for arg in call_args), \
            f"dynaudnorm not found in ffmpeg command: {call_args}"
    
    @patch('scribe.core.converter.subprocess.Popen')
    @patch('scribe.core.converter.get_audio_duration')
    @patch('scribe.core.converter.verify_file_content')
    def test_convert_stdin_devnull(self, mock_verify, mock_duration, mock_popen, tmp_path):
        """Test conversion uses stdin=DEVNULL to prevent hanging on prompts."""
        converter = Converter()
        
        # Create input file
        input_file = tmp_path / "test.mp4"
        input_file.write_bytes(b"fake audio" * 1000)
        
        # Create output file but make it OLDER than input
        output_file = tmp_path / "custom_output.wav"
        output_file.write_bytes(b"old fake wav" * 100)
        
        # Make input newer
        import time
        time.sleep(0.1)
        input_file.touch()
        
        mock_duration.return_value = 10.0
        
        mock_process = Mock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.returncode = 0
        mock_process.communicate.return_value = ("", "")
        mock_popen.return_value = mock_process
        
        converter.convert_to_wav(input_file, output_file)
        
        # Verify stdin=DEVNULL was used
        assert mock_popen.called, "Popen was not called"
        call_kwargs = mock_popen.call_args[1]
        assert call_kwargs.get('stdin') == subprocess.DEVNULL


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    @patch('scribe.core.converter.Converter')
    def test_convert_to_wav_function(self, mock_converter_class, tmp_path):
        """Test convert_to_wav convenience function."""
        from scribe.core.converter import convert_to_wav
        
        mock_converter = Mock()
        mock_converter_class.return_value = mock_converter
        mock_converter.convert_to_wav.return_value = tmp_path / "output.wav"
        
        input_file = tmp_path / "input.mp4"
        result = convert_to_wav(input_file)
        
        mock_converter.convert_to_wav.assert_called_once_with(input_file)
        assert result == tmp_path / "output.wav"
    
    @patch('scribe.core.converter.Converter')
    def test_convert_to_mp3_function(self, mock_converter_class, tmp_path):
        """Test convert_to_mp3 convenience function."""
        from scribe.core.converter import convert_to_mp3
        
        mock_converter = Mock()
        mock_converter_class.return_value = mock_converter
        mock_converter.convert_to_mp3.return_value = tmp_path / "output.mp3"
        
        input_file = tmp_path / "input.wav"
        result = convert_to_mp3(input_file)
        
        mock_converter.convert_to_mp3.assert_called_once_with(input_file)
        assert result == tmp_path / "output.mp3"


# TODO: Add real integration tests with actual audio files
# These would require test fixtures with real audio/video files
# and would be slower but more comprehensive
