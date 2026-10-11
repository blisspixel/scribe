"""Local CPU and NVIDIA transcription through faster-whisper."""

import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from scribe.core.diarizer import SpeakerDiarizer

from scribe.exceptions import TranscriptionError
from scribe.models.gpu import GPUConfig
from scribe.models.transcript import Transcript, TranscriptSegment, TranscriptWord
from scribe.utils.audio import detect_silence_periods, format_timestamp, get_audio_duration
from scribe.utils.files import extract_date_from_filename, format_date, format_duration_minutes
from scribe.utils.gpu import clear_gpu_cache, set_gpu_optimizations
from scribe.utils.gpu_manager import get_gpu_manager
from scribe.utils.logging import get_logger
from scribe.utils.model_selection import local_resource_guidance

logger = get_logger(__name__)


#: Approximate VRAM (GB) a float16 Whisper model needs to run without spilling.
_MODEL_VRAM_GB = {"tiny": 1.5, "base": 1.5, "small": 2.5, "medium": 4.0}
_LARGE_MODEL_VRAM_GB = 5.0

# Parameter counts provide a lower bound, not a peak-memory fit prediction.
_MODEL_PARAMETERS_M = {"tiny": 39, "base": 74, "small": 244, "medium": 769, "turbo": 809}


def check_model_memory(
    model_size: str, free_gb: float | None, *, device: str, bytes_per_weight: int
) -> None:
    """Reject known memory below the weights alone; leave unknown/peak use honest."""
    parameters = _MODEL_PARAMETERS_M.get(model_size, 1550)
    if model_size == "large-v3-turbo":
        parameters = 809
    weights_gb = parameters * 1_000_000 * bytes_per_weight / (1024**3)
    if free_gb is not None and free_gb < weights_gb:
        raise TranscriptionError(
            f"Whisper {model_size} cannot fit its weights in the known free {device} memory "
            f"({free_gb:.1f} GB free; at least {weights_gb:.1f} GB for weights alone). "
            "Free memory or explicitly choose --quality balanced, --quality fast, or --model. "
            "No smaller model or cloud service was selected.",
            context={"model": model_size, "device": device, "free_gb": free_gb},
        )


def _vram_key(model_size: str) -> str:
    size = model_size.lower()
    if size.startswith(("large", "distil", "turbo")):
        return "large"
    return size.split(".")[0]


def warn_if_gpu_memory_contended(model_size: str, free: float | None = None) -> float | None:
    """Warn when other processes leave too little free VRAM for the Whisper model.

    Returns the free VRAM in GB (queried when not supplied), or None if unknown.
    """
    if free is None:
        free = GPUConfig.query_free_memory_gb()
    needed = _MODEL_VRAM_GB.get(_vram_key(model_size), _LARGE_MODEL_VRAM_GB)
    if free is None or free >= needed:
        return free
    logger.warning(
        f"Only {free:.1f} GB of GPU memory is free; Whisper {model_size} needs about "
        f"{needed:.0f} GB. Another app (for example a local LLM loaded in Ollama) is using "
        "the GPU, so transcription may run far slower than usual. Free GPU memory "
        "(for example `ollama stop <model>`) or choose a smaller --model."
    )
    return free


#: Measured float16 VRAM for batched decoding at beam 5, as (fixed GB, GB per batch
#: item), including model weights. large-v3 measured 6.7 GB at batch 8 and 9.1 GB at
#: batch 16 on an RTX 4090; medium measured 3.8 GB and 5.3 GB.
_BATCHED_VRAM_GB = {
    "large": (4.4, 0.3),
    "medium": (2.2, 0.2),
    "small": (1.2, 0.1),
    "base": (0.8, 0.05),
    "tiny": (0.6, 0.05),
}
#: Below this batch size the batched pipeline is not worth its VAD chunking.
_MIN_BATCH_SIZE = 4
#: Free VRAM to leave untouched for the diarizer, the desktop, and allocator slack.
_VRAM_MARGIN_GB = 1.0


