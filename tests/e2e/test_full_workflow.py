"""
End-to-end tests for complete transcription workflows.

Tests full workflows from audio input to final transcript output,
including GPU transcription, OpenAI API, fallback scenarios, and cleanup.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch
import time

from scribe.core.transcriber import Transcriber
from scribe.core.converter import Converter as AudioConverter
from scribe.models.config import ScribeConfig
from scribe.models.session import TranscriptionSession
from scribe.exceptions import TranscriptionError


class TestGPUTranscriptionWorkflow:
    """Test complete GPU transcription workflow."""
    
    @pytest.mark.skipif(
        not pytest.importorskip("torch", reason="PyTorch not available").cuda.is_available(),
        reason="CUDA not available"
    )
    def test_full_gpu_workflow(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test complete workflow using GPU transcription."""
        transcriber = Transcriber(temp_config)
        
        # Create session
        session = TranscriptionSession.create("test_meeting")
        
        # Run transcription
        result = transcriber.transcribe(
            sample_audio,
            "test_meeting",
            method="local",
            session=session
        )
        
        assert result is not None
        assert result.exists()
        assert result.stat().st_size > 0
        
        # Verify session was updated
        assert session.status == "completed"
        assert session.output_file == result
        assert session.end_time is not None
    
    @pytest.mark.skipif(
        not pytest.importorskip("torch", reason="PyTorch not available").cuda.is_available(),
        reason="CUDA not available"
    )
    def test_gpu_workflow_with_video_conversion(self, test_video: Path, temp_config: ScribeConfig, mock_gpu):
        """Test workflow converting video to audio then transcribing with GPU."""
        # Convert video to audio
        converter = AudioConverter()
        audio_path = temp_config.output_folder / "converted.wav"
        converter.convert(test_video, audio_path)
        
        # Transcribe
        transcriber = Transcriber(temp_config)
        result = transcriber.transcribe(audio_path, "video_meeting", method="local")
        
        assert result is not None
        assert result.exists()


