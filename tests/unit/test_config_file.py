from __future__ import annotations

from pathlib import Path

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


def test_flatten_for_settings_maps_known_sections_only():
    flattened = config_file.flatten_for_settings(
        {
            "output": {"folder": "C:/scribe/out", "ignored": "value"},
            "transcription": {"method": "local", "model": "large-v3", "language": "es"},
            "features": {"generate_notes": 1, "generate_joke": 0, "generate_meme": True},
            "unknown": {"value": "ignored"},
        }
    )

    assert flattened == {
        "output_folder": "C:/scribe/out",
        "default_method": "local",
        "default_model": "large-v3",
        "default_language": "es",
        "enable_notes": True,
        "enable_joke": False,
        "enable_meme": True,
    }


def test_save_config_file_writes_sections_and_escaped_values(monkeypatch, tmp_path):
    config_path = _use_temp_config(monkeypatch, tmp_path)

    saved_path = config_file.save_config_file(
        {
            # Use an explicit backslash string (not a Path) so the escaping
            # assertion is identical on Windows and POSIX runners; str(Path)
            # would otherwise normalize separators per platform.
            "output": {"folder": "C:\\Users\\Nick\\Scribe Output"},
            "transcription": {"method": "auto", "model": "large-v3"},
            "features": {"generate_notes": False, "generate_joke": True},
            "providers": {"joke_provider": 'open"ai'},
        }
    )

    assert saved_path == config_path
    contents = config_path.read_text(encoding="utf-8")
    assert "[output]" in contents
    assert 'folder = "C:\\\\Users\\\\Nick\\\\Scribe Output"' in contents
    assert "generate_notes = false" in contents
    assert "generate_joke = true" in contents
    assert 'joke_provider = "open\\"ai"' in contents
