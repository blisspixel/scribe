from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from scribe.cli import mobile


def test_find_wav_file_prefers_converted_variant(tmp_path: Path) -> None:
    input_file = tmp_path / "meeting.mp4"
    input_file.write_text("video")
    converted = tmp_path / "meeting_converted.wav"
    converted.write_text("wav")

    assert mobile.find_wav_file(input_file) == converted


def test_find_wav_file_raises_when_candidates_missing(tmp_path: Path) -> None:
    input_file = tmp_path / "meeting.mp4"
    input_file.write_text("video")

    with pytest.raises(FileNotFoundError, match=r"meeting_converted.wav"):
        mobile.find_wav_file(input_file)


def test_mobile_transcribe_success_cleans_up_temp_mp3(tmp_path: Path) -> None:
    input_file = tmp_path / "meeting.mp4"
    input_file.write_text("video")
    mp3_path = tmp_path / "meeting.mp3"
    mp3_path.write_text("mp3")
    transcript_path = tmp_path / "meeting.txt"
    transcript_path.write_text("transcript")

    config = Mock()
    config.openai_api_key = "sk-test"
    config.openai_model = "gpt-4o-transcribe"
    config.keep_intermediate_files = False
    config.log_folder = tmp_path / "logs"

    converter = Mock()
    converter.convert_to_mp3.return_value = mp3_path

    transcriber = Mock()
    transcriber.transcribe.return_value = transcript_path

    with (
        patch("scribe.cli.mobile.ScribeConfig", return_value=config),
        patch("scribe.cli.mobile.validate_file_path", return_value=input_file),
        patch("scribe.cli.mobile.setup_logging"),
        patch("scribe.cli.mobile.Converter", return_value=converter),
        patch("scribe.cli.mobile.OpenAITranscriber", return_value=transcriber),
        patch("scribe.cli.mobile.open_file_with_default_app", return_value=True),
    ):
        mobile.mobile_transcribe(str(input_file))

    assert not mp3_path.exists()
    transcriber.transcribe.assert_called_once()


def test_mobile_transcribe_exits_when_api_key_missing(tmp_path: Path) -> None:
    input_file = tmp_path / "meeting.mp4"
    input_file.write_text("video")

    config = Mock()
    config.openai_api_key = None

    with patch("scribe.cli.mobile.ScribeConfig", return_value=config), pytest.raises(SystemExit):
        mobile.mobile_transcribe(str(input_file))


def test_mobile_transcribe_warns_when_open_fails(tmp_path: Path) -> None:
    input_file = tmp_path / "meeting.mp4"
    input_file.write_text("video")
    mp3_path = tmp_path / "meeting.mp3"
    mp3_path.write_text("mp3")
    transcript_path = tmp_path / "meeting.txt"
    transcript_path.write_text("transcript")

    config = Mock()
    config.openai_api_key = "sk-test"
    config.openai_model = "gpt-4o-transcribe"
    config.keep_intermediate_files = True
    config.log_folder = tmp_path / "logs"

    converter = Mock()
    converter.convert_to_mp3.return_value = mp3_path

    transcriber = Mock()
    transcriber.transcribe.return_value = transcript_path

    with (
        patch("scribe.cli.mobile.ScribeConfig", return_value=config),
        patch("scribe.cli.mobile.validate_file_path", return_value=input_file),
        patch("scribe.cli.mobile.setup_logging"),
        patch("scribe.cli.mobile.Converter", return_value=converter),
        patch("scribe.cli.mobile.OpenAITranscriber", return_value=transcriber),
        patch("scribe.cli.mobile.open_file_with_default_app", return_value=False),
    ):
        mobile.mobile_transcribe(str(input_file))

    assert mp3_path.exists()
