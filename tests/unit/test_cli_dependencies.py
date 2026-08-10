"""Tests for lazy CLI dependency construction seams."""

from pathlib import Path
from unittest.mock import Mock, patch

from scribe.cli import dependencies


def test_transcriber_constructor_is_loaded_on_demand() -> None:
    expected = Mock()
    with patch("scribe.core.transcriber.Transcriber", return_value=expected) as constructor:
        result = dependencies.Transcriber("config", option=True)

    assert result is expected
    constructor.assert_called_once_with("config", option=True)


def test_obs_constructor_is_loaded_on_demand() -> None:
    expected = Mock()
    with patch("scribe.core.recorder.OBSRecorder", return_value=expected) as constructor:
        result = dependencies.OBSRecorder("config")

    assert result is expected
    constructor.assert_called_once_with("config")


def test_settings_constructor_is_loaded_on_demand() -> None:
    expected = Mock()
    with patch("scribe.models.config.ScribeConfig", return_value=expected) as constructor:
        result = dependencies.ScribeConfig(output_folder="output")

    assert result is expected
    constructor.assert_called_once_with(output_folder="output")


def test_gpu_detection_is_loaded_on_demand() -> None:
    expected = Mock()
    with patch("scribe.models.gpu.GPUConfig.detect", return_value=expected) as detect:
        result = dependencies.GPUConfig.detect()

    assert result is expected
    detect.assert_called_once_with()


def test_session_creation_is_loaded_on_demand() -> None:
    expected = Mock()
    with patch(
        "scribe.models.session.TranscriptionSession.create", return_value=expected
    ) as create:
        result = dependencies.TranscriptionSession.create("meeting")

    assert result is expected
    create.assert_called_once_with("meeting")


def test_docx_converter_is_loaded_on_demand(tmp_path: Path) -> None:
    source = tmp_path / "transcript.txt"
    output = tmp_path / "transcript.docx"
    with patch("scribe.utils.docx_converter.txt_to_docx", return_value=output) as convert:
        result = dependencies.txt_to_docx(source, output, "Title")

    assert result == output
    convert.assert_called_once_with(source, output, "Title")


def test_joke_generator_is_loaded_on_demand(tmp_path: Path) -> None:
    transcript = tmp_path / "transcript.txt"
    with patch(
        "scribe.utils.joke_generator.generate_transcript_joke",
        return_value=("joke", "style"),
    ) as generate:
        result = dependencies.generate_transcript_joke(transcript, "key", "openai")

    assert result == ("joke", "style")
    generate.assert_called_once_with(transcript, "key", "openai")
