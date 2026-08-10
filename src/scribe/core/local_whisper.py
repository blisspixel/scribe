"""
Local GPU transcription using faster-whisper.

This module provides high-performance GPU-accelerated transcription
with RTX 4090 optimization, silence detection, and clean output formatting.
"""

import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scribe.core.diarizer import SpeakerDiarizer

from scribe.exceptions import TranscriptionError
from scribe.models.gpu import GPUConfig
from scribe.models.transcript import Transcript, TranscriptSegment
from scribe.utils.audio import detect_silence_periods, format_timestamp, get_audio_duration
from scribe.utils.files import extract_date_from_filename, format_date, format_duration_minutes
from scribe.utils.gpu import clear_gpu_cache, set_gpu_optimizations
from scribe.utils.gpu_manager import get_gpu_manager
from scribe.utils.logging import get_logger

logger = get_logger(__name__)


class LocalWhisperTranscriber:
    """
    Local GPU-accelerated transcription using faster-whisper.

    Features:
    - Automatic GPU detection and optimization
    - RTX 4090 specific settings (beam_size=10, FP16)
    - Continuous progress updates
    - Silence detection and marking
    - Clean transcript output (no technical metadata)
    """

    def __init__(
        self,
        model_size: str = "large-v3",
        language: str | None = "en",
        gpu_config: GPUConfig | None = None,
    ) -> None:
        """
        Initialize local whisper transcriber.

        Args:
            model_size: Whisper model size
            language: ISO language code (None for auto-detection)
            gpu_config: Optional GPU configuration (auto-detected if None)
        """
        self.model_size = model_size
        self.language = language

        # Detect GPU if not provided
        if gpu_config is None:
            gpu_config = GPUConfig.detect()

        self.gpu_config = gpu_config

        # Validate GPU availability
        if not gpu_config.has_gpu:
            logger.warning("No GPU detected, will use CPU (significantly slower)")

        # Set GPU optimizations
        if gpu_config.has_gpu and gpu_config.enable_tensor_cores:
            set_gpu_optimizations(enable_tensor_cores=True)

        # Log configuration
        logger.info("Initializing local transcription:")
        logger.info(f"  Model: {model_size}")
        logger.info(f"  Language: {language if language else 'auto-detect'}")
        if gpu_config.has_gpu:
            logger.info(f"  GPU: {gpu_config.gpu_name}")
            logger.info(f"  VRAM: {gpu_config.gpu_memory_gb:.1f}GB")
            logger.info(f"  Beam size: {gpu_config.beam_size}")
            logger.info(f"  FP16: {gpu_config.use_fp16}")

        self.model: Any | None = None
        # The structured transcript from the most recent transcribe() call, so callers
        # (and the structured-output writers) can reuse the segments without re-parsing.
        self.last_transcript: Transcript | None = None

    def detect_language(
        self, audio_path: Path, sample_duration: int = 30
    ) -> tuple[str | None, float, bool]:
        """
        Detect the language of audio file with confidence scoring.

        Uses a quick scan of the audio to detect language and determine if speech is present.
        This is more efficient than full transcription for language detection.

        Args:
            audio_path: Path to audio file
            sample_duration: Seconds of audio to sample for detection (default: 30)

        Returns:
            Tuple of (language_code, confidence, has_speech):
                - language_code: ISO 639-1 code if detected, None otherwise
                - confidence: Probability score (0.0-1.0)
                - has_speech: True if speech detected, False if instrumental/silent
        """
        self._load_model()
        model = self.model
        if model is None:
            raise TranscriptionError("Whisper model failed to load")

        try:
            logger.info(f"Detecting language (sampling {sample_duration}s)...")

            # Quick transcription for language detection only
            segments_iter, info = model.transcribe(
                str(audio_path),
                language=None,  # Auto-detect
                beam_size=5,  # Faster for detection
                best_of=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                condition_on_previous_text=False,
                temperature=0.0,
            )

            # Consume segments to check if any speech was detected
            segment_count = 0
            total_text_length = 0
            for segment in segments_iter:
                segment_count += 1
                total_text_length += len(segment.text.strip())
                # Only sample first portion for speed
                if segment.end > sample_duration:
                    break

            # Get detected language from info
            detected_lang = info.language
            detected_prob = info.language_probability

            # Determine if speech is present
            has_speech = segment_count > 0 and total_text_length > 10

            if has_speech:
                logger.info(
                    f"Detected: {detected_lang} (confidence: {detected_prob:.1%}, {segment_count} segments)"
                )
            else:
                logger.info("No speech detected (instrumental or silent)")
                return None, 0.0, False

            # Return language if confidence is reasonable
            # Lower threshold (0.3) because even uncertain detection is better than none
            if detected_prob >= 0.3:
                return detected_lang, detected_prob, True
            else:
                logger.info(
                    f"Low confidence ({detected_prob:.1%}), will use auto-detect during transcription"
                )
                return None, detected_prob, True

        except (RuntimeError, ValueError, OSError) as e:
            logger.warning(f"Language detection failed: {e}")
            # Assume speech present, let transcription handle it
            return None, 0.0, True

    def _load_model(self) -> None:
        """Load faster-whisper model with GPU optimization and resource management."""
        if self.model is not None:
            return

        try:
            import os

            from faster_whisper import WhisperModel

            # Suppress download progress bars
            os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"

            logger.info(f"Loading {self.model_size} model...")

            if self.gpu_config.has_gpu:
                device = "cuda"
                compute_type = "float16" if self.gpu_config.use_fp16 else "float32"
                num_workers = 8
            else:
                device = "cpu"
                compute_type = "int8"
                num_workers = 4

            # Acquire GPU resource lock to prevent concurrent model loading
            gpu_manager = get_gpu_manager()
            model_id = f"faster-whisper-{self.model_size}"

            # Check if we need to unload a different model
            current_model = gpu_manager.get_current_model()
            if current_model and current_model != model_id:
                logger.info(f"Unloading previous model: {current_model}")
                gpu_manager.unload_current_model()

            # Map legacy aliases to the model names recognized by faster-whisper.
            model_name = self.model_size
            if model_name == "large-v3-turbo":
                model_name = "turbo"
                logger.info("Using turbo model (large-v3-turbo alias)")

            self.model = WhisperModel(
                model_name,
                device=device,
                device_index=0,
                compute_type=compute_type,
                num_workers=num_workers,
            )

            # Register model with GPU manager
            gpu_manager._current_model = model_id
            gpu_manager._current_model_obj = self.model

            logger.info("Model loaded successfully")

        except ImportError as e:
            raise TranscriptionError(
                "faster-whisper not installed. Install with: pip install faster-whisper",
                context={"error": str(e)},
            )
        except (RuntimeError, ValueError, OSError) as e:
            raise TranscriptionError(
                f"Failed to load Whisper model: {e}",
                context={"model": self.model_size, "error": str(e)},
            )

    def _generate_output_path(self, audio_path: Path, output_path: Path | None) -> Path:
        """Generate clean output path removing intermediate suffixes."""
        if output_path is not None:
            return output_path

        clean_stem = audio_path.stem
        for suffix in ["_16k_mono", "_standardized", "_converted"]:
            clean_stem = clean_stem.replace(suffix, "")
        return audio_path.parent / f"{clean_stem}_transcription.txt"

    def _validate_and_correct_duration(
        self, audio_path: Path, duration: float | None
    ) -> float | None:
        """Validate duration and correct if WAV header is incorrect."""
        if not duration:
            logger.warning("Could not determine audio duration")
            return None

        duration_mins = duration / 60
        logger.info(f"Audio duration: {duration:.1f}s ({duration_mins:.1f} minutes)")

        # Sanity check - WAV files with wrong headers can report incorrect duration
        if duration > 7200:  # More than 2 hours seems suspicious
            logger.debug(
                f"WAV duration seems incorrect: {duration_mins:.1f} minutes, checking original file"
            )

            # Try to find original file
            for ext in [".mp4", ".mp3"]:
                original_path = audio_path.parent / audio_path.name.replace("_16k_mono.wav", ext)
                if original_path.exists() and original_path != audio_path:
                    original_duration = get_audio_duration(original_path)
                    if original_duration and original_duration < duration:
                        logger.debug(
                            f"Using original file duration: {original_duration:.1f}s instead of {duration:.1f}s"
                        )
                        return original_duration

        return duration

    def _detect_silence_if_needed(
        self, audio_path: Path, duration: float | None, detect_silence: bool
    ) -> list[tuple[float, float]]:
        """Detect silence periods if enabled and audio is long enough."""
        if not detect_silence or not duration or duration <= 300:
            return []

        logger.info("Analyzing audio for silence periods...")
        try:
            silence_periods = detect_silence_periods(
                audio_path, silence_threshold=-45.0, min_silence_duration=60.0
            )
            if silence_periods:
                logger.info(f"Found {len(silence_periods)} silence periods")
                for i, (start, end) in enumerate(silence_periods, 1):
                    duration_mins = (end - start) / 60
                    logger.debug(
                        f"  Silence {i}: {format_timestamp(start)} - "
                        f"{format_timestamp(end)} ({duration_mins:.1f}min)"
                    )
            return silence_periods
        except (RuntimeError, ValueError, OSError) as e:
            logger.warning(f"Silence detection failed: {e}")
            return []

    def _prepare_initial_prompt(self, initial_prompt: str | None, music_mode: bool) -> str:
        """Prepare initial prompt for transcription."""
        if not initial_prompt:
            return "Meeting recording. High-quality transcription with proper punctuation and capitalization."
        elif initial_prompt == "Song lyrics.":
            return initial_prompt  # Music mode - use as-is
        else:
            # Custom vocabulary - combine with meeting context
            return f"Meeting recording. High-quality transcription with proper punctuation and capitalization. Key terms: {initial_prompt}"

    def _estimate_transcription_time(self, duration: float | None) -> tuple[float, float]:
        """Estimate transcription time based on GPU."""
        gpu_name = self.gpu_config.gpu_name or ""
        if "4090" in gpu_name:
            expected_speed = 11.5
        elif "4080" in gpu_name:
            expected_speed = 8.0
        elif "4070" in gpu_name:
            expected_speed = 6.0
        else:
            expected_speed = 4.0

        estimated_time = (duration / expected_speed) if duration else 60
        return expected_speed, estimated_time

    def _execute_transcription(
        self, audio_path: Path, duration: float | None, initial_prompt: str
    ) -> Transcript:
        """Execute the actual transcription and return a structured Transcript."""
        if duration:
            duration_mins = int(duration / 60)
            logger.info(f"Transcribing {duration_mins} min audio with Whisper {self.model_size}...")

        model = self.model
        if model is None:
            raise TranscriptionError("Whisper model failed to load")

        segments_iter, info = model.transcribe(
            str(audio_path),
            language=self.language,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400},
            beam_size=self.gpu_config.beam_size,
            best_of=self.gpu_config.beam_size,
            temperature=0.0,
            condition_on_previous_text=False,
            initial_prompt=initial_prompt,
        )

        segments = [
            TranscriptSegment(start=segment.start, end=segment.end, text=segment.text)
            for segment in segments_iter
        ]
        return Transcript(
            segments=segments,
            language=getattr(info, "language", self.language),
            duration=duration,
            backend="faster-whisper",
            model=self.model_size,
        )

    def transcribe(
        self,
        audio_path: Path,
        output_path: Path | None = None,
        detect_silence: bool = True,
        initial_prompt: str | None = None,
        music_mode: bool = False,
        diarizer: "SpeakerDiarizer | None" = None,
    ) -> Path:
        """
        Transcribe audio file with GPU acceleration.

        Args:
            audio_path: Path to audio file
            output_path: Optional output path
            detect_silence: Whether to detect silence periods
            initial_prompt: Optional prompt to guide transcription
            music_mode: If True, optimized for music/lyrics

        Returns:
            Path to transcript file

        Raises:
            TranscriptionError: If transcription fails
        """
        logger.info(f"Starting local transcription: {audio_path.name}")

        # Prepare paths and validate duration
        output_path = self._generate_output_path(audio_path, output_path)
        duration = get_audio_duration(audio_path)
        duration = self._validate_and_correct_duration(audio_path, duration)

        # Detect silence periods if needed
        silence_periods = self._detect_silence_if_needed(audio_path, duration, detect_silence)

        # Load model and prepare prompt
        self._load_model()
        prompt = self._prepare_initial_prompt(initial_prompt, music_mode)

        # Execute transcription
        logger.info("Starting GPU-accelerated transcription...")
        start_time = time.time()

        try:
            transcript = self._execute_transcription(audio_path, duration, prompt)
            if diarizer is not None:
                # Label speakers before writing so the .txt and the structured
                # outputs both carry them, and silence markers stay intact.
                transcript = diarizer.apply(audio_path, transcript)
            self.last_transcript = transcript
            elapsed = time.time() - start_time

            if not transcript.segments:
                if duration and duration < 1.0:
                    raise TranscriptionError(
                        "Audio file is too short (less than 1 second)",
                        context={"audio_path": str(audio_path), "duration": duration},
                    )
                else:
                    raise TranscriptionError(
                        "No speech detected in audio (file may be silent or contain only noise)",
                        context={"audio_path": str(audio_path), "duration": duration},
                    )

            # Log performance
            if duration and elapsed > 0:
                speed_ratio = duration / elapsed
                logger.info(
                    f"Transcription completed in {elapsed:.1f}s ({speed_ratio:.1f}x realtime)"
                )

            # Write transcript
            self._write_clean_transcript(
                transcript=transcript,
                output_path=output_path,
                audio_path=audio_path,
                silence_periods=silence_periods,
            )

            logger.info(f"Transcript saved: {output_path}")
            return output_path

        except TranscriptionError:
            raise
        except (RuntimeError, ValueError, OSError) as e:
            raise TranscriptionError(
                f"Transcription failed: {e}",
                context={"audio_path": str(audio_path), "error": str(e)},
            )
        finally:
            if self.gpu_config.has_gpu:
                clear_gpu_cache()

    def _write_clean_transcript(
        self,
        transcript: Transcript,
        output_path: Path,
        audio_path: Path,
        silence_periods: list[tuple[float, float]],
    ) -> None:
        """Write the clean ``.txt`` transcript (delegates to the shared writer)."""
        write_clean_transcript(transcript, output_path, audio_path, silence_periods)


