"""
User-level config file (~/.scribe/config.toml).

Loaded as a layer between built-in defaults and environment variables: env vars
override the file, and CLI flags override env vars. Existing SCRIBE_* env vars
keep working unchanged.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tomllib
from datetime import date, datetime, time
from pathlib import Path
from typing import Any

CONFIG_DIR = Path.home() / ".scribe"
CONFIG_PATH = CONFIG_DIR / "config.toml"
_BARE_TOML_KEY = re.compile(r"^[A-Za-z0-9_-]+$")


def config_exists() -> bool:
    return CONFIG_PATH.is_file()


def load_config_file() -> dict[str, Any]:
    """Return the TOML config as a flat dict, or {} if missing/invalid."""
    try:
        return load_config_file_strict()
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def load_config_file_strict() -> dict[str, Any]:
    """Read config for mutation, preserving parse and filesystem failures."""
    try:
        with CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        return {}


def flatten_for_settings(data: dict[str, Any]) -> dict[str, Any]:
    """
    Map nested TOML sections to ScribeConfig field names.

    The TOML file uses readable section names but ScribeConfig is flat, so we
    translate here. Unknown keys are dropped.
    """
    out: dict[str, Any] = {}
    output = _section(data, "output")
    if "folder" in output:
        out["output_folder"] = output["folder"]

    transcription = _section(data, "transcription")
    if "method" in transcription:
        out["default_method"] = transcription["method"]
    if "model" in transcription:
        out["default_model"] = transcription["model"]
    if "language" in transcription:
        out["default_language"] = transcription["language"]
    if "local_backend" in transcription:
        out["local_backend"] = transcription["local_backend"]
    if "local_only" in transcription:
        out["local_only"] = transcription["local_only"]
    if "openrouter_model" in transcription:
        out["openrouter_model"] = transcription["openrouter_model"]
    if "openrouter_timeout_seconds" in transcription:
        out["openrouter_timeout_seconds"] = transcription["openrouter_timeout_seconds"]

    features = _section(data, "features")
    if "generate_notes" in features:
        out["enable_notes"] = features["generate_notes"]
    if "generate_joke" in features:
        out["enable_joke"] = features["generate_joke"]
    if "generate_meme" in features:
        out["enable_meme"] = features["generate_meme"]

    obs = _section(data, "obs")
    if "host" in obs:
        out["obs_host"] = obs["host"]
    if "port" in obs:
        out["obs_port"] = obs["port"]
    if "password" in obs:
        out["obs_password"] = obs["password"]

    return out


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a config section only when it is a table."""
    section = data.get(name, {})
    return section if isinstance(section, dict) else {}


def save_config_file(data: dict[str, Any]) -> Path:
    """Write the complete TOML config without dropping unknown user tables."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Keep ~/.scribe owner-only so it is locked down before any sensitive value
    # could ever be written there (no-op on platforms without POSIX modes).
    with contextlib.suppress(OSError):
        os.chmod(CONFIG_DIR, 0o700)
    lines: list[str] = []

    def append_table(path: tuple[str, ...], body: dict[str, Any]) -> None:
        values = [(key, value) for key, value in body.items() if not isinstance(value, dict)]
        subtables = [(key, value) for key, value in body.items() if isinstance(value, dict)]
        if path and (values or not body):
            lines.append(f"[{'.'.join(_toml_key(part) for part in path)}]")
        for key, value in values:
            lines.append(f"{_toml_key(key)} = {_toml_value(value)}")
        if values or (path and not body):
            lines.append("")
        for key, value in subtables:
            append_table((*path, str(key)), value)

    append_table((), data)

    from scribe.utils.safe_write import atomic_write

    atomic_write(CONFIG_PATH, "\n".join(lines), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(CONFIG_PATH, 0o600)
    return CONFIG_PATH


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int | float):
        return str(v)
    if isinstance(v, datetime | date | time):
        return v.isoformat()
    if isinstance(v, Path):
        v = str(v)
    if isinstance(v, list | tuple):
        return "[" + ", ".join(_toml_value(item) for item in v) + "]"
    if isinstance(v, dict):
        entries = ", ".join(f"{_toml_key(key)} = {_toml_value(value)}" for key, value in v.items())
        return "{ " + entries + " }"
    return json.dumps(str(v), ensure_ascii=False)


def _toml_key(value: Any) -> str:
    """Serialize one TOML key without corrupting valid quoted-key configs."""
    text = str(value)
    return text if _BARE_TOML_KEY.fullmatch(text) else json.dumps(text, ensure_ascii=False)
