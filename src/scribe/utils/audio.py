"""
Audio processing utilities.

This module provides audio file analysis, duration detection,
silence detection, and format validation with multiple fallback methods.
"""

import contextlib
import json
import subprocess
import wave
from pathlib import Path
from typing import Optional, List, Tuple

from scribe.exceptions import AudioFormatError
from scribe.utils.platform import get_ffprobe_path


def get_audio_duration(path: Path) -> Optional[float]:
    """
    Robustly determine audio file duration using multiple fallback methods.
    
    Method priority:
    1. WAV native parsing (fastest, most reliable for WAV files)
    2. Torchaudio metadata extraction (handles multiple formats)
    3. FFprobe subprocess (last resort, requires ffmpeg installation)
    
    Args:
        path: Path to audio file
        
    Returns:
        Duration in seconds, or None if unable to determine
    """
    # Method 1: Native WAV parsing
    duration = _get_duration_wave(path)
    if duration is not None:
        return duration
    
    # Method 2: Torchaudio metadata
    duration = _get_duration_torchaudio(path)
    if duration is not None:
        return duration
    
    # Method 3: FFprobe subprocess
    duration = _get_duration_ffprobe(path)
    return duration


def _get_duration_wave(path: Path) -> Optional[float]:
    """Get duration from WAV file using wave module."""
    if path.suffix.lower() != ".wav":
        return None
    
    try:
        with contextlib.closing(wave.open(str(path), "rb")) as w:
            frames = w.getnframes()
            rate = w.getframerate()
            if rate > 0:
                duration = frames / float(rate)
                # Debug log for troubleshooting
                from scribe.utils.logging import get_logger
                logger = get_logger(__name__)
                logger.debug(f"WAV duration: {duration:.1f}s (frames={frames}, rate={rate})")
                return duration
    except Exception as e:
        from scribe.utils.logging import get_logger
        logger = get_logger(__name__)
        logger.debug(f"Failed to read WAV duration: {e}")
        pass
    
    return None


def _get_duration_torchaudio(path: Path) -> Optional[float]:
    """Get duration using torchaudio metadata."""
    try:
        import torchaudio
        info = torchaudio.info(str(path))
        if hasattr(info, "sample_rate") and hasattr(info, "num_frames"):
            if info.sample_rate > 0 and info.num_frames > 0:
                return float(info.num_frames) / float(info.sample_rate)
    except Exception:
        pass
    
    return None


def _get_duration_ffprobe(path: Path) -> Optional[float]:
    """Get duration using ffprobe subprocess."""
    ffprobe_path = get_ffprobe_path()
    if not ffprobe_path:
        return None
    
    try:
        result = subprocess.run(
            [
                str(ffprobe_path),
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path)
            ],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode != 0:
            return None
        
        info = json.loads(result.stdout)
        
        # Try format duration first
        duration = (info.get("format") or {}).get("duration")
        if duration:
            return float(duration)
        
        # Try stream duration
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "audio" and "duration" in stream:
                return float(stream["duration"])
        
    except Exception:
        pass
    
    return None


def detect_silence_periods(
    audio_path: Path,
    silence_threshold: float = -40.0,
    min_silence_duration: float = 30.0
) -> List[Tuple[float, float]]:
    """
    Analyze audio file to detect significant periods of silence.
    
    This function uses sliding window analysis to identify silence periods
    in audio recordings. Useful for long recordings where silence markers
    can help users navigate to content sections.
    
    Args:
        audio_path: Path to audio file
        silence_threshold: RMS energy threshold in dB below which audio is silence
        min_silence_duration: Minimum duration in seconds for significant silence
        
    Returns:
        List of (start_time, end_time) tuples in seconds
    """
    try:
        import torch
        import torchaudio
        
        waveform, sample_rate = torchaudio.load(str(audio_path))
        
        # Convert to mono if stereo
        if waveform.shape[0] > 1:
            waveform = torch.mean(waveform, dim=0, keepdim=True)
        
        # Calculate RMS energy in sliding windows
        window_size = int(sample_rate * 0.5)  # 0.5 second windows
        hop_size = int(sample_rate * 0.1)     # 0.1 second hops
        
        silence_periods = []
        current_silence_start = None
        
        for i in range(0, waveform.shape[1] - window_size, hop_size):
            window = waveform[0, i:i + window_size]
            
            # Calculate RMS and convert to dB
            rms = torch.sqrt(torch.mean(window ** 2))
            db = 20 * torch.log10(rms + 1e-10)  # Add small value to avoid log(0)
            
            current_time = i / sample_rate
            
            if db < silence_threshold:
                # Start of silence period
                if current_silence_start is None:
                    current_silence_start = current_time
            else:
                # End of silence period
                if current_silence_start is not None:
                    silence_duration = current_time - current_silence_start
                    if silence_duration >= min_silence_duration:
                        silence_periods.append((current_silence_start, current_time))
                    current_silence_start = None
        
        # Handle silence that extends to end of file
        if current_silence_start is not None:
            total_duration = waveform.shape[1] / sample_rate
            silence_duration = total_duration - current_silence_start
            if silence_duration >= min_silence_duration:
                silence_periods.append((current_silence_start, total_duration))
        
        return silence_periods
        
    except Exception:
        return []


