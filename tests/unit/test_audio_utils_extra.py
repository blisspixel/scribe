import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from scribe.exceptions import AudioFormatError
from scribe.utils.audio import (
    detect_silence_periods,
    format_duration,
    format_timestamp,
    get_audio_info,
    validate_audio_file,
)


def test_validate_audio_file_rejects_missing_directory_empty_and_bad_formats(tmp_path):
    with pytest.raises(AudioFormatError, match="does not exist"):
        validate_audio_file(tmp_path / "missing.wav")

    directory = tmp_path / "folder"
    directory.mkdir()
    with pytest.raises(AudioFormatError, match="not a file"):
        validate_audio_file(directory)

    empty_file = tmp_path / "empty.wav"
    empty_file.write_bytes(b"")
    with pytest.raises(AudioFormatError, match="is empty"):
        validate_audio_file(empty_file)

    bad_extension = tmp_path / "audio.aac"
    bad_extension.write_bytes(b"x" * 200)
    with pytest.raises(AudioFormatError, match="Unsupported audio format"):
        validate_audio_file(bad_extension)


def test_validate_audio_file_checks_header_size_and_read_failures(tmp_path):
    tiny_file = tmp_path / "tiny.wav"
    tiny_file.write_bytes(b"x" * 10)

    with pytest.raises(AudioFormatError, match="appears corrupted"):
        validate_audio_file(tiny_file)

    valid_file = tmp_path / "valid.wav"
    valid_file.write_bytes(b"x" * 200)

    with patch("builtins.open", side_effect=OSError("permission denied")):
        with pytest.raises(AudioFormatError, match="Cannot read audio file"):
            validate_audio_file(valid_file)


def test_validate_audio_file_logs_large_files_and_accepts_valid_inputs(tmp_path):
    valid_file = tmp_path / "large.wav"
    valid_file.write_bytes(b"x" * 200)

    class FakeLargeAudioPath:
        suffix = ".wav"

        def exists(self):
            return True

        def is_file(self):
            return True

        def stat(self):
            return SimpleNamespace(st_size=3 * 1024**3)

        def __fspath__(self):
            return str(valid_file)

        def __str__(self):
            return str(valid_file)

    with patch.object(logging, "warning") as mock_warning:
        validate_audio_file(FakeLargeAudioPath())

    mock_warning.assert_called_once()


def test_detect_silence_periods_and_format_helpers():
    waveform = np.zeros((2, 100), dtype=float)
    fake_torch = SimpleNamespace(
        mean=lambda arr, dim=0, keepdim=True: np.mean(arr, axis=dim, keepdims=keepdim),
        sqrt=np.sqrt,
        log10=np.log10,
    )
    fake_torchaudio = SimpleNamespace(load=lambda _path: (waveform, 10))

    with patch.dict(sys.modules, {"torch": fake_torch, "torchaudio": fake_torchaudio}):
        silence_periods = detect_silence_periods(
            Path("song.wav"), silence_threshold=-20.0, min_silence_duration=1.0
        )

    assert silence_periods == [(0.0, 10.0)]
    assert format_timestamp(3661) == "01:01:01"
    assert format_duration(3661) == "1h 1m"
    assert format_duration(7200) == "2h"
    assert format_duration(1800) == "30m"


def test_detect_silence_periods_returns_empty_on_processing_failures():
    broken_torchaudio = SimpleNamespace(
        load=lambda _path: (_ for _ in ()).throw(RuntimeError("decode error"))
    )

    with patch.dict(sys.modules, {"torchaudio": broken_torchaudio}):
        assert detect_silence_periods(Path("broken.wav")) == []


def test_get_audio_info_reports_missing_and_available_metadata(tmp_path):
    missing_info = get_audio_info(tmp_path / "missing.wav")
    assert missing_info["exists"] is False
    assert missing_info["format"] is None

    audio_path = tmp_path / "song.wav"
    audio_path.write_bytes(b"x" * 200)
    fake_audio_info = SimpleNamespace(sample_rate=44100, num_channels=2)
    fake_torchaudio = SimpleNamespace(info=lambda _path: fake_audio_info)

    with (
        patch("scribe.utils.audio.get_audio_duration", return_value=125.0),
        patch.dict(sys.modules, {"torchaudio": fake_torchaudio}),
    ):
        info = get_audio_info(audio_path)

    assert info["exists"] is True
    assert info["duration_seconds"] == 125.0
    assert info["duration_formatted"] == "2m"
    assert info["sample_rate"] == 44100
    assert info["channels"] == 2
