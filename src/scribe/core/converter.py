"""
Audio/video format conversion module.

This module provides conversion to optimal formats for transcription:
- 16kHz mono WAV for local GPU transcription
- Optimized MP3 for OpenAI API transcription
"""

import math
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from scribe.exceptions import AudioFormatError, ProcessError
from scribe.utils.audio import get_audio_duration
from scribe.utils.files import verify_file_content
from scribe.utils.logging import console, get_logger
from scribe.utils.platform import get_ffmpeg_path

logger = get_logger(__name__)


def _is_finite_number(value: Any) -> bool:
    """True if ``value`` parses as a finite float (not -inf/inf/nan)."""
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


class Converter:
    """
    Audio/video format converter with progress tracking.

    This class handles conversion of various audio/video formats to
    optimized formats for transcription using ffmpeg.
    """

    def __init__(self) -> None:
        """Initialize converter and validate ffmpeg availability."""
        self.ffmpeg_path = get_ffmpeg_path()
        if not self.ffmpeg_path:
            import platform

            install = {
                "Windows": "winget install FFmpeg.FFmpeg",
                "Darwin": "brew install ffmpeg",
                "Linux": "sudo apt install ffmpeg",
            }.get(platform.system(), "install ffmpeg from https://ffmpeg.org/download.html")
            raise ProcessError(
                f"ffmpeg not found. Install it with: {install}\n"
                "Then re-run, or run `scribe doctor` to verify.",
                context={"ffmpeg_path": None},
            )

        logger.debug(f"Using ffmpeg: {self.ffmpeg_path}")

    def _analyze_audio_loudness(
        self,
        input_file: Path,
        duration: float | None,
        show_progress: bool,
        progress_callback: Callable[[float], None] | None,
    ) -> dict[str, str]:
        """
        Analyze audio for optimal loudness normalization parameters.

        Returns dict with measured_i, measured_tp, measured_lra, measured_thresh.
        """
        logger.info("Analyzing audio for optimal normalization...")

        analyze_command = [
            str(self.ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "info",
            "-i",
            str(input_file),
            "-vn",
            "-map",
            "0:a:0?",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ]

        if show_progress:
            progress_ctx = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]Analyzing audio for optimal normalization..."),
                TimeElapsedColumn(),
                console=console,
                transient=False,
            )
            progress_ctx.__enter__()
            task = progress_ctx.add_task("Analyzing", total=None)
        else:
            progress_ctx = None

        defaults = {
            "measured_i": "-16",
            "measured_tp": "-1.5",
            "measured_lra": "11",
            "measured_thresh": "-27",
        }

        try:
            if progress_callback:
                progress_callback(0.05)

            result = subprocess.run(
                analyze_command,
                capture_output=True,
                text=True,
                timeout=max(60, duration * 2) if duration else 300,
            )

            if progress_callback:
                progress_callback(0.50)

            # Extract loudnorm measurements from stderr
            import json
            import re

            json_match = re.search(
                r'\{[^}]*"input_i"[^}]*"input_tp"[^}]*"input_lra"[^}]*"input_thresh"[^}]*\}',
                result.stderr,
                re.DOTALL,
            )

            if json_match:
                try:
                    loudnorm_data = json.loads(json_match.group())
                    measured = {
                        "measured_i": loudnorm_data.get("input_i", "-16"),
                        "measured_tp": loudnorm_data.get("input_tp", "-1.5"),
                        "measured_lra": loudnorm_data.get("input_lra", "11"),
                        "measured_thresh": loudnorm_data.get("input_thresh", "-27"),
                    }
                    # Near-silent or empty audio makes ffmpeg report "-inf" for these,
                    # which the second loudnorm pass then rejects. Fall back to the
                    # standard targets so silent intros/instrumentals still convert.
                    if not all(_is_finite_number(v) for v in measured.values()):
                        logger.info(
                            "Loudnorm measurements are not finite (near-silent audio); "
                            "using default normalization"
                        )
                        if show_progress and progress_ctx:
                            progress_ctx.update(task, description="Using default settings")
                        return defaults
                    logger.info(
                        f"Audio analysis complete: I={measured['measured_i']}, TP={measured['measured_tp']}"
                    )
                    if show_progress and progress_ctx:
                        progress_ctx.update(task, description="Analysis complete")
                    return measured
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse loudnorm JSON: {e}")
            else:
                logger.warning("Could not find loudnorm JSON in output")

            if show_progress and progress_ctx:
                progress_ctx.update(task, description="[yellow]Warning: using default settings")
            return defaults

        except Exception as e:
            logger.warning(f"Audio analysis failed, using defaults: {e}")
            if show_progress and progress_ctx:
                progress_ctx.update(
                    task, description="[yellow]Warning: analysis failed, using defaults"
                )
            return defaults
        finally:
            if show_progress and progress_ctx:
                progress_ctx.__exit__(None, None, None)

    def _build_conversion_command(
        self,
        input_file: Path,
        output_file: Path,
        sample_rate: int,
        channels: int,
        loudness_params: dict[str, str],
    ) -> list[str]:
        """Build ffmpeg command for audio conversion with normalization."""
        return [
            str(self.ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-threads",
            "0",
            "-y",
            "-i",
            str(input_file),
            "-vn",
            "-map",
            "0:a:0?",
            "-af",
            (
                f"loudnorm=I=-16:TP=-1.5:LRA=11:"
                f"measured_I={loudness_params['measured_i']}:"
                f"measured_TP={loudness_params['measured_tp']}:"
                f"measured_LRA={loudness_params['measured_lra']}:"
                f"measured_thresh={loudness_params['measured_thresh']}:"
                f"linear=true,acompressor=threshold=-18dB:ratio=4:attack=5:release=50,"
                f"alimiter=limit=0.95"
            ),
            "-ac",
            str(channels),
            "-ar",
            str(sample_rate),
            "-c:a",
            "pcm_s16le",
            str(output_file),
        ]

    def _execute_conversion_with_progress(
        self,
        command: list[str],
        input_file: Path,
        duration: float | None,
        show_progress: bool,
        progress_callback: Callable[[float], None] | None,
    ) -> None:
        """Execute ffmpeg conversion with progress monitoring."""
        start_time = time.time()
        timeout_seconds = max(300, (duration * 2) if duration else 600)
        expected_total_time = max(15, (duration / 25)) if duration else 30

        if show_progress:
            progress_ctx = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=console,
                transient=False,
            )
            progress_ctx.__enter__()
            task: TaskID | None = progress_ctx.add_task(
                "Converting to WAV (with audio normalization)", total=100
            )
        else:
            progress_ctx = None
            task = None

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                stdin=subprocess.DEVNULL,
            )

            last_update = time.time()

            while process.poll() is None:
                current_time = time.time()
                elapsed = current_time - start_time

                if elapsed > timeout_seconds:
                    process.kill()
                    raise ProcessError(
                        f"Conversion timed out after {timeout_seconds}s",
                        context={"timeout": timeout_seconds, "input_file": str(input_file)},
                    )

                if current_time - last_update > 1.0:
                    if duration and duration > 0:
                        conversion_progress = min(1.0, elapsed / expected_total_time)
                        progress_ratio = 0.50 + (conversion_progress * 0.50)
                        overall_progress = progress_ratio * 100

                        if show_progress and progress_ctx is not None and task is not None:
                            progress_ctx.update(task, completed=overall_progress)
                        if progress_callback:
                            progress_callback(progress_ratio)
                    else:
                        if progress_callback:
                            progress_callback(0.75)

                    last_update = current_time

                time.sleep(0.5)

            try:
                _stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                _stdout, stderr = process.communicate()
                raise ProcessError("Process hung during final communication")

            if show_progress and progress_ctx is not None and task is not None:
                progress_ctx.update(task, description="Converted to WAV", completed=100)
                progress_ctx.__exit__(None, None, None)

            if process.returncode != 0:
                raise ProcessError(
                    f"ffmpeg conversion failed with return code {process.returncode}",
                    context={
                        "return_code": process.returncode,
                        "stderr": stderr[-500:] if stderr else None,
                    },
                )

        except ProcessError:
            raise
        except Exception as e:
            raise ProcessError(f"Conversion failed: {e}")

    def convert_to_wav(
        self,
        input_file: Path,
        output_file: Path | None = None,
        sample_rate: int = 16000,
        channels: int = 1,
        show_progress: bool = True,
        progress_callback: Callable[[float], None] | None = None,
    ) -> Path:
        """
        Convert audio/video to optimized WAV for transcription.

        Creates a 16kHz mono PCM WAV file optimized for Whisper models with
        two-pass loudness normalization for maximum quality.

        Args:
            input_file: Path to input file (MP4, MP3, etc.)
            output_file: Optional output path (auto-generated if None)
            sample_rate: Target sample rate (default: 16000 Hz)
            channels: Number of channels (default: 1 for mono)
            show_progress: Show progress indicators
            progress_callback: Optional callback for progress updates

        Returns:
            Path to converted WAV file

        Raises:
            ProcessError: If conversion fails
            AudioFormatError: If input file is invalid
        """
        # Validate input
        if not input_file.exists():
            raise AudioFormatError(
                f"Input file does not exist: {input_file}", context={"path": str(input_file)}
            )

        # Generate output filename if not provided
        if output_file is None:
            output_file = input_file.with_name(f"{input_file.stem}_16k_mono.wav")

        logger.info(f"Converting {input_file.name} to 16kHz mono WAV...")

        # Get duration for progress estimation
        duration = get_audio_duration(input_file)
        if duration:
            logger.debug(f"Input duration: {duration:.1f}s ({duration / 3600:.2f}h)")

        start_time = time.time()

        staged_output: Path | None = None
        try:
            # Pass 1: Analyze audio for optimal normalization
            loudness_params = self._analyze_audio_loudness(
                input_file, duration, show_progress, progress_callback
            )

            # Pass 2: Apply normalization and convert
            if show_progress:
                console.print()
            logger.info("Applying normalization and processing...")

            fd, staged_name = tempfile.mkstemp(
                prefix=f".{output_file.stem}.",
                suffix=output_file.suffix or ".wav",
                dir=output_file.parent,
            )
            staged_output = Path(staged_name)
            try:
                os.close(fd)
            except OSError as close_error:
                try:
                    os.fdopen(fd, "wb").close()
                except OSError as fallback_error:
                    logger.warning(
                        "Could not close staged WAV descriptor %s after close failure: %s",
                        staged_output,
                        fallback_error,
                    )
                raise close_error

            command = self._build_conversion_command(
                input_file, staged_output, sample_rate, channels, loudness_params
            )

            self._execute_conversion_with_progress(
                command, input_file, duration, show_progress, progress_callback
            )

            # Verify output
            if not staged_output.exists():
                raise ProcessError(
                    "Conversion completed but output file not found",
                    context={"output_file": str(staged_output)},
                )

            verify_file_content(staged_output, min_size=1024)
            output_size_mb = staged_output.stat().st_size / (1024 * 1024)
            os.replace(staged_output, output_file)
            staged_output = None

            elapsed = time.time() - start_time
            logger.info(
                f"Conversion complete: {output_file.name} ({output_size_mb:.1f}MB, {elapsed:.1f}s)"
            )

            return output_file

        except ProcessError:
            raise
        except Exception as e:
            raise ProcessError(
                f"Conversion failed: {e}", context={"input": str(input_file), "error": str(e)}
            )
        finally:
            if staged_output is not None:
                try:
                    staged_output.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    logger.warning(
                        "Could not remove staged WAV %s after conversion failure: %s",
                        staged_output,
                        cleanup_error,
                    )

    def _execute_simple_conversion(
        self,
        command: list[str],
        input_file: Path,
        output_file: Path,
        duration: float | None,
        format_name: str,
    ) -> None:
        """Execute simple ffmpeg conversion with spinner progress."""
        start_time = time.time()
        timeout_seconds = max(300, (duration * 2) if duration else 600)

        with Progress(
            SpinnerColumn(),
            TextColumn(f"[bold blue]Converting to {format_name}..."),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("Converting", total=None)

            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                stdin=subprocess.DEVNULL,
            )

            while process.poll() is None:
                elapsed = time.time() - start_time

                if elapsed > timeout_seconds:
                    process.kill()
                    raise ProcessError(
                        f"{format_name} conversion timed out after {timeout_seconds}s",
                        context={"timeout": timeout_seconds, "input_file": str(input_file)},
                    )

                time.sleep(0.1)
                progress.update(task)

            try:
                _stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                _stdout, stderr = process.communicate()
                raise ProcessError(
                    f"{format_name} process hung during final communication",
                    context={"input_file": str(input_file)},
                )

            if process.returncode != 0:
                raise ProcessError(
                    f"{format_name} conversion failed with return code {process.returncode}",
                    context={
                        "return_code": process.returncode,
                        "stderr": stderr[-500:] if stderr else None,
                    },
                )

    def convert_to_mp3(
        self, input_file: Path, output_file: Path | None = None, bitrate: int = 48
    ) -> Path:
        """
        Convert audio to optimized MP3 for OpenAI API.

        Creates a mono 16kHz MP3 at specified bitrate, optimized
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
        if not input_file.exists():
            raise AudioFormatError(
                f"Input file does not exist: {input_file}", context={"path": str(input_file)}
            )

        if output_file is None:
            output_file = input_file.with_suffix(".mp3")
            # If the input is itself an .mp3, the derived name collides with it.
            # Use a distinct name so we never "convert in place" and return the
            # untouched input (which skips loudnorm / 16k / mono / bitrate).
            if output_file == input_file:
                output_file = input_file.with_name(f"{input_file.stem}_converted.mp3")

        # Reuse an existing, distinct output only if it is newer than the input.
        if output_file != input_file and output_file.exists():
            if output_file.stat().st_mtime >= input_file.stat().st_mtime:
                logger.info(f"Already converted: {output_file.name}")
                return output_file

        logger.info(f"Converting {input_file.name} to MP3 ({bitrate}kbps)...")

        command = [
            str(self.ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-threads",
            "0",
            "-y",
            "-i",
            str(input_file),
            "-vn",
            "-af",
            "loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            f"{bitrate}k",
            str(output_file),
        ]

        duration = get_audio_duration(input_file)
        start_time = time.time()

        try:
            self._execute_simple_conversion(command, input_file, output_file, duration, "MP3")

            elapsed = time.time() - start_time
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
                f"MP3 conversion failed: {e}", context={"input": str(input_file), "error": str(e)}
            )


def convert_to_wav(input_file: Path, **kwargs: Any) -> Path:
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


def convert_to_mp3(input_file: Path, **kwargs: Any) -> Path:
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