def validate_audio_file(path: Path) -> None:
    """
    Validate audio file for common issues.
    
    Args:
        path: Path to audio file
        
    Raises:
        AudioFormatError: If file has issues
    """
    if not path.exists():
        raise AudioFormatError(
            f"Audio file does not exist: {path}",
            context={"path": str(path)}
        )
    
    if not path.is_file():
        raise AudioFormatError(
            f"Path is not a file: {path}",
            context={"path": str(path)}
        )
    
    # Check file size
    file_size = path.stat().st_size
    if file_size == 0:
        raise AudioFormatError(
            f"Audio file is empty: {path}",
            context={"path": str(path)}
        )
    
    # Warn if very large (> 2GB)
    if file_size > 2 * 1024 * 1024 * 1024:
        import logging
        logging.warning(
            f"Large file size ({file_size / (1024**3):.2f} GB). "
            f"Processing may take a while: {path}"
        )
    
    # Check file extension
    valid_extensions = {".wav", ".mp3", ".mp4", ".m4a", ".mkv", ".flac", ".ogg", ".webm"}
    if path.suffix.lower() not in valid_extensions:
        raise AudioFormatError(
            f"Unsupported audio format: {path.suffix}",
            context={
                "path": str(path),
                "extension": path.suffix,
                "supported": ", ".join(sorted(valid_extensions))
            }
        )
    
    # Try to read first few bytes
    try:
        with open(path, "rb") as f:
            header = f.read(1024)
            if len(header) < 100:
                raise AudioFormatError(
                    f"Audio file appears corrupted (too small): {path}",
                    context={"path": str(path), "header_size": len(header)}
                )
    except AudioFormatError:
        raise
    except Exception as e:
        raise AudioFormatError(
            f"Cannot read audio file: {path}",
            context={"path": str(path), "error": str(e)}
        )


def format_timestamp(seconds: float) -> str:
    """
    Format seconds as HH:MM:SS timestamp.
    
    Args:
        seconds: Time in seconds
        
    Returns:
        Formatted timestamp string
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_duration(seconds: float) -> str:
    """
    Format duration in human-readable format.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted duration string (e.g., "1h 23m", "45m", "2h")
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    
    if hours > 0 and minutes > 0:
        return f"{hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h"
    else:
        return f"{minutes}m"


def get_audio_info(path: Path) -> dict:
    """
    Get comprehensive audio file information.
    
    Args:
        path: Path to audio file
        
    Returns:
        Dictionary with audio metadata
    """
    info = {
        "path": str(path),
        "exists": path.exists(),
        "size_mb": 0.0,
        "duration_seconds": None,
        "duration_formatted": None,
        "sample_rate": None,
        "channels": None,
        "format": path.suffix.lower() if path.exists() else None,
    }
    
    if not path.exists():
        return info
    
    # File size
    try:
        info["size_mb"] = path.stat().st_size / (1024 * 1024)
    except Exception:
        pass
    
    # Duration
    duration = get_audio_duration(path)
    if duration:
        info["duration_seconds"] = duration
        info["duration_formatted"] = format_duration(duration)
    
    # Try to get sample rate and channels
    try:
        import torchaudio
        audio_info = torchaudio.info(str(path))
        if hasattr(audio_info, "sample_rate"):
            info["sample_rate"] = audio_info.sample_rate
        if hasattr(audio_info, "num_channels"):
            info["channels"] = audio_info.num_channels
    except Exception:
        pass
    
    return info
