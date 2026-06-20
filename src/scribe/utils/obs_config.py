"""OBS WebSocket configuration discovery.

This module is intentionally read-only. It never starts, stops, or modifies OBS.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from scribe.utils.platform import get_platform


@dataclass(frozen=True)
class OBSWebSocketConfig:
    """Best-effort view of OBS WebSocket settings."""

    path: Path | None
    exists: bool
    server_enabled: bool | None = None
    auth_required: bool | None = None
    server_port: int | None = None
    error: str | None = None


def obs_config_dir() -> Path | None:
    """Return OBS Studio's per-user config directory for this platform."""
    platform = get_platform()
    if platform == "windows":
        appdata = os.environ.get("APPDATA", "")
        return Path(appdata) / "obs-studio" if appdata else None
    if platform == "macos":
        return Path.home() / "Library" / "Application Support" / "obs-studio"

    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    config_home = Path(xdg) if xdg else Path.home() / ".config"
    return config_home / "obs-studio"


def obs_websocket_config_path() -> Path | None:
    """Return the OBS WebSocket config path for this platform."""
    config_dir = obs_config_dir()
    if config_dir is None:
        return None
    return config_dir / "plugin_config" / "obs-websocket" / "config.json"


def read_obs_websocket_config() -> OBSWebSocketConfig:
    """Read OBS WebSocket config if it exists."""
    path = obs_websocket_config_path()
    if path is None:
        return OBSWebSocketConfig(
            path=None,
            exists=False,
            error="Could not locate OBS config directory",
        )
    if not path.is_file():
        return OBSWebSocketConfig(
            path=path,
            exists=False,
            error="OBS WebSocket config not found",
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return OBSWebSocketConfig(
            path=path,
            exists=True,
            error=f"Could not read OBS WebSocket config: {e}",
        )

    raw_port = data.get("server_port", 4455)
    try:
        server_port = int(raw_port)
    except (TypeError, ValueError):
        server_port = 4455

    return OBSWebSocketConfig(
        path=path,
        exists=True,
        server_enabled=bool(data.get("server_enabled", False)),
        auth_required=bool(data.get("auth_required", False)),
        server_port=server_port,
    )
