"""
Transcription orchestrator with local-first method selection and bounded fallback.

═══════════════════════════════════════════════════════════════════════════════
ARCHITECTURAL PATTERN: Facade + Strategy + Chain of Responsibility
═══════════════════════════════════════════════════════════════════════════════

This module implements a sophisticated orchestration layer that combines three
design patterns to create a robust, self-healing transcription system:

1. FACADE PATTERN: Provides a simple interface (transcribe()) that hides the
   complexity of GPU detection, format conversion, method selection, and error
   recovery. Clients don't need to understand the underlying subsystems.

2. STRATEGY PATTERN: Encapsulates local and cloud transcription algorithms
   behind a common interface, allowing runtime selection based on
   system capabilities and user preferences.

3. CHAIN OF RESPONSIBILITY: An explicitly selected cloud attempt may fall back to
   local processing. Local and automatic requests never upload audio as fallback.

DESIGN RATIONALE:
─────────────────
Transcription is inherently unreliable - GPUs can run out of memory, APIs can
be rate-limited, audio files can be corrupted. Rather than exposing this
complexity to callers, the Transcriber provides a "best effort" interface that:

- Uses local transcription by default and honors explicit cloud selection
- Validates resources before attempting transcription (fail fast)
- Converts audio to the optimal format for each method
- Falls back to alternative methods on failure
- Tracks session metadata for debugging and analytics
- Cleans up intermediate files to prevent disk bloat

This design embodies the principle of "make the common case simple, make the
complex case possible": callers can use transcribe() for the standard path,
while power users can override method selection and control cleanup behavior.

TRANSCRIPTION PIPELINE:
───────────────────────
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. VALIDATION PHASE                                                         │
│    ├─ Check file size against max_file_size_gb (prevent OOM)               │
│    ├─ Check duration against max_audio_duration_hours (prevent timeout)    │
│    └─ Validate file format and accessibility                               │
├─────────────────────────────────────────────────────────────────────────────┤
│ 2. METHOD SELECTION PHASE                                                   │
│    ├─ User preference: "local", "openai", "openrouter", or "auto"        │
│    ├─ Detect the available local backend and model tier                    │
│    ├─ Check an API key only for an explicit cloud request                  │
│    └─ Decision: local by default; cloud only when selected                  │
├─────────────────────────────────────────────────────────────────────────────┤
│ 3. FORMAT CONVERSION PHASE                                                  │
│    ├─ Local method: Convert to 16kHz mono WAV (optimal for Whisper)       │
│    ├─ API method: Keep original if <25MB, else compress to MP3            │
│    └─ Atomic conversion: Write to temp file, rename on success            │
├─────────────────────────────────────────────────────────────────────────────┤
│ 4. TRANSCRIPTION PHASE                                                      │
│    ├─ Execute primary method with progress tracking                        │
│    ├─ On failure: preserve local/cloud trust boundaries                    │
│    └─ On success: Return transcript path, update session metadata          │
├─────────────────────────────────────────────────────────────────────────────┤
│ 5. CLEANUP PHASE                                                            │
│    ├─ Keep: Original file, final audio, transcript, documents             │
│    ├─ Delete: Temp conversions, chunks, standardized files                │
│    └─ Log: Files deleted, space freed                                      │
└─────────────────────────────────────────────────────────────────────────────┘

INTELLIGENT METHOD SELECTION:
──────────────────────────────
The choose_method() algorithm implements a decision tree that considers:

1. Explicit user preference (overrides all other factors)
2. The local-only policy
3. API key presence for an explicit cloud request

Decision matrix:
┌──────────────┬─────────────┬─────────────┬──────────────────┐
│ Preference   │ GPU Present │ API Key     │ Selected Method  │
├──────────────┼─────────────┼─────────────┼──────────────────┤
│ "local"      │ Yes         │ Any         │ local            │
│ "local"      │ No          │ Any         │ local (warning)  │
│ "openai"     │ Any         │ Yes         │ openai           │
│ "openai"     │ Any         │ No          │ local (fallback) │
│ "openrouter" │ Any         │ Yes         │ openrouter       │
│ "openrouter" │ Any         │ No          │ local (fallback) │
│ "auto"       │ Yes         │ Any         │ local            │
│ "auto"       │ No          │ Yes         │ local            │
│ "auto"       │ No          │ No          │ local (warning)  │
└──────────────┴─────────────┴─────────────┴──────────────────┘

FALLBACK STRATEGY:
──────────────────
When explicitly selected cloud transcription fails, Scribe may fall back to the
local backend. Local and automatic requests never fall back to cloud because that
would upload audio without explicit permission.

Fallback is NOT attempted for:
- ValidationError (file too large, invalid format)
- Music mode with "No speech detected" (expected for instrumental tracks)

This prevents infinite retry loops and respects domain-specific error semantics.

PERFORMANCE CHARACTERISTICS:
────────────────────────────
Local transcription speed depends on the selected backend, model, and hardware.
It has no provider usage charge and keeps audio on the machine. Cloud
transcription speed, pricing, file limits, and capabilities depend on the selected
provider model; audio is uploaded only after an explicit cloud selection.

RESEARCH REFERENCES:
────────────────────
- "Design Patterns: Elements of Reusable Object-Oriented Software" (GoF, 1994)
  -> Facade, Strategy, Chain of Responsibility patterns
- "Release It! Design and Deploy Production-Ready Software" (Nygard, 2018)
  -> Circuit breaker, bulkhead, timeout patterns for resilience
- "Whisper: Robust Speech Recognition via Large-Scale Weak Supervision" (Radford et al., 2022)
  -> Understanding of Whisper's initial_prompt mechanism for vocabulary guidance

This orchestration layer is the heart of Scribe's reliability - it makes
transcription "just work" by handling the complexity of method selection,
format conversion, error recovery, and resource management transparently.
"""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional, cast

