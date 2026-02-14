"""
Pytest configuration and fixtures for Scribe test suite.

This module provides shared fixtures for testing including
mock objects, sample audio files, and temporary configurations.
"""

import os
import tempfile
from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock, Mock

import pytest

from scribe.models.config import ScribeConfig


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_audio(temp_dir: Path) -> Path:
    """Generate 10-second test audio file."""
    audio_path = temp_dir / "test_audio.wav"

    # Create a simple WAV file
    import wave

    import numpy as np

    sample_rate = 16000
    duration = 10  # seconds
    frequency = 440  # Hz (A4 note)

    # Generate sine wave
    t = np.linspace(0, duration, int(sample_rate * duration))
    audio_data = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)

    # Write WAV file
    with wave.open(str(audio_path), 'w') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data.tobytes())

    return audio_path


@pytest.fixture
def mock_openai(monkeypatch):
    """
    Mock OpenAI API responses with proper types.
    
    Returns a properly typed mock that matches the actual OpenAI API response
    structure, preventing type errors in tests.
    """
    mock_client = MagicMock()

    # Create a proper response object with text attribute
    class MockTranscriptionResponse:
        def __init__(self, text: str):
            self.text = text

    # Default response
    mock_client.audio.transcriptions.create.return_value = MockTranscriptionResponse(
        "This is a test transcription."
    )

    def mock_openai_init(*args, **kwargs):
        return mock_client

    monkeypatch.setattr("scribe.core.openai_api.OpenAI", mock_openai_init)

    return mock_client


@pytest.fixture
def mock_obs(monkeypatch):
    """Mock OBS WebSocket connection."""
    mock_client = MagicMock()
    mock_status = Mock()
    mock_status.output_active = False

    mock_client.get_record_status.return_value = mock_status

    return mock_client


@pytest.fixture
def mock_gpu(monkeypatch):
    """Mock GPU detection."""
    def mock_cuda_available():
        return True

    def mock_get_device_name(idx):
        return "NVIDIA GeForce RTX 4090"

    def mock_get_device_properties(idx):
        props = Mock()
        props.total_memory = 24 * 1024**3  # 24GB
        return props

    monkeypatch.setattr("torch.cuda.is_available", mock_cuda_available)
    monkeypatch.setattr("torch.cuda.get_device_name", mock_get_device_name)
    monkeypatch.setattr("torch.cuda.get_device_properties", mock_get_device_properties)


@pytest.fixture
def temp_config(temp_dir: Path, monkeypatch) -> ScribeConfig:
    """Create temporary configuration."""
    # Set environment variables for testing
    monkeypatch.setenv("SCRIBE_OUTPUT_FOLDER", str(temp_dir / "output"))
    monkeypatch.setenv("SCRIBE_LOG_FOLDER", str(temp_dir / "logs"))
    monkeypatch.setenv("SCRIBE_OPENAI_API_KEY", "sk-test-key")

    return ScribeConfig()


@pytest.fixture
def sample_transcript(temp_dir: Path) -> Path:
    """Create sample transcript file."""
    transcript_path = temp_dir / "test_transcription.txt"

    content = """Meeting: Test Meeting
Date: November 7, 2025
Duration: 10 minutes

────────────────────────────────────────────────────────────────────────────────

[00:00:05] This is a test transcription.

[00:00:10] It contains multiple segments.

[00:00:15] For testing purposes.
"""

    transcript_path.write_text(content, encoding="utf-8")
    return transcript_path


@pytest.fixture
def long_audio(temp_dir: Path) -> Path:
    """
    Generate 30-minute test audio file for chunking tests.
    
    Creates a longer audio file to test chunking logic, large file handling,
    and timeout scenarios.
    """
    audio_path = temp_dir / "long_audio.wav"

    import wave

    import numpy as np

    sample_rate = 16000
    duration = 1800  # 30 minutes in seconds
    frequency = 440  # Hz (A4 note)

    # Generate sine wave (use smaller chunks to avoid memory issues)
    chunk_duration = 60  # Generate 1 minute at a time

    with wave.open(str(audio_path), 'w') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)

        # Write in chunks to avoid memory issues
        for chunk_start in range(0, duration, chunk_duration):
            chunk_end = min(chunk_start + chunk_duration, duration)
            chunk_len = chunk_end - chunk_start

            t = np.linspace(chunk_start, chunk_end, int(sample_rate * chunk_len))
            audio_data = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
            wav_file.writeframes(audio_data.tobytes())

    return audio_path


