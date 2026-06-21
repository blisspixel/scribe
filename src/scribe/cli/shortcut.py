"""
Cross-platform "Quick Record" launcher installer.

Creates a native, icon-bearing launcher that runs ``scribe rec`` so users can start
a recording without opening a terminal. It replaces the old hand-made Windows
``.bat`` workaround and works the same way on all three desktop platforms:

- Windows: a Start Menu ``.lnk`` pointing straight at ``scribe.exe`` (so Windows
  allows pinning it to the taskbar), with the Scribe ``.ico``.
- macOS: a small ``.app`` bundle in ``~/Applications`` that carries the ``.icns``
  and opens Terminal to run ``scribe rec`` (so it shows in Launchpad and the Dock).
- Linux: an XDG ``.desktop`` entry with the Scribe ``.png`` icon.

The launcher targets whatever ``scribe`` resolves to at install time (preferring a
``scribe`` on PATH, e.g. one installed via ``uv tool install``), falling back to
``python -m scribe`` so it keeps working even when no console script is on PATH.
"""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from contextlib import suppress
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING

from scribe.utils.platform import is_macos, is_windows

if TYPE_CHECKING:
    from rich.console import Console

LAUNCHER_NAME = "Scribe Quick Record"
LINUX_DESKTOP_ID = "scribe-quick-record.desktop"
MACOS_APP_NAME = f"{LAUNCHER_NAME}.app"


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


def _target_and_args() -> tuple[str, list[str]]:
    """Split the resolved command into (executable, args) with ``rec`` appended."""
    tokens = resolve_scribe_command()
    return tokens[0], [*tokens[1:], "rec"]


def _packaged_icon_bytes(name: str) -> bytes:
    """Read a bundled icon (scribe.ico / scribe.icns / scribe.png) from the package."""
    return (files("scribe") / "assets" / "icons" / name).read_bytes()


# ── Windows ──────────────────────────────────────────────────────────────────


def _windows_start_menu_dir() -> Path:
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def _windows_desktop_dir() -> Path:
    """The real Desktop folder, honoring OneDrive/known-folder redirection.

    ``~/Desktop`` is wrong when the Desktop is redirected into OneDrive, so read the
    actual location from the per-user shell-folders registry key and expand it.
    """
    if sys.platform == "win32":
        import winreg

        with suppress(OSError):
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "Desktop")
                return Path(os.path.expandvars(value))
    return Path.home() / "Desktop"


def _windows_icon_path() -> Path:
    """Copy the .ico to a stable per-user location and return it.

    The shortcut references this path, so it survives even if the install that
    provided the bundled icon is moved or upgraded.
    """
    dest = Path.home() / ".scribe" / "scribe.ico"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_packaged_icon_bytes("scribe.ico"))
    return dest