if TYPE_CHECKING:
    from scribe.core.backends import TranscriptionBackend
    from scribe.core.diarizer import SpeakerDiarizer
    from scribe.utils.vocabulary import CustomVocabulary

from scribe.core.converter import Converter
from scribe.core.local_whisper import LocalWhisperTranscriber
from scribe.core.openai_api import OpenAITranscriber
from scribe.core.openrouter_api import OpenRouterTranscriber
from scribe.exceptions import TranscriptionError, ValidationError
from scribe.models.config import ScribeConfig
from scribe.models.gpu import GPUConfig
from scribe.models.options import ModelSize, TranscriptionMethod
from scribe.models.session import TranscriptionSession
from scribe.models.transcript import Transcript
from scribe.models.transcription_review import AcousticPass
from scribe.utils.files import cleanup_files
from scribe.utils.logging import get_logger
from scribe.utils.model_selection import (
    resolve_local_batch_size,
    resolve_local_language,
    resolve_local_model,
    resolve_verification,
)
from scribe.utils.resource_limits import validate_audio_file

logger = get_logger(__name__)


class Transcriber:
    """
    Orchestrates transcription with intelligent method selection and fallback.

    This class provides the main interface for transcription operations,
    handling method selection, format conversion, and error recovery.

    Attributes:
        config: System configuration (models, paths, API keys)
        gpu_config: GPU detection and capability information
        converter: Audio format converter instance

    Features:
        - Local-first automatic method selection
        - Local fallback after an explicitly selected cloud failure
        - Audio format conversion for optimal processing
        - Resource limit validation to prevent OOM
        - Session tracking for metadata and debugging
        - Cleanup of intermediate files

    Example:
        >>> from scribe.core.transcriber import Transcriber
        >>> from scribe.models.config import ScribeConfig
        >>>
        >>> config = ScribeConfig()
        >>> transcriber = Transcriber(config)
        >>>
        >>> # Transcribe with automatic method selection
        >>> transcript = transcriber.transcribe(audio_path)
        >>> print(f"Transcript: {transcript}")

    Notes:
        - GPU detection happens once at initialization
        - Converter is reused across multiple transcriptions
        - Method selection can be overridden per transcription
        - Fallback is automatic and transparent to caller
    """

    def __init__(self, config: ScribeConfig):
        """
        Initialize transcriber with configuration and detect GPU.

        Performs GPU detection and initializes the audio converter.
        GPU detection results are cached for the lifetime of the instance.

        Args:
            config: System configuration containing:
                - Model settings (default_model, openai_model, openrouter_model)
                - API keys (openai_api_key, openrouter_api_key)
                - File paths (output_folder, log_folder)
                - Processing options (keep_intermediate_files)

        Example:
            >>> config = ScribeConfig()
            >>> transcriber = Transcriber(config)
            >>> print(f"GPU available: {transcriber.gpu_config.has_gpu}")

        Notes:
            - GPU detection is performed immediately
            - Converter is initialized but doesn't load models yet
            - Configuration is stored for use in transcription methods
        """
        logger.debug("Initializing Transcriber")

        self.config = config
        self.gpu_config = GPUConfig.detect()
        self.converter = Converter()
        # Structured transcript from the most recent transcribe(), so the CLI can
        # write JSON/VTT/SRT/Markdown artifacts without re-parsing the .txt.
        self.last_transcript: Transcript | None = None
        self.review_phase_callback: Callable[[str], None] | None = None
        self.review_error: str | None = None
        self._review_primary: AcousticPass | None = None
        self._review_source: Path | None = None
        self._cached_diarizer: SpeakerDiarizer | None = None

        logger.info(
            f"Transcriber initialized - GPU: {self.gpu_config.has_gpu}, "
            f"Model: {config.default_model}, "
            "Cloud keys: OpenAI=%s, OpenRouter=%s",
            "configured" if config.openai_api_key else "not configured",
            "configured" if config.openrouter_api_key else "not configured",
        )

        if self.gpu_config.has_gpu:
            logger.debug(
                f"GPU detected: {self.gpu_config.gpu_name}, "
                f"VRAM: {self.gpu_config.gpu_memory_gb:.1f}GB, "
                f"Recommended model: {self.gpu_config.model_size}"
            )

    def choose_method(
        self, preference: TranscriptionMethod = "auto"
    ) -> Literal["local", "openai", "openrouter"]:
        """
        Choose transcription method based on preference and system capabilities.

        Implements intelligent method selection considering:
        - User preference (explicit choice or auto)
        - GPU availability and capabilities
        - API key configuration
        - Explicit local-only policy

        Args:
            preference: User preference for transcription method:
                - "auto": Automatic selection based on capabilities
                - "local": Force local transcription
                - "openai": Force OpenAI API transcription
                - "openrouter": Force OpenRouter API transcription

        Returns:
            Chosen method: "local", "openai", or "openrouter"

        Example:
            >>> transcriber = Transcriber(config)
            >>> method = transcriber.choose_method("auto")
            >>> print(f"Selected method: {method}")
            Selected method: local

        Notes:
            - "local" runs on a compatible accelerator or the CPU fallback
            - "openai" without API key falls back to "local"
            - "openrouter" without API key falls back to "local"
            - "auto" stays local and never silently selects a paid API
            - Warnings are logged for suboptimal configurations
        """
        logger.debug(f"Choosing transcription method - preference: {preference}")

        # Local-only mode ($0): never touch a cloud API, whatever the preference.
        if getattr(self.config, "local_only", False):
            if preference in {"openai", "openrouter"}:
                logger.warning(
                    "%s transcription requested but local-only mode is enabled "
                    "(SCRIBE_LOCAL_ONLY); using free local transcription instead.",
                    preference,
                )
            return "local"

        if preference == "local":
            logger.debug("Local transcription selected")
            return "local"

        elif preference == "openai":
            if not self.config.openai_api_key:
                logger.warning(
                    "OpenAI API requested but API key not configured - "
                    "falling back to local transcription"
                )
                return "local"
            logger.info(f"OpenAI API transcription selected - Model: {self.config.openai_model}")
            return "openai"

        elif preference == "openrouter":
            if not self.config.openrouter_api_key:
                logger.warning(
                    "OpenRouter requested but OPENROUTER_API_KEY is not configured; "
                    "falling back to local transcription"
                )
                return "local"
            logger.info(
                "OpenRouter transcription selected - Model: %s", self.config.openrouter_model
            )
            return "openrouter"

        else:  # auto
            # $0-first: local transcription runs on any machine (GPU when present,
            # CPU int8 as the universal floor), so "auto" never silently spends on
            # a paid API. Users opt in explicitly with --method openai or openrouter.
            logger.debug("Auto-selected local transcription")
            return "local"

    def _prepare_audio_for_method(self, audio_path: Path, method: TranscriptionMethod) -> Path:
        """Prepare audio file in optimal format for chosen transcription method."""
        if method == "local":
            if audio_path.suffix.lower() == ".wav":
                logger.info("Using existing WAV file for local transcription")
                return audio_path
            logger.info("Converting to 16kHz mono WAV for local transcription...")
            return self.converter.convert_to_wav(audio_path)
        elif method == "openai":
            # OpenAI API - check file size
            file_size_mb = audio_path.stat().st_size / (1024 * 1024)
            if file_size_mb > 24:
                from scribe.utils.logging import console

                console.print(
                    f"[yellow]File is {file_size_mb:.0f}MB (OpenAI limit is 25MB)[/yellow]"
                )
                console.print("[cyan]Converting to compressed MP3...[/cyan]")
                logger.info(f"File is {file_size_mb:.1f}MB, converting to compressed MP3...")
                return self.converter.convert_to_mp3(audio_path, bitrate=48)
            else:
                logger.info(f"Using original file for OpenAI API ({file_size_mb:.1f}MB)")
                return audio_path
        else:
            # OpenRouter always normalizes and splits behind its upload boundary.
            # Keeping the original here avoids a lossy double conversion in CLI paths.
            logger.info("OpenRouter will normalize audio into bounded upload chunks")
            return audio_path

    def _detect_language_for_music(
        self, audio_file: Path, detector: LocalWhisperTranscriber
    ) -> tuple[str | None, float]:
        """Use the selected faster-whisper decoder for its music speech pre-pass."""
        from scribe.utils.logging import console

        console.print("  [dim]Detecting language...[/dim]", end="")
        detected_lang, confidence, has_speech = detector.detect_language(audio_file)

        if not has_speech:
            console.print(" [yellow]no speech[/yellow]")
            raise TranscriptionError(
                "No speech detected in audio (file may be silent or contain only noise)"
            )

        if detected_lang:
            logger.info(f"Using detected language: {detected_lang} ({confidence:.1%} confidence)")
            console.print(f" [green]{detected_lang.upper()}[/green] [dim]({confidence:.0%})[/dim]")
            return detected_lang, confidence
        else:
            logger.info("Speech detected but uncertain language, using auto-detect")
            console.print(" [green]auto-detect[/green]")
            return None, confidence

    def _get_effective_local_model(self) -> ModelSize:
        """Resolve file quality without silently downgrading for hardware."""
        configured_model = self.config.default_model
        configured_fields: set[str] = cast(
            set[str], getattr(self.config, "model_fields_set", set())
        )
        effective_model, profile_adjusted = resolve_local_model(
            configured_model, configured_fields, self.config.transcription_quality
        )
        if profile_adjusted:
            logger.info(
                "File quality profile selects local Whisper model %s instead of %s",
                effective_model,
                configured_model,
            )
        return effective_model

    def _attempt_fallback_transcription(
        self,
        audio_path: Path,
        chosen_method: TranscriptionMethod,
        session: TranscriptionSession | None,
        custom_vocabulary: Optional["CustomVocabulary"],
        music_mode: bool,
        primary_error: Exception,
        language_override: str | None = None,
    ) -> Path:
        """Fall back from explicitly selected cloud transcription to local processing."""
        if chosen_method not in {"openai", "openrouter"}:
            raise TranscriptionError(
                "Cloud transcription was not explicitly selected; local audio was not uploaded",
                context={"primary_method": chosen_method},
            ) from primary_error
        fallback_method = "local"
        logger.info(f"Attempting fallback to {fallback_method}...")

        audio_file = self.converter.convert_to_wav(audio_path)
        transcript_path = self._transcribe_local(
            audio_file,
            session,
            custom_vocabulary,
            music_mode,
            language_override,
        )

        logger.info(f"Fallback transcription successful with {fallback_method}")

        if session:
            session.add_file(transcript_path, "transcript")
            session.transcription_method = fallback_method

        return transcript_path

    def transcribe(
        self,
        audio_path: Path,
        method: TranscriptionMethod = "auto",
        session: TranscriptionSession | None = None,
        custom_vocabulary: Optional["CustomVocabulary"] = None,
        music_mode: bool = False,
    ) -> Path:
        """
        Transcribe audio file with automatic method selection and fallback.

        Args:
            audio_path: Path to audio file
            method: Transcription method preference
            session: Optional session for tracking
            custom_vocabulary: Optional custom vocabulary for improved accuracy
            music_mode: If True, optimized for music/lyrics transcription

        Returns:
            Path to transcript file

        Raises:
            TranscriptionError: If all methods fail
            ValidationError: If file exceeds resource limits
        """
        try:
            transcript_path = self._transcribe(
                audio_path, method, session, custom_vocabulary, music_mode
            )
        finally:
            # Free GPU memory as soon as this file is done, so a finished run never
            # holds the Whisper model while notes use a local LLM, while a shortcut
            # window waits for Enter, or across long-lived processes.
            self.release_resources()
        if not music_mode:
            self._name_speakers(transcript_path, audio_path)
        return transcript_path

    def _name_speakers(self, transcript_path: Path, audio_path: Path) -> None:
        """Add best-guess speaker names and re-render the .txt, when enabled.

        Runs after GPU memory is released so a local model has room. Applies only
        to transcripts from the local writer; naming never fails a transcription.
        """
        transcript = self.last_transcript
        if (
            not getattr(self.config, "name_speakers", False)
            or transcript is None
            or not transcript.speakers
            or "silence_periods" not in transcript.metadata
        ):
            return

        from dataclasses import replace

        from scribe.core.local_whisper import rewrite_clean_transcript
        from scribe.core.speaker_naming import name_speakers

        names = name_speakers(transcript)
        if not names:
            return
        named = replace(transcript, metadata={**transcript.metadata, "speaker_names": names})
        try:
            rewrite_clean_transcript(named, transcript_path, audio_path)
        except OSError as e:
            logger.warning(f"Could not add speaker names to {transcript_path.name}: {e}")
            return
        self.last_transcript = named

    def release_resources(self) -> None:
        """Unload local models (Whisper and the diarizer) and release GPU memory.

        Safe to call repeatedly and after any failure. The next transcription loads
        what it needs again.
        """
        self._cached_diarizer = None
        try:
            from scribe.utils.gpu_manager import get_gpu_manager

            get_gpu_manager().unload_current_model()
        except Exception as e:
            logger.debug(f"GPU model release failed: {e}")
        import gc

        gc.collect()
        if self.gpu_config.has_gpu:
            from scribe.utils.gpu import clear_gpu_cache

            clear_gpu_cache()

    def _transcribe(
        self,
        audio_path: Path,
        method: TranscriptionMethod,
        session: TranscriptionSession | None,
        custom_vocabulary: Optional["CustomVocabulary"],
        music_mode: bool,
    ) -> Path:
        """Body of :meth:`transcribe`; the public wrapper releases GPU resources."""
        # Reset so a stale transcript from a previous call can never be written as
        # this file's structured sidecar if a path forgets to repopulate it.
        self.last_transcript = None
        self.review_error = None
        self._review_primary = None
        self._review_source = session.source_file if session and session.source_file else audio_path

        # Validate resource limits
        logger.info("Validating audio file resource limits...")
        validate_audio_file(
            audio_path,
            max_size_gb=self.config.max_file_size_gb,
            max_duration_hours=self.config.max_audio_duration_hours,
        )

        # Choose method and prepare audio
        chosen_method = self.choose_method(method)
        audio_file = self._prepare_audio_for_method(audio_path, chosen_method)

        if session:
            session.add_file(audio_file, "audio")

        # Try primary method
        try:
            if chosen_method == "local":
                transcript_path = self._transcribe_local(
                    audio_file,
                    session,
                    custom_vocabulary,
                    music_mode,
                )
            elif chosen_method == "openai":
                transcript_path = self._transcribe_openai(audio_file, session, custom_vocabulary)
            else:
                transcript_path = self._transcribe_openrouter(
                    audio_file, session, custom_vocabulary
                )

            self._complete_acoustic_review(transcript_path, session, music_mode)
            self._apply_term_normalization(transcript_path, custom_vocabulary)

            if session:
                session.add_file(transcript_path, "transcript")

            return transcript_path

        except TranscriptionError as e:
            # In music mode, instrumental detection is expected
            if music_mode and "No speech detected" in str(e):
                logger.debug("No speech detected in music file (likely instrumental)")
                raise

            logger.error(f"Primary transcription method ({chosen_method}) failed: {e}")

            # In music mode, don't fallback
            if music_mode:
                raise

            # A local or auto request never grants permission to upload audio.
            if chosen_method == "local":
                logger.error(
                    "Local transcription failed; audio remains on-device. Select "
                    "--method openai or --method openrouter explicitly to permit "
                    "cloud transcription."
                )
                raise

            # Attempt fallback
            try:
                transcript_path = self._attempt_fallback_transcription(
                    audio_path,
                    chosen_method,
                    session,
                    custom_vocabulary,
                    music_mode,
                    e,
                )
                self._complete_acoustic_review(transcript_path, session, music_mode)
                self._apply_term_normalization(transcript_path, custom_vocabulary)
                return transcript_path

            except Exception as fallback_error:
                logger.error(f"Fallback transcription also failed: {fallback_error}")
                fallback_method = "local"
                raise TranscriptionError(
                    "All transcription methods failed",
                    context={
                        "primary_method": chosen_method,
                        "primary_error": str(e),
                        "fallback_method": fallback_method,
                        "fallback_error": str(fallback_error),
                    },
                )

    def _report_review_phase(self, phase: str) -> None:
        logger.info("Acoustic review: %s", phase)
        if self.review_phase_callback is not None:
            try:
                self.review_phase_callback(phase)
            except Exception as error:
                logger.warning("Could not display acoustic phase: %s", error)

    def _complete_acoustic_review(
        self, transcript_path: Path, session: TranscriptionSession | None, music_mode: bool
    ) -> None:
        from scribe.core.transcription_review import complete_review, unavailable_review

        policy = resolve_verification(
            self.config.transcription_quality, self.config.transcription_verification
        )
        if policy == "off":
            return
        if music_mode or self.last_transcript is None:
            reason = "Acoustic review unavailable for music or an untimed primary transcript"
            logger.warning(reason)
            receipt, paths = unavailable_review(
                self.config,
                self._review_source or transcript_path,
                self.last_transcript,
                transcript_path,
                reason,
            )
        else:
            # The primary model's context has ended before the independent checkpoint loads.
            self.release_resources()
            receipt, paths = complete_review(
                self.config,
                self.gpu_config,
                self._review_source or transcript_path,
                self.last_transcript,
                self._review_primary,
                self._report_review_phase,
            )
        self.review_error = receipt.error if policy == "required" else None
        if session:
            session.review_source_required = receipt.requires_review
            if self.review_error:
                session.artifact_errors.append(self.review_error)
            for path in paths:
                session.add_file(path, "acoustic_review")
        logger.info(
            "Acoustic review %s; %s spans require review. Agreement is not proof of accuracy.",
            receipt.status,
            len(receipt.spans),
        )

    def _apply_term_normalization(
        self, transcript_path: Path, custom_vocabulary: Optional["CustomVocabulary"]
    ) -> None:
        """Rewrite known misrecognitions to canonical terms in the .txt and Transcript.

        Deterministic, offline glossary normalization applied to every path so the
        .txt on disk and the structured outputs (built from last_transcript) come out
        consistent. A no-op when the vocabulary carries no aliases.
        """
        aliases = getattr(custom_vocabulary, "aliases", None)
        if not aliases:
            return

        from scribe.utils.term_normalize import build_replacements, normalize_txt_body

        replacements = build_replacements(aliases)
        if not replacements:
            return
        try:
            body = transcript_path.read_text(encoding="utf-8")
            transcript_path.write_text(normalize_txt_body(body, replacements), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Term normalization of transcript text failed: {e}")
        if self.last_transcript is not None and custom_vocabulary is not None:
            self.last_transcript = custom_vocabulary.normalize_transcript(self.last_transcript)

    def _transcribe_local(
        self,
        audio_path: Path,
        session: TranscriptionSession | None,
        custom_vocabulary: Optional["CustomVocabulary"] = None,
        music_mode: bool = False,
        language_override: str | None = None,
    ) -> Path:
        """Transcribe locally, picking the engine that fits the hardware."""
        from scribe.core.backends import (
            CPU,
            FASTER_WHISPER,
            build_backend,
            detect_hardware,
            select_backend,
        )

        language = (
            language_override
            if language_override is not None
            else self._get_effective_file_language()
        )
        model_size = self._get_effective_local_model()

        # Convert vocabulary to Whisper prompt format
        initial_prompt = None
        if custom_vocabulary:
            initial_prompt = custom_vocabulary.to_prompt()
            logger.info(f"Using custom vocabulary with {len(custom_vocabulary)} terms")
        elif music_mode:
            # Use music-specific prompt
            initial_prompt = "Song lyrics."

        hardware = detect_hardware()
        backend_name = select_backend(
            hardware, override=getattr(self.config, "local_backend", "auto")
        )
        override = self.config.local_backend.strip().lower()
        if override not in ("", "auto", "default") and backend_name != override:
            raise TranscriptionError(
                f"Requested local backend {override!r} is unknown or unavailable. "
                "Install its optional extra or explicitly select another local backend.",
                context={"backend": override, "model": model_size},
            )
        logger.info(
            f"Local backend: {backend_name} "
            f"(hardware: {hardware.vendor}, {hardware.accelerator_name or 'cpu'})"
        )

        # Local speaker diarization (skipped for music). Resolved here so both
        # engine paths label speakers identically before writing.
        diarizer = None if music_mode else self._build_diarizer()

        # NVIDIA and the CPU floor stay on the production faster-whisper engine,
        # which also runs the silence pre-pass. Other vendors route to mlx-whisper
        # or whisper.cpp, which produce the same Transcript written by the same
        # shared writer.
        if backend_name in (FASTER_WHISPER, CPU):
            transcript_path = self._transcribe_faster_whisper(
                audio_path,
                model_size,
                language,
                initial_prompt,
                diarizer,
                force_cpu=backend_name == CPU,
                music_mode=music_mode,
            )
        else:
            if self.config.local_compute_type is not None:
                raise TranscriptionError(
                    f"local_compute_type is a faster-whisper setting; {backend_name} does not "
                    "support this override. Unset it or explicitly select cpu/faster-whisper."
                )
            if self.config.local_batch_size not in (None, 0):
                raise TranscriptionError(
                    f"local_batch_size is a faster-whisper setting; {backend_name} does not "
                    "support batching. Unset it or explicitly select cpu/faster-whisper."
                )
            transcript_path = self._transcribe_alt_backend(
                build_backend(backend_name),
                audio_path,
                model_size,
                language,
                initial_prompt,
                diarizer,
            )

        if session:
            session.transcription_method = "local"
            # Label with the engine that actually ran (from the Transcript's own
            # provenance) so the CPU floor reads "faster-whisper-..." not "cpu-...".
            engine = (
                self.last_transcript.backend
                if self.last_transcript and self.last_transcript.backend
                else backend_name
            )
            session.model_used = f"{engine}-{model_size}"
            session.gpu_info = self.gpu_config.to_dict()

        return transcript_path

    def _get_effective_file_language(self) -> str | None:
        """Resolve explicit/manual/automatic language selection in one place."""
        return resolve_local_language(
            self.config.default_language,
            self.config.auto_detect_language,
            self.config.primary_language,
        )

    def _build_diarizer(self) -> "SpeakerDiarizer | None":
        """Build a local diarizer when enabled, or None when disabled or nothing can run.

        Resolves the backend from hardware, installed extras, credentials, and the
        ``diarization_backend`` setting, falling back through the preference order,
        so diarization degrades to unlabeled output rather than failing.
        """
        if not getattr(self.config, "enable_speaker_diarization", False):
            return None

        if self._cached_diarizer is not None:
            return self._cached_diarizer

        from scribe.core.backends import detect_hardware
        from scribe.core.diarization.registry import resolve_diarizer

        device = "cuda" if self.gpu_config.has_gpu else "cpu"
        diarizer = resolve_diarizer(detect_hardware(), config=self.config, device=device)
        self._cached_diarizer = diarizer
        return diarizer

    def _transcribe_faster_whisper(
        self,
        audio_path: Path,
        model_size: str,
        language: str | None,
        initial_prompt: str | None,
        diarizer: "SpeakerDiarizer | None" = None,
        *,
        force_cpu: bool = False,
        music_mode: bool = False,
    ) -> Path:
        """Run the production faster-whisper engine (CUDA or CPU int8)."""
        from dataclasses import replace

        gpu_config = (
            replace(self.gpu_config, has_gpu=False, cuda_available=False)
            if force_cpu
            else self.gpu_config
        )
        if (
            not music_mode
            and resolve_verification(
                self.config.transcription_quality, self.config.transcription_verification
            )
            != "off"
        ):
            from scribe.core.review_engine import bounded_pass
            from scribe.core.transcription_review import pass_settings

            acoustic = bounded_pass(
                self._review_source or audio_path,
                pass_settings(
                    self.config,
                    gpu_config,
                    model_size,
                    primary=True,
                    language=language,
                    prompt=initial_prompt or "",
                ),
                self._report_review_phase,
            )
            self._review_primary = acoustic
            # Reuse the existing writer/diarization path after both acoustic passes.
            self.last_transcript = acoustic.transcript
            return self._write_bounded_primary(audio_path, acoustic.transcript, diarizer)
        transcriber = LocalWhisperTranscriber(
            model_size=model_size,
            language=language,
            gpu_config=gpu_config,
            batch_size=resolve_local_batch_size(
                self.config.transcription_quality, self.config.local_batch_size
            ),
            compute_type=self.config.local_compute_type,
        )
        language_detection = None
        if music_mode and language is None:
            language_detection = self._detect_language_for_music(audio_path, transcriber)
            transcriber.language = language_detection[0]
        transcript_path = transcriber.transcribe(
            audio_path,
            detect_silence=self.config.enable_silence_detection,
            initial_prompt=initial_prompt,
            music_mode=music_mode,
            diarizer=diarizer,
        )
        self.last_transcript = transcriber.last_transcript
        if language_detection and language_detection[0] and self.last_transcript is not None:
            self.last_transcript.metadata.update(
                language_mode="automatic (music pre-pass)",
                requested_language=None,
                detected_language=language_detection[0],
                language_probability=language_detection[1],
                language_detection_backend="faster-whisper",
            )
        return transcript_path

    def _write_bounded_primary(
        self, audio_path: Path, transcript: Transcript, diarizer: "SpeakerDiarizer | None"
    ) -> Path:
        from scribe.core.local_whisper import apply_diarizer_safely, write_clean_transcript

        if diarizer is not None:
            transcript = apply_diarizer_safely(
                diarizer, self._review_source or audio_path, transcript
            )
        clean_stem = audio_path.stem
        for suffix in ("_16k_mono", "_standardized", "_converted"):
            clean_stem = clean_stem.replace(suffix, "")
        output_path = audio_path.parent / f"{clean_stem}_transcription.txt"
        write_clean_transcript(transcript, output_path, self._review_source or audio_path, [])
        self.last_transcript = transcript
        return output_path

    def _transcribe_alt_backend(
        self,
        backend: "TranscriptionBackend",
        audio_path: Path,
        model_size: str,
        language: str | None,
        initial_prompt: str | None,
        diarizer: "SpeakerDiarizer | None" = None,
    ) -> Path:
        """Run a non-CUDA backend (mlx-whisper, whisper.cpp) and write the .txt."""
        from scribe.core.local_whisper import apply_diarizer_safely, write_clean_transcript
        from scribe.utils.audio import detect_silence_periods, get_audio_duration

        try:
            transcript = backend.transcribe(
                audio_path,
                language=language,
                model_size=model_size,
                beam_size=self.gpu_config.beam_size,
                initial_prompt=initial_prompt,
            )
        finally:
            # Best-effort CUDA cache release for the override case (an alt backend
            # forced on an NVIDIA box). Metal/Vulkan memory is the engine's own.
            if self.gpu_config.has_gpu:
                from scribe.utils.gpu import clear_gpu_cache

                clear_gpu_cache()

        if not transcript.segments:
            raise TranscriptionError(
                "No speech detected in audio (file may be silent or contain only noise)",
                context={"audio_path": str(audio_path), "backend": backend.name},
            )

        # Use the real audio duration, not the last segment's end (VAD trims
        # trailing silence), so the .txt header matches the faster-whisper path.
        duration = get_audio_duration(audio_path)
        if duration:
            transcript.duration = duration

        if diarizer is not None:
            transcript = apply_diarizer_safely(diarizer, audio_path, transcript)

        # Silence markers are engine-independent (they read the audio file), so the
        # alt path emits them too rather than dropping them for Apple/AMD users.
        silence_periods: list[tuple[float, float]] = []
        if self.config.enable_silence_detection and duration and duration > 300:
            try:
                silence_periods = detect_silence_periods(
                    audio_path, silence_threshold=-45.0, min_silence_duration=60.0
                )
            except Exception as e:
                logger.warning(f"Silence detection failed: {e}")

        clean_stem = audio_path.stem
        for suffix in ("_16k_mono", "_standardized", "_converted"):
            clean_stem = clean_stem.replace(suffix, "")
        output_path = audio_path.parent / f"{clean_stem}_transcription.txt"

        write_clean_transcript(transcript, output_path, audio_path, silence_periods)
        self.last_transcript = transcript
        logger.info(f"Transcript saved: {output_path}")
        return output_path

    def _transcribe_openai(
        self,
        audio_path: Path,
        session: TranscriptionSession | None,
        custom_vocabulary: Optional["CustomVocabulary"] = None,
    ) -> Path:
        """Transcribe using OpenAI API."""
        if not self.config.openai_api_key:
            raise ValidationError("OpenAI API key not configured")

        transcriber = OpenAITranscriber(
            api_key=self.config.openai_api_key,
            model=self.config.openai_model,
            language=self._get_effective_file_language(),
        )

        # Convert vocabulary to Whisper prompt format
        initial_prompt = None
        if custom_vocabulary:
            initial_prompt = custom_vocabulary.to_prompt()
            logger.info(f"Using custom vocabulary with {len(custom_vocabulary)} terms")

        transcript_path = transcriber.transcribe(
            audio_path,
            cleanup_temp=not self.config.keep_intermediate_files,
            initial_prompt=initial_prompt,
        )
        self.last_transcript = transcriber.last_transcript

        if session:
            session.transcription_method = "openai"
            session.model_used = self.config.openai_model

        return transcript_path

    def _transcribe_openrouter(
        self,
        audio_path: Path,
        session: TranscriptionSession | None,
        custom_vocabulary: Optional["CustomVocabulary"] = None,
    ) -> Path:
        """Transcribe through OpenRouter only after explicit method selection."""
        if not self.config.openrouter_api_key:
            raise ValidationError("OpenRouter API key not configured")

        if custom_vocabulary:
            logger.info(
                "OpenRouter STT does not have a provider-neutral prompt field; "
                "configured vocabulary aliases will still be normalized locally"
            )

        transcriber = OpenRouterTranscriber(
            api_key=self.config.openrouter_api_key,
            model=self.config.openrouter_model,
            language=self._get_effective_file_language(),
            max_attempts=self.config.max_retries,
            timeout_seconds=self.config.openrouter_timeout_seconds,
            max_spend_usd=self.config.openrouter_max_spend_usd,
        )
        try:
            transcript_path = transcriber.transcribe(
                audio_path,
                cleanup_temp=not self.config.keep_intermediate_files,
            )
        except TranscriptionError:
            self.last_transcript = transcriber.last_transcript
            partial_path = audio_path.parent / (
                f"{OpenRouterTranscriber._clean_stem(audio_path)}_transcription.partial.txt"
            )
            if session and partial_path.exists():
                session.add_file(partial_path, "partial_transcript")
            raise

        self.last_transcript = transcriber.last_transcript
        if session:
            session.transcription_method = "openrouter"
            session.model_used = self.config.openrouter_model
        return transcript_path

    def cleanup_intermediate_files(
        self, directory: Path, keep_patterns: list[str] | None = None
    ) -> list[Path]:
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

        # Patterns to delete - only intermediate conversion files
        delete_patterns = [
            "*_temp.*",
            "*_tmp.*",
            "*_cleaned.*",
            "*_standardized.*",
            "*_chunk_*.mp3",
            "*_chunk_*.wav",
            "*_converted.mp3",  # Delete converted MP3 files
        ]

        # Patterns to keep - original files, processed audio, and outputs
        default_keep_patterns = [
            "*.mp4",  # Keep original video
            "*.mkv",  # Keep original video
            "*.avi",  # Keep original video
            "*.mp3",  # Keep original MP3 files
            "*.flac",  # Keep original FLAC files
            "*.m4a",  # Keep original M4A files
            "*.wav",  # Keep all WAV files (original and processed)
            "*_transcription.txt",  # Keep transcript
            "*_transcription.docx",  # Keep DOCX
            "*_lyrics.txt",  # Keep lyrics files
            "*_notes.md",  # Keep notes
            "*.png",  # Keep memes
        ]

        if keep_patterns:
            default_keep_patterns.extend(keep_patterns)

        # Capture sizes BEFORE deleting - cleanup_files unlinks the files, so a
        # stat() afterwards always sees them gone and would report 0 bytes freed.
        to_delete = cleanup_files(
            directory=directory,
            patterns=delete_patterns,
            keep_patterns=default_keep_patterns,
            dry_run=True,
        )
        total_size_mb = sum(f.stat().st_size for f in to_delete if f.exists()) / (1024 * 1024)

        deleted_files = cleanup_files(
            directory=directory, patterns=delete_patterns, keep_patterns=default_keep_patterns
        )

        if deleted_files:
            logger.info(f"Cleaned up {len(deleted_files)} files ({total_size_mb:.1f}MB freed)")

        return deleted_files
