"""
Unit tests for OpenAITranscriber.
"""

from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from scribe.core.openai_api import OpenAITranscriber, _bounded_chunk_endpoints
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
    @patch("scribe.core.openai_api.get_audio_duration")
    def test_transcribe_success(
        self, mock_duration, mock_verify, mock_open, mock_openai_class, tmp_path: Path
    ):
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

        audio_path = tmp_path / "test.wav"
        audio_path.write_bytes(b"audio")
        result = transcriber.transcribe(audio_path)

        assert result.name == "test_transcription.txt"
        assert mock_client.audio.transcriptions.create.called

    @patch("scribe.core.openai_api.OpenAI")
    @patch("scribe.core.openai_api.open", create=True)
    @patch("scribe.core.openai_api.get_audio_duration")
    def test_transcribe_failure(self, mock_duration, mock_open, mock_openai_class, tmp_path: Path):
        """Test transcription failure."""
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        from openai import APIConnectionError

        mock_client.audio.transcriptions.create.side_effect = APIConnectionError(request=Mock())

        # Mock duration
        mock_duration.return_value = 100.0

        transcriber = OpenAITranscriber(api_key="sk-test")

        audio_path = tmp_path / "test.wav"
        audio_path.write_bytes(b"audio")
        with pytest.raises(TranscriptionError, match="OpenAI transcription failed"):
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
    @patch("scribe.core.openai_api.get_audio_duration")
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
        tmp_path: Path,
    ):
        """Test that large files trigger client-side chunking."""
        transcriber = OpenAITranscriber(api_key="sk-test")

        # Mock duration to be > 1300 seconds
        mock_duration.return_value = 1400.0

        mock_standardize.return_value = Path("standardized.wav")
        mock_split.return_value = [Path("chunk1.wav"), Path("chunk2.wav")]
        mock_transcribe_chunk.return_value = (True, "Chunk text")

        audio_path = tmp_path / "large_audio.wav"
        audio_path.write_bytes(b"audio")
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

    def test_bounded_chunk_endpoints_enforces_cap_without_silence(self):
        """Hard boundaries protect the duration cap when no silence is available."""
        assert _bounded_chunk_endpoints([], duration_ms=130_000, cap_ms=60_000) == [
            60_000,
            120_000,
            130_000,
        ]

    def test_bounded_chunk_endpoints_prefers_useful_silence(self):
        """Useful silence near each cap is preferred over an arbitrary early split."""
        assert _bounded_chunk_endpoints(
            [5_000, 40_000, 90_000, 130_000, 130_000, 140_000],
            duration_ms=130_000,
            cap_ms=60_000,
        ) == [40_000, 90_000, 130_000]

    @patch("scribe.core.openai_api.OpenAI")
    @patch("scribe.core.openai_api.subprocess.run")
    @patch("scribe.core.openai_api.get_ffmpeg_path", return_value=Path("ffmpeg"))
    @patch("scribe.core.openai_api.get_audio_duration", return_value=130.0)
    @patch("scribe.core.openai_api._load_native_audio_core", side_effect=ModuleNotFoundError)
    def test_split_audio_falls_back_and_enforces_cap(
        self,
        _mock_import,
        mock_duration,
        _mock_ffmpeg_path,
        mock_run,
        _mock_openai,
    ):
        """The portable root install chunks safely without the Rust extension."""
        transcriber = OpenAITranscriber(api_key="sk-test")

        chunks = transcriber.split_audio_on_silence(Path("long.mp3"), max_chunk_minutes=1)

        assert chunks == [
            Path("long_chunk_1.mp3"),
            Path("long_chunk_2.mp3"),
            Path("long_chunk_3.mp3"),
        ]
        assert mock_duration.call_count == 1
        assert mock_run.call_count == 3
        durations = [call.args[0][call.args[0].index("-t") + 1] for call in mock_run.call_args_list]
        assert durations == ["59.450", "59.750", "12.000"]
        assert all(float(duration) <= 60 for duration in durations)
        assert all("48k" in call.args[0] for call in mock_run.call_args_list)

    @patch("scribe.core.openai_api.OpenAI")
    @patch("scribe.core.openai_api.subprocess.run")
    @patch("scribe.core.openai_api.get_ffmpeg_path", return_value=Path("ffmpeg"))
    @patch("scribe.core.openai_api.get_audio_duration", return_value=130.0)
    @patch("scribe.core.openai_api._load_native_audio_core")
    def test_split_audio_uses_native_silence_and_bounds_old_core_results(
        self,
        mock_import,
        mock_duration,
        _mock_ffmpeg_path,
        mock_run,
        _mock_openai,
    ):
        """Candidate timestamps from old native builds cannot bypass the hard cap."""
        native_core = Mock()
        native_core.get_audio_dbfs.return_value = -20.0
        native_core.get_split_timestamps.return_value = [45_000, 130_000]
        mock_import.return_value = native_core
        transcriber = OpenAITranscriber(api_key="sk-test")

        chunks = transcriber.split_audio_on_silence(
            Path("long.mp3"), max_chunk_minutes=1, keep_silence_ms=0
        )

        assert len(chunks) == 3
        mock_duration.assert_not_called()
        native_core.get_split_timestamps.assert_called_once_with(
            "long.mp3",
            min_silence_ms=500,
            silence_thresh_db=-50.0,
            max_duration_ms=59_750,
        )
        durations = [call.args[0][call.args[0].index("-t") + 1] for call in mock_run.call_args_list]
        assert durations == ["45.000", "59.750", "25.250"]

    @patch("scribe.core.openai_api.OpenAI")
    @patch("scribe.core.openai_api.subprocess.run")
    @patch("scribe.core.openai_api.get_ffmpeg_path", return_value=Path("ffmpeg"))
    @patch("scribe.core.openai_api.get_audio_duration", return_value=130.0)
    @patch("scribe.core.openai_api._load_native_audio_core")
    def test_split_audio_recovers_from_native_analysis_failure(
        self,
        mock_import,
        mock_duration,
        _mock_ffmpeg_path,
        mock_run,
        _mock_openai,
        caplog,
    ):
        """A broken native extension degrades visibly to portable duration splits."""
        native_core = Mock()
        native_core.get_audio_dbfs.side_effect = RuntimeError("decoder rejected media")
        mock_import.return_value = native_core
        transcriber = OpenAITranscriber(api_key="sk-test")

        chunks = transcriber.split_audio_on_silence(
            Path("long.mp3"), max_chunk_minutes=1, keep_silence_ms=0
        )

        assert len(chunks) == 3
        mock_duration.assert_called_once_with(Path("long.mp3"))
        assert mock_run.call_count == 3
        assert "portable duration-based chunking" in caplog.text

    @patch("scribe.core.openai_api.OpenAI")
    @patch("scribe.core.openai_api.subprocess.run")
    @patch("scribe.core.openai_api.get_ffmpeg_path", return_value=Path("ffmpeg"))
    @patch("scribe.core.openai_api.get_audio_duration", return_value=None)
    @patch("scribe.core.openai_api._load_native_audio_core", side_effect=ModuleNotFoundError)
    def test_split_audio_fails_when_duration_is_unavailable(
        self,
        _mock_import,
        _mock_duration,
        _mock_ffmpeg_path,
        mock_run,
        _mock_openai,
    ):
        """Unknown duration is an actionable failure, never an empty success."""
        transcriber = OpenAITranscriber(api_key="sk-test")

        with pytest.raises(TranscriptionError, match="determine audio duration"):
            transcriber.split_audio_on_silence(Path("bad.mp3"))

        mock_run.assert_not_called()

    @patch("scribe.core.openai_api.OpenAITranscriber.transcribe")
    def test_transcribe_with_openai_function(self, mock_transcribe):
        """Test the transcribe_with_openai convenience function."""
        from scribe.core.openai_api import transcribe_with_openai

        mock_transcribe.return_value = Path("output.txt")

        result = transcribe_with_openai(Path("test.wav"), api_key="sk-test")
        assert result == Path("output.txt")
        mock_transcribe.assert_called_once()
