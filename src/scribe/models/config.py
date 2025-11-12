"""
Configuration models with Pydantic validation.

This module provides type-safe configuration management with runtime validation,
environment variable loading, and self-healing for common configuration issues.
"""

import os
from pathlib import Path
from typing import Optional, Literal

from pydantic import BaseModel, Field, field_validator, ConfigDict
from pydantic_settings import BaseSettings, SettingsConfigDict

from scribe.exceptions import ValidationError


TranscriptionMethod = Literal["auto", "local", "openai"]
ModelSize = Literal["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]


class ScribeConfig(BaseSettings):
    """
    System configuration with validation and environment variable loading.
    
    This configuration class provides:
    - Automatic loading from environment variables (SCRIBE_ prefix)
    - Loading from .env file
    - Runtime validation of all values
    - Self-healing for common path issues
    - Type safety with Pydantic
    
    Example:
        # Load from environment
        config = ScribeConfig()
        
        # Or provide values directly
        config = ScribeConfig(
            output_folder=Path("/custom/output"),
            openai_api_key="sk-..."
        )
    """
    
    model_config = SettingsConfigDict(
        env_prefix="SCRIBE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,  # Allow both prefixed and non-prefixed names
    )
    
    # Paths
    output_folder: Path = Field(
        default=Path.home() / "Videos" / "Transcriptions",
        description="Output directory for transcriptions and recordings"
    )
    
    log_folder: Path = Field(
        default=Path("logs"),
        description="Directory for log files"
    )
    
    # Audio settings
    expected_audio_output: Optional[str] = Field(
        default=None,
        description="Expected Windows audio output device name"
    )
    
    # Transcription settings
    default_model: ModelSize = Field(
        default="large-v3",
        description="Default Whisper model size"
    )
    
    default_language: str = Field(
        default="en",
        description="Default language code (ISO 639-1)"
    )
    
    default_method: TranscriptionMethod = Field(
        default="auto",
        description="Default transcription method"
    )
    
    # OpenAI settings
    openai_api_key: Optional[str] = Field(
        default=None,
        description="OpenAI API key for cloud transcription",
        alias="OPENAI_API_KEY"  # Use standard OPENAI_API_KEY
    )
    
    openai_model: str = Field(
        default="gpt-4o-transcribe",
        description="OpenAI transcription model"
    )
    
    # Hugging Face settings (for speaker diarization)
    hf_token: Optional[str] = Field(
        default=None,
        description="Hugging Face token for speaker diarization models"
    )
    
    # OBS settings
    obs_host: str = Field(
        default="localhost",
        description="OBS WebSocket host"
    )
    
    obs_port: int = Field(
        default=4455,
        description="OBS WebSocket port"
    )
    
    obs_password: Optional[str] = Field(
        default=None,
        description="OBS WebSocket password"
    )
    
    # Processing settings
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retry attempts for failed operations"
    )
    
    process_timeout: int = Field(
        default=14400,  # 4 hours
        ge=60,
        description="Maximum timeout for processes in seconds"
    )
    
    file_wait_timeout: int = Field(
        default=300,  # 5 minutes
        ge=10,
        description="Maximum time to wait for files in seconds"
    )
    
    # Resource limits (prevent OOM and runaway processes)
    max_audio_duration_hours: float = Field(
        default=12.0,
        ge=0.1,
        le=48.0,
        description="Maximum audio duration in hours (prevents runaway processing)"
    )
    
    max_file_size_gb: float = Field(
        default=25.0,
        ge=0.01,
        le=100.0,
        description="Maximum file size in GB (prevents OOM)"
    )
    
    # Cleanup settings
    keep_intermediate_files: bool = Field(
        default=False,
        description="Keep all intermediate files (WAV, chunks, etc.)"
    )
    
    # Feature flags
    enable_silence_detection: bool = Field(
        default=True,
        description="Enable silence period detection"
    )
    
    enable_speaker_diarization: bool = Field(
        default=True,
        description="Enable speaker diarization (requires HF_TOKEN)"
    )
    
    enable_notes: bool = Field(
        default=True,
        description="Enable automatic meeting notes generation"
    )
    
    notes_model: str = Field(
        default="gpt-5",
        description="GPT model to use for notes generation"
    )
    
    @field_validator("output_folder", "log_folder")
    @classmethod
    def validate_and_create_folder(cls, v: Path) -> Path:
        """
        Validate and create directory if it doesn't exist.
        
        This validator:
        - Expands ~ to home directory
        - Converts to absolute path
        - Creates directory if missing
        - Tests write permissions
        
        Args:
            v: Path to validate
            
        Returns:
            Validated and created Path
            
        Raises:
            ValidationError: If path is not writable
        """
        # Expand and resolve path
        v = v.expanduser().resolve()
        
        # Create directory if it doesn't exist
        try:
            v.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise ValidationError(
                f"Cannot create directory: {v}",
                context={"error": str(e)}
            )
        
        # Test write permissions
        test_file = v / ".write_test"
        try:
            test_file.touch()
            test_file.unlink()
        except Exception as e:
            raise ValidationError(
                f"Directory not writable: {v}",
                context={"error": str(e)}
            )
        
        # Check disk space (warn if < 1GB)
        import shutil
        try:
            stat = shutil.disk_usage(v)
            free_gb = stat.free / (1024**3)
            if free_gb < 1.0:
                import logging
                logging.warning(f"Low disk space: {free_gb:.1f}GB free in {v}")
        except Exception:
            pass  # Don't fail on disk space check
        
        return v
    
    @field_validator("openai_api_key", mode="before")
    @classmethod
    def validate_api_key(cls, v: Optional[str]) -> Optional[str]:
        """
        Validate OpenAI API key format.
        
        Accepts OPENAI_API_KEY (standard) or SCRIBE_OPENAI_API_KEY (legacy).
        
        Args:
            v: API key to validate
            
        Returns:
            Validated API key or None
            
        Raises:
            ValidationError: If API key format is invalid
        """
        if v is None:
            return None
        
        v = v.strip()
        
        if not v:
            return None
        
        if not v.startswith("sk-"):
            raise ValidationError(
                "Invalid OpenAI API key format (should start with 'sk-')",
                context={"key_prefix": v[:10] if len(v) >= 10 else v}
            )
        
        return v
    
    @field_validator("default_language")
    @classmethod
    def validate_language_code(cls, v: str) -> str:
        """
        Validate language code is 2-letter ISO 639-1 format.
        
        Args:
            v: Language code to validate
            
        Returns:
            Validated language code
            
        Raises:
            ValidationError: If language code format is invalid
        """
        v = v.strip().lower()
        
        if len(v) != 2:
            raise ValidationError(
                "Language code must be 2-letter ISO 639-1 format (e.g., 'en', 'es', 'fr')",
                context={"provided": v}
            )
        
        return v
    
    @field_validator("obs_port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """
        Validate port number is in valid range.
        
        Args:
            v: Port number to validate
            
        Returns:
            Validated port number
            
        Raises:
            ValidationError: If port is out of range
        """
        if not (1 <= v <= 65535):
            raise ValidationError(
                "Port must be between 1 and 65535",
                context={"provided": v}
            )
        
        return v
    
    def validate_for_transcription(self, method: TranscriptionMethod) -> None:
        """
        Validate configuration for specific transcription method.
        
        Args:
            method: Transcription method to validate for
            
        Raises:
            ValidationError: If configuration is invalid for method
        """
        if method == "openai":
            if not self.openai_api_key:
                raise ValidationError(
                    "OpenAI API key required for OpenAI transcription method",
                    context={"method": method}
                )
        
        if method == "local":
            # GPU validation will be done at runtime
            pass
    
    def get_session_log_path(self, session_name: str) -> Path:
        """
        Get log file path for a session.
        
        Args:
            session_name: Name of the session
            
        Returns:
            Path to log file
        """
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.log_folder / f"scribe_{session_name}_{timestamp}.log"
