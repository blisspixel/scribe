"""
Audio/video format conversion module.

This module provides conversion to optimal formats for transcription:
- 16kHz mono WAV for local GPU transcription
- Optimized MP3 for OpenAI API transcription
"""

import subprocess
import time
from pathlib import Path
from typing import Optional

from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn

from scribe.exceptions import ProcessError, AudioFormatError
from scribe.utils.platform import get_ffmpeg_path
from scribe.utils.files import verify_file_content
from scribe.utils.audio import get_audio_duration
from scribe.utils.logging import console, get_logger

logger = get_logger(__name__)


class Converter:
    """
    Audio/video format converter with progress tracking.
    
    This class handles conversion of various audio/video formats to
    optimized formats for transcription using ffmpeg.
    """
    
    def __init__(self):
        """Initialize converter and validate ffmpeg availability."""
        self.ffmpeg_path = get_ffmpeg_path()
        if not self.ffmpeg_path:
            raise ProcessError(
                "ffmpeg not found. Please install ffmpeg and ensure it's in your PATH.",
                context={"ffmpeg_path": None}
            )
        
        logger.debug(f"Using ffmpeg: {self.ffmpeg_path}")
    
    def convert_to_wav(
        self,
        input_file: Path,
        output_file: Optional[Path] = None,
        sample_rate: int = 16000,
        channels: int = 1,
        show_progress: bool = True,
        progress_callback: Optional[callable] = None
    ) -> Path:
        """
        Convert audio/video to optimized WAV for transcription.
        
        This creates a 16kHz mono PCM WAV file optimized for Whisper models.
        
        Args:
            input_file: Path to input file (MP4, MP3, etc.)
            output_file: Optional output path (auto-generated if None)
            sample_rate: Target sample rate (default: 16000 Hz)
            channels: Number of channels (default: 1 for mono)
            
        Returns:
            Path to converted WAV file
            
        Raises:
            ProcessError: If conversion fails
            AudioFormatError: If input file is invalid
        """
        # Validate input
        if not input_file.exists():
            raise AudioFormatError(
                f"Input file does not exist: {input_file}",
                context={"path": str(input_file)}
            )
        
        # Generate output filename if not provided
        if output_file is None:
            output_file = input_file.with_name(
                f"{input_file.stem}_16k_mono.wav"
            )
        
        # Delete any existing cached file to ensure fresh conversion
        if output_file.exists():
            logger.info(f"Removing cached WAV: {output_file.name}")
            output_file.unlink()
        
        logger.info(f"Converting {input_file.name} to 16kHz mono WAV...")
        
        # Get duration for progress estimation
        duration = get_audio_duration(input_file)
        if duration:
            logger.debug(f"Input duration: {duration:.1f}s ({duration/3600:.2f}h)")
        
        # Two-pass loudnorm for maximum quality
        # Pass 1: Analyze audio to get optimal normalization parameters
        logger.info("Analyzing audio for optimal normalization...")
        
        analyze_command = [
            str(self.ffmpeg_path),
            "-hide_banner",
            "-loglevel", "info",
            "-i", str(input_file),
            "-vn",
            "-map", "0:a:0?",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f", "null",
            "-"
        ]
        
        # Show analysis progress (if enabled)
        if show_progress:
            progress_ctx = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Analyzing audio for optimal normalization..."),
                TimeElapsedColumn(),
                console=console,
                transient=False
            )
            progress_ctx.__enter__()
            task = progress_ctx.add_task("Analyzing", total=None)
        else:
            progress_ctx = None
            task = None
        
        try:
            # Call progress callback at start of analysis
            # Analysis takes ~60s for 60 min audio (half of preparing phase)
            # Show 5% immediately so user knows something is happening
            if progress_callback:
                progress_callback(0.05)
            
            result = subprocess.run(
                analyze_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=max(60, duration * 2) if duration else 300
            )
            
            # Call progress callback after analysis (halfway through preparing = 50% of 18% = 9%)
            if progress_callback:
                progress_callback(0.50)
            
            # Extract loudnorm measurements from stderr
            import json
            import re
            
            # Find JSON block in stderr (multi-line friendly)
            json_match = re.search(
                r'\{[^}]*"input_i"[^}]*"input_tp"[^}]*"input_lra"[^}]*"input_thresh"[^}]*\}',
                result.stderr,
                re.DOTALL
            )
            
            if json_match:
                try:
                    loudnorm_data = json.loads(json_match.group())
                    measured_i = loudnorm_data.get("input_i", "-16")
                    measured_tp = loudnorm_data.get("input_tp", "-1.5")
                    measured_lra = loudnorm_data.get("input_lra", "11")
                    measured_thresh = loudnorm_data.get("input_thresh", "-27")
                    logger.info(f"Audio analysis complete: I={measured_i}, TP={measured_tp}, LRA={measured_lra}")
                    if show_progress and progress_ctx:
                        progress_ctx.update(task, description="Analysis complete")
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse loudnorm JSON: {e}")
                    logger.debug(f"stderr output: {result.stderr[-500:]}")
                    measured_i = "-16"
                    measured_tp = "-1.5"
                    measured_lra = "11"
                    measured_thresh = "-27"
                    if show_progress and progress_ctx:
                        progress_ctx.update(task, description="[yellow]⚠ Using default settings")
            else:
                # Fallback to defaults if analysis fails
                logger.warning("Could not find loudnorm JSON in output")
                logger.debug(f"stderr output: {result.stderr[-500:]}")
                measured_i = "-16"
                measured_tp = "-1.5"
                measured_lra = "11"
                measured_thresh = "-27"
                if show_progress and progress_ctx:
                    progress_ctx.update(task, description="[yellow]⚠ Using default settings")
        except Exception as e:
            logger.warning(f"Audio analysis failed, using single-pass: {e}")
            measured_i = "-16"
            measured_tp = "-1.5"
            measured_lra = "11"
            measured_thresh = "-27"
            if show_progress and progress_ctx:
                progress_ctx.update(task, description="[yellow]⚠ Analysis failed, using defaults")
        
        # Close progress context if it was opened
        if show_progress and progress_ctx:
            progress_ctx.__exit__(None, None, None)
        
        # Pass 2: Apply normalization with measured parameters + compressor + limiter
        logger.info("Applying normalization and processing...")
        if show_progress:
            console.print()
        command = [
            str(self.ffmpeg_path),
            "-hide_banner",
            "-loglevel", "error",
            "-threads", "0",
            "-y",
            "-i", str(input_file),
            "-vn",
            "-map", "0:a:0?",
            "-af", f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={measured_i}:measured_TP={measured_tp}:measured_LRA={measured_lra}:measured_thresh={measured_thresh}:linear=true,acompressor=threshold=-18dB:ratio=4:attack=5:release=50,alimiter=limit=0.95",
            "-ac", str(channels),
            "-ar", str(sample_rate),
            "-c:a", "pcm_s16le",
            str(output_file)
        ]
        
        # Execute conversion with progress
        start_time = time.time()
        
        try:
            if show_progress:
                progress_ctx = Progress(
                    SpinnerColumn(),
                    TextColumn("[bold blue]{task.description}"),
                    BarColumn(),
                    TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                    TimeElapsedColumn(),
                    console=console,
                    transient=False
                )
                progress_ctx.__enter__()
                task = progress_ctx.add_task("Converting to WAV (with audio normalization)", total=100)
            else:
                progress_ctx = None
                task = None
            
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                stdin=subprocess.DEVNULL  # Prevent hanging on input prompts
            )
            
            # Monitor progress with timeout
            last_update = time.time()
            timeout_seconds = max(300, (duration * 2) if duration else 600)  # At least 5 min, or 2x duration
            
            # Two-pass operation: analyze + normalize + convert to WAV
            # Estimate total time: two-pass loudnorm+compressor+limiter processes at ~25x real-time
            # For a 60 min file, expect ~2.4 minutes total processing
            expected_total_time = max(15, (duration / 25)) if duration else 30
            
            while process.poll() is None:
                current_time = time.time()
                elapsed = current_time - start_time
                
                # Check for timeout
                if elapsed > timeout_seconds:
                    process.kill()
                    raise ProcessError(
                        f"Conversion timed out after {timeout_seconds}s",
                        context={
                            "timeout": timeout_seconds,
                            "input_file": str(input_file),
                            "duration": duration
                        }
                    )
                
                # Update progress bar based on elapsed time (throttled to 1 update per second)
                if current_time - last_update > 1.0:
                    # Calculate progress ratio
                    if duration and duration > 0:
                        # Smooth progress from 50-100% based on expected time
                        # (0-50% was used for analysis phase)
                        conversion_progress = min(1.0, elapsed / expected_total_time)
                        progress_ratio = 0.50 + (conversion_progress * 0.50)  # 50% to 100%
                        overall_progress = progress_ratio * 100
                        
                        # Update internal progress display if enabled
                        if show_progress and progress_ctx:
                            progress_ctx.update(task, completed=overall_progress)
                        
                        # Call external progress callback if provided
                        if progress_callback:
                            progress_callback(progress_ratio)
                    else:
                        # No duration info - just show that we're working (75%)
                        if progress_callback:
                            progress_callback(0.75)
                    
                    last_update = current_time
                
                time.sleep(0.5)
            
            # Get final output
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                raise ProcessError(
                    "Process hung during final communication",
                    context={"input_file": str(input_file)}
                )
            
            # Complete progress
            if show_progress and progress_ctx:
                progress_ctx.update(task, description="Converted to WAV", completed=100)
                progress_ctx.__exit__(None, None, None)
            
            if process.returncode != 0:
                raise ProcessError(
                    f"ffmpeg conversion failed with return code {process.returncode}",
                    context={
                        "command": " ".join(command),
                        "return_code": process.returncode,
                        "stderr": stderr[-500:] if stderr else None
                    }
                )
            
            elapsed = time.time() - start_time
            
            # Verify output
            if not output_file.exists():
                raise ProcessError(
                    "Conversion completed but output file not found",
                    context={"output_file": str(output_file)}
                )
            
            verify_file_content(output_file, min_size=1024)
            
            output_size_mb = output_file.stat().st_size / (1024 * 1024)
            logger.info(
                f"Conversion complete: {output_file.name} "
                f"({output_size_mb:.1f}MB, {elapsed:.1f}s)"
            )
            
            return output_file
            
        except ProcessError:
            raise
        except Exception as e:
            raise ProcessError(
                f"Conversion failed: {e}",
                context={"input": str(input_file), "error": str(e)}
            )
    
    def convert_to_mp3(
        self,
        input_file: Path,
        output_file: Optional[Path] = None,
        bitrate: int = 48
    ) -> Path:
        """
        Convert audio to optimized MP3 for OpenAI API.
        
        This creates a mono 16kHz MP3 at specified bitrate, optimized
        for API upload size limits.
        
        Args:
            input_file: Path to input file
            output_file: Optional output path
            bitrate: Target bitrate in kbps (default: 48)
            
        Returns:
            Path to converted MP3 file
            
        Raises:
            ProcessError: If conversion fails
        """
        # Validate input
        if not input_file.exists():
            raise AudioFormatError(
                f"Input file does not exist: {input_file}",
                context={"path": str(input_file)}
            )
        
        # Generate output filename if not provided
        if output_file is None:
            output_file = input_file.with_suffix(".mp3")
        
        # Check if already converted
        if output_file.exists():
            if output_file.stat().st_mtime >= input_file.stat().st_mtime:
                logger.info(f"Already converted: {output_file.name}")
                return output_file
        
        logger.info(f"Converting {input_file.name} to MP3 ({bitrate}kbps)...")
        
        # Build ffmpeg command with loudnorm for consistent volume
        # Apply same normalization as WAV for consistent perceived loudness
        command = [
            str(self.ffmpeg_path),
            "-hide_banner",
            "-loglevel", "error",
            "-threads", "0",
            "-y",
            "-i", str(input_file),
            "-vn",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",  # Single-pass for speed
            "-ac", "1",  # Mono
            "-ar", "16000",  # 16kHz
            "-codec:a", "libmp3lame",
            "-b:a", f"{bitrate}k",
            str(output_file)
        ]
        
        # Get duration for better progress tracking
        duration = get_audio_duration(input_file)
        
        # Execute conversion
        start_time = time.time()
        
        try:
            # Use spinner with live elapsed time
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Converting to MP3..."),
                TimeElapsedColumn(),
                console=console,
                transient=False
            ) as progress:
                task = progress.add_task("Converting", total=None)
                
                process = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    stdin=subprocess.DEVNULL  # Prevent hanging on input prompts
                )
                
                # Poll process with timeout
                timeout_seconds = max(300, (duration * 2) if duration else 600)
                
                while process.poll() is None:
                    elapsed = time.time() - start_time
                    
                    # Check for timeout
                    if elapsed > timeout_seconds:
                        process.kill()
                        raise ProcessError(
                            f"MP3 conversion timed out after {timeout_seconds}s",
                            context={
                                "timeout": timeout_seconds,
                                "input_file": str(input_file)
                            }
                        )
                    
                    time.sleep(0.1)
                    # This keeps the progress display refreshing
                    progress.update(task)
                
                # Get final output
                try:
                    stdout, stderr = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise ProcessError(
                        "MP3 process hung during final communication",
                        context={"input_file": str(input_file)}
                    )
                
                if process.returncode != 0:
                    raise ProcessError(
                        f"MP3 conversion failed with return code {process.returncode}",
                        context={
                            "command": " ".join(command),
                            "return_code": process.returncode,
                            "stderr": stderr[-500:] if stderr else None
                        }
                    )
            
            elapsed = time.time() - start_time
            
            # Verify output
            verify_file_content(output_file, min_size=1024)
            
            output_size_mb = output_file.stat().st_size / (1024 * 1024)
            logger.info(
                f"MP3 conversion complete: {output_file.name} "
                f"({output_size_mb:.1f}MB, {elapsed:.1f}s)"
            )
            
            return output_file
            
        except ProcessError:
            raise
        except Exception as e:
            raise ProcessError(
                f"MP3 conversion failed: {e}",
                context={"input": str(input_file), "error": str(e)}
            )


def convert_to_wav(input_file: Path, **kwargs) -> Path:
    """
    Convenience function for WAV conversion.
    
    Args:
        input_file: Path to input file
        **kwargs: Additional arguments for Converter.convert_to_wav()
        
    Returns:
        Path to converted WAV file
    """
    converter = Converter()
    return converter.convert_to_wav(input_file, **kwargs)


def convert_to_mp3(input_file: Path, **kwargs) -> Path:
    """
    Convenience function for MP3 conversion.
    
    Args:
        input_file: Path to input file
        **kwargs: Additional arguments for Converter.convert_to_mp3()
        
    Returns:
        Path to converted MP3 file
    """
    converter = Converter()
    return converter.convert_to_mp3(input_file, **kwargs)
