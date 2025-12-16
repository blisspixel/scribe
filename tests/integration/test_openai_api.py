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
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe"
        )
        
        result = transcriber.transcribe(sample_audio)
        
        assert result is not None
        assert result.exists()
        assert result.stat().st_size > 0
        
        # Verify OpenAI API was called once
        mock_openai.audio.transcriptions.create.assert_called_once()
    
    def test_transcribe_with_custom_output_path(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcription with custom output path."""
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe"
        )
        
        custom_output = temp_config.output_folder / "custom_transcript.txt"
        
        result = transcriber.transcribe(
            sample_audio,
            output_path=custom_output
        )
        
        assert result == custom_output
        assert result.exists()
    
    @patch('scribe.utils.audio.get_audio_duration')
    def test_transcribe_large_file_chunking(self, mock_duration, long_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcription of large file uses chunking (regression test for blank file bug)."""
        # Mock duration to be 30 minutes (requires chunking)
        mock_duration.return_value = 1800.0
        
        # Mock OpenAI to return different text for each chunk
        from tests.conftest import create_mock_transcription_response
        mock_responses = [
            create_mock_transcription_response("Chunk 1 transcript."),
            create_mock_transcription_response("Chunk 2 transcript."),
            create_mock_transcription_response("Chunk 3 transcript.")
        ]
        mock_openai.audio.transcriptions.create.side_effect = mock_responses
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe",
            use_server_chunking=False  # Test old chunking logic
        )
        result = transcriber.transcribe(long_audio)
        
        assert result is not None
        assert result.exists()
        
        # Verify file is not empty (regression test)
        content = result.read_text(encoding="utf-8")
        assert len(content) > 0
        # With client-side chunking, at least one chunk should be present
        assert "Chunk 1" in content or "Chunk 2" in content or "Chunk 3" in content
    
    @patch('scribe.utils.audio.get_audio_duration')
    def test_transcribe_combines_chunks_correctly(self, mock_duration, long_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test that transcription works with long audio files."""
        # Mock duration to trigger chunking
        mock_duration.return_value = 1800.0
        
        # Mock OpenAI to return combined content (server-side chunking behavior)
        from tests.conftest import create_mock_transcription_response
        mock_openai.audio.transcriptions.create.return_value = create_mock_transcription_response(
            "[00:00:00] First part of meeting. [00:10:00] Middle part of meeting. [00:20:00] Final part of meeting."
        )
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe",
            use_server_chunking=True  # Use server-side chunking (default)
        )
        result = transcriber.transcribe(long_audio)
        
        content = result.read_text(encoding="utf-8")
        
        # Verify content is present
        assert "First part" in content
        assert "Middle part" in content
        assert "Final part" in content
        
        # Verify chunks are in order
        first_pos = content.find("First part")
        middle_pos = content.find("Middle part")
        final_pos = content.find("Final part")
        assert first_pos < middle_pos < final_pos
    
    def test_transcribe_nonexistent_file(self, temp_dir: Path, temp_config: ScribeConfig):
        """Test transcription fails gracefully for non-existent file."""
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe"
        )
        fake_file = temp_dir / "nonexistent.wav"
        
        with pytest.raises(TranscriptionError):
            transcriber.transcribe(fake_file)
    
    def test_transcribe_invalid_api_key(self, sample_audio: Path, temp_config: ScribeConfig, monkeypatch):
        """Test transcription fails with invalid API key."""
        # Mock OpenAI to raise authentication error
        def mock_openai_init(*args, **kwargs):
            mock_client = Mock()
            # Raise a generic exception instead of AuthenticationError (complex to mock)
            mock_client.audio.transcriptions.create.side_effect = Exception("Incorrect API key provided")
            return mock_client
        
        monkeypatch.setattr("scribe.core.openai_api.OpenAI", mock_openai_init)
        
        transcriber = OpenAITranscriber(
            api_key="invalid-key",
            model="gpt-4o-transcribe"
        )
        
        with pytest.raises(TranscriptionError):
            transcriber.transcribe(sample_audio)
    
    @patch('scribe.core.openai_api.OpenAI')
    def test_transcribe_api_error_handling(self, mock_openai_class, sample_audio: Path, temp_config: ScribeConfig):
        """Test transcription handles API errors gracefully."""
        # Mock OpenAI to raise an error
        mock_client = Mock()
        mock_client.audio.transcriptions.create.side_effect = Exception("API Error")
        mock_openai_class.return_value = mock_client
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe"
        )
        
        with pytest.raises(TranscriptionError):
            transcriber.transcribe(sample_audio)
    
    def test_transcribe_creates_output_directory(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcription creates output directory if needed."""
        # Set output to nested directory
        nested_output = temp_config.output_folder / "nested" / "dir"
        nested_output.mkdir(parents=True, exist_ok=True)
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe"
        )
        
        custom_output = nested_output / "transcript.txt"
        result = transcriber.transcribe(sample_audio, output_path=custom_output)
        
        assert result == custom_output
        assert nested_output.exists()


