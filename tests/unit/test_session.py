"""
Unit tests for session management.

Tests session tracking, file management, and metadata handling.
"""

import pytest
import json
import time
from pathlib import Path
from datetime import datetime
from scribe.models.session import TranscriptionSession


class TestSessionCreation:
    """Test session creation and initialization."""
    
    def test_create_session(self):
        """Test creating a new session."""
        session = TranscriptionSession.create("Test Meeting")
        
        assert session.meeting_name == "Test Meeting"
        assert session.session_id is not None
        assert "Test Meeting" in session.session_id
        assert session.start_time is not None
        assert session.end_time is None
        assert session.success is False
    
    def test_session_id_is_unique(self):
        """Test session IDs are unique."""
        session1 = TranscriptionSession.create("Meeting")
        time.sleep(0.01)  # Ensure different timestamp
        session2 = TranscriptionSession.create("Meeting")
        
        assert session1.session_id != session2.session_id
    
    def test_session_id_contains_timestamp(self):
        """Test session ID contains timestamp."""
        session = TranscriptionSession.create("Meeting")
        
        # Should contain date in YYYYMMDD format
        assert any(char.isdigit() for char in session.session_id)
    
    def test_session_starts_with_defaults(self):
        """Test session starts with default values."""
        session = TranscriptionSession.create("Meeting")
        
        assert session.source_file is None
        assert session.audio_file is None
        assert session.transcript_file is None
        assert session.docx_file is None
        assert session.transcription_method is None
        assert session.model_used is None
        assert session.files_created == []
        assert session.files_cleaned == []


class TestSessionCompletion:
    """Test session completion."""
    
    def test_complete_success(self):
        """Test completing session successfully."""
        session = TranscriptionSession.create("Meeting")
        time.sleep(0.01)  # Ensure duration > 0
        
        session.complete(success=True)
        
        assert session.success is True
        assert session.end_time is not None
        assert session.duration_seconds is not None
        assert session.duration_seconds > 0
        assert session.error_message is None
    
    def test_complete_failure(self):
        """Test completing session with failure."""
        session = TranscriptionSession.create("Meeting")
        time.sleep(0.01)
        
        session.complete(success=False, error_message="Test error")
        
        assert session.success is False
        assert session.error_message == "Test error"
        assert session.end_time is not None
        assert session.duration_seconds is not None
    
    def test_duration_calculation(self):
        """Test duration is calculated correctly."""
        session = TranscriptionSession.create("Meeting")
        time.sleep(0.1)  # 100ms
        
        session.complete(success=True)
        
        assert session.duration_seconds >= 0.1
        assert session.duration_seconds < 1.0  # Should be quick


class TestFileTracking:
    """Test file tracking functionality."""
    
    def test_add_source_file(self, tmp_path):
        """Test adding source file."""
        session = TranscriptionSession.create("Meeting")
        source_file = tmp_path / "recording.mp4"
        
        session.add_file(source_file, "source")
        
        assert session.source_file == source_file
        assert source_file in session.files_created
    
    def test_add_audio_file(self, tmp_path):
        """Test adding audio file."""
        session = TranscriptionSession.create("Meeting")
        audio_file = tmp_path / "audio.wav"
        
        session.add_file(audio_file, "audio")
        
        assert session.audio_file == audio_file
        assert audio_file in session.files_created
    
    def test_add_transcript_file(self, tmp_path):
        """Test adding transcript file."""
        session = TranscriptionSession.create("Meeting")
        transcript_file = tmp_path / "transcript.txt"
        
        session.add_file(transcript_file, "transcript")
        
        assert session.transcript_file == transcript_file
        assert transcript_file in session.files_created
    
    def test_add_docx_file(self, tmp_path):
        """Test adding DOCX file."""
        session = TranscriptionSession.create("Meeting")
        docx_file = tmp_path / "document.docx"
        
        session.add_file(docx_file, "docx")
        
        assert session.docx_file == docx_file
        assert docx_file in session.files_created
    
    def test_add_meme_file(self, tmp_path):
        """Test adding meme file."""
        session = TranscriptionSession.create("Meeting")
        meme_file = tmp_path / "meme.png"
        
        session.add_file(meme_file, "meme")
        
        assert session.meme_file == meme_file
        assert meme_file in session.files_created
    
    def test_add_multiple_files(self, tmp_path):
        """Test adding multiple files."""
        session = TranscriptionSession.create("Meeting")
        
        source = tmp_path / "source.mp4"
        audio = tmp_path / "audio.wav"
        transcript = tmp_path / "transcript.txt"
        
        session.add_file(source, "source")
        session.add_file(audio, "audio")
        session.add_file(transcript, "transcript")
        
        assert len(session.files_created) == 3
        assert session.source_file == source
        assert session.audio_file == audio
        assert session.transcript_file == transcript
    
    def test_add_cleaned_file(self, tmp_path):
        """Test tracking cleaned files."""
        session = TranscriptionSession.create("Meeting")
        cleaned_file = tmp_path / "temp.wav"
        
        session.add_cleaned_file(cleaned_file)
        
        assert cleaned_file in session.files_cleaned
        assert len(session.files_cleaned) == 1


