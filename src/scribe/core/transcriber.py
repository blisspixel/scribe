"""
Transcription orchestrator with method selection and fallback.

This module provides intelligent transcription method selection,
graceful degradation, and file cleanup management.
"""

from pathlib import Path
from typing import Optional, Literal, List

from scribe.models.config import ScribeConfig, TranscriptionMethod
from scribe.models.session import TranscriptionSession
from scribe.models.gpu import GPUConfig
from scribe.core.converter import Converter
from scribe.core.local_whisper import LocalWhisperTranscriber
from scribe.core.openai_api import OpenAITranscriber
from scribe.exceptions import TranscriptionError, ValidationError
from scribe.utils.files import cleanup_files
from scribe.utils.resource_limits import validate_audio_file
from scribe.utils.logging import get_logger

logger = get_logger(__name__)


class Transcriber:
    """
    Orchestrates transcription with method selection and fallback.
    
    Features:
    - Automatic method selection (GPU vs OpenAI)
    - Graceful degradation on failures
    - File cleanup management
    - Session tracking
    """
    
    def __init__(self, config: ScribeConfig):
        """
        Initialize transcriber.
        
        Args:
            config: System configuration
        """
        self.config = config
        self.gpu_config = GPUConfig.detect()
        self.converter = Converter()
        
        logger.debug("Transcriber initialized")
    
    def choose_method(
        self,
        preference: TranscriptionMethod = "auto"
    ) -> Literal["local", "openai"]:
        """
        Choose transcription method based on preference and capabilities.
        
        Args:
            preference: User preference (auto, local, openai)
            
        Returns:
            Chosen method: "local" or "openai"
        """
        if preference == "local":
            if not self.gpu_config.has_gpu:
                logger.warning("Local transcription requested but no GPU available")
            return "local"
        
        elif preference == "openai":
            if not self.config.openai_api_key:
                logger.warning("OpenAI requested but API key not configured")
                return "local"
            return "openai"
        
        else:  # auto
            # Use GPU recommendation
            if self.gpu_config.recommendation == "local":
                logger.info(f"Auto-selected local transcription: {self.gpu_config.reason}")
                return "local"
            else:
                if self.config.openai_api_key:
                    logger.info(f"Auto-selected OpenAI transcription: {self.gpu_config.reason}")
                    return "openai"
                else:
                    logger.info("No OpenAI API key, falling back to local transcription")
                    return "local"
    
    def transcribe(
        self,
        audio_path: Path,
        method: TranscriptionMethod = "auto",
        session: Optional[TranscriptionSession] = None
    ) -> Path:
        """
        Transcribe audio file with automatic method selection and fallback.
        
        Args:
            audio_path: Path to audio file
            method: Transcription method preference
            session: Optional session for tracking
            
        Returns:
            Path to transcript file
            
        Raises:
            TranscriptionError: If all methods fail
            ValidationError: If file exceeds resource limits
        """
        # Validate resource limits (prevent OOM)
        logger.info("Validating audio file resource limits...")
        validate_audio_file(
            audio_path,
            max_size_gb=self.config.max_file_size_gb,
            max_duration_hours=self.config.max_audio_duration_hours
        )
        
        # Choose method
        chosen_method = self.choose_method(method)
        
        # Convert audio to optimal format
        if chosen_method == "local":
            # Check if already a WAV file
            if audio_path.suffix.lower() == '.wav':
                logger.info("Using existing WAV file for local transcription")
                audio_file = audio_path
            else:
                # Convert to 16kHz mono WAV for local transcription
                logger.info("Converting to 16kHz mono WAV for local transcription...")
                audio_file = self.converter.convert_to_wav(audio_path)
        else:
            # OpenAI supports mp3, mp4, mpeg, mpga, m4a, wav, webm directly
            # No conversion needed unless file is too large (>25MB)
            file_size_mb = audio_path.stat().st_size / (1024 * 1024)
            if file_size_mb > 24:  # Leave 1MB buffer
                from scribe.utils.logging import console
                console.print(f"[yellow]File is {file_size_mb:.0f}MB (OpenAI limit is 25MB)[/yellow]")
                console.print(f"[cyan]Converting to compressed MP3... (this may take a few minutes)[/cyan]")
                logger.info(f"File is {file_size_mb:.1f}MB, converting to compressed MP3...")
                audio_file = self.converter.convert_to_mp3(audio_path, bitrate=48)
            else:
                logger.info(f"Using original file for OpenAI API ({file_size_mb:.1f}MB)")
                audio_file = audio_path
        
        if session:
            session.add_file(audio_file, "audio")
        
        # Try primary method
        try:
            if chosen_method == "local":
                transcript_path = self._transcribe_local(audio_file, session)
            else:
                transcript_path = self._transcribe_openai(audio_file, session)
            
            if session:
                session.add_file(transcript_path, "transcript")
            
            return transcript_path
            
        except TranscriptionError as e:
            logger.error(f"Primary transcription method ({chosen_method}) failed: {e}")
            
            # Try fallback
            fallback_method = "openai" if chosen_method == "local" else "local"
            logger.info(f"Attempting fallback to {fallback_method}...")
            
            try:
                # Convert to appropriate format for fallback
                if fallback_method == "local":
                    audio_file = self.converter.convert_to_wav(audio_path)
                    transcript_path = self._transcribe_local(audio_file, session)
                else:
                    if not self.config.openai_api_key:
                        raise TranscriptionError("OpenAI API key not configured for fallback")
                    # Check file size for OpenAI
                    file_size_mb = audio_path.stat().st_size / (1024 * 1024)
                    if file_size_mb > 24:
                        audio_file = self.converter.convert_to_mp3(audio_path, bitrate=48)
                    else:
                        audio_file = audio_path
                    transcript_path = self._transcribe_openai(audio_file, session)
                
                logger.info(f"Fallback transcription successful with {fallback_method}")
                
                if session:
                    session.add_file(transcript_path, "transcript")
                    session.transcription_method = fallback_method
                
                return transcript_path
                
            except Exception as fallback_error:
                logger.error(f"Fallback transcription also failed: {fallback_error}")
                raise TranscriptionError(
                    "All transcription methods failed",
                    context={
                        "primary_method": chosen_method,
                        "primary_error": str(e),
                        "fallback_method": fallback_method,
                        "fallback_error": str(fallback_error)
                    }
                )
    
    def _transcribe_local(
        self,
        audio_path: Path,
        session: Optional[TranscriptionSession]
    ) -> Path:
        """Transcribe using local GPU."""
        transcriber = LocalWhisperTranscriber(
            model_size=self.config.default_model,
            language=self.config.default_language,
            gpu_config=self.gpu_config
        )
        
        transcript_path = transcriber.transcribe(
            audio_path,
            detect_silence=self.config.enable_silence_detection
        )
        
        if session:
            session.transcription_method = "local"
            session.model_used = f"faster-whisper-{self.config.default_model}"
            session.gpu_info = self.gpu_config.to_dict()
        
        return transcript_path
    
    def _transcribe_openai(
        self,
        audio_path: Path,
        session: Optional[TranscriptionSession]
    ) -> Path:
        """Transcribe using OpenAI API."""
        if not self.config.openai_api_key:
            raise ValidationError("OpenAI API key not configured")
        
        transcriber = OpenAITranscriber(
            api_key=self.config.openai_api_key,
            model=self.config.openai_model
        )
        
        transcript_path = transcriber.transcribe(
            audio_path,
            cleanup_temp=not self.config.keep_intermediate_files
        )
        
        if session:
            session.transcription_method = "openai"
            session.model_used = self.config.openai_model
        
        return transcript_path
    
    def cleanup_intermediate_files(
        self,
        directory: Path,
        keep_patterns: Optional[List[str]] = None
    ) -> List[Path]:
        """
        Clean up intermediate files.
        
        Keeps:
        - Source file (MP4, MKV)
        - One audio file (16k_mono.wav or .mp3)
        - Transcript (.txt)
        - Document (.docx)
        
        Deletes:
        - Temporary conversions
        - Chunks
        - Standardized files
        
        Args:
            directory: Directory to clean
            keep_patterns: Additional patterns to keep
            
        Returns:
            List of deleted files
        """
        if self.config.keep_intermediate_files:
            logger.info("Keeping all intermediate files (keep_intermediate_files=True)")
            return []
        
        # Patterns to delete - keep one audio file (WAV), delete everything else
        delete_patterns = [
            "*_temp.*",
            "*_tmp.*",
            "*_cleaned.*",
            "*_standardized.*",
            "*_chunk_*.mp3",
            "*_chunk_*.wav",
            "*_converted.mp3",  # Delete converted MP3 files
            "*.mp3",  # Delete all MP3 files (keep WAV instead)
        ]
        
        # Patterns to keep - original video, one audio file (WAV), and transcripts
        default_keep_patterns = [
            "*.mp4",  # Keep original video
            "*.mkv",  # Keep original video
            "*.avi",  # Keep original video
            "*_16k_mono.wav",  # Keep the processed WAV file
            "*_transcription.txt",  # Keep transcript
            "*_transcription.docx",  # Keep DOCX
        ]
        
        if keep_patterns:
            default_keep_patterns.extend(keep_patterns)
        
        deleted_files = cleanup_files(
            directory=directory,
            patterns=delete_patterns,
            keep_patterns=default_keep_patterns
        )
        
        if deleted_files:
            total_size_mb = sum(
                f.stat().st_size for f in deleted_files if f.exists()
            ) / (1024 * 1024)
            logger.info(
                f"Cleaned up {len(deleted_files)} files "
                f"({total_size_mb:.1f}MB freed)"
            )
        
        return deleted_files
