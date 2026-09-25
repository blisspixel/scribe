"""Transcriber.transcribe must release GPU models whether it succeeds or fails."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scribe.core.transcriber import Transcriber
from scribe.exceptions import TranscriptionError
from scribe.models.config import ScribeConfig
from scribe.models.gpu import GPUConfig


@pytest.fixture
def transcriber(tmp_path: Path) -> Transcriber:
    # Bypass __init__, which needs FFmpeg; these tests only exercise resource release.
    instance = object.__new__(Transcriber)
    instance.config = ScribeConfig(output_folder=tmp_path)
    instance.gpu_config = GPUConfig(has_gpu=False)
    instance._cached_diarizer = None
    instance.last_transcript = None
    return instance


def test_release_after_success(transcriber: Transcriber, tmp_path: Path) -> None:
    out = tmp_path / "t.txt"
    with (
        patch.object(transcriber, "_transcribe", return_value=out),
        patch.object(transcriber, "release_resources") as release,
    ):
        assert transcriber.transcribe(tmp_path / "a.wav") == out
    release.assert_called_once()


def test_release_after_failure(transcriber: Transcriber, tmp_path: Path) -> None:
    with (
        patch.object(transcriber, "_transcribe", side_effect=TranscriptionError("boom")),
        patch.object(transcriber, "release_resources") as release,
        pytest.raises(TranscriptionError),
    ):
        transcriber.transcribe(tmp_path / "a.wav")
    release.assert_called_once()


def test_release_resources_unloads_models_and_diarizer(transcriber: Transcriber) -> None:
    transcriber._cached_diarizer = MagicMock()
    manager = MagicMock()
    with patch("scribe.utils.gpu_manager.get_gpu_manager", return_value=manager):
        transcriber.release_resources()
        transcriber.release_resources()  # idempotent
    assert transcriber._cached_diarizer is None
    assert manager.unload_current_model.call_count == 2


def test_release_resources_tolerates_manager_errors(transcriber: Transcriber) -> None:
    with patch("scribe.utils.gpu_manager.get_gpu_manager", side_effect=RuntimeError("x")):
        transcriber.release_resources()