def choose_batch_size(
    model_size: str, requested: int, free_gb: float | None, *, memory_scale: float = 1.0
) -> int:
    """Largest batch size up to ``requested`` that fits in free VRAM; 0 means sequential.

    With unknown free memory the requested (tier-based) size is trusted. Too little
    room for a useful batch falls back to sequential decoding, which needs the least
    memory.
    """
    if requested < _MIN_BATCH_SIZE:
        return 0
    if free_gb is None:
        return requested
    fixed, per_item = _BATCHED_VRAM_GB.get(_vram_key(model_size), _BATCHED_VRAM_GB["large"])
    fixed *= memory_scale
    per_item *= memory_scale
    fits = int((free_gb - _VRAM_MARGIN_GB - fixed) / per_item)
    batch = min(requested, fits)
    return batch if batch >= _MIN_BATCH_SIZE else 0


#: Temperature fallback for sequential decoding (Whisper's standard schedule).
_FALLBACK_TEMPERATURES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)

#: Batched decoding returns whole VAD chunks (often 25 to 35 seconds). These bounds
#: split them back into readable, subtitle-sized segments using word timings.
_SPLIT_MAX_SECONDS = 12.0
_SPLIT_MAX_WORDS = 40
_SPLIT_MIN_WORDS = 4
_SENTENCE_END = (".", "?", "!")


def split_long_segment(segment: TranscriptSegment) -> list[TranscriptSegment]:
    """Split a long segment at sentence ends, falling back to the longest pause.

    Needs word timestamps; a segment without words, or already within bounds, is
    returned unchanged. Text is rebuilt by concatenating word tokens, which carry
    their own leading whitespace, so no words are added or lost.
    """
    words = segment.words
    if not words or (
        segment.end - segment.start <= _SPLIT_MAX_SECONDS and len(words) <= _SPLIT_MAX_WORDS
    ):
        return [segment]

    pieces: list[list[TranscriptWord]] = []
    current: list[TranscriptWord] = []
    for word in words:
        current.append(word)
        span = current[-1].end - current[0].start
        sentence_end = word.text.strip().endswith(_SENTENCE_END)
        if sentence_end and len(current) >= _SPLIT_MIN_WORDS:
            pieces.append(current)
            current = []
        elif span > _SPLIT_MAX_SECONDS or len(current) >= _SPLIT_MAX_WORDS:
            # No sentence end in range: cut at the longest pause inside the run.
            gaps = [
                (current[i + 1].start - current[i].end, i)
                for i in range(_SPLIT_MIN_WORDS - 1, len(current) - 1)
            ]
            cut = max(gaps)[1] + 1 if gaps else len(current)
            pieces.append(current[:cut])
            current = current[cut:]
    if current:
        if pieces and len(current) < _SPLIT_MIN_WORDS:
            pieces[-1].extend(current)
        else:
            pieces.append(current)

    result = []
    for piece in pieces:
        text = "".join(w.text for w in piece)
        if not text.strip():
            continue
        result.append(
            TranscriptSegment(
                start=piece[0].start,
                end=piece[-1].end,
                text=text,
                confidence=segment.confidence,
                words=tuple(piece),
            )
        )
    return result or [segment]