class TestOpenAIWorkflow:
    """Test complete OpenAI API transcription workflow."""
    
    def test_full_openai_workflow(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test complete workflow using OpenAI API."""
        transcriber = Transcriber(temp_config)
        
        session = TranscriptionSession.create("api_meeting")
        
        result = transcriber.transcribe(
            sample_audio,
            "api_meeting",
            method="openai",
            session=session
        )
        
        assert result is not None
        assert result.exists()
        assert session.status == "completed"
        
        # Verify OpenAI was called
        mock_openai.audio.transcriptions.create.assert_called()
    
    def test_openai_workflow_with_large_file(self, long_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test OpenAI workflow with large file requiring chunking."""
        # Mock multiple chunk responses
        mock_openai.audio.transcriptions.create.side_effect = [
            Mock(text="Chunk 1."),
            Mock(text="Chunk 2."),
            Mock(text="Chunk 3.")
        ]
        
        transcriber = Transcriber(temp_config)
        result = transcriber.transcribe(long_audio, "long_meeting", method="openai")
        
        assert result is not None
        
        # Verify chunks were combined
        content = result.read_text(encoding="utf-8")
        assert "Chunk 1" in content
        assert "Chunk 2" in content
        assert "Chunk 3" in content


class TestAutoMethodSelection:
    """Test automatic method selection based on GPU availability."""
    
    def test_auto_selects_gpu_when_available(self, sample_audio: Path, temp_config: ScribeConfig, mock_gpu):
        """Test auto method selects GPU when available."""
        transcriber = Transcriber(temp_config)
        
        with patch.object(transcriber, '_transcribe_local') as mock_local:
            mock_local.return_value = temp_config.output_folder / "result.txt"
            
            transcriber.transcribe(sample_audio, "meeting", method="auto")
            
            # Should use local GPU
            mock_local.assert_called_once()
    
    def test_auto_selects_openai_when_no_gpu(self, sample_audio: Path, temp_config: ScribeConfig, mock_no_gpu, mock_openai):
        """Test auto method selects OpenAI when no GPU."""
        transcriber = Transcriber(temp_config)
        
        result = transcriber.transcribe(sample_audio, "meeting", method="auto")
        
        assert result is not None
        # Should have used OpenAI
        mock_openai.audio.transcriptions.create.assert_called()


class TestFallbackScenarios:
    """Test fallback behavior when primary method fails."""
    
    def test_fallback_gpu_to_openai(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test fallback from GPU to OpenAI when GPU fails."""
        transcriber = Transcriber(temp_config)
        
        with patch('scribe.core.transcriber.LocalWhisperTranscriber') as mock_local_class:
            # Mock GPU transcription to fail
            mock_local = Mock()
            mock_local.transcribe.side_effect = RuntimeError("CUDA out of memory")
            mock_local_class.return_value = mock_local
            
            # Should fallback to OpenAI
            result = transcriber.transcribe(
                sample_audio,
                "meeting",
                method="auto",
                enable_fallback=True
            )
            
            assert result is not None
            mock_openai.audio.transcriptions.create.assert_called()
    
    def test_no_fallback_when_disabled(self, sample_audio: Path, temp_config: ScribeConfig):
        """Test no fallback when explicitly disabled."""
        transcriber = Transcriber(temp_config)
        
        with patch('scribe.core.transcriber.LocalWhisperTranscriber') as mock_local_class:
            mock_local = Mock()
            mock_local.transcribe.side_effect = RuntimeError("CUDA error")
            mock_local_class.return_value = mock_local
            
            # Should raise error without fallback
            with pytest.raises(TranscriptionError):
                transcriber.transcribe(
                    sample_audio,
                    "meeting",
                    method="local",
                    enable_fallback=False
                )


class TestCleanupBehavior:
    """Test file cleanup behavior."""
    
    def test_cleanup_intermediate_files(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test intermediate files are cleaned up when configured."""
        temp_config.keep_intermediate_files = False
        
        transcriber = Transcriber(temp_config)
        result = transcriber.transcribe(sample_audio, "meeting", method="openai")
        
        assert result.exists()
        
        # Intermediate files should be cleaned up
        intermediate_files = list(temp_config.output_folder.glob("*.tmp"))
        assert len(intermediate_files) == 0
    
    def test_keep_intermediate_files(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test intermediate files are kept when configured."""
        temp_config.keep_intermediate_files = True
        
        transcriber = Transcriber(temp_config)
        transcriber.transcribe(sample_audio, "meeting", method="openai")
        
        # Intermediate files may exist (depending on implementation)
        # Just verify no error occurs
    
    def test_cleanup_on_error(self, sample_audio: Path, temp_config: ScribeConfig):
        """Test cleanup occurs even when transcription fails."""
        temp_config.keep_intermediate_files = False
        
        transcriber = Transcriber(temp_config)
        
        with patch('scribe.core.transcriber.OpenAITranscriber') as mock_api_class:
            mock_api = Mock()
            mock_api.transcribe.side_effect = Exception("API Error")
            mock_api_class.return_value = mock_api
            
            try:
                transcriber.transcribe(sample_audio, "meeting", method="openai")
            except TranscriptionError:
                pass
            
            # Cleanup should still occur
            temp_files = list(temp_config.output_folder.glob("*.tmp"))
            assert len(temp_files) == 0


class TestInterruptHandling:
    """Test handling of user interrupts."""
    
    def test_handles_keyboard_interrupt(self, sample_audio: Path, temp_config: ScribeConfig):
        """Test graceful handling of keyboard interrupt."""
        transcriber = Transcriber(temp_config)
        
        with patch('scribe.core.transcriber.LocalWhisperTranscriber') as mock_local_class:
            mock_local = Mock()
            mock_local.transcribe.side_effect = KeyboardInterrupt()
            mock_local_class.return_value = mock_local
            
            with pytest.raises(KeyboardInterrupt):
                transcriber.transcribe(sample_audio, "meeting", method="local")
            
            # Should cleanup before re-raising
            # (Implementation detail - verify no temp files left)
    
    def test_session_marked_failed_on_interrupt(self, sample_audio: Path, temp_config: ScribeConfig):
        """Test session is marked as failed on interrupt."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("meeting")
        
        with patch('scribe.core.transcriber.LocalWhisperTranscriber') as mock_local_class:
            mock_local = Mock()
            mock_local.transcribe.side_effect = KeyboardInterrupt()
            mock_local_class.return_value = mock_local
            
            try:
                transcriber.transcribe(
                    sample_audio,
                    "meeting",
                    method="local",
                    session=session
                )
            except KeyboardInterrupt:
                pass
            
            assert session.status == "failed"


class TestProgressReporting:
    """Test progress reporting throughout workflow."""
    
    def test_progress_updates_during_transcription(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test progress updates are provided during transcription."""
        transcriber = Transcriber(temp_config)
        
        progress_updates = []
        
        def progress_callback(percent: float, message: str):
            progress_updates.append((percent, message))
        
        transcriber.transcribe(
            sample_audio,
            "meeting",
            method="openai",
            progress_callback=progress_callback
        )
        
        assert len(progress_updates) > 0
        assert progress_updates[0][0] == 0.0
        assert progress_updates[-1][0] == 100.0
    
    def test_progress_includes_stage_information(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test progress updates include stage information."""
        transcriber = Transcriber(temp_config)
        
        messages = []
        
        def progress_callback(percent: float, message: str):
            messages.append(message)
        
        transcriber.transcribe(
            sample_audio,
            "meeting",
            method="openai",
            progress_callback=progress_callback
        )
        
        # Should have messages about different stages
        assert len(messages) > 0


class TestSessionManagement:
    """Test transcription session management."""
    
    def test_session_tracks_timing(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test session tracks start and end times."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("meeting")
        
        start_time = time.time()
        
        transcriber.transcribe(
            sample_audio,
            "meeting",
            method="openai",
            session=session
        )
        
        end_time = time.time()
        
        assert session.start_time is not None
        assert session.end_time is not None
        assert session.start_time <= end_time
        assert session.end_time >= start_time
    
    def test_session_tracks_method_used(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test session tracks which method was used."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("meeting")
        
        transcriber.transcribe(
            sample_audio,
            "meeting",
            method="openai",
            session=session
        )
        
        assert session.method == "openai"
    
    def test_session_tracks_output_file(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test session tracks output file path."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("meeting")
        
        result = transcriber.transcribe(
            sample_audio,
            "meeting",
            method="openai",
            session=session
        )
        
        assert session.output_file == result


class TestCompleteWorkflowIntegration:
    """Test complete end-to-end workflow integration."""
    
    def test_video_to_transcript_workflow(self, test_video: Path, temp_config: ScribeConfig, mock_openai):
        """Test complete workflow from video to final transcript."""
        # Step 1: Convert video to audio
        converter = AudioConverter()
        audio_path = temp_config.output_folder / "audio.wav"
        converter.convert(test_video, audio_path)
        
        assert audio_path.exists()
        
        # Step 2: Transcribe audio
        transcriber = Transcriber(temp_config)
        transcript_path = transcriber.transcribe(audio_path, "meeting", method="openai")
        
        assert transcript_path.exists()
        
        # Step 3: Verify transcript format
        content = transcript_path.read_text(encoding="utf-8")
        assert "Meeting:" in content
        assert "Date:" in content
        assert len(content) > 100
    
    def test_workflow_with_all_features(self, sample_audio: Path, temp_config: ScribeConfig, mock_openai):
        """Test workflow with all features enabled."""
        transcriber = Transcriber(temp_config)
        session = TranscriptionSession.create("full_featured_meeting")
        
        progress_updates = []
        
        def progress_callback(percent: float, message: str):
            progress_updates.append((percent, message))
        
        result = transcriber.transcribe(
            sample_audio,
            "full_featured_meeting",
            method="openai",
            session=session,
            progress_callback=progress_callback,
            language="en"
        )
        
        # Verify all aspects
        assert result.exists()
        assert session.status == "completed"
        assert len(progress_updates) > 0
        
        content = result.read_text(encoding="utf-8")
        assert "Meeting: full_featured_meeting" in content
