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
        channels: int = 1
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
        
        # Check if already converted (idempotent)
        if output_file.exists():
            if output_file.stat().st_mtime >= input_file.stat().st_mtime:
                logger.info(f"Already converted: {output_file.name}")
                return output_file
        
        logger.info(f"Converting {input_file.name} to 16kHz mono WAV...")
        
        # Get duration for progress estimation
        duration = get_audio_duration(input_file)
        if duration:
            logger.debug(f"Input duration: {duration:.1f}s ({duration/3600:.2f}h)")
        
        # Build ffmpeg command with dynamic audio normalization
        # Note: Using dynaudnorm (single-pass) instead of loudnorm (two-pass) to avoid hangs
        # dynaudnorm provides excellent normalization without the hanging risk
        command = [
            str(self.ffmpeg_path),
            "-y",  # Overwrite output
            "-i", str(input_file),
            "-vn",  # No video
            "-map", "0:a:0?",  # Select first audio track (tolerate missing)
            "-af", "dynaudnorm=f=150:g=15",  # Dynamic audio normalization (single-pass, no hanging)
            "-ac", str(channels),  # Mono
            "-ar", str(sample_rate),  # 16kHz
            "-c:a", "pcm_s16le",  # 16-bit PCM
            str(output_file)
        ]
        
        # Execute conversion with progress
        start_time = time.time()
        
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Converting to WAV..."),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console,
                transient=False
            ) as progress:
                task = progress.add_task("Converting", total=100)
                
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
                    
                    # Update progress bar periodically
                    if current_time - last_update > 0.5:
                        if duration:
                            # Estimate progress based on time
                            estimated_progress = min(95, (elapsed / (duration / 4)) * 100)
                            progress.update(task, completed=estimated_progress)
                        last_update = current_time
                    
                    time.sleep(0.1)
                
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
                progress.update(task, completed=100)
                
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
        
        # Build ffmpeg command
        command = [
            str(self.ffmpeg_path),
            "-y",
            "-i", str(input_file),
            "-vn",
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
