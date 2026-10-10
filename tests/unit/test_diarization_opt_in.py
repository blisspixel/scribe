"""Local speaker models only run after an explicit opt-in."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scribe.cli.main import _apply_diarization_options
from scribe.core.transcriber import Transcriber
from scribe.models.config import ScribeConfig
from scribe.models.gpu import GPUConfig


@pytest.fixture
def config(tmp_path: Path) -> ScribeConfig:
    with patch("scribe.config_file.load_config_file", return_value={}):
        return ScribeConfig(_env_file=None, output_folder=tmp_path, log_folder=tmp_path)


def test_default_skips_installed_and_cached_speaker_models(config: ScribeConfig) -> None:
    transcriber = object.__new__(Transcriber)
    transcriber.config = config
    transcriber._cached_diarizer = MagicMock()
    with patch("scribe.core.diarization.registry.resolve_diarizer") as resolve:
        assert transcriber._build_diarizer() is None
    resolve.assert_not_called()
    assert config.default_model == "large-v3"


def test_explicit_opt_in_resolves_speaker_model(config: ScribeConfig) -> None:
    _apply_diarization_options(config, True, None)
    transcriber = object.__new__(Transcriber)
    transcriber.config = config
    transcriber.gpu_config = GPUConfig(has_gpu=False)
    transcriber._cached_diarizer = None
    with (
        patch("scribe.core.backends.detect_hardware"),
        patch("scribe.core.diarization.registry.resolve_diarizer") as resolve,
    ):
        assert transcriber._build_diarizer() is resolve.return_value
    resolve.assert_called_once()


@pytest.mark.parametrize(
    ("diarize", "diarizer", "name_speakers", "enabled"),
    [
        (None, None, None, False),
        (True, None, None, True),
        (None, "nemotron", None, True),
        (None, "auto", None, True),
        (None, None, True, True),
        (None, None, False, False),
        (False, "nemotron", True, False),
        (None, "none", True, False),
    ],
)
def test_cli_opt_in_and_explicit_opt_out(
    config: ScribeConfig,
    diarize: bool | None,
    diarizer: str | None,
    name_speakers: bool | None,
    enabled: bool,
) -> None:
    _apply_diarization_options(config, diarize, diarizer, name_speakers)
    assert config.enable_speaker_diarization is enabled


def test_cli_opt_out_overrides_persistent_opt_in(config: ScribeConfig) -> None:
    config.enable_speaker_diarization = True
    _apply_diarization_options(config, False, None)
    assert config.enable_speaker_diarization is False


def test_configured_opt_in_is_preserved(tmp_path: Path) -> None:
    with patch(
        "scribe.config_file.load_config_file", return_value={"diarization": {"enabled": True}}
    ):
        config = ScribeConfig(_env_file=None, output_folder=tmp_path, log_folder=tmp_path)
    _apply_diarization_options(config, None, None)
    assert config.enable_speaker_diarization is True
