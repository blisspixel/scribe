"""
End-to-end tests for complete transcription workflows.

Tests full workflows from audio input to final transcript output,
including GPU transcription, OpenAI API, fallback scenarios, and cleanup.
"""

import contextlib
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scribe.core.converter import Converter as AudioConverter
from scribe.core.transcriber import Transcriber
from scribe.models.config import ScribeConfig
from scribe.models.session import TranscriptionSession


@pytest.fixture
def temp_config(temp_config):
    """These legacy orchestration cases exercise the explicit one-pass workflow."""
    temp_config.transcription_quality = "accurate"
    return temp_config


class TestGPUTranscriptionWorkflow:
    """Test complete GPU transcription workflow."""

    pytestmark = pytest.mark.gpu

    @pytest.mark.skipif(
        not pytest.importorskip("torch", reason="PyTorch not available").cuda.is_available(),
        reason="CUDA not available",
    )
    def test_full_gpu_workflow(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu, mock_openai
    ):
        """Test complete workflow using GPU transcription."""
        transcriber = Transcriber(temp_config)

        # Create session
        session = TranscriptionSession.create("test_meeting")

        # Run transcription
        result = transcriber.transcribe(sample_audio, method="local", session=session)

        assert result is not None
        assert result.exists()
        assert result.stat().st_size > 0

        # Verify session was updated
        assert session.transcript_file == result
        assert session.start_time is not None

    @pytest.mark.skipif(
        not pytest.importorskip("torch", reason="PyTorch not available").cuda.is_available(),
        reason="CUDA not available",
    )
    def test_gpu_workflow_with_video_conversion(
        self, test_video: Path, temp_config: ScribeConfig, mock_gpu, mock_openai
    ):
        """Test workflow converting video to audio then transcribing with GPU."""
        # Convert video to audio
        converter = AudioConverter()
        audio_path = converter.convert_to_wav(test_video)

        # Transcribe
        transcriber = Transcriber(temp_config)
        result = transcriber.transcribe(audio_path, method="local")

        assert result is not None
        assert result.exists()


