"""Run the resident voice tray automatically at login (per-OS, user-scoped).

Reuses the launcher command resolution from ``scribe.cli.shortcut``. Everything is
user-scoped (no admin) and explicit - ``start_at_login`` is never enabled silently:

- Windows: a ``.lnk`` in the per-user Startup folder, launched minimized so no
  console window lingers.
- macOS: a user LaunchAgent plist in ``~/Library/LaunchAgents`` with RunAtLoad.
- Linux: an XDG autostart ``.desktop`` entry in ``~/.config/autostart``.
"""

from __future__ import annotations

import logging
import os
import platform
import plistlib
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from scribe.cli.shortcut import resolve_scribe_command
from scribe.utils.platform import is_linux, is_macos, is_windows
from scribe.utils.safe_write import atomic_write

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)

STARTUP_NAME = "Scribe Voice Tray"
MACOS_LABEL = "io.pueo.scribe.tray"
LINUX_AUTOSTART_ID = "scribe-voice-tray.desktop"


def _tray_command() -> tuple[str, list[str]]:
    """Resolve (executable, args) that launch ``scribe tray``."""
    tokens = resolve_scribe_command()
    return tokens[0], [*tokens[1:], "tray"]


# ── Windows ───────────────────────────────────────────────────────────────────


def _windows_startup_path() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return (
        Path(appdata)
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
        / f"{STARTUP_NAME}.lnk"
    )


def _install_windows() -> Path:  # pragma: no cover - shell/registry I/O
    from scribe.cli.shortcut import _create_windows_lnk, _windows_icon_path

    target, args = _tray_command()
    lnk = _windows_startup_path()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    _create_windows_lnk(
        lnk,
        target,
        subprocess.list2cmdline(args),
        Path.home(),
        _windows_icon_path(),
        window_style=7,  # minimized, so no console window lingers at login
        description="Scribe resident voice tray",
    )
    return lnk


# ── macOS ─────────────────────────────────────────────────────────────────────


def _macos_agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{MACOS_LABEL}.plist"


def _install_macos() -> Path:  # pragma: no cover - launchctl I/O
    target, args = _tray_command()
    path = _macos_agent_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = plistlib.dumps(
        {
            "Label": MACOS_LABEL,
            "ProgramArguments": [target, *args],
            "RunAtLoad": True,
            "ProcessType": "Interactive",
        }
    )
    previous = path.read_bytes() if path.exists() else None
    atomic_write(path, payload, mode="wb")
    try:
        result = subprocess.run(
            ["launchctl", "load", str(path)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
        )
        if getattr(result, "returncode", 0) != 0:
            raise OSError(
                f"launchctl could not load run-at-login entry: status {result.returncode}"
            )
    except Exception as error:
        logger.warning("launchctl could not load run-at-login entry: %s", error)
        try:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, previous, mode="wb")
        except OSError as rollback_error:
            raise OSError(
                f"{error}; restoring the prior LaunchAgent also failed: {rollback_error}"
            ) from error
        raise OSError(str(error)) from error
    return path


# ── Linux ─────────────────────────────────────────────────────────────────────


def _linux_autostart_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config_home) / "autostart" / LINUX_AUTOSTART_ID


