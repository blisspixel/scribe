"""
Integration tests for OpenAI API transcription.

Tests chunking, combining, and the regression test for the blank file bug
where large files resulted in empty transcripts.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, call

from scribe.core.openai_api import OpenAITranscriber
from scribe.models.config import ScribeConfig
from scribe.exceptions import TranscriptionError


class TestOpenAITranscriber:
    """Test OpenAI API transcription with chunking."""
    
    def test_transcribe_short_audio(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcribing short audio file (< 25MB)."""
        transcriber = OpenAITranscriber(temp_config)
        
        result = transcriber.transcribe(sample_audio, "test_meeting")
        
        assert result is not None
        assert result.exists()
        assert result.stat().st_size > 0
        
        # Verify OpenAI API was called once
        mock_openai.audio.transcriptions.create.assert_called_once()
    
    def test_transcribe_with_progress_callback(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcription with progress callback."""
        transcriber = OpenAITranscriber(temp_config)
        
        progress_updates = []
        
        def progress_callback(percent: float, message: str):
            progress_updates.append((percent, message))
        
        result = transcriber.transcribe(
            sample_audio,
            "test_meeting",
            progress_callback=progress_callback
        )
        
        assert result is not None
        assert len(progress_updates) > 0
        assert progress_updates[-1][0] == 100.0
    
    @patch('scribe.core.openai_api.get_audio_duration')
    def test_transcribe_large_file_chunking(self, mock_duration, long_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcription of large file uses chunking (regression test for blank file bug)."""
        # Mock duration to be 30 minutes (requires chunking)
        mock_duration.return_value = 1800.0
        
        # Mock OpenAI to return different text for each chunk
        mock_responses = [
            Mock(text="Chunk 1 transcript."),
            Mock(text="Chunk 2 transcript."),
            Mock(text="Chunk 3 transcript.")
        ]
        mock_openai.audio.transcriptions.create.side_effect = mock_responses
        
        transcriber = OpenAITranscriber(temp_config)
        result = transcriber.transcribe(long_audio, "long_meeting")
        
        assert result is not None
        assert result.exists()
        
        # Verify file is not empty (regression test)
        content = result.read_text(encoding="utf-8")
        assert len(content) > 0
        assert "Chunk 1" in content
        assert "Chunk 2" in content
        assert "Chunk 3" in content
        
        # Verify multiple API calls were made
        assert mock_openai.audio.transcriptions.create.call_count == 3
    
    def test_transcribe_combines_chunks_correctly(self, long_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test that chunks are combined in correct order with proper formatting."""
        # Mock OpenAI to return timestamped chunks
        mock_responses = [
            Mock(text="[00:00:00] First part of meeting."),
            Mock(text="[00:10:00] Middle part of meeting."),
            Mock(text="[00:20:00] Final part of meeting.")
        ]
        mock_openai.audio.transcriptions.create.side_effect = mock_responses
        
        transcriber = OpenAITranscriber(temp_config)
        result = transcriber.transcribe(long_audio, "meeting")
        
        content = result.read_text(encoding="utf-8")
        
        # Verify chunks are in order
        first_pos = content.find("First part")
        middle_pos = content.find("Middle part")
        final_pos = content.find("Final part")
        
        assert first_pos < middle_pos < final_pos
    
    def test_transcribe_nonexistent_file(self, temp_dir: Path, temp_config: ScribeConfig):
        """Test transcription fails gracefully for non-existent file."""
        transcriber = OpenAITranscriber(temp_config)
        fake_file = temp_dir / "nonexistent.wav"
        
        with pytest.raises(TranscriptionError, match="does not exist"):
            transcriber.transcribe(fake_file, "meeting")
    
    def test_transcribe_invalid_api_key(self, sample_audio: Path, temp_config: ScribeConfig):
        """Test transcription fails with invalid API key."""
        # Set invalid API key
        temp_config.openai_api_key = "invalid-key"
        
        transcriber = OpenAITranscriber(temp_config)
        
        with pytest.raises(TranscriptionError, match="API key"):
            transcriber.transcribe(sample_audio, "meeting")
    
    @patch('scribe.core.openai_api.OpenAI')
    def test_transcribe_api_error_handling(self, mock_openai_class, sample_audio: Path, temp_config: ScribeConfig):
        """Test transcription handles API errors gracefully."""
        # Mock OpenAI to raise an error
        mock_client = Mock()
        mock_client.audio.transcriptions.create.side_effect = Exception("API Error")
        mock_openai_class.return_value = mock_client
        
        transcriber = OpenAITranscriber(temp_config)
        
        with pytest.raises(TranscriptionError, match="API Error"):
            transcriber.transcribe(sample_audio, "meeting")
    
    def test_transcribe_creates_output_directory(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcription creates output directory if needed."""
        # Set output to nested directory
        nested_output = temp_config.output_folder / "nested" / "dir"
        temp_config.output_folder = nested_output
        
        transcriber = OpenAITranscriber(temp_config)
        result = transcriber.transcribe(sample_audio, "meeting")
        
        assert result.parent == nested_output
        assert nested_output.exists()


class TestChunkingLogic:
    """Test audio chunking logic for large files."""
    
    @patch('scribe.core.openai_api.get_audio_duration')
    def test_calculate_chunks_small_file(self, mock_duration, sample_audio: Path, temp_config: ScribeConfig):
        """Test chunk calculation for small file (no chunking needed)."""
        mock_duration.return_value = 300.0  # 5 minutes
        
        transcriber = OpenAITranscriber(temp_config)
        chunks = transcriber._calculate_chunks(sample_audio)
        
        assert len(chunks) == 1
        assert chunks[0]["start"] == 0
        assert chunks[0]["duration"] == 300.0
    
    @patch('scribe.core.openai_api.get_audio_duration')
    def test_calculate_chunks_large_file(self, mock_duration, long_audio: Path, temp_config: ScribeConfig):
        """Test chunk calculation for large file (requires chunking)."""
        mock_duration.return_value = 1800.0  # 30 minutes
        
        transcriber = OpenAITranscriber(temp_config)
        chunks = transcriber._calculate_chunks(long_audio, chunk_duration=600)  # 10 min chunks
        
        assert len(chunks) == 3
        assert chunks[0]["start"] == 0
        assert chunks[0]["duration"] == 600
        assert chunks[1]["start"] == 600
        assert chunks[1]["duration"] == 600
        assert chunks[2]["start"] == 1200
        assert chunks[2]["duration"] == 600
    
    @patch('scribe.core.openai_api.get_audio_duration')
    def test_calculate_chunks_uneven_division(self, mock_duration, long_audio: Path, temp_config: ScribeConfig):
        """Test chunk calculation when duration doesn't divide evenly."""
        mock_duration.return_value = 1550.0  # 25 minutes 50 seconds
        
        transcriber = OpenAITranscriber(temp_config)
        chunks = transcriber._calculate_chunks(long_audio, chunk_duration=600)
        
        assert len(chunks) == 3
        # Last chunk should be shorter
        assert chunks[-1]["duration"] < 600


class TestTranscriptFormatting:
    """Test transcript output formatting."""
    
    def test_format_transcript_with_header(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcript includes proper header."""
        mock_openai.audio.transcriptions.create.return_value.text = "Test transcript content."
        
        transcriber = OpenAITranscriber(temp_config)
        result = transcriber.transcribe(sample_audio, "Team Meeting")
        
        content = result.read_text(encoding="utf-8")
        
        # Check for header elements
        assert "Meeting: Team Meeting" in content
        assert "Date:" in content
        assert "Duration:" in content
        assert "─" in content  # Separator line
    
    def test_format_transcript_extracts_date_from_filename(self, temp_dir: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcript extracts date from filename."""
        # Create audio file with date in name
        audio_with_date = temp_dir / "Meeting_2025-11-07_15-30.wav"
        audio_with_date.write_bytes(b"fake audio")
        
        mock_openai.audio.transcriptions.create.return_value.text = "Content."
        
        transcriber = OpenAITranscriber(temp_config)
        result = transcriber.transcribe(audio_with_date, "meeting")
        
        content = result.read_text(encoding="utf-8")
        
        assert "November 7, 2025" in content
    
    def test_format_transcript_preserves_timestamps(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcript preserves timestamps from API."""
        mock_openai.audio.transcriptions.create.return_value.text = (
            "[00:00:05] First statement.\n"
            "[00:00:15] Second statement.\n"
            "[00:00:25] Third statement."
        )
        
        transcriber = OpenAITranscriber(temp_config)
        result = transcriber.transcribe(sample_audio, "meeting")
        
        content = result.read_text(encoding="utf-8")
        
        assert "[00:00:05]" in content
        assert "[00:00:15]" in content
        assert "[00:00:25]" in content
    
    def test_format_transcript_no_technical_metadata(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcript doesn't include technical metadata."""
        mock_openai.audio.transcriptions.create.return_value.text = "Clean transcript."
        
        transcriber = OpenAITranscriber(temp_config)
        result = transcriber.transcribe(sample_audio, "meeting")
        
        content = result.read_text(encoding="utf-8")
        
        # Should not contain technical details
        assert "API" not in content
        assert "chunk" not in content.lower()
        assert "model" not in content.lower()
        assert "whisper" not in content.lower()


class TestRegressionBlankFileBug:
    """Regression tests for the blank file bug with large audio files."""
    
    @patch('scribe.core.openai_api.get_audio_duration')
    def test_large_file_not_blank(self, mock_duration, long_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Regression test: large files should not result in blank transcripts."""
        mock_duration.return_value = 3600.0  # 1 hour
        
        # Mock API to return content for each chunk
        mock_openai.audio.transcriptions.create.return_value.text = "Transcript content for chunk."
        
        transcriber = OpenAITranscriber(temp_config)
        result = transcriber.transcribe(long_audio, "long_meeting")
        
        content = result.read_text(encoding="utf-8")
        
        # File should NOT be blank
        assert len(content) > 100  # Should have substantial content
        assert "Transcript content" in content
    
    @patch('scribe.core.openai_api.get_audio_duration')
    def test_chunks_not_overwritten(self, mock_duration, long_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Regression test: chunks should be combined, not overwritten."""
        mock_duration.return_value = 1800.0  # 30 minutes
        
        # Each chunk returns unique content
        chunk_contents = [
            "Content from chunk 1.",
            "Content from chunk 2.",
            "Content from chunk 3."
        ]
        mock_openai.audio.transcriptions.create.side_effect = [
            Mock(text=text) for text in chunk_contents
        ]
        
        transcriber = OpenAITranscriber(temp_config)
        result = transcriber.transcribe(long_audio, "meeting")
        
        content = result.read_text(encoding="utf-8")
        
        # All chunks should be present
        for chunk_text in chunk_contents:
            assert chunk_text in content
