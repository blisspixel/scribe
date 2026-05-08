"""
Session tracking models for transcription workflows.

This module provides models for tracking transcription sessions,
including metadata, files, processing stats, and results.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class TranscriptionSession:
    """
    Track a complete transcription session.

    This class maintains all metadata about a transcription session including
    input/output files, processing method, timing, and results.

    Attributes:
        session_id: Unique identifier for this session
        meeting_name: Name of the meeting/recording
        start_time: When the session started
        end_time: When the session completed (None if in progress)
        source_file: Original source file (MP4, MKV, etc.)
        audio_file: Processed audio file (WAV or MP3)
        transcript_file: Output transcript file (TXT)
        docx_file: Output formatted document (DOCX)
        transcription_method: Method used (local, openai)
        model_used: Model name (large-v3, gpt-4o-transcribe, etc.)
        gpu_info: GPU information if GPU was used
        success: Whether transcription succeeded
        error_message: Error message if failed
        duration_seconds: Total processing time
        processing_speed_ratio: Speed ratio (e.g., 8.5x realtime)
        files_created: List of all files created
        files_cleaned: List of files cleaned up
    """

    session_id: str
    meeting_name: str
    start_time: datetime
    end_time: datetime | None = None

    # Files
    source_file: Path | None = None
    audio_file: Path | None = None
    transcript_file: Path | None = None
    docx_file: Path | None = None
    meme_file: Path | None = None
    joke_data: dict[str, str] | None = None

    # Method and settings
    transcription_method: str | None = None
    model_used: str | None = None
    gpu_info: dict[str, Any] | None = None

    # Results
    success: bool = False
    error_message: str | None = None
    duration_seconds: float | None = None
    processing_speed_ratio: float | None = None

    # File tracking
    files_created: list[Path] = field(default_factory=list)
    files_cleaned: list[Path] = field(default_factory=list)

    # Additional metadata
    audio_duration_seconds: float | None = None
    silence_periods_detected: int = 0
    speakers_detected: int = 0

    @classmethod
    def create(cls, meeting_name: str) -> "TranscriptionSession":
        """
        Create a new session with generated ID.

        Args:
            meeting_name: Name of the meeting/recording

        Returns:
            New TranscriptionSession instance
        """
        import uuid

        session_id = (
            f"{meeting_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        )

        return cls(session_id=session_id, meeting_name=meeting_name, start_time=datetime.now())

    def complete(self, success: bool = True, error_message: str | None = None) -> None:
        """
        Mark session as complete.

        Args:
            success: Whether the session succeeded
            error_message: Error message if failed
        """
        self.end_time = datetime.now()
        self.success = success
        self.error_message = error_message

        if self.start_time and self.end_time:
            self.duration_seconds = (self.end_time - self.start_time).total_seconds()

    def add_file(self, file_path: Path, file_type: str) -> None:
        """
        Add a created file to the session.

        Args:
            file_path: Path to the file
            file_type: Type of file (source, audio, transcript, docx, meme)
        """
        self.files_created.append(file_path)

        if file_type == "source":
            self.source_file = file_path
        elif file_type == "audio":
            self.audio_file = file_path
        elif file_type == "transcript":
            self.transcript_file = file_path
        elif file_type == "docx":
            self.docx_file = file_path
        elif file_type == "meme":
            self.meme_file = file_path

    def add_cleaned_file(self, file_path: Path) -> None:
        """
        Track a file that was cleaned up.

        Args:
            file_path: Path to the cleaned file
        """
        self.files_cleaned.append(file_path)

    def to_dict(self) -> dict[str, Any]:
        """
        Convert session to dictionary.

        Returns:
            Dictionary representation of session
        """
        data = asdict(self)

        # Convert datetime objects to ISO format
        if self.start_time:
            data["start_time"] = self.start_time.isoformat()
        if self.end_time:
            data["end_time"] = self.end_time.isoformat()

        # Convert Path objects to strings
        for key in [
            "source_file",
            "audio_file",
            "transcript_file",
            "docx_file",
            "meme_file",
        ]:
            if data.get(key):
                data[key] = str(data[key])

        data["files_created"] = [str(f) for f in self.files_created]
        data["files_cleaned"] = [str(f) for f in self.files_cleaned]

        return data

    def to_json(self) -> str:
        """
        Serialize session to JSON string.

        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), indent=2)

    def save_summary(self, output_dir: Path) -> Path:
        """
        Save session summary to JSON file using atomic write.

        Args:
            output_dir: Directory to save summary

        Returns:
            Path to saved summary file
        """
        from scribe.utils.safe_write import atomic_write_json
        from scribe.utils.validation import sanitize_meeting_name

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize meeting name for filename
        safe_name = sanitize_meeting_name(self.meeting_name)
        summary_file = output_dir / f"{safe_name}_session_summary.json"

        # Use atomic write to prevent corruption
        atomic_write_json(summary_file, self.to_dict())

        return summary_file

    def get_summary_text(self) -> str:
        """
        Get human-readable summary text.

        Returns:
            Formatted summary string
        """
        lines = [
            f"Session: {self.meeting_name}",
            f"ID: {self.session_id}",
            f"Started: {self.start_time.strftime('%Y-%m-%d %H:%M:%S')}",
        ]

        if self.end_time:
            lines.append(f"Completed: {self.end_time.strftime('%Y-%m-%d %H:%M:%S')}")

        if self.duration_seconds:
            minutes = int(self.duration_seconds / 60)
            lines.append(f"Duration: {minutes} minutes")

        lines.append(f"Status: {'Success' if self.success else 'Failed'}")

        if self.error_message:
            lines.append(f"Error: {self.error_message}")

        if self.transcription_method:
            lines.append(f"Method: {self.transcription_method}")

        if self.model_used:
            lines.append(f"Model: {self.model_used}")

        if self.processing_speed_ratio:
            lines.append(f"Speed: {self.processing_speed_ratio:.1f}x realtime")

        if self.audio_duration_seconds:
            audio_minutes = int(self.audio_duration_seconds / 60)
            lines.append(f"Audio Duration: {audio_minutes} minutes")

        if self.files_created:
            lines.append(f"\nFiles Created ({len(self.files_created)}):")
            for file_path in self.files_created:
                lines.append(f"  - {Path(file_path).name}")

        if self.files_cleaned:
            lines.append(f"\nFiles Cleaned ({len(self.files_cleaned)}):")
            for file_path in self.files_cleaned:
                lines.append(f"  - {Path(file_path).name}")

        return "\n".join(lines)
