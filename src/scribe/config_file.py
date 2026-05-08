"""
User-level config file (~/.scribe/config.toml).

Loaded as a layer between built-in defaults and environment variables: env vars
override the file, and CLI flags override env vars. Existing SCRIBE_* env vars
keep working unchanged.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


CONFIG_DIR = Path.home() / ".scribe"
CONFIG_PATH = CONFIG_DIR / "config.toml"


def config_exists() -> bool:
    return CONFIG_PATH.is_file()


def load_config_file() -> dict[str, Any]:
    """Return the TOML config as a flat dict, or {} if missing/invalid."""
    if not config_exists():
        return {}
    try:
        with CONFIG_PATH.open("rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def flatten_for_settings(data: dict[str, Any]) -> dict[str, Any]:
    """
    Map nested TOML sections to ScribeConfig field names.

    The TOML file uses readable section names but ScribeConfig is flat, so we
    translate here. Unknown keys are dropped.
    """
    out: dict[str, Any] = {}
    output = data.get("output", {})
    if "folder" in output:
        out["output_folder"] = output["folder"]

    transcription = data.get("transcription", {})
    if "method" in transcription:
        out["default_method"] = transcription["method"]
    if "model" in transcription:
        out["default_model"] = transcription["model"]
    if "language" in transcription:
        out["default_language"] = transcription["language"]

    features = data.get("features", {})
    if "generate_notes" in features:
        out["enable_notes"] = bool(features["generate_notes"])
    if "generate_joke" in features:
        out["enable_joke"] = bool(features["generate_joke"])
    if "generate_meme" in features:
        out["enable_meme"] = bool(features["generate_meme"])

    return out


def save_config_file(data: dict[str, Any]) -> Path:
    """Write the TOML config, creating the parent dir if needed."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def section(name: str, body: dict[str, Any]) -> None:
        if not body:
            return
        lines.append(f"[{name}]")
        for k, v in body.items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")

    section("output", data.get("output", {}))
    section("transcription", data.get("transcription", {}))
    section("features", data.get("features", {}))
    section("providers", data.get("providers", {}))

    CONFIG_PATH.write_text("\n".join(lines), encoding="utf-8")
    return CONFIG_PATH


def _toml_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, Path):
        v = str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
