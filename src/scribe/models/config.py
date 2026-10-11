"""
Configuration models with Pydantic validation.

This module provides type-safe configuration management with runtime validation,
environment variable loading, and self-healing for common configuration issues.
"""

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from scribe.exceptions import ValidationError
from scribe.models.options import FileQuality, LocalComputeType, ModelSize, TranscriptionMethod


class _ScribeUserConfigSource(PydanticBaseSettingsSource):
    """Pydantic-settings source that reads ~/.scribe/config.toml."""

    def __init__(self, settings_cls: type[BaseSettings]) -> None:
        super().__init__(settings_cls)
        from scribe.config_file import flatten_for_settings, load_config_file

        self._data: dict[str, Any] = flatten_for_settings(load_config_file())

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        if field_name in self._data:
            return self._data[field_name], field_name, False
        return None, field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(self._data)


def _find_env_file() -> str | None:
    """
    Find .env file in multiple locations.

    Search order:
    1. Current working directory
    2. User's home directory
    3. Package installation directory (where this file is)

    Returns:
        Path to .env file if found, None otherwise
    """
    # Try current working directory first
    cwd_env = Path.cwd() / ".env"
    if cwd_env.exists():
        return str(cwd_env)

    # Try user's home directory
    home_env = Path.home() / ".env"
    if home_env.exists():
        return str(home_env)

    # Try package directory and one level up (project root in editable installs).
    # __file__ = src/scribe/models/config.py -> walk up looking for .env.
    here = Path(__file__).resolve()
    for parent in (here.parent.parent.parent, here.parent.parent.parent.parent):
        candidate = parent / ".env"
        if candidate.exists():
            return str(candidate)

    # Return None to use default behavior (environment variables only)
    return None


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
        env_file=_find_env_file(),  # Find .env in multiple locations
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,  # Allow both prefixed and non-prefixed names
    )

    # Paths
    output_folder: Path = Field(
        default=Path.home() / "Videos" / "Transcriptions",
        description="Output directory for transcriptions and recordings",
    )

    log_folder: Path = Field(
        default_factory=lambda: Path.home() / ".scribe" / "logs",
        description="Directory for log files",
    )

    # Audio settings
    expected_audio_output: str | None = Field(
        default=None, description="Expected Windows audio output device name"
    )

    # Transcription settings
    default_model: ModelSize = Field(
        default="large-v3",
        description="Explicit Whisper model override; otherwise the file quality profile applies",
    )

    transcription_quality: FileQuality = Field(
        default="accurate",
        description=(
            "File profile: accurate (full large-v3), balanced (turbo), fast (small). "
            "An explicit model wins. Resident voice profiles are separate. "
            "Env: SCRIBE_TRANSCRIPTION_QUALITY."
        ),
    )

    default_language: str | None = Field(
        default=None, description="Explicit forced file language; unset/auto detects speech"
    )

    auto_detect_language: bool = Field(
        default=True,
        description="Detect file speech language when no explicit language is set",
    )

    primary_language: str = Field(
        default="en",
        description=(
            "Manual language preset used only when auto detection is disabled and no "
            "explicit language is set. Does not bias or constrain automatic detection."
        ),
    )

    default_method: TranscriptionMethod = Field(
        default="auto", description="Default transcription method"
    )

    output_formats: str = Field(
        default="json",
        description=(
            "Comma-separated structured outputs to write alongside the .txt "
            "(json, vtt, srt, md). Set empty to write only the .txt."
        ),
    )

    local_backend: str = Field(
        default="auto",
        description=(
            "Local transcription engine: auto (pick by hardware), faster-whisper, "
            "mlx (Apple Silicon), whispercpp, or cpu. Env: SCRIBE_LOCAL_BACKEND."
        ),
    )

    local_batch_size: int | None = Field(
        default=None,
        ge=0,
        description=(
            "Batched GPU decoding size for local Whisper: unset picks one from the GPU "
            "and free VRAM, 0 forces sequential decoding. Env: SCRIBE_LOCAL_BATCH_SIZE."
        ),
    )

    local_compute_type: LocalComputeType | None = Field(
        default=None,
        description=(
            "Optional faster-whisper precision override. Unset uses CPU int8 or CUDA "
            "float16/float32. Other engines reject this setting rather than ignore it. "
            "Env: SCRIBE_LOCAL_COMPUTE_TYPE."
        ),
    )

    local_only: bool = Field(
        default=False,
        description=(
            "Run everything locally at $0: force local transcription (never a "
            "cloud transcription API, even on fallback) and route notes/jokes/meme-concepts "
            "to local Ollama. Meme image generation has no local backend and is "
            "unavailable in this mode. Env: SCRIBE_LOCAL_ONLY."
        ),
    )

    # OpenAI settings
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key for cloud transcription",
        alias="OPENAI_API_KEY",  # Use standard OPENAI_API_KEY
    )

    openai_model: str = Field(
        default="gpt-4o-transcribe-diarize",
        description="OpenAI transcription model (with speaker diarization)",
    )

    # OpenRouter settings. These are inert unless --method openrouter (or an
    # equivalent explicit default_method) is selected.
    openrouter_api_key: str | None = Field(
        default=None,
        description="OpenRouter API key for optional cloud transcription",
        alias="OPENROUTER_API_KEY",
    )

    openrouter_model: str = Field(
        default="openai/whisper-large-v3",
        description="OpenRouter speech-to-text model slug",
    )

    openrouter_timeout_seconds: float = Field(
        default=90.0,
        ge=10.0,
        le=600.0,
        description="Per-request timeout for OpenRouter transcription",
    )

    openrouter_max_spend_usd: float = Field(
        default=5.0,
        gt=0.0,
        le=1000.0,
        allow_inf_nan=False,
        description=(
            "Per-transcription OpenRouter reported-cost circuit breaker in USD. "
            "A provider-side key limit is still required for an absolute cap."
        ),
    )

    # Hugging Face settings (for speaker diarization)
    hf_token: str | None = Field(
        default=None, description="Hugging Face token for speaker diarization models"
    )

    # OBS settings
    obs_host: str = Field(default="localhost", description="OBS WebSocket host")

    obs_port: int = Field(default=4455, description="OBS WebSocket port")

    obs_password: str | None = Field(default=None, description="OBS WebSocket password")

    # Processing settings
    max_retries: int = Field(
        default=3, ge=1, le=10, description="Maximum retry attempts for failed operations"
    )

    process_timeout: int = Field(
        default=14400,
        ge=60,
        description="Maximum timeout for processes in seconds",  # 4 hours
    )

    file_wait_timeout: int = Field(
        default=300,
        ge=10,
        description="Maximum time to wait for files in seconds",  # 5 minutes
    )

    max_recording_hours: float = Field(
        default=9.0,
        ge=0.1,
        le=24.0,
        description="Maximum recording duration in hours before Scribe auto-stops OBS",
    )

    recording_warning_fraction: float = Field(
        default=0.9,
        ge=0.1,
        le=1.0,
        description="Fraction of max recording duration at which to show a warning",
    )

    # Resource limits (prevent OOM and runaway processes)
    max_audio_duration_hours: float = Field(
        default=12.0,
        ge=0.1,
        le=48.0,
        description="Maximum audio duration in hours (prevents runaway processing)",
    )

    max_file_size_gb: float = Field(
        default=25.0, ge=0.01, le=100.0, description="Maximum file size in GB (prevents OOM)"
    )

    # Cleanup settings
    keep_intermediate_files: bool = Field(
        default=False, description="Keep all intermediate files (WAV, chunks, etc.)"
    )

    # Feature flags
    enable_silence_detection: bool = Field(
        default=True, description="Enable silence period detection"
    )

    enable_speaker_diarization: bool = Field(
        default=False,
        description="Opt in to local speaker labels with an installed diarization backend",
    )

    diarization_backend: str = Field(
        default="auto",
        description=(
            "Speaker diarization engine: auto (hardware-adaptive), nemotron, pyannote, mlx, "
            "or none. Env: SCRIBE_DIARIZATION_BACKEND."
        ),
    )

    name_speakers: bool = Field(
        default=False,
        description=(
            "Suggest real speaker names from the conversation with a language model "
            "(local Ollama by default; SCRIBE_SPEAKERS_PROVIDER selects a cloud provider)"
        ),
    )

    pyannote_pipeline: str = Field(
        default="pyannote/speaker-diarization-community-1",
        description="Hugging Face pipeline ID for pyannote diarization.",
    )

    enable_notes: bool = Field(
        default=False,
        description=(
            "Enable automatic meeting notes generation. Off by default because it "
            "makes several paid text-API calls per transcript. Enable automatically "
            "via SCRIBE_ENABLE_NOTES=true, ~/.scribe/config.toml, or scribe init; or "
            "generate on demand with `scribe notes <transcript>`."
        ),
    )

    enable_joke: bool = Field(
        default=False,
        description=(
            "Enable automatic joke generation. Off by default because it makes paid "
            "text-API calls per transcript. Enable automatically via "
            "SCRIBE_ENABLE_JOKE=true, ~/.scribe/config.toml, or scribe init; or "
            "generate on demand with `scribe joke <transcript>`."
        ),
    )

    enable_meme: bool = Field(
        default=False,
        description=(
            "Enable automatic meme generation. Off by default because it calls a "
            "paid image-generation API (e.g. xAI Grok Imagine, OpenAI gpt-image-2) "
            "with a multi-attempt QA loop. Enable automatically via "
            "SCRIBE_ENABLE_MEME=true, ~/.scribe/config.toml, or scribe init; or "
            "generate on demand with `scribe meme <transcript>`."
        ),
    )

    notes_model: str = Field(
        default="",
        description="Optional notes model override; empty uses the selected provider's default",
    )

    # URL download settings
    download_timeout: int = Field(
        default=600, ge=30, le=7200, description="Maximum time in seconds for URL downloads"
    )

    keep_downloads: bool = Field(
        default=False, description="Keep downloaded files after transcription (default: cleanup)"
    )

    download_folder: Path | None = Field(
        default=None, description="Directory for downloaded files (default: temp directory)"
    )

    download_audio_only: bool = Field(
        default=True, description="Download audio only from URLs (saves bandwidth)"
    )

    cookies_from_browser: str | None = Field(
        default=None,
        description="Browser to extract cookies from for URL downloads (chrome, firefox, edge, etc.)",
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
            raise ValidationError(f"Cannot create directory: {v}", context={"error": str(e)})

        # Test write permissions
        test_file = v / ".write_test"
        try:
            test_file.touch()
            test_file.unlink()
        except Exception as e:
            raise ValidationError(f"Directory not writable: {v}", context={"error": str(e)})

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
    def validate_api_key(cls, v: str | None) -> str | None:
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
                context={"provider": "openai"},
            )

        return v

    @field_validator("openrouter_api_key", mode="before")
    @classmethod
    def validate_openrouter_api_key(cls, v: str | None) -> str | None:
        """Normalize an optional OpenRouter key without logging or exposing it."""
        if v is None:
            return None

        value = str(v).strip()
        if not value:
            return None
        if len(value) < 16 or any(character.isspace() for character in value):
            raise ValidationError(
                "Invalid OpenRouter API key format",
                context={"provider": "openrouter"},
            )
        return value

    @field_validator("openrouter_model", mode="before")
    @classmethod
    def validate_openrouter_model(cls, v: str) -> str:
        """Require a bounded provider model slug before transcription starts."""
        value = str(v).strip()
        if not value or len(value) > 200 or any(character.isspace() for character in value):
            raise ValidationError(
                "Invalid OpenRouter model slug",
                context={"provider": "openrouter"},
            )
        return value

    @field_validator("default_language")
    @classmethod
    def validate_language_code(cls, v: str | None) -> str | None:
        """
        Validate language code is 2-letter ISO 639-1 format.

        Args:
            v: Language code to validate

        Returns:
            Validated language code

        Raises:
            ValidationError: If language code format is invalid
        """
        if v is None:
            return None

        v = v.strip().lower()
        if v == "auto":
            return None

        if len(v) != 2 or not v.isascii() or not v.isalpha():
            raise ValidationError(
                "Language code must be 2-letter ISO 639-1 format (e.g., 'en', 'es', 'fr')",
                context={"provided": v},
            )

        return v

    @field_validator("primary_language")
    @classmethod
    def validate_primary_language(cls, v: str) -> str:
        language = cls.validate_language_code(v)
        if language is None:
            raise ValidationError("primary_language must be a manual ISO language code, not auto")
        return language

    @field_validator("diarization_backend", mode="before")
    @classmethod
    def validate_diarization_backend(cls, v: object) -> str:
        """Normalize the diarization backend; an unknown value falls back to auto.

        Speaker labels are optional, so a typo in the config file or environment
        must not block recording or transcription.
        """
        norm = str(v or "").strip().lower() or "auto"
        if norm == "default":
            norm = "auto"
        allowed = ("auto", "nemotron", "pyannote", "mlx", "none")
        if norm not in allowed:
            import logging

            logging.getLogger(__name__).warning(
                f"Unknown diarization_backend {norm!r}; using auto "
                f"(choose one of: {', '.join(allowed)})"
            )
            return "auto"
        return norm

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
            raise ValidationError("Port must be between 1 and 65535", context={"provided": v})

        return v

    def validate_for_transcription(self, method: TranscriptionMethod) -> None:
        """
        Validate configuration for specific transcription method.

        Args:
            method: Transcription method to validate for

        Raises:
            ValidationError: If configuration is invalid for method
        """
        if method == "openai" and not self.openai_api_key:
            raise ValidationError(
                "OpenAI API key required for OpenAI transcription method",
                context={"method": method},
            )

        if method == "openrouter" and not self.openrouter_api_key:
            raise ValidationError(
                "OpenRouter API key required for OpenRouter transcription method",
                context={"method": method},
            )

        if method == "local":
            # GPU validation will be done at runtime
            pass

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """
        Inject ~/.scribe/config.toml between dotenv and file_secret sources.

        Precedence (highest to lowest): init kwargs > env vars > .env file >
        ~/.scribe/config.toml > built-in defaults. Lets the wizard persist
        preferences while keeping env vars and CLI flags as overrides.
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            _ScribeUserConfigSource(settings_cls),
            file_secret_settings,
        )

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