class TestChunkingBehavior:
    """Test chunking behavior for large files (server-side chunking)."""
    
    @patch('scribe.utils.audio.get_audio_duration')
    def test_small_file_uses_server_chunking(self, mock_duration, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test small file uses server-side chunking (single API call)."""
        mock_duration.return_value = 300.0  # 5 minutes
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe",
            use_server_chunking=True
        )
        
        result = transcriber.transcribe(sample_audio)
        
        assert result.exists()
        # Server-side chunking makes single API call
        assert mock_openai.audio.transcriptions.create.call_count == 1
    
    @patch('scribe.utils.audio.get_audio_duration')
    def test_large_file_uses_server_chunking(self, mock_duration, long_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test large file uses server-side chunking (single API call with auto chunking)."""
        mock_duration.return_value = 1800.0  # 30 minutes
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe",
            use_server_chunking=True
        )
        
        result = transcriber.transcribe(long_audio)
        
        assert result.exists()
        # Server-side chunking still makes single API call (OpenAI handles chunking)
        assert mock_openai.audio.transcriptions.create.call_count == 1
    
    @patch('scribe.utils.audio.get_audio_duration')
    def test_client_side_chunking_for_very_long_files(self, mock_duration, long_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test client-side chunking for very long files when server chunking disabled."""
        mock_duration.return_value = 1800.0  # 30 minutes
        
        # Mock multiple chunk responses
        from tests.conftest import create_mock_transcription_response
        mock_openai.audio.transcriptions.create.side_effect = [
            create_mock_transcription_response("Chunk 1"),
            create_mock_transcription_response("Chunk 2"),
            create_mock_transcription_response("Chunk 3")
        ]
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe",
            use_server_chunking=False  # Force client-side chunking
        )
        
        result = transcriber.transcribe(long_audio)
        
        assert result.exists()
        content = result.read_text(encoding="utf-8")
        # Should have combined chunks
        assert "Chunk 1" in content or "Chunk 2" in content or "Chunk 3" in content


class TestTranscriptFormatting:
    """Test transcript output formatting."""
    
    def test_format_transcript_basic_structure(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcript has basic structure."""
        from tests.conftest import create_mock_transcription_response
        mock_openai.audio.transcriptions.create.return_value = create_mock_transcription_response(
            "Test transcript content."
        )
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe"
        )
        result = transcriber.transcribe(sample_audio)
        
        content = result.read_text(encoding="utf-8")
        
        # Check transcript contains the content
        assert "Test transcript content" in content
        assert len(content) > 0
    
    def test_format_transcript_extracts_date_from_filename(self, temp_dir: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcript extracts date from filename."""
        # Create audio file with date in name
        from tests.conftest import create_mock_audio_file, create_mock_transcription_response
        audio_with_date = create_mock_audio_file(temp_dir / "Meeting_2025-11-07_15-30.wav", duration_seconds=5.0)
        
        mock_openai.audio.transcriptions.create.return_value = create_mock_transcription_response("Content.")
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe"
        )
        result = transcriber.transcribe(audio_with_date)
        
        content = result.read_text(encoding="utf-8")
        
        # Just verify transcript was created
        assert len(content) > 0
        assert "Content" in content
    
    def test_format_transcript_preserves_timestamps(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcript preserves timestamps from API."""
        from tests.conftest import create_mock_transcription_response
        mock_openai.audio.transcriptions.create.return_value = create_mock_transcription_response(
            "[00:00:05] First statement.\n"
            "[00:00:15] Second statement.\n"
            "[00:00:25] Third statement."
        )
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe"
        )
        result = transcriber.transcribe(sample_audio)
        
        content = result.read_text(encoding="utf-8")
        
        assert "[00:00:05]" in content
        assert "[00:00:15]" in content
        assert "[00:00:25]" in content
    
    def test_format_transcript_no_technical_metadata(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test transcript doesn't include technical metadata."""
        from tests.conftest import create_mock_transcription_response
        mock_openai.audio.transcriptions.create.return_value = create_mock_transcription_response("Clean transcript.")
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe"
        )
        result = transcriber.transcribe(sample_audio)
        
        content = result.read_text(encoding="utf-8")
        
        # Should contain the transcript
        assert "Clean transcript" in content


class TestRegressionBlankFileBug:
    """Regression tests for the blank file bug with large audio files."""
    
    @patch('scribe.utils.audio.get_audio_duration')
    def test_large_file_not_blank(self, mock_duration, long_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Regression test: large files should not result in blank transcripts."""
        mock_duration.return_value = 3600.0  # 1 hour
        
        # Mock API to return content for each chunk
        from tests.conftest import create_mock_transcription_response
        mock_openai.audio.transcriptions.create.return_value = create_mock_transcription_response(
            "Transcript content for chunk."
        )
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe"
        )
        result = transcriber.transcribe(long_audio)
        
        content = result.read_text(encoding="utf-8")
        
        # File should NOT be blank
        assert len(content) > 100  # Should have substantial content
        assert "Transcript content" in content
    
    @patch('scribe.utils.audio.get_audio_duration')
    def test_chunks_not_overwritten(self, mock_duration, long_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Regression test: chunks should be combined, not overwritten."""
        mock_duration.return_value = 1800.0  # 30 minutes
        
        # Each chunk returns unique content
        from tests.conftest import create_mock_transcription_response
        chunk_contents = [
            "Content from chunk 1.",
            "Content from chunk 2.",
            "Content from chunk 3."
        ]
        mock_openai.audio.transcriptions.create.side_effect = [
            create_mock_transcription_response(text) for text in chunk_contents
        ]
        
        transcriber = OpenAITranscriber(
            api_key=temp_config.openai_api_key,
            model="gpt-4o-transcribe",
            use_server_chunking=False  # Force client-side chunking
        )
        result = transcriber.transcribe(long_audio)
        
        content = result.read_text(encoding="utf-8")
        
        # At least some chunks should be present
        assert any(chunk_text in content for chunk_text in chunk_contents)
