from __future__ import annotations

from scribe.utils import obs_config


def test_obs_config_dir_windows(monkeypatch, tmp_path):
    appdata = tmp_path / "Roaming"
    monkeypatch.setattr(obs_config, "get_platform", lambda: "windows")
    monkeypatch.setenv("APPDATA", str(appdata))

    assert obs_config.obs_config_dir() == appdata / "obs-studio"


def test_obs_config_dir_linux_xdg(monkeypatch, tmp_path):
    xdg = tmp_path / "xdg"
    monkeypatch.setattr(obs_config, "get_platform", lambda: "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))

    assert obs_config.obs_config_dir() == xdg / "obs-studio"


def test_read_obs_websocket_config_missing(monkeypatch, tmp_path):
    path = tmp_path / "missing.json"
    monkeypatch.setattr(obs_config, "obs_websocket_config_path", lambda: path)

    result = obs_config.read_obs_websocket_config()

    assert result.path == path
    assert result.exists is False
    assert result.error == "OBS WebSocket config not found"


def test_read_obs_websocket_config_invalid(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(obs_config, "obs_websocket_config_path", lambda: path)

    result = obs_config.read_obs_websocket_config()

    assert result.path == path
    assert result.exists is True
    assert result.error is not None
    assert "Could not read" in result.error


def test_read_obs_websocket_config_valid(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"server_enabled": true, "auth_required": true, "server_port": "4456"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(obs_config, "obs_websocket_config_path", lambda: path)

    result = obs_config.read_obs_websocket_config()

    assert result.path == path
    assert result.exists is True
    assert result.error is None
    assert result.server_enabled is True
    assert result.auth_required is True
    assert result.server_port == 4456


def test_read_obs_websocket_config_invalid_port_defaults(monkeypatch, tmp_path):
    path = tmp_path / "config.json"
    path.write_text(
        '{"server_enabled": true, "auth_required": false, "server_port": "bad"}',
        encoding="utf-8",
    )
    monkeypatch.setattr(obs_config, "obs_websocket_config_path", lambda: path)

    result = obs_config.read_obs_websocket_config()

    assert result.server_port == 4455