def write_clean_transcript(
    transcript: Transcript,
    output_path: Path,
    audio_path: Path,
    silence_periods: list[tuple[float, float]],
) -> None:
    """
    Write clean transcript with minimal metadata.

    Shared by every local backend (faster-whisper, mlx-whisper, whisper.cpp) so
    the plain-text output is identical regardless of which engine produced the
    Transcript.

    Format:
    - 3-line header: Meeting name, Date, Duration
    - Separator line
    - Clean transcript with timestamps
    - Silence markers for gaps
    - NO technical metadata
    """
    duration = transcript.duration
    with open(output_path, "w", encoding="utf-8") as f:
        # Extract meeting info
        meeting_name = audio_path.stem.replace("_16k_mono", "").replace("_converted", "")
        date_str = extract_date_from_filename(audio_path.name)

        # Write header
        f.write(f"Meeting: {meeting_name}\n")
        if date_str:
            f.write(f"Date: {format_date(date_str)}\n")
        else:
            f.write(f"Date: {datetime.now().strftime('%B %d, %Y')}\n")

        if duration:
            f.write(f"Duration: {format_duration_minutes(duration)}\n")
        else:
            f.write("Duration: Unknown\n")

        f.write("\n")
        f.write("─" * 80 + "\n")
        f.write("\n")
        f.flush()

        # Write transcript with silence markers
        last_end = 0.0

        for segment in transcript.segments:
            # Check for silence gaps
            if silence_periods:
                for silence_start, silence_end in silence_periods:
                    if last_end < silence_start < segment.start:
                        silence_duration = silence_end - silence_start
                        if silence_duration > 120:  # 2+ minutes
                            silence_mins = silence_duration / 60
                            if silence_mins > 60:
                                silence_hours = silence_mins / 60
                                marker = (
                                    f"[NO AUDIO FOR {silence_hours:.1f} HOURS - "
                                    f"{format_timestamp(silence_start)} to {format_timestamp(silence_end)}]\n\n"
                                )
                            else:
                                marker = (
                                    f"[NO AUDIO FOR {silence_mins:.0f} MINUTES - "
                                    f"{format_timestamp(silence_start)} to {format_timestamp(silence_end)}]\n\n"
                                )
                            f.write(marker)
                            f.flush()
                            break

            # Write segment (without timestamp). When a backend or local
            # diarization labeled the speaker, prefix it; otherwise the line is
            # unchanged, so non-diarized output stays byte-for-byte the same.
            text = segment.text.strip()

            if text:
                if segment.speaker:
                    f.write(f"{segment.speaker}: {text}\n\n")
                else:
                    f.write(f"{text}\n\n")
                f.flush()

            last_end = segment.end

        # Final flush
        f.flush()


def transcribe_with_local_whisper(
    audio_path: Path,
    model_size: str = "large-v3",
    language: str | None = "en",
    **kwargs: Any,
) -> Path:
    """
    Convenience function for local GPU transcription.

    Args:
        audio_path: Path to audio file
        model_size: Whisper model size
        language: ISO language code (None for auto-detection)
        **kwargs: Additional arguments for LocalWhisperTranscriber.transcribe()

    Returns:
        Path to transcript file
    """
    transcriber = LocalWhisperTranscriber(model_size=model_size, language=language)
    return transcriber.transcribe(audio_path, **kwargs)
