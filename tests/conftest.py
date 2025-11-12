"""
Pytest configuration and fixtures for Scribe test suite.

This module provides shared fixtures for testing including
mock objects, sample audio files, and temporary configurations.
"""

import os
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from unittest.mock import Mock, MagicMock


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
    """Mock OpenAI API responses."""
    mock_client = MagicMock()
    mock_response = Mock()
    mock_response.text = "This is a test transcription."
    
    mock_client.audio.transcriptions.create.return_value = mock_response
    
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
def temp_config(temp_dir: Path, monkeypatch) -> Generator[None, None, None]:
    """Create temporary configuration."""
    # Set environment variables for testing
    monkeypatch.setenv("SCRIBE_OUTPUT_FOLDER", str(temp_dir / "output"))
    monkeypatch.setenv("SCRIBE_LOG_FOLDER", str(temp_dir / "logs"))
    monkeypatch.setenv("SCRIBE_OPENAI_API_KEY", "sk-test-key")
    
    yield


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


@pytest.fixture(scope="function")
def clean_env(monkeypatch):
    """Clean environment for config tests."""
    import os
    # Clear all SCRIBE_ and OPENAI_ env vars
    for key in list(os.environ.keys()):
        if key.startswith("SCRIBE_") or key.startswith("OPENAI_"):
            monkeypatch.delenv(key, raising=False)
    
    # Prevent .env file loading
    monkeypatch.setenv("SCRIBE_ENV_FILE", "")
    return monkeypatch