class LocalWhisperTranscriber:
    """
    Local transcription using faster-whisper on CPU or a compatible NVIDIA GPU.

    Features:
    - Automatic device detection and VRAM-aware settings
    - Continuous progress updates
    - Silence detection and marking
    - Clean transcript output (no technical metadata)
    """

    def __init__(
        self,
        model_size: str = "large-v3",
        language: str | None = None,
        gpu_config: GPUConfig | None = None,
        batch_size: int | None = None,
        compute_type: str | None = None,
    ) -> None:
        """
        Initialize local whisper transcriber.

        Args:
            model_size: Whisper model size
            language: ISO language code (None for auto-detection)
            gpu_config: Optional GPU configuration (auto-detected if None)
            batch_size: GPU batched-decoding size; None picks one from the GPU tier
                and free VRAM, 0 forces sequential decoding
        """
        self.model_size = model_size
        self.language = language

        # Detect GPU if not provided
        if gpu_config is None:
            gpu_config = GPUConfig.detect()

        self.gpu_config = gpu_config

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

        self.requested_batch_size = batch_size
        self.requested_compute_type = compute_type
        # Resolved when the model loads: 0 means sequential decoding.
        self.batch_size = 0
        self.device = "cuda" if gpu_config.has_gpu else "cpu"
        self.compute_type = compute_type or (
            ("float16" if gpu_config.use_fp16 else "float32") if gpu_config.has_gpu else "int8"
        )
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

            device = "cuda" if self.gpu_config.has_gpu else "cpu"
            compute_type = self.requested_compute_type or (
                ("float16" if self.gpu_config.use_fp16 else "float32")
                if self.gpu_config.has_gpu
                else "int8"
            )
            if self.requested_compute_type is not None:
                import ctranslate2  # type: ignore[import-untyped]

                supported = ctranslate2.get_supported_compute_types(device, device_index=0)
                if compute_type not in supported:
                    raise TranscriptionError(
                        f"Requested compute type {compute_type} is unsupported on {device}; "
                        f"supported: {', '.join(sorted(supported))}. No precision fallback was selected."
                    )
            bytes_per_weight = (
                1 if compute_type.startswith("int8") else 2 if compute_type == "float16" else 4
            )

            if self.gpu_config.has_gpu:
                num_workers = 8
                free = warn_if_gpu_memory_contended(self.model_size)
                check_model_memory(
                    self.model_size,
                    free,
                    device="GPU",
                    bytes_per_weight=bytes_per_weight,
                )
                requested = (
                    self.gpu_config.batch_size
                    if self.requested_batch_size is None
                    else self.requested_batch_size
                )
                self.batch_size = choose_batch_size(
                    self.model_size,
                    requested,
                    free,
                    memory_scale=2.0 if compute_type == "float32" else 1.0,
                )
            else:
                num_workers = 4
                import psutil  # type: ignore[import-untyped]

                free_ram = psutil.virtual_memory().available / (1024**3)
                check_model_memory(
                    self.model_size, free_ram, device="CPU", bytes_per_weight=bytes_per_weight
                )

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
            self.device = device
            actual_compute_type = getattr(getattr(self.model, "model", None), "compute_type", None)
            self.compute_type = (
                actual_compute_type if isinstance(actual_compute_type, str) else compute_type
            )

            # Register model with GPU manager
            gpu_manager._current_model = model_id
            gpu_manager._current_model_obj = self.model

            logger.info("Model loaded successfully")

        except ImportError as e:
            raise TranscriptionError(
                "faster-whisper not installed. Reinstall Scribe from its source.",
                context={"error": str(e)},
            )
        except (RuntimeError, MemoryError, ValueError, OSError) as e:
            raise TranscriptionError(
                f"Failed to load Whisper {self.model_size}: {e}. "
                "Free memory or explicitly choose a faster quality profile, smaller --model, "
                "or SCRIBE_LOCAL_BACKEND=cpu. The selected model was not downgraded.",
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
        # English boilerplate can steer automatically detected non-English speech.
        # Forward only the vocabulary/context that the caller deliberately supplied.
        return initial_prompt or ""

    def _estimate_transcription_time(self, duration: float | None) -> tuple[float, float]:
        """Estimate transcription time from the detected accelerator tier."""
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

    def _decode(
        self,
        model: Any,
        audio_path: Path,
        initial_prompt: str,
        word_timestamps: bool,
        batch_size: int,
    ) -> tuple[list[TranscriptSegment], Any]:
        """Decode the file, batched when ``batch_size`` > 0, and materialize segments.

        Both paths use VAD, beam search at the tier's beam width, and greedy
        temperature. The batched pipeline decodes VAD chunks in parallel on the GPU;
        quality differs from conditioned sequential decoding; compare on your audio.
        """
        if batch_size > 0:
            from faster_whisper import BatchedInferencePipeline

            logger.info(f"Batched GPU decoding (batch size {batch_size})")
            segments_iter, info = BatchedInferencePipeline(model=model).transcribe(
                str(audio_path),
                language=self.language,
                beam_size=self.gpu_config.beam_size,
                temperature=0.0,
                initial_prompt=initial_prompt,
                word_timestamps=True,
                vad_filter=True,
                batch_size=batch_size,
            )
        else:
            # Whisper's standard decoding: each window is conditioned on the previous
            # text, which keeps punctuation and casing consistent (without it, windows
            # after the first lose the prompt and often come back lowercase and
            # unpunctuated). Temperature fallback with compression-ratio and
            # log-probability checks breaks the repetition loops that conditioning
            # can otherwise cause, and resets the context when it does.
            segments_iter, info = model.transcribe(
                str(audio_path),
                language=self.language,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 400},
                beam_size=self.gpu_config.beam_size,
                best_of=self.gpu_config.beam_size,
                temperature=_FALLBACK_TEMPERATURES,
                compression_ratio_threshold=2.4,
                log_prob_threshold=-1.0,
                no_speech_threshold=0.6,
                condition_on_previous_text=True,
                prompt_reset_on_temperature=0.5,
                initial_prompt=initial_prompt,
                word_timestamps=word_timestamps,
            )

        segments: list[TranscriptSegment] = []
        for segment in segments_iter:
            words_tuple = None
            if getattr(segment, "words", None):
                words_tuple = tuple(
                    TranscriptWord(
                        start=float(w.start),
                        end=float(w.end),
                        text=w.word,
                        confidence=float(w.probability)
                        if getattr(w, "probability", None) is not None
                        else None,
                    )
                    for w in segment.words
                    if w.start is not None and w.end is not None and w.end >= w.start
                )
            segments.append(
                TranscriptSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text,
                    words=words_tuple,
                )
            )
        if batch_size > 0:
            segments = [piece for seg in segments for piece in split_long_segment(seg)]
            if not word_timestamps:
                segments = [replace(seg, words=None) for seg in segments]
        return segments, info

    def _execute_transcription(
        self,
        audio_path: Path,
        duration: float | None,
        initial_prompt: str,
        *,
        word_timestamps: bool = False,
    ) -> Transcript:
        """Execute the actual transcription and return a structured Transcript."""
        if duration:
            duration_mins = int(duration / 60)
            logger.info(f"Transcribing {duration_mins} min audio with Whisper {self.model_size}...")

        model = self.model
        if model is None:
            raise TranscriptionError("Whisper model failed to load")

        actual_batch_size = self.batch_size
        if self.batch_size > 0:
            try:
                segments, info = self._decode(
                    model, audio_path, initial_prompt, word_timestamps, self.batch_size
                )
            except (RuntimeError, MemoryError) as e:
                # Typically CUDA out of memory because another process grew; the
                # sequential path needs the least memory, so retry the file with it.
                logger.warning(f"Batched GPU transcription failed ({e}); retrying sequentially")
                clear_gpu_cache()
                actual_batch_size = 0
                segments, info = self._decode(model, audio_path, initial_prompt, word_timestamps, 0)
        else:
            segments, info = self._decode(model, audio_path, initial_prompt, word_timestamps, 0)

        return Transcript(
            segments=segments,
            language=getattr(info, "language", self.language),
            duration=duration,
            backend="faster-whisper",
            model=self.model_size,
            metadata={
                "device": self.device,
                "compute_type": self.compute_type,
                "beam_size": self.gpu_config.beam_size,
                "batch_size": actual_batch_size,
                "decoding": "batched" if actual_batch_size else "conditioned sequential",
                "initial_prompt_applied": bool(initial_prompt),
                "language_mode": "automatic" if self.language is None else "forced",
                "requested_language": self.language,
                "detected_language": getattr(info, "language", None)
                if self.language is None
                else None,
                "language_probability": getattr(info, "language_probability", None)
                if self.language is None
                else None,
            },
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
        Transcribe an audio file with the selected local device.

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
        if self.device == "cpu":
            logger.info(
                f"CPU {self.compute_type}: a long recording may take longer than its duration. "
                f"{local_resource_guidance(self.model_size)}"
            )
        prompt = self._prepare_initial_prompt(initial_prompt, music_mode)

        # Execute transcription
        logger.info("Starting local transcription...")
        start_time = time.time()

        try:
            transcript = self._execute_transcription(
                audio_path,
                duration,
                prompt,
                word_timestamps=(diarizer is not None),
            )
            if diarizer is not None:
                # Label speakers before writing so the .txt and the structured
                # outputs both carry them, and silence markers stay intact.
                transcript = apply_diarizer_safely(diarizer, audio_path, transcript)
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
        except (RuntimeError, MemoryError, ValueError, OSError) as e:
            raise TranscriptionError(
                f"Transcription with Whisper {self.model_size} failed: {e}. "
                "Free memory or explicitly choose another local backend, quality profile or model. "
                "No smaller model or cloud service was selected.",
                context={"audio_path": str(audio_path), "model": self.model_size, "error": str(e)},
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

        transcript.metadata["silence_periods"] = [[a, b] for a, b in silence_periods]
        if transcript.speakers:
            f.write("\n")
            f.write(speaker_header(transcript))

        f.write("\n")
        f.write("─" * 80 + "\n")
        f.write("\n")

        # Speaker-labeled transcripts group each speaker's consecutive segments into
        # paragraphs; unlabeled transcripts keep one paragraph per segment as before.
        paragraph: list[str] = []
        paragraph_speaker: str | None = None
        paragraph_words = 0

        def flush_paragraph() -> None:
            nonlocal paragraph, paragraph_words
            if paragraph:
                name = speaker_display_name(transcript, paragraph_speaker)
                f.write(f"{name}: " + " ".join(paragraph) + "\n\n")
            paragraph = []
            paragraph_words = 0

        last_end = 0.0
        for segment in transcript.segments:
            marker = _silence_marker(silence_periods, last_end, segment.start)
            if marker:
                flush_paragraph()
                f.write(marker)

            text = segment.text.strip()
            if text:
                if segment.speaker:
                    new_speaker = segment.speaker != paragraph_speaker
                    too_long = paragraph_words >= _PARAGRAPH_WORDS and paragraph[-1].endswith(
                        (".", "?", "!")
                    )
                    if new_speaker or too_long:
                        flush_paragraph()
                    paragraph_speaker = segment.speaker
                    paragraph.append(text)
                    paragraph_words += len(text.split())
                else:
                    flush_paragraph()
                    paragraph_speaker = None
                    f.write(f"{text}\n\n")

            last_end = segment.end

        flush_paragraph()


#: Start a new paragraph for the same speaker after about this many words.
_PARAGRAPH_WORDS = 150


def _silence_marker(
    silence_periods: list[tuple[float, float]], last_end: float, next_start: float
) -> str | None:
    """The "[NO AUDIO FOR ...]" marker for a 2+ minute silence before a segment."""
    for silence_start, silence_end in silence_periods or ():
        if last_end < silence_start < next_start:
            silence_duration = silence_end - silence_start
            if silence_duration <= 120:
                return None
            span = f"{format_timestamp(silence_start)} to {format_timestamp(silence_end)}"
            silence_mins = silence_duration / 60
            if silence_mins > 60:
                return f"[NO AUDIO FOR {silence_mins / 60:.1f} HOURS - {span}]\n\n"
            return f"[NO AUDIO FOR {silence_mins:.0f} MINUTES - {span}]\n\n"
    return None


def speaker_display_name(transcript: Transcript, label: str | None) -> str:
    """The name to show for a speaker label: an identified name, else the label."""
    return transcript.speaker_name(label) or ""


def speaker_header(transcript: Transcript) -> str:
    """Header block listing speakers, with best-guess names when they were identified."""
    names = transcript.metadata.get("speaker_names") or {}
    lines: list[str] = []
    if names:
        lines.append("Speakers (best guess from the conversation; fix names here and in the text):")
        for label in transcript.speakers:
            entry = names.get(label)
            if isinstance(entry, dict) and entry.get("name"):
                line = f"  {entry['name']} = {label}"
                if entry.get("alternatives"):
                    line += f" (possibly also: {', '.join(entry['alternatives'])})"
                lines.append(line)
            else:
                lines.append(f"  {label} = unidentified")
    else:
        lines.append(f"Speakers: {', '.join(transcript.speakers)}")
    return "\n".join(lines) + "\n"


def rewrite_clean_transcript(transcript: Transcript, output_path: Path, audio_path: Path) -> None:
    """Re-render a transcript's .txt, reusing the silence periods from the first write."""
    periods = [(float(a), float(b)) for a, b in transcript.metadata.get("silence_periods") or []]
    write_clean_transcript(transcript, output_path, audio_path, periods)


def apply_diarizer_safely(
    diarizer: "SpeakerDiarizer", audio_path: Path, transcript: Transcript
) -> Transcript:
    """Apply speaker labels, keeping the unlabeled transcript if labeling fails.

    Diarization is an enhancement: a model, alignment, or memory failure must never
    discard a completed transcription.
    """
    try:
        return diarizer.apply(audio_path, transcript)
    except Exception as e:
        logger.warning(f"Speaker labeling failed, keeping the unlabeled transcript: {e}")
        return transcript


def transcribe_with_local_whisper(
    audio_path: Path,
    model_size: str = "large-v3",
    language: str | None = None,
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
