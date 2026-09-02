from __future__ import annotations

import tomllib
from datetime import UTC, date, datetime, time
from pathlib import Path

import pytest

from scribe import config_file


def _use_temp_config(monkeypatch, tmp_path: Path) -> Path:
    config_dir = tmp_path / ".scribe"
    config_path = config_dir / "config.toml"
    monkeypatch.setattr(config_file, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_file, "CONFIG_PATH", config_path)
    return config_path


def test_load_config_file_returns_empty_when_missing(monkeypatch, tmp_path):
    _use_temp_config(monkeypatch, tmp_path)

    assert config_file.config_exists() is False
    assert config_file.load_config_file() == {}


def test_load_config_file_returns_empty_for_invalid_toml(monkeypatch, tmp_path):
    config_path = _use_temp_config(monkeypatch, tmp_path)
    config_path.parent.mkdir(parents=True)
    config_path.write_text("[broken\n", encoding="utf-8")

    assert config_file.config_exists() is True
    assert config_file.load_config_file() == {}

    with pytest.raises(tomllib.TOMLDecodeError):
        config_file.load_config_file_strict()


def test_flatten_for_settings_maps_known_sections_only():
    flattened = config_file.flatten_for_settings(
        {
            "output": {"folder": "C:/scribe/out", "ignored": "value"},
            "transcription": {
                "method": "local",
                "model": "large-v3",
                "language": "es",
                "openrouter_model": "openai/whisper-1",
                "openrouter_timeout_seconds": 120,
                "openrouter_max_spend_usd": 2.5,
            },
            "features": {
                "generate_notes": 1,
                "generate_joke": 0,
                "generate_meme": True,
            },
            "obs": {"host": "127.0.0.1", "port": 4456, "password": "secret"},
            "unknown": {"value": "ignored"},
        }
    )

    assert flattened == {
        "output_folder": "C:/scribe/out",
        "default_method": "local",
        "default_model": "large-v3",
        "default_language": "es",
        "openrouter_model": "openai/whisper-1",
        "openrouter_timeout_seconds": 120,
        "openrouter_max_spend_usd": 2.5,
        "enable_notes": 1,
        "enable_joke": 0,
        "enable_meme": True,
        "obs_host": "127.0.0.1",
        "obs_port": 4456,
        "obs_password": "secret",
    }


def test_flatten_for_settings_preserves_string_booleans_for_pydantic():
    flattened = config_file.flatten_for_settings(
        {
            "transcription": {"local_only": "false"},
            "features": {"generate_notes": "false", "generate_joke": "true"},
        }
    )

    assert flattened == {
        "local_only": "false",
        "enable_notes": "false",
        "enable_joke": "true",
    }


def test_string_booleans_from_user_config_are_parsed_by_settings(monkeypatch, tmp_path):
    from scribe.models.config import ScribeConfig

    for name in ("SCRIBE_LOCAL_ONLY", "SCRIBE_ENABLE_NOTES", "SCRIBE_ENABLE_JOKE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        config_file,
        "load_config_file",
        lambda: {
            "transcription": {"local_only": "false"},
            "features": {"generate_notes": "false", "generate_joke": "true"},
        },
    )

    settings = ScribeConfig(
        output_folder=tmp_path / "output",
        log_folder=tmp_path / "logs",
        _env_file=None,
    )

    assert settings.local_only is False
    assert settings.enable_notes is False
    assert settings.enable_joke is True


def test_flatten_for_settings_ignores_malformed_sections():
    flattened = config_file.flatten_for_settings(
        {
            "output": "not-a-table",
            "transcription": None,
            "features": ["not", "a", "table"],
            "obs": "localhost",
        }
    )

    assert flattened == {}


def test_save_config_file_writes_sections_and_escaped_values(monkeypatch, tmp_path):
    config_path = _use_temp_config(monkeypatch, tmp_path)
    output_folder = r"C:\scribe\output"

    saved_path = config_file.save_config_file(
        {
            # Use an explicit backslash string (not a Path) so the escaping
            # assertion is identical on Windows and POSIX runners; str(Path)
            # would otherwise normalize separators per platform.
            "output": {"folder": output_folder},
            "transcription": {"method": "auto", "model": "large-v3"},
            "features": {"generate_notes": False, "generate_joke": True},
            "providers": {"joke_provider": 'open"ai\nsecond-line'},
            "obs": {"host": "localhost", "port": 4455, "password": "secret"},
        }
    )

    assert saved_path == config_path
    contents = config_path.read_text(encoding="utf-8")
    assert "[output]" in contents
    assert 'folder = "C:\\\\scribe\\\\output"' in contents
    assert "generate_notes = false" in contents
    assert "generate_joke = true" in contents
    assert 'joke_provider = "open\\"ai\\nsecond-line"' in contents
    assert config_file.load_config_file()["providers"]["joke_provider"] == 'open"ai\nsecond-line'
    assert "[obs]" in contents
    assert 'host = "localhost"' in contents
    assert "port = 4455" in contents
    assert 'password = "secret"' in contents


def test_save_config_file_serializes_scalar_root_values_without_table_headers(
    monkeypatch, tmp_path
):
    config_path = _use_temp_config(monkeypatch, tmp_path)

    config_file.save_config_file(
        {
            "output": {"folder": "out"},
            "obs": "not-a-table",
        }
    )

    contents = config_path.read_text(encoding="utf-8")
    assert "[output]" in contents
    assert "[obs]" not in contents
    assert tomllib.loads(contents)["obs"] == "not-a-table"


def test_save_config_file_preserves_original_when_atomic_replace_fails(monkeypatch, tmp_path):
    config_path = _use_temp_config(monkeypatch, tmp_path)
    config_path.parent.mkdir(parents=True)
    config_path.write_text("original config", encoding="utf-8")
    monkeypatch.setattr(
        "scribe.utils.safe_write.os.replace",
        lambda *_args: (_ for _ in ()).throw(PermissionError("replace denied")),
    )

    with pytest.raises(OSError, match="replace denied"):
        config_file.save_config_file({"output": {"folder": "new"}})

    assert config_path.read_text(encoding="utf-8") == "original config"


def test_save_config_file_preserves_valid_quoted_keys(monkeypatch, tmp_path):
    config_path = _use_temp_config(monkeypatch, tmp_path)

    config_file.save_config_file(
        {"providers": {"custom provider": "local", "line\nbreak": "escaped"}}
    )

    loaded = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert loaded["providers"] == {
        "custom provider": "local",
        "line\nbreak": "escaped",
    }


def test_save_config_file_round_trips_unknown_nested_user_tables(monkeypatch, tmp_path):
    config_path = _use_temp_config(monkeypatch, tmp_path)
    expected = {
        "root_note": "keep me",
        "custom plugin": {
            "enabled": True,
            "schedule": {
                "day": date(2026, 8, 1),
                "at": time(9, 30, 15),
                "updated": datetime(2026, 8, 1, 16, 30, tzinfo=UTC),
            },
            "thresholds": [1, 2.5, "three"],
            "targets": [
                {"name": "primary", "active": True},
                {"name": "backup", "active": False},
            ],
        },
        "voice": {
            "tray": {"dictate_hotkey": "f9"},
            "future backend": {"enabled": True},
        },
        "empty table": {},
    }

    config_file.save_config_file(expected)

    assert tomllib.loads(config_path.read_text(encoding="utf-8")) == expected
