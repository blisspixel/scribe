"""
Local GPU transcription using faster-whisper.

This module provides high-performance GPU-accelerated transcription
with RTX 4090 optimization, silence detection, and clean output formatting.
"""

import time
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any
from datetime import datetime

from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn, TimeRemainingColumn

from scribe.exceptions import TranscriptionError, GPUError
from scribe.models.gpu import GPUConfig
from scribe.utils.audio import detect_silence_periods, get_audio_duration, format_timestamp
from scribe.utils.files import extract_date_from_filename, format_date, format_duration_minutes
from scribe.utils.gpu import set_gpu_optimizations, clear_gpu_cache
from scribe.utils.gpu_manager import get_gpu_manager
from scribe.utils.logging import console, get_logger

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
        language: str = "en",
        gpu_config: Optional[GPUConfig] = None
    ):
        """
        Initialize local whisper transcriber.
        
        Args:
            model_size: Whisper model size
            language: ISO language code
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
        logger.info(f"Initializing local transcription:")
        logger.info(f"  Model: {model_size}")
        logger.info(f"  Language: {language}")
        if gpu_config.has_gpu:
            logger.info(f"  GPU: {gpu_config.gpu_name}")
            logger.info(f"  VRAM: {gpu_config.gpu_memory_gb:.1f}GB")
            logger.info(f"  Beam size: {gpu_config.beam_size}")
            logger.info(f"  FP16: {gpu_config.use_fp16}")
        
        self.model = None
    
    def _load_model(self) -> None:
        """Load faster-whisper model with GPU optimization and resource management."""
        if self.model is not None:
            return
        
        try:
            from faster_whisper import WhisperModel
            
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
            
            self.model = WhisperModel(
                self.model_size,
                device=device,
                device_index=0,
                compute_type=compute_type,
                num_workers=num_workers
            )
            
            # Register model with GPU manager
            gpu_manager._current_model = model_id
            gpu_manager._current_model_obj = self.model
            
            logger.info("Model loaded successfully")
            
        except ImportError as e:
            raise TranscriptionError(
                "faster-whisper not installed. Install with: pip install faster-whisper",
                context={"error": str(e)}
            )
        except Exception as e:
            raise TranscriptionError(
                f"Failed to load Whisper model: {e}",
                context={"model": self.model_size, "error": str(e)}
            )
    
    def transcribe(
        self,
        audio_path: Path,
        output_path: Optional[Path] = None,
        detect_silence: bool = True
    ) -> Path:
        """
        Transcribe audio file with GPU acceleration.
        
        Args:
            audio_path: Path to audio file
            output_path: Optional output path
            detect_silence: Whether to detect silence periods
            
        Returns:
            Path to transcript file
            
        Raises:
            TranscriptionError: If transcription fails
        """
        logger.info(f"Starting local transcription: {audio_path.name}")
        
        # Generate output path - use original filename without intermediate suffixes
        if output_path is None:
            # Remove intermediate suffixes like _16k_mono, _standardized, etc.
            clean_stem = audio_path.stem
            for suffix in ['_16k_mono', '_standardized', '_converted']:
                clean_stem = clean_stem.replace(suffix, '')
            output_path = audio_path.parent / f"{clean_stem}_transcription.txt"
        
        # Get audio duration with validation
        duration = get_audio_duration(audio_path)
        if duration:
            duration_mins = duration / 60
            
            # Sanity check - WAV files with wrong headers can report incorrect duration
            # If duration seems impossibly long, silently use the original file's duration
            if duration > 7200:  # More than 2 hours seems suspicious
                logger.debug(f"WAV duration seems incorrect: {duration_mins:.1f} minutes, checking original file")
                
                # Try to find original file (before _16k_mono suffix)
                original_path = audio_path.parent / audio_path.name.replace("_16k_mono.wav", ".mp4")
                if not original_path.exists():
                    original_path = audio_path.parent / audio_path.name.replace("_16k_mono.wav", ".mp3")
                
                if original_path.exists() and original_path != audio_path:
                    original_duration = get_audio_duration(original_path)
                    if original_duration and original_duration < duration:
                        logger.debug(f"Using original file duration: {original_duration:.1f}s instead of {duration:.1f}s")
                        duration = original_duration
                        duration_mins = duration / 60
            
            logger.info(f"Audio duration: {duration:.1f}s ({duration_mins:.1f} minutes)")
        else:
            logger.warning("Could not determine audio duration")
            duration = None
        
        # Detect silence periods
        silence_periods: List[Tuple[float, float]] = []
        if detect_silence and duration and duration > 300:  # > 5 minutes
            logger.info("Analyzing audio for silence periods...")
            try:
                silence_periods = detect_silence_periods(
                    audio_path,
                    silence_threshold=-45.0,
                    min_silence_duration=60.0
                )
                if silence_periods:
                    logger.info(f"Found {len(silence_periods)} silence periods")
                    for i, (start, end) in enumerate(silence_periods, 1):
                        duration_mins = (end - start) / 60
                        logger.debug(
                            f"  Silence {i}: {format_timestamp(start)} - "
                            f"{format_timestamp(end)} ({duration_mins:.1f}min)"
                        )
            except Exception as e:
                logger.warning(f"Silence detection failed: {e}")
        
        # Load model
        self._load_model()
        
        # Transcribe with progress
        logger.info("Starting GPU-accelerated transcription...")
        
        start_time = time.time()
        segments = []
        
        try:
            # Configure transcription parameters
            initial_prompt = "Meeting recording. High-quality transcription with proper punctuation and capitalization."
            
            # Estimate total time based on GPU
            # RTX 4090: ~11-12x, RTX 4080: ~8x, RTX 4070: ~6x, fallback: ~4x
            if "4090" in self.gpu_config.gpu_name:
                expected_speed = 11.5
            elif "4080" in self.gpu_config.gpu_name:
                expected_speed = 8.0
            elif "4070" in self.gpu_config.gpu_name:
                expected_speed = 6.0
            else:
                expected_speed = 4.0
            
            estimated_time = (duration / expected_speed) if duration else 60
            estimated_mins = int(estimated_time / 60)
            estimated_secs = int(estimated_time % 60)
            
            # Show clean, simple estimate
            if duration:
                duration_mins = int(duration / 60)
                console.print(f"[cyan]Transcribing {duration_mins} min recording → estimated {estimated_mins}m {estimated_secs}s[/cyan]")
            
            with Progress(
                SpinnerColumn(),
                BarColumn(bar_width=40),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TextColumn("•"),
                TextColumn("[cyan]{task.fields[status]}"),
                console=console,
                transient=False
            ) as progress:
                
                task = progress.add_task(
                    "",
                    total=estimated_time,
                    status="Loading model..."
                )
                
                # Execute transcription
                segments_iter, info = self.model.transcribe(
                    str(audio_path),
                    language=self.language,
                    vad_filter=True,
                    vad_parameters={"min_silence_duration_ms": 400},
                    beam_size=self.gpu_config.beam_size,
                    best_of=self.gpu_config.beam_size,
                    temperature=0.0,
                    condition_on_previous_text=False,
                    initial_prompt=initial_prompt
                )
                
                # Process segments with progress updates
                last_update = time.time()
                estimate_refined = False
                
                for segment in segments_iter:
                    segments.append({
                        "start": segment.start,
                        "end": segment.end,
                        "text": segment.text
                    })
                    
                    # Update progress based on elapsed time
                    current_time = time.time()
                    if current_time - last_update > 0.5:  # Update every 0.5s
                        elapsed = current_time - start_time
                        if elapsed > 0 and segment.end > 0 and duration:
                            # Calculate actual speed ratio
                            speed_ratio = segment.end / elapsed
                            
                            # Calculate percentage based on audio position
                            percent_audio = (segment.end / duration) * 100
                            
                            # Show "Loading model..." until we're halfway through
                            if percent_audio < 50 and not estimate_refined:
                                # Use initial estimate
                                remaining_estimate = estimated_time - elapsed
                                if remaining_estimate > 0:
                                    eta_mins = int(remaining_estimate / 60)
                                    eta_secs = int(remaining_estimate % 60)
                                    status_str = f"~{eta_mins}m {eta_secs}s remaining"
                                else:
                                    status_str = "finishing..."
                            else:
                                # Refine estimate at halfway point
                                if not estimate_refined and percent_audio >= 50:
                                    refined_total = duration / speed_ratio
                                    progress.update(task, total=refined_total)
                                    estimate_refined = True
                                
                                # Calculate ETA based on remaining audio and current speed
                                if speed_ratio > 0:
                                    remaining_audio = duration - segment.end
                                    eta_seconds = remaining_audio / speed_ratio
                                    
                                    # Format ETA - simple and clear
                                    if eta_seconds < 60:
                                        status_str = f"{int(eta_seconds)}s remaining"
                                    elif eta_seconds < 3600:
                                        eta_mins = int(eta_seconds / 60)
                                        eta_secs = int(eta_seconds % 60)
                                        if eta_secs < 10:
                                            status_str = f"{eta_mins}m remaining"
                                        else:
                                            status_str = f"{eta_mins}m {eta_secs}s remaining"
                                    else:
                                        eta_hours = int(eta_seconds / 3600)
                                        eta_mins = int((eta_seconds % 3600) / 60)
                                        status_str = f"{eta_hours}h {eta_mins}m remaining"
                                else:
                                    status_str = "calculating..."
                            
                            # Update progress based on elapsed time vs estimate
                            progress.update(
                                task,
                                completed=elapsed,
                                status=status_str
                            )
                        
                        last_update = current_time
                
                # Complete progress
                final_elapsed = time.time() - start_time
                progress.update(task, completed=final_elapsed, total=final_elapsed, status="complete")
            
            elapsed = time.time() - start_time
            
            if not segments:
                # Check if audio was too short or silent
                if duration and duration < 1.0:
                    raise TranscriptionError(
                        "Audio file is too short (less than 1 second)",
                        context={"audio_path": str(audio_path), "duration": duration}
                    )
                else:
                    raise TranscriptionError(
                        "No speech detected in audio (file may be silent or contain only noise)",
                        context={"audio_path": str(audio_path), "duration": duration}
                    )
            
            # Calculate speed ratio
            if duration and elapsed > 0:
                speed_ratio = duration / elapsed
                logger.info(f"Transcription completed in {elapsed:.1f}s ({speed_ratio:.1f}x realtime)")
            
            # Write clean transcript
            self._write_clean_transcript(
                segments=segments,
                output_path=output_path,
                audio_path=audio_path,
                duration=duration,
                silence_periods=silence_periods
            )
            
            logger.info(f"Transcript saved: {output_path}")
            return output_path
            
        except TranscriptionError:
            raise
        except Exception as e:
            raise TranscriptionError(
                f"Transcription failed: {e}",
                context={"audio_path": str(audio_path), "error": str(e)}
            )
        finally:
            # Clear GPU cache
            if self.gpu_config.has_gpu:
                clear_gpu_cache()
    
    def _write_clean_transcript(
        self,
        segments: List[Dict[str, Any]],
        output_path: Path,
        audio_path: Path,
        duration: Optional[float],
        silence_periods: List[Tuple[float, float]]
    ) -> None:
        """
        Write clean transcript with minimal metadata.
        
        Format:
        - 3-line header: Meeting name, Date, Duration
        - Separator line
        - Clean transcript with timestamps
        - Silence markers for gaps
        - NO technical metadata
        """
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
                f.write(f"Duration: Unknown\n")
            
            f.write("\n")
            f.write("─" * 80 + "\n")
            f.write("\n")
            f.flush()
            
            # Write transcript with silence markers
            last_end = 0.0
            
            for segment in segments:
                # Check for silence gaps
                if silence_periods:
                    for silence_start, silence_end in silence_periods:
                        if last_end < silence_start < segment["start"]:
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
                
                # Write segment (without timestamp)
                text = segment["text"].strip()
                
                if text:
                    f.write(f"{text}\n\n")
                    f.flush()
                
                last_end = segment["end"]
            
            # Final flush
            f.flush()


def transcribe_with_local_whisper(
    audio_path: Path,
    model_size: str = "large-v3",
    language: str = "en",
    **kwargs
) -> Path:
    """
    Convenience function for local GPU transcription.
    
    Args:
        audio_path: Path to audio file
        model_size: Whisper model size
        language: ISO language code
        **kwargs: Additional arguments for LocalWhisperTranscriber.transcribe()
        
    Returns:
        Path to transcript file
    """
    transcriber = LocalWhisperTranscriber(
        model_size=model_size,
        language=language
    )
    return transcriber.transcribe(audio_path, **kwargs)
