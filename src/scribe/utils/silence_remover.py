"""
Silence removal utility for cleaning up long recordings.

Useful for recordings left running overnight or with long pauses.
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def remove_silence(
    input_path: Path,
    output_path: Path | None = None,
    silence_threshold: str = "-50dB",
    silence_duration: float = 2.0,
    keep_silence: float = 0.5
) -> Path:
    """
    Remove silence from audio/video file using FFmpeg.

    This uses a simple but effective approach: the silenceremove filter
    which reduces silent sections. While it doesn't physically cut out
    the silence (file duration stays the same), it makes silent sections
    nearly inaudible, which is perfect for transcription since Whisper
    will skip over the silent parts anyway.

    Args:
        input_path: Path to input audio/video file
        output_path: Path for output file (default: input_cleaned.ext)
        silence_threshold: Volume threshold for silence (default: -50dB)
        silence_duration: Minimum duration of silence to remove in seconds (default: 2.0)
        keep_silence: Amount of silence to keep at cuts in seconds (default: 0.5)

    Returns:
        Path to cleaned file

    Note:
        The output file will have the same duration as the input, but silent
        sections will be reduced to near-silence. This is ideal for transcription
        as Whisper will process it much faster by skipping the silent parts.

    Example:
        >>> clean_file = remove_silence(Path("long_recording.mp4"))
        >>> print(f"Cleaned file: {clean_file}")
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    # Default output path
    if output_path is None:
        output_path = input_path.parent / f"{input_path.stem}_cleaned{input_path.suffix}"

    logger.info(f"Removing silence from: {input_path.name}")
    logger.info(f"Threshold: {silence_threshold}, Min duration: {silence_duration}s")

    # Use silenceremove filter
    # This reduces silent sections to near-silence, making transcription much faster
    filter_complex = (
        f"silenceremove="
        f"start_periods=1:"
        f"start_threshold={silence_threshold}:"
        f"start_duration={silence_duration}:"
        f"stop_periods=-1:"
        f"stop_threshold={silence_threshold}:"
        f"stop_duration={silence_duration}:"
        f"detection=peak"
    )

    # Build FFmpeg command
    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-af", filter_complex,
        "-c:v", "copy",  # Copy video without re-encoding (fast)
        "-c:a", "aac",   # Re-encode audio to apply filter
        "-b:a", "192k",  # Good audio quality
        "-y",  # Overwrite output file
        str(output_path)
    ]

    try:
        logger.info("Running FFmpeg silence removal...")
        logger.info("Note: This reduces silent sections for faster transcription")
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )

        logger.info(f"Silence removed successfully: {output_path}")
        return output_path

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg failed: {e.stderr}")
        raise RuntimeError(f"Failed to remove silence: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError(
            "FFmpeg not found. Please install FFmpeg:\n"
            "  Windows: choco install ffmpeg\n"
            "  macOS: brew install ffmpeg\n"
            "  Linux: apt-get install ffmpeg"
        )


def analyze_silence(
    input_path: Path,
    silence_threshold: str = "-50dB",
    silence_duration: float = 2.0
) -> dict:
    """
    Analyze how much silence is in a file without removing it.

    Args:
        input_path: Path to audio/video file
        silence_threshold: Volume threshold for silence
        silence_duration: Minimum duration to count as silence

    Returns:
        Dictionary with analysis results
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    logger.info(f"Analyzing silence in: {input_path.name}")

    # Use silencedetect filter to analyze
    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-af", f"silencedetect=noise={silence_threshold}:d={silence_duration}",
        "-f", "null",
        "-"
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False  # Don't raise on non-zero exit (expected for analysis)
        )

        # Parse silence periods from stderr
        stderr = result.stderr
        silence_starts = []
        silence_ends = []

        for line in stderr.split('\n'):
            if 'silence_start' in line:
                try:
                    time = float(line.split('silence_start: ')[1].split()[0])
                    silence_starts.append(time)
                except (IndexError, ValueError):
                    pass
            elif 'silence_end' in line:
                try:
                    time = float(line.split('silence_end: ')[1].split()[0])
                    silence_ends.append(time)
                except (IndexError, ValueError):
                    pass

        # Calculate total silence
        total_silence = 0
        silence_periods = []
        for start, end in zip(silence_starts, silence_ends, strict=False):
            duration = end - start
            total_silence += duration
            silence_periods.append({
                'start': start,
                'end': end,
                'duration': duration
            })

        return {
            'total_silence_seconds': total_silence,
            'total_silence_minutes': total_silence / 60,
            'silence_periods': len(silence_periods),
            'periods': silence_periods
        }

    except FileNotFoundError:
        raise RuntimeError("FFmpeg not found. Please install FFmpeg.")



def trim_file(
    input_path: Path,
    output_path: Path | None = None,
    end_time: str | None = None,
    start_time: str = "00:00:00"
) -> Path:
    """
    Trim audio/video file to a specific time range.

    Args:
        input_path: Path to input audio/video file
        output_path: Path for output file (default: input_trimmed.ext)
        end_time: End time in format HH:MM:SS or seconds (e.g., "01:42:00" or "6120")
        start_time: Start time in format HH:MM:SS (default: "00:00:00")

    Returns:
        Path to trimmed file

    Example:
        >>> # Trim to first 1.7 hours
        >>> trimmed = trim_file(Path("long.mp4"), end_time="01:42:00")
        >>> # Or use seconds
        >>> trimmed = trim_file(Path("long.mp4"), end_time="6120")
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    if not end_time:
        raise ValueError("end_time is required")

    # Default output path
    if output_path is None:
        output_path = input_path.parent / f"{input_path.stem}_trimmed{input_path.suffix}"

    logger.info(f"Trimming file: {input_path.name}")
    logger.info(f"Time range: {start_time} to {end_time}")

    # Build FFmpeg command
    # Using -t for duration or -to for end time
    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-ss", start_time,  # Start time
        "-to", end_time,    # End time
        "-c", "copy",       # Copy without re-encoding (fast!)
        "-y",               # Overwrite output file
        str(output_path)
    ]

    try:
        logger.info("Running FFmpeg trim...")
        subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )

        logger.info(f"File trimmed successfully: {output_path}")
        return output_path

    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg failed: {e.stderr}")
        raise RuntimeError(f"Failed to trim file: {e.stderr}")
    except FileNotFoundError:
        raise RuntimeError("FFmpeg not found. Please install FFmpeg.")