class TestSessionSerialization:
    """Test session serialization."""
    
    def test_to_dict(self, tmp_path):
        """Test converting session to dictionary."""
        session = TranscriptionSession.create("Meeting")
        session.add_file(tmp_path / "test.mp4", "source")
        session.complete(success=True)
        
        data = session.to_dict()
        
        assert isinstance(data, dict)
        assert data["meeting_name"] == "Meeting"
        assert data["success"] is True
        assert "start_time" in data
        assert "end_time" in data
    
    def test_to_dict_datetime_serialization(self):
        """Test datetime objects are serialized to ISO format."""
        session = TranscriptionSession.create("Meeting")
        session.complete(success=True)
        
        data = session.to_dict()
        
        # Should be ISO format strings
        assert isinstance(data["start_time"], str)
        assert isinstance(data["end_time"], str)
        assert "T" in data["start_time"]  # ISO format has T separator
    
    def test_to_dict_path_serialization(self, tmp_path):
        """Test Path objects are serialized to strings."""
        session = TranscriptionSession.create("Meeting")
        session.add_file(tmp_path / "test.mp4", "source")
        
        data = session.to_dict()
        
        assert isinstance(data["source_file"], str)
        assert isinstance(data["files_created"], list)
        assert all(isinstance(f, str) for f in data["files_created"])
    
    def test_to_json(self):
        """Test converting session to JSON string."""
        session = TranscriptionSession.create("Meeting")
        session.complete(success=True)
        
        json_str = session.to_json()
        
        assert isinstance(json_str, str)
        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["meeting_name"] == "Meeting"


class TestSessionSummary:
    """Test session summary generation."""
    
    def test_save_summary(self, tmp_path):
        """Test saving session summary to file."""
        session = TranscriptionSession.create("Meeting")
        session.complete(success=True)
        
        summary_path = session.save_summary(tmp_path)
        
        assert summary_path.exists()
        assert summary_path.suffix == ".json"
        assert "Meeting" in summary_path.name
    
    def test_save_summary_creates_directory(self, tmp_path):
        """Test save_summary creates output directory."""
        session = TranscriptionSession.create("Meeting")
        output_dir = tmp_path / "new_dir"
        assert not output_dir.exists()
        
        summary_path = session.save_summary(output_dir)
        
        assert output_dir.exists()
        assert summary_path.exists()
    
    def test_save_summary_content(self, tmp_path):
        """Test saved summary contains correct data."""
        session = TranscriptionSession.create("Meeting")
        session.transcription_method = "openai"
        session.model_used = "gpt-4o-transcribe-diarize"
        session.complete(success=True)
        
        summary_path = session.save_summary(tmp_path)
        
        with open(summary_path, 'r') as f:
            data = json.load(f)
        
        assert data["meeting_name"] == "Meeting"
        assert data["transcription_method"] == "openai"
        assert data["model_used"] == "gpt-4o-transcribe-diarize"
        assert data["success"] is True
    
    def test_get_summary_text(self):
        """Test getting human-readable summary."""
        session = TranscriptionSession.create("Meeting")
        session.transcription_method = "local"
        session.model_used = "large-v3"
        session.processing_speed_ratio = 12.6
        session.complete(success=True)
        
        summary = session.get_summary_text()
        
        assert "Meeting" in summary
        assert "Success" in summary
        assert "local" in summary
        assert "large-v3" in summary
        assert "12.6x" in summary
    
    def test_get_summary_text_with_error(self):
        """Test summary text includes error message."""
        session = TranscriptionSession.create("Meeting")
        session.complete(success=False, error_message="Test error")
        
        summary = session.get_summary_text()
        
        assert "Failed" in summary
        assert "Test error" in summary