def _desktop_exec_arg(value: str) -> str:
    """Quote one freedesktop Exec argument without relying on shell syntax."""
    if "\0" in value:
        raise ValueError("desktop startup arguments cannot contain NUL bytes")
    escaped = (
        value.replace("%", "%%")
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("`", "\\`")
        .replace("$", "\\$")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _install_linux() -> Path:  # pragma: no cover - file I/O
    target, args = _tray_command()
    path = _linux_autostart_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    exec_line = " ".join(_desktop_exec_arg(token) for token in [target, *args])
    atomic_write(
        path,
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={STARTUP_NAME}\n"
        "Comment=Resident dictation and read-aloud\n"
        f"Exec={exec_line}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )
    return path


# ── Public API ──────────────────────────────────────────────────────────────


def startup_path() -> Path:
    """The per-OS path where the autostart entry lives."""
    if is_windows():
        return _windows_startup_path()
    if is_macos():
        return _macos_agent_path()
    if is_linux():
        return _linux_autostart_path()
    raise OSError(f"Run-at-login is not supported on {platform.system()}")


def is_startup_enabled() -> bool:
    """Whether the tray is currently configured to run at login."""
    try:
        return startup_path().exists()
    except OSError:
        return False


def install_startup() -> Path:  # pragma: no cover - per-OS I/O
    """Enable run-at-login for the tray. Returns the created entry path."""
    if is_windows():
        return _install_windows()
    if is_macos():
        return _install_macos()
    if is_linux():
        return _install_linux()
    raise OSError(f"Run-at-login is not supported on {platform.system()}")


def remove_startup() -> Path | None:  # pragma: no cover - per-OS I/O
    """Disable run-at-login. Returns the removed path, or None if not enabled."""
    path = startup_path()
    if not path.exists():
        return None
    unload_error: Exception | None = None
    if is_macos():
        try:
            result = subprocess.run(
                ["launchctl", "unload", str(path)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            if getattr(result, "returncode", 0) != 0:
                unload_error = OSError(
                    f"launchctl could not unload run-at-login entry: status {result.returncode}"
                )
        except Exception as error:
            unload_error = error
        if unload_error is not None:
            logger.warning("launchctl could not unload run-at-login entry: %s", unload_error)
    path.unlink()
    if unload_error is not None:
        raise OSError(
            "The LaunchAgent file was removed, but launchctl could not unload the current "
            f"login-session job: {unload_error}"
        ) from unload_error
    return path


def run_tray_startup(console: Console, action: str) -> int:
    """CLI handler for ``scribe tray --startup install|remove|status``."""
    choice = (action or "status").strip().lower()
    if choice not in {"install", "remove", "status"}:
        console.print("[red]--startup must be one of: install, remove, status[/red]")
        return 2

    if choice == "status":
        try:
            path = startup_path()
            enabled = path.exists()
        except OSError as e:
            console.print(f"[red]Could not inspect run at login:[/red] {e}")
            return 1
        if enabled:
            console.print(f"[green]Run at login: enabled[/green]\n  [dim]{path}[/dim]")
        else:
            console.print(
                "[yellow]Run at login: disabled[/yellow]\n"
                "[dim]Enable with `scribe tray --startup install`.[/dim]"
            )
        return 0

    if choice == "remove":
        try:
            removed = remove_startup()
        except Exception as e:
            console.print(f"[red]Could not disable run at login:[/red] {e}")
            return 1
        if removed is not None:
            console.print(f"[green]Removed run-at-login entry:[/green] [dim]{removed}[/dim]")
        else:
            console.print("[yellow]Run at login was not enabled.[/yellow]")
        return 0

    try:
        created = install_startup()
    except Exception as e:
        console.print(f"[red]Could not enable run at login:[/red] {e}")
        return 1
    console.print(
        f"[green]Scribe Voice tray will now start at login.[/green]\n  [dim]{created}[/dim]"
    )
    if is_windows():
        console.print("[dim]It launches minimized to the system tray.[/dim]")
    elif is_macos():
        console.print(
            "[dim]macOS: a user LaunchAgent was written. Grant Input Monitoring and "
            "Microphone to the same binary that starts at login, then log out/in once.[/dim]"
        )
    else:
        console.print(
            "[dim]Linux: XDG autostart entry written. On Wayland, including Omarchy, "
            "this does not register global hotkeys. Leave F9 to Omarchy dictation "
            "when that backend is installed. `scribe voice` is the experimental "
            "compositor path and is not validated by this startup entry.[/dim]"
        )
    console.print("[dim]Disable anytime with `scribe tray --startup remove`.[/dim]")
    return 0