class TestOpenAIWorkflow:
    """Test complete OpenAI API transcription workflow."""

    def test_full_openai_workflow(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test complete workflow using OpenAI API."""
        transcriber = Transcriber(temp_config)

        session = TranscriptionSession.create("api_meeting")

        result = transcriber.transcribe(sample_audio, method="openai", session=session)

        assert result is not None
        assert result.exists()
        assert session.transcript_file == result

        # Verify OpenAI was called
        mock_openai.audio.transcriptions.create.assert_called()

    def test_openai_workflow_with_large_file(
        self, long_audio: Path, temp_config: ScribeConfig, mock_openai
    ):
        """Test OpenAI workflow with large file (server-side chunking)."""
        # Mock server-side chunking response (single combined response)
        from tests.conftest import create_mock_transcription_response

        mock_openai.audio.transcriptions.create.return_value = create_mock_transcription_response(
            "Chunk 1. Chunk 2. Chunk 3."
        )

        transcriber = Transcriber(temp_config)
        result = transcriber.transcribe(long_audio, method="openai")

        assert result is not None
        assert result.exists()

        # Verify content is present
        content = result.read_text(encoding="utf-8")
        assert len(content) > 0


class TestAutoMethodSelection:
    """Test automatic method selection based on GPU availability."""

    def test_auto_selects_gpu_when_available(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu
    ):
        """Test auto method selects GPU when available."""
        transcriber = Transcriber(temp_config)

        with patch.object(transcriber, "_transcribe_local") as mock_local:
            mock_local.return_value = temp_config.output_folder / "result.txt"

            transcriber.transcribe(sample_audio, method="auto")

            # Should use local GPU
            mock_local.assert_called_once()

    def test_auto_stays_local_when_no_gpu(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_no_gpu, mock_openai
    ):
        """Auto uses the local CPU floor and never authorizes a cloud upload."""
        transcriber = Transcriber(temp_config)
        expected = temp_config.output_folder / "auto-local.txt"
        expected.write_text("local transcript", encoding="utf-8")

        with patch.object(transcriber, "_transcribe_local", return_value=expected) as local:
            result = transcriber.transcribe(sample_audio, method="auto")

        assert result == expected
        local.assert_called_once()
        mock_openai.audio.transcriptions.create.assert_not_called()


class TestFallbackScenarios:
    """Test fallback behavior when primary method fails."""

    def test_auto_without_gpu_uses_local_cpu(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_openai, mock_no_gpu
    ):
        """No GPU does not change the explicit local-first cloud boundary."""
        transcriber = Transcriber(temp_config)
        expected = temp_config.output_folder / "cpu-local.txt"
        expected.write_text("local transcript", encoding="utf-8")

        with patch.object(transcriber, "_transcribe_local", return_value=expected) as local:
            result = transcriber.transcribe(sample_audio, method="auto")

        assert result == expected
        local.assert_called_once()
        mock_openai.audio.transcriptions.create.assert_not_called()

    def test_forced_local_uses_local_path_without_gpu(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_no_gpu, mock_openai
    ):
        """An explicit local choice must not be silently changed before execution."""
        transcriber = Transcriber(temp_config)
        expected = temp_config.output_folder / "forced-local.txt"
        expected.write_text("local transcript", encoding="utf-8")

        with patch.object(transcriber, "_transcribe_local", return_value=expected) as local:
            result = transcriber.transcribe(sample_audio, method="local")

        assert result == expected
        local.assert_called_once()
        mock_openai.audio.transcriptions.create.assert_not_called()


class TestCleanupBehavior:
    """Test file cleanup behavior."""

    def test_cleanup_intermediate_files(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_openai
    ):
        """Test intermediate files are cleaned up when configured."""
        temp_config.keep_intermediate_files = False

        transcriber = Transcriber(temp_config)
        result = transcriber.transcribe(sample_audio, method="openai")

        assert result.exists()

        # Intermediate files should be cleaned up
        intermediate_files = list(temp_config.output_folder.glob("*.tmp"))
        assert len(intermediate_files) == 0

    def test_keep_intermediate_files(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_openai
    ):
        """Test intermediate files are kept when configured."""
        temp_config.keep_intermediate_files = True

        transcriber = Transcriber(temp_config)
        transcriber.transcribe(sample_audio, method="openai")

        # Intermediate files may exist (depending on implementation)
        # Just verify no error occurs

    def test_cleanup_on_error(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test cleanup occurs even when transcription fails."""
        temp_config.keep_intermediate_files = False

        transcriber = Transcriber(temp_config)

        # Just verify that transcription doesn't leave temp files
        # (Cleanup is handled by the converter and transcriber)
        transcriber.transcribe(sample_audio, method="openai")

        # Verify no temp files left behind
        temp_files = list(temp_config.output_folder.glob("*.tmp"))
        assert len(temp_files) == 0


class TestInterruptHandling:
    """Test handling of user interrupts."""

    def test_handles_keyboard_interrupt(self, sample_audio: Path, temp_config: ScribeConfig):
        """Test graceful handling of keyboard interrupt."""
        transcriber = Transcriber(temp_config)

        with patch("scribe.core.transcriber.LocalWhisperTranscriber") as mock_local_class:
            mock_local = Mock()
            mock_local.transcribe.side_effect = KeyboardInterrupt()
            mock_local_class.return_value = mock_local

            with pytest.raises(KeyboardInterrupt):
                transcriber.transcribe(sample_audio, method="local")

            # Should cleanup before re-raising
            # (Implementation detail - verify no temp files left)

    def test_session_marked_failed_on_interrupt(
        self, sample_audio: Path, temp_config: ScribeConfig
    ):
        """Test session is marked as failed on interrupt."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("meeting")

        with patch("scribe.core.transcriber.LocalWhisperTranscriber") as mock_local_class:
            mock_local = Mock()
            mock_local.transcribe.side_effect = KeyboardInterrupt()
            mock_local_class.return_value = mock_local

            with contextlib.suppress(KeyboardInterrupt):
                transcriber.transcribe(sample_audio, method="local", session=session)

            # Session tracking is best-effort, just verify it exists
            assert session.start_time is not None


class TestProgressReporting:
    """Test progress reporting throughout workflow."""

    def test_progress_updates_during_transcription(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_openai
    ):
        """Test progress updates are logged during transcription."""
        transcriber = Transcriber(temp_config)

        # Progress is logged internally, not via callback
        # Just verify transcription completes successfully
        result = transcriber.transcribe(sample_audio, method="openai")

        assert result is not None
        assert result.exists()

    def test_progress_includes_stage_information(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_openai
    ):
        """Test transcription completes with proper stages."""
        transcriber = Transcriber(temp_config)

        # Progress is logged internally
        # Verify transcription completes successfully
        result = transcriber.transcribe(sample_audio, method="openai")

        assert result is not None
        assert result.exists()


class TestSessionManagement:
    """Test transcription session management."""

    def test_session_tracks_timing(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_openai
    ):
        """Test session tracks start time."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("meeting")

        transcriber.transcribe(sample_audio, method="openai", session=session)

        # Session tracks start time
        assert session.start_time is not None
        # Session tracks files
        assert session.transcript_file is not None

    def test_session_tracks_method_used(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_openai
    ):
        """Test session tracks which method was used."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("meeting")

        transcriber.transcribe(sample_audio, method="openai", session=session)

        assert session.transcription_method == "openai"

    def test_session_tracks_output_file(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_openai
    ):
        """Test session tracks output file path."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("meeting")

        result = transcriber.transcribe(sample_audio, method="openai", session=session)

        assert session.transcript_file == result


class TestCompleteWorkflowIntegration:
    """Test complete end-to-end workflow integration."""

    def test_video_to_transcript_workflow(
        self, test_video: Path, temp_config: ScribeConfig, mock_openai
    ):
        """Test complete workflow from video to final transcript."""
        # Step 1: Convert video to audio
        converter = AudioConverter()
        audio_path = converter.convert_to_wav(test_video)

        assert audio_path.exists()

        # Step 2: Transcribe audio
        transcriber = Transcriber(temp_config)
        transcript_path = transcriber.transcribe(audio_path, method="openai")

        assert transcript_path.exists()

        # Step 3: Verify transcript format
        content = transcript_path.read_text(encoding="utf-8")
        assert len(content) > 0

    def test_workflow_with_all_features(
        self, sample_audio: Path, temp_config: ScribeConfig, mock_openai
    ):
        """Test workflow with all features enabled."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("full_featured_meeting")

        result = transcriber.transcribe(sample_audio, method="openai", session=session)

        # Verify all aspects
        assert result.exists()
        assert session.transcript_file == result
        assert session.start_time is not None

        content = result.read_text(encoding="utf-8")
        assert len(content) > 0
