"""Product storage paths, with XDG conventions on Linux only.

Resolving persistent paths never moves user files. Runtime paths are validated
before use because a control socket, token, and lock must share a private owner.
"""

from __future__ import annotations

import logging
import os
import re
import stat
import sys
from pathlib import Path

_RUNTIME_WARNING_SHOWN = False
_VIDEO_DIR = re.compile(r'^\s*XDG_VIDEOS_DIR\s*=\s*"((?:[^"\\]|\\.)*)"\s*(?:#.*)?$')


def legacy_dir(home: Path | None = None) -> Path:
    return (Path.home() if home is None else home) / ".scribe"


def _xdg_home(name: str, default: Path) -> Path:
    value = os.environ.get(name, "")
    path = Path(value)
    return path if value and path.is_absolute() else default


def config_home(home: Path | None = None) -> Path:
    return _xdg_home("XDG_CONFIG_HOME", (Path.home() if home is None else home) / ".config")


def data_home(home: Path | None = None) -> Path:
    return _xdg_home("XDG_DATA_HOME", (Path.home() if home is None else home) / ".local/share")


def config_dir(home: Path | None = None) -> Path:
    return config_home(home) / "scribe" if sys.platform == "linux" else legacy_dir(home)


def data_dir(home: Path | None = None) -> Path:
    return data_home(home) / "scribe" if sys.platform == "linux" else legacy_dir(home)


def state_dir(home: Path | None = None) -> Path:
    if sys.platform != "linux":
        return legacy_dir(home)
    base = Path.home() if home is None else home
    return _xdg_home("XDG_STATE_HOME", base / ".local/state") / "scribe"


def default_log_dir(home: Path | None = None) -> Path:
    return state_dir(home) / "logs" if sys.platform == "linux" else legacy_dir(home) / "logs"


def vocabulary_dirs(home: Path | None = None) -> tuple[Path, ...]:
    """New user vocabulary takes precedence over legacy files, then bundled data."""
    return tuple(dict.fromkeys((data_dir(home) / "vocab", legacy_dir(home) / "vocab")))


def videos_dir(home: Path | None = None) -> Path:
    """Read the standard quoted user-dir format without executing shell code."""
    base = Path.home() if home is None else home
    if sys.platform == "darwin":
        return base / "Movies"
    if sys.platform != "linux":
        return base / "Videos"
    try:
        lines = (config_home(home) / "user-dirs.dirs").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        return base / "Videos"
    for line in reversed(lines):
        match = _VIDEO_DIR.fullmatch(line)
        if match is None:
            continue
        value = match.group(1)
        # Only the documented leading $HOME expansion is supported. Backslash
        # escapes quote, backslash, dollar and backtick in this shell format.
        prefix = "$HOME"
        from_home = value == prefix or value.startswith(prefix + "/")
        if from_home:
            value = value[len(prefix) :]
        # Reject substitutions instead of evaluating the user's shell fragment.
        if re.search(r"(?<!\\)[$`]", value):
            continue
        value = re.sub(r'\\([\\"$`])', r"\1", value)
        path = Path(str(base) + value) if from_home else Path(value)
        if path.is_absolute():
            return path
    return base / "Videos"


def _no_symlink_components(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise OSError(f"Scribe runtime path must not contain a symbolic link: {component}")


def _private_directory(path: Path, *, create: bool = False) -> None:
    _no_symlink_components(path)
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise OSError(f"Scribe runtime directory must be a directory owned by your user: {path}")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise OSError(f"Scribe runtime directory must have permissions 0700: {path}")


def runtime_dir(home: Path | None = None) -> Path:
    """Return a validated private control directory; never replace an unsafe override."""
    if sys.platform != "linux":
        return legacy_dir(home)
    value = os.environ.get("XDG_RUNTIME_DIR", "")
    if value:
        base = Path(value)
        try:
            if not base.is_absolute():
                raise OSError("XDG_RUNTIME_DIR must be an absolute path")
            _private_directory(base)
            result = base / "scribe"
            _private_directory(result, create=True)
            return result
        except OSError as error:
            raise OSError(
                f"Unsafe XDG_RUNTIME_DIR: {error}. Use your login session's private "
                "runtime directory; Scribe did not fall back to another location."
            ) from error
    global _RUNTIME_WARNING_SHOWN
    if not _RUNTIME_WARNING_SHOWN:
        logging.getLogger(__name__).warning(
            "XDG_RUNTIME_DIR is unset; Scribe voice uses the legacy ~/.scribe runtime directory."
        )
        _RUNTIME_WARNING_SHOWN = True
    result = legacy_dir(home)
    _private_directory(result, create=True)
    return result


def validate_runtime_file(path: Path, *, socket_file: bool = False) -> None:
    """Reject existing control leaves with the wrong type, owner, or permissions."""
    if sys.platform != "linux":
        return
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    valid_type = stat.S_ISSOCK(info.st_mode) if socket_file else stat.S_ISREG(info.st_mode)
    if not valid_type or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise OSError(
            f"Scribe runtime file must be user-owned, private, and the expected type: {path}"
        )
