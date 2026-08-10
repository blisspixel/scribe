import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scribe.utils.silence_remover import analyze_silence, remove_silence, trim_file


def test_remove_silence_uses_default_output_name(tmp_path: Path) -> None:
    input_path = tmp_path / "meeting.mp4"
    input_path.write_text("video")

    with patch("scribe.utils.silence_remover.subprocess.run") as mock_run:
        result = remove_silence(input_path)

    assert result == tmp_path / "meeting_cleaned.mp4"
    cmd = mock_run.call_args.args[0]
    assert str(result) in cmd
    assert "silenceremove=" in cmd[4]


def test_remove_silence_raises_when_input_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        remove_silence(tmp_path / "missing.mp4")


def test_remove_silence_wraps_ffmpeg_error(tmp_path: Path) -> None:
    input_path = tmp_path / "meeting.mp4"
    input_path.write_text("video")

    error = subprocess.CalledProcessError(1, "ffmpeg", stderr="boom")
    with (
        patch("scribe.utils.silence_remover.subprocess.run", side_effect=error),
        pytest.raises(RuntimeError, match="boom"),
    ):
        remove_silence(input_path)


def test_analyze_silence_parses_detected_ranges(tmp_path: Path) -> None:
    input_path = tmp_path / "meeting.mp4"
    input_path.write_text("video")
    stderr = "\n".join(
        [
            "silence_start: 10.0",
            "silence_end: 25.5 | silence_duration: 15.5",
            "silence_start: 30.0",
            "silence_end: 35.0 | silence_duration: 5.0",
        ]
    )

    completed = subprocess.CompletedProcess(args=["ffmpeg"], returncode=0, stderr=stderr)
    with patch("scribe.utils.silence_remover.subprocess.run", return_value=completed):
        result = analyze_silence(input_path)

    assert result["silence_periods"] == 2
    assert result["total_silence_seconds"] == pytest.approx(20.5)
    assert result["periods"][0]["start"] == 10.0


def test_trim_file_uses_default_output_name(tmp_path: Path) -> None:
    input_path = tmp_path / "meeting.mp4"
    input_path.write_text("video")

    with patch("scribe.utils.silence_remover.subprocess.run") as mock_run:
        result = trim_file(input_path, end_time="00:10:00")

    assert result == tmp_path / "meeting_trimmed.mp4"
    cmd = mock_run.call_args.args[0]
    assert cmd[4] == "00:00:00"
    assert cmd[6] == "00:10:00"


def test_trim_file_requires_end_time(tmp_path: Path) -> None:
    input_path = tmp_path / "meeting.mp4"
    input_path.write_text("video")

    with pytest.raises(ValueError, match="end_time is required"):
        trim_file(input_path)
