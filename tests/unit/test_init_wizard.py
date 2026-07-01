from __future__ import annotations

from io import StringIO
from unittest.mock import Mock, patch

from rich.console import Console

from scribe.cli import init as init_wizard


def _console() -> Console:
    return Console(file=StringIO())


def test_detect_gpu_summary_reports_capable_gpu():
    with (
        patch(
            "scribe.utils.gpu.detect_gpu_capability",
            return_value={
                "cuda_available": True,
                "gpu_name": "NVIDIA RTX 4090",
                "gpu_memory_gb": 24,
            },
        ),
        patch("scribe.utils.gpu.is_high_end_gpu", return_value=True),
    ):
        has_gpu, summary = init_wizard._detect_gpu_summary()

    assert has_gpu is True
    assert "RTX 4090" in summary
    assert "high-end" in summary


def test_detect_gpu_summary_handles_detection_failure():
    with patch("scribe.utils.gpu.detect_gpu_capability", side_effect=RuntimeError("boom")):
        has_gpu, summary = init_wizard._detect_gpu_summary()

    assert has_gpu is False
    assert "GPU detection failed" in summary


def test_detected_keys_reads_discovered_env_file(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("OPENAI_API_KEY=sk-test\nXAI_API_KEY=xai-test\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)

    with patch("scribe.models.config._find_env_file", return_value=env_path):
        assert init_wizard._detected_keys() == {"openai": True, "xai": True}


def test_default_output_folder_prefers_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SCRIBE_OUTPUT_FOLDER", str(tmp_path / "env-output"))
    monkeypatch.setattr(init_wizard, "CONFIG_PATH", tmp_path / "missing.toml")

    assert init_wizard._default_output_folder() == str(tmp_path / "env-output")


def test_default_output_folder_uses_existing_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    configured_output = (tmp_path / "configured-output").as_posix()
    config_path.write_text(
        f'[output]\nfolder = "{configured_output}"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("SCRIBE_OUTPUT_FOLDER", raising=False)
    monkeypatch.setattr(init_wizard, "CONFIG_PATH", config_path)

    assert init_wizard._default_output_folder() == configured_output


def test_default_output_folder_uses_platform_default(tmp_path, monkeypatch):
    expected = tmp_path / "Videos" / "Transcriptions"
    monkeypatch.delenv("SCRIBE_OUTPUT_FOLDER", raising=False)
    monkeypatch.setattr(init_wizard, "CONFIG_PATH", tmp_path / "missing.toml")

    with patch("scribe.utils.platform.get_default_output_directory", return_value=expected):
        assert init_wizard._default_output_folder() == str(expected)


def test_run_wizard_writes_expected_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    save_config = Mock(return_value=config_path)
    monkeypatch.setenv("SCRIBE_OUTPUT_FOLDER", str(tmp_path / "out"))
    monkeypatch.setattr(init_wizard, "CONFIG_PATH", config_path)
    monkeypatch.setattr(init_wizard, "save_config_file", save_config)
    monkeypatch.setattr(init_wizard, "_detect_gpu_summary", lambda: (True, "RTX 4090"))
    monkeypatch.setattr(init_wizard, "_detected_keys", lambda: {"openai": True, "xai": True})
    monkeypatch.setattr(init_wizard, "_resolve_env_conflicts", Mock())

    with (
        patch(
            "scribe.cli.init.Prompt.ask",
            side_effect=[
                str(tmp_path / "out"),
                "local",
                "xai",
                "localhost",
                "4455",
                "obs-secret",
            ],
        ),
        patch("scribe.cli.init.Confirm.ask", side_effect=[True, False, True, True, False]),
    ):
        result = init_wizard.run_wizard(console=_console(), force=True)

    assert result == config_path
    save_config.assert_called_once()
    saved_data = save_config.call_args.args[0]
    assert saved_data["output"]["folder"] == str(tmp_path / "out")
    assert saved_data["transcription"]["method"] == "local"
    assert saved_data["features"] == {
        "generate_notes": True,
        "generate_joke": False,
        "generate_meme": True,
    }
    assert saved_data["providers"]["joke_provider"] == "xai"
    assert saved_data["providers"]["meme_provider"] == "xai"
    assert saved_data["providers"]["notes_provider"] == "xai"
    assert saved_data["obs"] == {
        "host": "localhost",
        "port": 4455,
        "password": "obs-secret",
    }


def test_default_obs_settings_reads_existing_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[obs]\nhost = "127.0.0.1"\nport = 4456\npassword = "secret"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("SCRIBE_OBS_HOST", raising=False)
    monkeypatch.delenv("SCRIBE_OBS_PORT", raising=False)
    monkeypatch.delenv("SCRIBE_OBS_PASSWORD", raising=False)
    monkeypatch.setattr(init_wizard, "CONFIG_PATH", config_path)

    assert init_wizard._default_obs_settings() == {
        "host": "127.0.0.1",
        "port": "4456",
        "password": "secret",
    }


def test_default_obs_settings_prefers_env(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[obs]\nhost = "localhost"\nport = 4455\npassword = "config-secret"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("SCRIBE_OBS_HOST", "obs.local")
    monkeypatch.setenv("SCRIBE_OBS_PORT", "4457")
    monkeypatch.setenv("SCRIBE_OBS_PASSWORD", "env-secret")
    monkeypatch.setattr(init_wizard, "CONFIG_PATH", config_path)

    assert init_wizard._default_obs_settings() == {
        "host": "obs.local",
        "port": "4457",
        "password": "env-secret",
    }


def test_run_wizard_keeps_existing_config_when_declined(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(init_wizard, "CONFIG_PATH", config_path)

    with patch("scribe.cli.init.Confirm.ask", return_value=False):
        assert init_wizard.run_wizard(console=_console()) == config_path


def test_resolve_env_conflicts_comments_conflicting_lines(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "SCRIBE_ENABLE_NOTES=true",
                "SCRIBE_ENABLE_JOKE=false",
                "# SCRIBE_ENABLE_MEME=false",
                "OTHER=value",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with (
        patch("scribe.models.config._find_env_file", return_value=env_path),
        patch("scribe.cli.init.Confirm.ask", return_value=True),
    ):
        init_wizard._resolve_env_conflicts(
            console=_console(),
            chosen={
                "SCRIBE_ENABLE_NOTES": False,
                "SCRIBE_ENABLE_JOKE": False,
                "SCRIBE_ENABLE_MEME": True,
            },
        )

    contents = env_path.read_text(encoding="utf-8")
    assert "# SCRIBE_ENABLE_NOTES=true  # commented by scribe init" in contents
    assert "SCRIBE_ENABLE_JOKE=false" in contents
    assert "# SCRIBE_ENABLE_MEME=false" in contents


def test_maybe_prompt_first_run_respects_skip_conditions(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    monkeypatch.setattr(init_wizard, "CONFIG_PATH", config_path)

    monkeypatch.setenv("SCRIBE_SKIP_INIT", "1")
    assert init_wizard.maybe_prompt_first_run(console=_console()) is False

    monkeypatch.delenv("SCRIBE_SKIP_INIT", raising=False)
    with patch("sys.stdin.isatty", return_value=False):
        assert init_wizard.maybe_prompt_first_run(console=_console()) is False


def test_maybe_prompt_first_run_runs_wizard_when_accepted(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    monkeypatch.setattr(init_wizard, "CONFIG_PATH", config_path)
    run_wizard = Mock()
    monkeypatch.setattr(init_wizard, "run_wizard", run_wizard)

    with (
        patch("sys.stdin.isatty", return_value=True),
        patch("scribe.cli.init.Confirm.ask", return_value=True),
    ):
        assert init_wizard.maybe_prompt_first_run(console=_console()) is True

    run_wizard.assert_called_once()