class TestSessionMetadata:
    """Test session metadata handling."""
    
    def test_set_transcription_method(self):
        """Test setting transcription method."""
        session = TranscriptionSession.create("Meeting")
        session.transcription_method = "openai"
        
        assert session.transcription_method == "openai"
    
    def test_set_model_used(self):
        """Test setting model used."""
        session = TranscriptionSession.create("Meeting")
        session.model_used = "large-v3"
        
        assert session.model_used == "large-v3"
    
    def test_set_gpu_info(self):
        """Test setting GPU information."""
        session = TranscriptionSession.create("Meeting")
        gpu_info = {"name": "RTX 4090", "vram_gb": 24.0}
        session.gpu_info = gpu_info
        
        assert session.gpu_info == gpu_info
    
    def test_set_processing_stats(self):
        """Test setting processing statistics."""
        session = TranscriptionSession.create("Meeting")
        session.audio_duration_seconds = 3600.0  # 1 hour
        session.processing_speed_ratio = 8.5
        session.silence_periods_detected = 12
        session.speakers_detected = 3
        
        assert session.audio_duration_seconds == 3600.0
        assert session.processing_speed_ratio == 8.5
        assert session.silence_periods_detected == 12
        assert session.speakers_detected == 3


class TestSessionEdgeCases:
    """Test edge cases and error handling."""
    
    def test_complete_without_start_time(self):
        """Test completing session handles missing start time."""
        session = TranscriptionSession.create("Meeting")
        session.start_time = None
        
        session.complete(success=True)
        
        # Should not crash
        assert session.success is True
        assert session.duration_seconds is None
    
    def test_add_file_with_unknown_type(self, tmp_path):
        """Test adding file with unknown type."""
        session = TranscriptionSession.create("Meeting")
        test_file = tmp_path / "unknown.xyz"
        
        session.add_file(test_file, "unknown_type")
        
        # Should still track the file
        assert test_file in session.files_created
    
    def test_to_dict_with_none_values(self):
        """Test to_dict handles None values."""
        session = TranscriptionSession.create("Meeting")
        # Don't set any optional fields
        
        data = session.to_dict()
        
        assert data["source_file"] is None
        assert data["audio_file"] is None
        assert data["transcript_file"] is None
    
    def test_save_summary_with_special_characters(self, tmp_path):
        """Test saving summary with special characters in name."""
        session = TranscriptionSession.create("Meeting: Q4 (2025)")
        session.complete(success=True)
        
        # Should handle special characters
        summary_path = session.save_summary(tmp_path)
        
        assert summary_path.exists()


class TestSessionIntegration:
    """Test realistic session workflows."""
    
    def test_full_transcription_workflow(self, tmp_path):
        """Test complete transcription session workflow."""
        # Create session
        session = TranscriptionSession.create("Board Meeting")
        
        # Add files as they're created
        source = tmp_path / "recording.mp4"
        audio = tmp_path / "audio.wav"
        transcript = tmp_path / "transcript.txt"
        docx = tmp_path / "document.docx"
        
        session.add_file(source, "source")
        session.add_file(audio, "audio")
        session.add_file(transcript, "transcript")
        session.add_file(docx, "docx")
        
        # Set metadata
        session.transcription_method = "local"
        session.model_used = "large-v3"
        session.audio_duration_seconds = 3480.0  # 58 minutes
        session.processing_speed_ratio = 12.6
        
        # Track cleanup
        temp_file = tmp_path / "temp.wav"
        session.add_cleaned_file(temp_file)
        
        # Complete
        session.complete(success=True)
        
        # Verify
        assert session.success is True
        assert len(session.files_created) == 4
        assert len(session.files_cleaned) == 1
        assert session.duration_seconds is not None
        
        # Save and verify
        summary_path = session.save_summary(tmp_path)
        assert summary_path.exists()
        
        with open(summary_path, 'r') as f:
            data = json.load(f)
        
        assert data["success"] is True
        assert data["transcription_method"] == "local"
        assert data["processing_speed_ratio"] == 12.6
    
    def test_failed_transcription_workflow(self, tmp_path):
        """Test failed transcription session workflow."""
        session = TranscriptionSession.create("Failed Meeting")
        
        source = tmp_path / "recording.mp4"
        session.add_file(source, "source")
        
        session.transcription_method = "openai"
        session.complete(success=False, error_message="API error")
        
        # Verify failure is tracked
        assert session.success is False
        assert session.error_message == "API error"
        
        # Summary should include error
        summary = session.get_summary_text()
        assert "Failed" in summary
        assert "API error" in summary