@pytest.fixture
def test_video(temp_dir: Path) -> Path:
    """
    Generate test video file for conversion tests.
    
    Creates a minimal MP4 file with audio track for testing video-to-audio
    conversion workflows.
    """
    video_path = temp_dir / "test_video.mp4"

    # Create a minimal valid MP4 file with audio
    # This is a simplified approach - in production, use ffmpeg to create proper test files
    import wave

    import numpy as np

    # First create a WAV file
    temp_wav = temp_dir / "temp.wav"
    sample_rate = 16000
    duration = 5  # 5 seconds
    frequency = 440

    t = np.linspace(0, duration, int(sample_rate * duration))
    audio_data = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)

    with wave.open(str(temp_wav), 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data.tobytes())

    # For testing purposes, we'll use the WAV file directly
    # In real tests with ffmpeg available, convert to MP4
    try:
        import subprocess

        from scribe.utils.platform import get_ffmpeg_path

        ffmpeg_path = get_ffmpeg_path()
        if ffmpeg_path:
            # Create a black video with audio
            subprocess.run([
                str(ffmpeg_path),
                '-f', 'lavfi',
                '-i', 'color=c=black:s=320x240:d=5',
                '-i', str(temp_wav),
                '-c:v', 'libx264',
                '-c:a', 'aac',
                '-shortest',
                '-y',
                str(video_path)
            ], check=True, capture_output=True)
        else:
            # Fallback: just copy WAV as "video" for testing
            video_path.write_bytes(temp_wav.read_bytes())
    except Exception:
        # Fallback: just copy WAV as "video" for testing
        video_path.write_bytes(temp_wav.read_bytes())

    return video_path


@pytest.fixture
def mock_no_gpu(monkeypatch):
    """
    Mock GPU as unavailable.
    
    Simulates environment where CUDA is not available, forcing fallback
    to OpenAI API transcription.
    """
    def mock_cuda_not_available():
        return False

    monkeypatch.setattr("torch.cuda.is_available", mock_cuda_not_available)

    # Also mock GPUConfig to return no GPU
    from scribe.models.gpu import GPUConfig

    def mock_detect():
        config = GPUConfig(
            has_gpu=False,
            gpu_name=None,
            gpu_memory_gb=0.0,
            cuda_version=None,
            model_size="medium",
            beam_size=5,
            use_fp16=False,
            enable_tensor_cores=False
        )
        return config

    monkeypatch.setattr("scribe.models.gpu.GPUConfig.detect", mock_detect)


@pytest.fixture(scope="function")
def clean_env(monkeypatch):
    """Clean environment for config tests."""
    # Clear all SCRIBE_ and OPENAI_ env vars
    for key in list(os.environ.keys()):
        if key.startswith("SCRIBE_") or key.startswith("OPENAI_"):
            monkeypatch.delenv(key, raising=False)

    # Prevent .env file loading
    monkeypatch.setenv("SCRIBE_ENV_FILE", "")
    return monkeypatch


# ============================================================================
# Mock Factories - Create properly typed mocks for external dependencies
# ============================================================================

def create_mock_transcription_response(text: str):
    """
    Create a properly typed mock OpenAI transcription response.
    
    Args:
        text: The transcription text to return
        
    Returns:
        Mock object with .text attribute matching OpenAI API response
    """
    class MockTranscriptionResponse:
        def __init__(self, text: str):
            self.text = text

    return MockTranscriptionResponse(text)


def create_mock_audio_file(path: Path, duration_seconds: float = 10.0) -> Path:
    """
    Create a mock audio file with proper WAV structure.
    
    Args:
        path: Path where to create the file
        duration_seconds: Duration of the audio in seconds
        
    Returns:
        Path to the created audio file
    """
    import wave

    import numpy as np

    sample_rate = 16000
    frequency = 440  # Hz (A4 note)

    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds))
    audio_data = (np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)

    with wave.open(str(path), 'w') as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data.tobytes())

    return path


@pytest.fixture
def mock_audio_duration(monkeypatch):
    """
    Mock audio duration detection to return proper float values.
    
    Prevents Mock objects from being returned instead of actual durations.
    """
    def mock_get_duration(audio_path):
        """Return duration based on filename or default."""
        path_str = str(audio_path)

        # Parse duration from filename if present
        if "long" in path_str.lower():
            return 1800.0  # 30 minutes
        elif "short" in path_str.lower():
            return 60.0  # 1 minute
        else:
            return 600.0  # 10 minutes default

    monkeypatch.setattr("scribe.utils.audio.get_audio_duration", mock_get_duration)

    return mock_get_duration


@pytest.fixture
def mock_file_size(monkeypatch):
    """
    Mock file size detection to return proper int values.
    
    Prevents Mock objects from being returned instead of actual file sizes.
    """
    def mock_stat(self):
        """Return mock stat result with proper size."""
        class MockStat:
            st_size = 1024 * 1024 * 10  # 10 MB default
            st_mtime = 1700000000.0
            st_ctime = 1700000000.0

        return MockStat()

    from pathlib import Path
    monkeypatch.setattr(Path, "stat", mock_stat)

    return mock_stat