def _create_windows_lnk(
    lnk_path: Path,
    target: str,
    arguments: str,
    workdir: Path,
    icon: Path,
    *,
    window_style: int = 1,
    description: str = "Start a Scribe recording",
) -> None:
    """Create a Windows .lnk via WScript.Shell (no pywin32 dependency).

    ``window_style`` is the WScript Shortcut WindowStyle (1 = normal, 7 = minimized
    - used for the resident tray so it does not flash a console). Isolated so tests
    can monkeypatch it without invoking PowerShell.
    """

    def ps(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    script = (
        "$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut({ps(str(lnk_path))}); "
        f"$s.TargetPath = {ps(target)}; "
        f"$s.Arguments = {ps(arguments)}; "
        f"$s.WorkingDirectory = {ps(str(workdir))}; "
        f"$s.IconLocation = {ps(str(icon) + ',0')}; "
        f"$s.WindowStyle = {int(window_style)}; "
        f"$s.Description = {ps(description)}; "
        "$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )


def _install_windows(target: str, args: list[str], desktop: bool) -> list[Path]:
    icon = _windows_icon_path()
    arguments = subprocess.list2cmdline(args)
    home = Path.home()

    locations = [_windows_start_menu_dir() / f"{LAUNCHER_NAME}.lnk"]
    if desktop:
        locations.append(_windows_desktop_dir() / f"{LAUNCHER_NAME}.lnk")

    created: list[Path] = []
    for lnk in locations:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        _create_windows_lnk(lnk, target, arguments, home, icon)
        created.append(lnk)
    return created


# ── macOS ────────────────────────────────────────────────────────────────────


def _macos_app_paths(desktop: bool) -> list[Path]:
    home = Path.home()
    paths = [home / "Applications" / MACOS_APP_NAME]
    if desktop:
        paths.append(home / "Desktop" / MACOS_APP_NAME)
    return paths


def _write_macos_app(app: Path, target: str, args: list[str]) -> None:
    """Write a minimal .app bundle that opens Terminal to run the command.

    Double-clicking a plain script gives no icon, and a GUI-launched binary has no
    console for the interactive 'stop'. A tiny bundle solves both: it carries the
    icon and launches an interactive Terminal session via a helper command file.
    """
    contents = app / "Contents"
    macos_dir = contents / "MacOS"
    resources = contents / "Resources"
    for d in (macos_dir, resources):
        d.mkdir(parents=True, exist_ok=True)

    resources.joinpath("scribe.icns").write_bytes(_packaged_icon_bytes("scribe.icns"))

    command_line = " ".join(shlex.quote(t) for t in [target, *args])
    launch = resources / "launch.command"
    launch.write_text(f"#!/bin/bash\nexec {command_line}\n", encoding="utf-8")
    launch.chmod(0o755)

    run = macos_dir / "run"
    run.write_text(
        '#!/bin/bash\nDIR="$(cd "$(dirname "$0")" && pwd)"\n'
        'exec open -a Terminal "$DIR/../Resources/launch.command"\n',
        encoding="utf-8",
    )
    run.chmod(0o755)

    info = {
        "CFBundleName": LAUNCHER_NAME,
        "CFBundleDisplayName": LAUNCHER_NAME,
        "CFBundleIdentifier": "io.pueo.scribe.quickrecord",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "run",
        "CFBundleIconFile": "scribe.icns",
    }
    with contents.joinpath("Info.plist").open("wb") as f:
        plistlib.dump(info, f)


def _install_macos(target: str, args: list[str], desktop: bool) -> list[Path]:
    created: list[Path] = []
    for app in _macos_app_paths(desktop):
        if app.exists():
            shutil.rmtree(app, ignore_errors=True)
        _write_macos_app(app, target, args)
        created.append(app)
    return created


# ── Linux ────────────────────────────────────────────────────────────────────


def _linux_applications_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home) / "applications"


def _linux_icon_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home) / "icons" / "scribe.png"


def _linux_desktop_entry(target: str, args: list[str], icon: Path) -> str:
    exec_line = " ".join(shlex.quote(t) for t in [target, *args])
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={LAUNCHER_NAME}\n"
        "Comment=Start a Scribe recording (auto-transcribes when you stop)\n"
        f"Exec={exec_line}\n"
        "Terminal=true\n"
        f"Icon={icon}\n"
        "Categories=AudioVideo;Utility;\n"
    )


def _install_linux(target: str, args: list[str], desktop: bool) -> list[Path]:
    icon = _linux_icon_path()
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(_packaged_icon_bytes("scribe.png"))

    entry = _linux_desktop_entry(target, args, icon)
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
    target, args = _target_and_args()
    if is_windows():
        return _install_windows(target, args, desktop)
    if is_macos():
        return _install_macos(target, args, desktop)
    return _install_linux(target, args, desktop)


def _candidate_launcher_paths() -> list[Path]:
    """All paths the installer may have created on this OS (for removal).

    Includes legacy artifacts (the old .cmd / .command) so an upgrade cleans them up.
    """
    home = Path.home()
    if is_windows():
        return [
            home / ".scribe" / f"{LAUNCHER_NAME}.cmd",  # legacy
            _windows_start_menu_dir() / f"{LAUNCHER_NAME}.lnk",
            _windows_desktop_dir() / f"{LAUNCHER_NAME}.lnk",
            home / "Desktop" / f"{LAUNCHER_NAME}.lnk",  # legacy (non-redirected)
        ]
    if is_macos():
        return [
            home / "Applications" / MACOS_APP_NAME,
            home / "Desktop" / MACOS_APP_NAME,
            home / "Applications" / f"{LAUNCHER_NAME}.command",  # legacy
            home / "Desktop" / f"{LAUNCHER_NAME}.command",  # legacy
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
            if path.is_dir():
                shutil.rmtree(path)
                removed.append(path)
            elif path.exists():
                path.unlink()
                removed.append(path)
        except OSError:
            continue
    return removed


def _pin_hint() -> str:
    if is_windows():
        return (
            "Find 'Scribe Quick Record' in the Start Menu or on the Desktop. "
            "To put it on the taskbar, drag the Desktop icon onto the taskbar."
        )
    if is_macos():
        return "Open it from ~/Applications or Launchpad, then keep it in the Dock."
    return "Find 'Scribe Quick Record' in your applications menu."


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

    if desktop is None:
        interactive = bool(getattr(sys.stdin, "isatty", lambda: False)())
        want_desktop = (
            Confirm.ask("Also add a Desktop shortcut?", default=True) if interactive else False
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
