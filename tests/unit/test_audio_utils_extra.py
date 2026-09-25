import logging
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


def test_detect_silence_periods_and_format_helpers(tmp_path):
    from scribe.utils.audio_io import save_wav

    song = tmp_path / "song.wav"
    save_wav(song, np.zeros((2, 100), dtype=np.float32), 10)

    silence_periods = detect_silence_periods(
        song, silence_threshold=-20.0, min_silence_duration=1.0
    )

    assert silence_periods == [(0.0, 10.0)]
    assert format_timestamp(3661) == "01:01:01"
    assert format_duration(3661) == "1h 1m"
    assert format_duration(7200) == "2h"
    assert format_duration(1800) == "30m"
    # Sub-minute durations must render seconds, not a misleading "0m".
    assert format_duration(45) == "45s"
    assert format_duration(0) == "0s"


def test_detect_silence_periods_returns_empty_on_processing_failures():
    with patch("scribe.utils.audio_io.load_audio", side_effect=RuntimeError("decode error")):
        assert detect_silence_periods(Path("broken.wav")) == []


def test_detect_silence_periods_finds_quiet_gap_between_tones(tmp_path):
    from scribe.utils.audio_io import save_wav

    rate = 1000
    tone = 0.5 * np.sin(np.linspace(0, 200 * np.pi, 5 * rate, dtype=np.float32))
    audio = np.concatenate([tone, np.zeros(40 * rate, dtype=np.float32), tone])
    path = tmp_path / "gap.wav"
    save_wav(path, audio, rate)

    periods = detect_silence_periods(path, silence_threshold=-40.0, min_silence_duration=30.0)

    assert len(periods) == 1
    start, end = periods[0]
    assert 4.5 <= start <= 5.5
    assert 44.0 <= end <= 45.5


def test_get_audio_info_reports_missing_and_available_metadata(tmp_path):
    missing_info = get_audio_info(tmp_path / "missing.wav")
    assert missing_info["exists"] is False
    assert missing_info["format"] is None

    from scribe.utils.audio_io import save_wav

    audio_path = tmp_path / "song.wav"
    save_wav(audio_path, np.zeros((2, 441), dtype=np.float32), 44100)

    with patch("scribe.utils.audio.get_audio_duration", return_value=125.0):
        info = get_audio_info(audio_path)

    assert info["exists"] is True
    assert info["duration_seconds"] == 125.0
    assert info["duration_formatted"] == "2m"
    assert info["sample_rate"] == 44100
    assert info["channels"] == 2
