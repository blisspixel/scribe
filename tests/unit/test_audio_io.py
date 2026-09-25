"""Tests for the dependency-light audio loader and WAV writer."""

import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from scribe.utils.audio_io import load_audio, save_wav

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg not installed")


def test_wav_round_trip_preserves_shape_rate_and_values(tmp_path: Path) -> None:
    data = np.stack([np.linspace(-0.5, 0.5, 800), np.linspace(0.5, -0.5, 800)]).astype(np.float32)
    path = tmp_path / "stereo.wav"
    save_wav(path, data, 8000)

    loaded, rate = load_audio(path, channels=None)

    assert rate == 8000
    assert loaded.shape == (2, 800)
    assert loaded.dtype == np.float32
    np.testing.assert_allclose(loaded, data, atol=1e-4)


def test_mono_request_downmixes_stereo(tmp_path: Path) -> None:
    left = np.full(100, 0.4, dtype=np.float32)
    right = np.full(100, -0.2, dtype=np.float32)
    path = tmp_path / "stereo.wav"
    save_wav(path, np.stack([left, right]), 16000)

    mono, rate = load_audio(path)

    assert rate == 16000
    assert mono.shape == (1, 100)
    np.testing.assert_allclose(mono[0], 0.1, atol=1e-4)


def test_mono_file_is_duplicated_for_stereo_request(tmp_path: Path) -> None:
    path = tmp_path / "mono.wav"
    save_wav(path, np.full(50, 0.25, dtype=np.float32), 16000)

    stereo, _ = load_audio(path, channels=2)

    assert stereo.shape == (2, 50)


def test_save_wav_clips_and_writes_16_bit(tmp_path: Path) -> None:
    path = tmp_path / "loud.wav"
    save_wav(path, np.array([2.0, -2.0], dtype=np.float32), 16000)

    with wave.open(str(path), "rb") as wf:
        assert wf.getsampwidth() == 2
        frames = np.frombuffer(wf.readframes(2), dtype="<i2")
    assert frames.tolist() == [32767, -32767]


@needs_ffmpeg
def test_resampling_uses_ffmpeg(tmp_path: Path) -> None:
    path = tmp_path / "44k.wav"
    save_wav(path, np.zeros(44100, dtype=np.float32), 44100)

    data, rate = load_audio(path, sample_rate=16000)

    assert rate == 16000
    assert data.shape[0] == 1
    assert abs(data.shape[1] - 16000) <= 32


@needs_ffmpeg
def test_compressed_input_is_decoded_by_ffmpeg(tmp_path: Path) -> None:
    source = tmp_path / "tone.wav"
    save_wav(source, 0.3 * np.sin(np.linspace(0, 880 * np.pi, 16000)).astype(np.float32), 16000)
    flac = tmp_path / "tone.flac"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), str(flac)], check=True)

    data, rate = load_audio(flac, sample_rate=16000)

    assert rate == 16000
    assert abs(data.shape[1] - 16000) <= 32
    assert float(np.abs(data).max()) > 0.2


def test_undecodable_file_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises(RuntimeError):
        load_audio(bad)
