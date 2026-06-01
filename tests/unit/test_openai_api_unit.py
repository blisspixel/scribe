"""
Unit tests for OpenAITranscriber.
"""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from scribe.core.openai_api import OpenAITranscriber
from scribe.exceptions import TranscriptionError


class TestOpenAITranscriber:
    """Test OpenAITranscriber functionality."""

    def test_init(self):
        """Test initialization."""
        with patch("scribe.core.openai_api.OpenAI") as mock_openai:
            transcriber = OpenAITranscriber(api_key="sk-test", model="gpt-4o")
            assert transcriber.api_key == "sk-test"
            assert transcriber.model == "gpt-4o"
            mock_openai.assert_called_once_with(api_key="sk-test")

    @patch("scribe.core.openai_api.OpenAI")
    @patch("scribe.core.openai_api.open", create=True)
    @patch("scribe.core.openai_api.verify_file_content")
    @patch("scribe.utils.audio.get_audio_duration")
    def test_transcribe_success(self, mock_duration, mock_verify, mock_open, mock_openai_class):
        """Test successful transcription."""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client

        # Mock transcription response
        mock_response = Mock()
        mock_response.text = "Transcribed text"
        # Avoid the 'int(response.duration)' TypeError
        if hasattr(mock_response, "duration"):
            del mock_response.duration
        mock_client.audio.transcriptions.create.return_value = mock_response

        # Mock duration
        mock_duration.return_value = 100.0

        transcriber = OpenAITranscriber(api_key="sk-test")

        # Mock file handle
        mock_file = Mock()
        mock_open.return_value.__enter__.return_value = mock_file

        audio_path = Path("test.wav")
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = 100
                result = transcriber.transcribe(audio_path)

        assert result.name == "test_transcription.txt"
        assert mock_client.audio.transcriptions.create.called

    @patch("scribe.core.openai_api.OpenAI")
    @patch("scribe.core.openai_api.open", create=True)
    @patch("scribe.utils.audio.get_audio_duration")
    def test_transcribe_failure(self, mock_duration, mock_open, mock_openai_class):
        """Test transcription failure."""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        mock_client.audio.transcriptions.create.side_effect = Exception("API Error")

        # Mock duration
        mock_duration.return_value = 100.0

        transcriber = OpenAITranscriber(api_key="sk-test")

        audio_path = Path("test.wav")
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = 100
                with pytest.raises(
                    TranscriptionError, match="Server-side chunking transcription failed"
                ):
                    transcriber.transcribe(audio_path)

    @patch("scribe.core.openai_api.OpenAI")
    def test_format_transcript_response_text(self, mock_openai):
        """Test formatting a text response."""
        transcriber = OpenAITranscriber(api_key="sk-test")
        response = Mock()
        response.text = "Hello world"
        if hasattr(response, "duration"):
            del response.duration

        formatted = transcriber._format_transcript_response(
            response, Path("meeting_2026-06-01.wav")
        )
        assert "Hello world" in formatted
        assert "meeting" in formatted
        assert "2026-06-01" in formatted

    @patch("scribe.core.openai_api.OpenAI")
    def test_format_transcript_response_json(self, mock_openai):
        """Test formatting a JSON response with segments."""
        transcriber = OpenAITranscriber(api_key="sk-test")
        response = Mock()
        response.text = '{"segments": [{"start": 0, "end": 1, "text": "Hi"}]}'
        response.duration = 60

        # Mocking segments as if it was a dict or object
        response.segments = [{"start": 0, "end": 1, "text": "Hi"}]

        formatted = transcriber._format_transcript_response(response, Path("test.wav"))
        assert "Hi" in formatted
        assert "[00:00:00]" in formatted

    @patch("scribe.core.openai_api.OpenAI")
    @patch("scribe.core.openai_api.get_logger")
    @patch("scribe.utils.audio.get_audio_duration")
    @patch("scribe.core.openai_api.OpenAITranscriber.standardize_audio")
    @patch("scribe.core.openai_api.OpenAITranscriber.split_audio_on_silence")
    @patch("scribe.core.openai_api.OpenAITranscriber.transcribe_chunk")
    @patch("scribe.core.openai_api.open", create=True)
    @patch("scribe.core.openai_api.verify_file_content")
    def test_transcribe_client_side_chunking_trigger(
        self,
        mock_verify,
        mock_open,
        mock_transcribe_chunk,
        mock_split,
        mock_standardize,
        mock_duration,
        mock_logger,
        mock_openai,
    ):
        """Test that large files trigger client-side chunking."""
        transcriber = OpenAITranscriber(api_key="sk-test")

        # Mock duration to be > 1300 seconds
        mock_duration.return_value = 1400.0

        mock_standardize.return_value = Path("standardized.wav")
        mock_split.return_value = [Path("chunk1.wav"), Path("chunk2.wav")]
        mock_transcribe_chunk.return_value = (True, "Chunk text")

        audio_path = Path("large_audio.wav")
        # Mock Path methods
        with patch.object(Path, "exists", return_value=True):
            with patch.object(Path, "stat") as mock_stat:
                mock_stat.return_value.st_size = 100
                result = transcriber.transcribe(audio_path)

        assert result.name == "large_audio_transcription.txt"
        assert transcriber.use_server_chunking is False
        assert mock_transcribe_chunk.call_count == 2

    @patch("scribe.core.openai_api.OpenAI")
    @patch("scribe.core.openai_api.AudioSegment")
    def test_standardize_audio(self, mock_audio_segment, mock_openai):
        """Test audio standardization."""
        transcriber = OpenAITranscriber(api_key="sk-test")

        mock_audio = MagicMock()
        mock_audio_segment.from_file.return_value = mock_audio
        mock_audio.__len__.return_value = 10000
        mock_audio.channels = 1
        mock_audio.frame_rate = 44100
        mock_audio.dBFS = -20.0
        mock_audio.set_frame_rate.return_value = mock_audio
        mock_audio.set_channels.return_value = mock_audio
        mock_audio.normalize.return_value = mock_audio

        audio_path = Path("test.mp3")
        result = transcriber.standardize_audio(audio_path)

        assert result.name == "test_standardized.mp3"
        assert mock_audio.export.called

    @patch("scribe.core.openai_api.OpenAITranscriber.transcribe")
    def test_transcribe_with_openai_function(self, mock_transcribe):
        """Test the transcribe_with_openai convenience function."""
        from scribe.core.openai_api import transcribe_with_openai

        mock_transcribe.return_value = Path("output.txt")

        result = transcribe_with_openai(Path("test.wav"), api_key="sk-test")
        assert result == Path("output.txt")
        mock_transcribe.assert_called_once()
