"""
Cross-platform "Quick Record" launcher installer.

Creates a native, double-clickable launcher that runs ``scribe rec`` so users can
start a recording without opening a terminal. It replaces the old hand-made Windows
``.bat`` workaround and works on Windows (Start Menu ``.lnk``), macOS
(``~/Applications/*.command``) and Linux (XDG ``*.desktop``).

The launcher invokes whatever ``scribe`` resolves to at install time (preferring a
``scribe`` on PATH, e.g. one installed via ``uv tool install``), falling back to
``python -m scribe`` so it keeps working even when no console script is on PATH.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

from scribe.utils.platform import is_macos, is_windows

if TYPE_CHECKING:
    from rich.console import Console

LAUNCHER_NAME = "Scribe Quick Record"
# Linux .desktop files use a stable, lower-case, dashless id.
LINUX_DESKTOP_ID = "scribe-quick-record.desktop"


def resolve_scribe_command() -> list[str]:
    """Return the argv tokens that launch Scribe, for embedding in a launcher.

    Resolution order:
      1. A ``scribe`` console script on PATH (e.g. ``uv tool install``).
      2. The currently-running entry point, if it looks like a scribe executable.
      3. ``<python> -m scribe`` as a universal fallback.
    """
    on_path = shutil.which("scribe")
    if on_path:
        return [on_path]

    if sys.argv and sys.argv[0]:
        arg0 = Path(sys.argv[0])
        if arg0.name.lower().startswith("scribe") and arg0.exists():
            return [str(arg0.resolve())]

    return [sys.executable, "-m", "scribe"]


def _win_quote(token: str) -> str:
    return f'"{token}"' if (" " in token or "\t" in token) else token


def _windows_command_line(tokens: list[str]) -> str:
    return " ".join(_win_quote(t) for t in tokens)


def _posix_command_line(tokens: list[str]) -> str:
    return " ".join(shlex.quote(t) for t in tokens)


# ── Windows ──────────────────────────────────────────────────────────────────


def _windows_start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _windows_cmd_path() -> Path:
    return Path.home() / ".scribe" / f"{LAUNCHER_NAME}.cmd"


def _create_windows_lnk(lnk_path: Path, target: Path, workdir: Path) -> None:
    """Create a Windows .lnk via WScript.Shell (no pywin32 dependency).

    Isolated so tests can monkeypatch it without invoking PowerShell.
    """

    def ps(p: str) -> str:
        # Single-quote PowerShell string literal; escape embedded single quotes.
        return "'" + p.replace("'", "''") + "'"

    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut({ps(str(lnk_path))}); "
        f"$s.TargetPath = {ps(str(target))}; "
        f"$s.WorkingDirectory = {ps(str(workdir))}; "
        f"$s.Description = {ps('Start a Scribe recording (auto-transcribes when you stop)')}; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )


def _install_windows(tokens: list[str], desktop: bool) -> list[Path]:
    created: list[Path] = []
    cmd_line = _windows_command_line(tokens)

    cmd_path = _windows_cmd_path()
    cmd_path.parent.mkdir(parents=True, exist_ok=True)
    cmd_path.write_text(
        "@echo off\r\n"
        f"title {LAUNCHER_NAME}\r\n"
        'cd /d "%USERPROFILE%"\r\n'
        f"{cmd_line} rec\r\n"
        "echo.\r\n"
        "pause\r\n",
        encoding="utf-8",
    )
    created.append(cmd_path)

    home = Path.home()
    start_menu = _windows_start_menu_dir()
    start_menu.mkdir(parents=True, exist_ok=True)
    targets = [start_menu / f"{LAUNCHER_NAME}.lnk"]
    if desktop:
        targets.append(home / "Desktop" / f"{LAUNCHER_NAME}.lnk")

    for lnk in targets:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        _create_windows_lnk(lnk, cmd_path, home)
        created.append(lnk)

    return created


# ── macOS ────────────────────────────────────────────────────────────────────


def _macos_command_paths(desktop: bool) -> list[Path]:
    home = Path.home()
    paths = [home / "Applications" / f"{LAUNCHER_NAME}.command"]
    if desktop:
        paths.append(home / "Desktop" / f"{LAUNCHER_NAME}.command")
    return paths


def _install_macos(tokens: list[str], desktop: bool) -> list[Path]:
    cmd_line = _posix_command_line(tokens)
    body = f"#!/bin/bash\n# {LAUNCHER_NAME}\nexec {cmd_line} rec\n"

    created: list[Path] = []
    for path in _macos_command_paths(desktop):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
        created.append(path)
    return created


# ── Linux ────────────────────────────────────────────────────────────────────


def _linux_applications_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home) / "applications"


def _linux_desktop_entry(tokens: list[str]) -> str:
    exec_line = f"{_posix_command_line(tokens)} rec"
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={LAUNCHER_NAME}\n"
        "Comment=Start a Scribe recording (auto-transcribes when you stop)\n"
        f"Exec={exec_line}\n"
        "Terminal=true\n"
        "Icon=audio-input-microphone\n"
        "Categories=AudioVideo;Utility;\n"
    )


def _install_linux(tokens: list[str], desktop: bool) -> list[Path]:
    entry = _linux_desktop_entry(tokens)
    created: list[Path] = []

    apps_dir = _linux_applications_dir()
    apps_dir.mkdir(parents=True, exist_ok=True)
    app_file = apps_dir / LINUX_DESKTOP_ID
    app_file.write_text(entry, encoding="utf-8")
    app_file.chmod(0o755)
    created.append(app_file)

    if desktop:
        desk = Path.home() / "Desktop" / LINUX_DESKTOP_ID
        desk.parent.mkdir(parents=True, exist_ok=True)
        desk.write_text(entry, encoding="utf-8")
        desk.chmod(0o755)
        created.append(desk)

    # Best-effort: refresh the application database so the entry shows up promptly.
    updater = shutil.which("update-desktop-database")
    if updater:
        with suppress(Exception):
            subprocess.run(
                [updater, str(apps_dir)],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )

    return created


# ── Public install / remove ──────────────────────────────────────────────────


def install_quick_record_launcher(desktop: bool) -> list[Path]:
    """Install the Quick Record launcher for the current OS. Returns created paths."""
    tokens = resolve_scribe_command()
    if is_windows():
        return _install_windows(tokens, desktop)
    if is_macos():
        return _install_macos(tokens, desktop)
    return _install_linux(tokens, desktop)


def _candidate_launcher_paths() -> list[Path]:
    """All paths the installer may have created on this OS (for removal)."""
    home = Path.home()
    if is_windows():
        return [
            _windows_cmd_path(),
            _windows_start_menu_dir() / f"{LAUNCHER_NAME}.lnk",
            home / "Desktop" / f"{LAUNCHER_NAME}.lnk",
        ]
    if is_macos():
        return [
            home / "Applications" / f"{LAUNCHER_NAME}.command",
            home / "Desktop" / f"{LAUNCHER_NAME}.command",
        ]
    return [
        _linux_applications_dir() / LINUX_DESKTOP_ID,
        home / "Desktop" / LINUX_DESKTOP_ID,
    ]


def remove_quick_record_launcher() -> list[Path]:
    """Remove any installed Quick Record launchers. Returns removed paths."""
    removed: list[Path] = []
    for path in _candidate_launcher_paths():
        try:
            if path.exists():
                path.unlink()
                removed.append(path)
        except OSError:
            # Best-effort cleanup; a locked/permission-denied file is non-fatal.
            continue
    return removed


def _pin_hint() -> str:
    if is_windows():
        return "Find 'Scribe Quick Record' in the Start Menu, then right-click to pin to Start or the taskbar."
    if is_macos():
        return "Open it from ~/Applications (or Launchpad); drag to the Dock to keep it handy."
    return "Find 'Scribe Quick Record' in your applications menu; some desktops need you to mark a Desktop copy as trusted."


def run_shortcut(console: Console, desktop: bool | None, remove: bool) -> None:
    """CLI entry point for ``scribe shortcut`` (UX wrapper around install/remove)."""
    from rich.prompt import Confirm

    from scribe.utils.branding import brand_header_markup

    cprint = console.print

    cprint(brand_header_markup(f"{LAUNCHER_NAME} launcher"))
    cprint()

    if remove:
        removed = remove_quick_record_launcher()
        if removed:
            cprint("[green]Removed launcher:[/green]")
            for p in removed:
                cprint(f"  [dim]{p}[/dim]")
        else:
            cprint("[yellow]No installed launcher found.[/yellow]")
        return

    # Resolve the Desktop choice: explicit flag wins; otherwise offer interactively.
    want_desktop: bool
    if desktop is None:
        interactive = bool(getattr(sys.stdin, "isatty", lambda: False)())
        want_desktop = (
            Confirm.ask("Also add a Desktop shortcut?", default=False) if interactive else False
        )
    else:
        want_desktop = desktop

    try:
        created = install_quick_record_launcher(want_desktop)
    except Exception as e:
        cprint(f"[red]Could not install launcher:[/red] {e}")
        raise SystemExit(1) from e

    cprint("[green]Installed 'Quick Record' launcher:[/green]")
    for p in created:
        cprint(f"  [dim]{p}[/dim]")
    cprint()
    cprint(f"[cyan]{_pin_hint()}[/cyan]")
    cprint("[dim]It runs `scribe rec`. Start talking, then type 'stop' when done.[/dim]")
