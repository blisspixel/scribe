"""
Cross-platform "Quick Record" launcher installer.

Creates a native, icon-bearing launcher that runs ``scribe rec`` so users can start
a recording without opening a terminal first. Designed to be defensive and adaptive:

- Prefers runtime PATH lookup for "scribe" (so shortcuts survive `uv tool install`,
  upgrades, PATH changes, etc.).
- On Windows uses a generated .cmd wrapper (stable location under ~/.scribe) with
  fallbacks, clear errors, and pause so the console never flashes closed.
- The .lnk points at the wrapper (with Scribe icon for pinning).
- Similar wrapper/launcher patterns on macOS and Linux.
- Strong guidance at install time when the resolution at creation looks ephemeral.

Works the same on all three desktop platforms (details in code and README).
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
      1. A ``scribe`` console script on PATH (e.g. ``uv tool install``) -- preferred
         for durable shortcuts because it relies on PATH at *runtime*.
      2. The currently-running entry point, if it looks like a scribe executable.
      3. ``<python> -m scribe`` as a universal fallback.

    Callers (especially shortcut creation) should treat a PATH hit as the
    most adaptive choice and avoid baking ephemeral project/venv paths.
    """
    on_path = shutil.which("scribe")
    if on_path:
        return [on_path]

    if sys.argv and sys.argv[0]:
        arg0 = Path(sys.argv[0])
        if arg0.name.lower().startswith("scribe") and arg0.exists():
            return [str(arg0.resolve())]

    return [sys.executable, "-m", "scribe"]


def _get_scribe_command() -> list[str]:
    """Resolve for embedding. Prefers PATH for adaptive launchers."""
    return resolve_scribe_command()


def _get_launcher_target_and_args() -> tuple[str, list[str]]:
    """For launchers: strongly prefer bare 'scribe' (runtime PATH) for durability.

    Only falls back to full resolved path if 'scribe' is not on PATH at creation.
    This makes the generated launchers (wrappers, .desktop, .app) adapt to the
    user's eventual stable install (uv tool, etc.).
    """
    if shutil.which("scribe"):
        return "scribe", ["rec"]
    tokens = _get_scribe_command()
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


def _windows_pinned_taskbar_path() -> Path:
    """Return the existing per-user taskbar pin location used by Explorer."""
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return (
        Path(appdata)
        / "Microsoft"
        / "Internet Explorer"
        / "Quick Launch"
        / "User Pinned"
        / "TaskBar"
        / f"{LAUNCHER_NAME}.lnk"
    )


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


def _windows_record_wrapper(fallback_exe: str) -> Path:
    """Create (or overwrite) a small .cmd wrapper that is *bulletproof* and adaptive.

    - Prefers the creation-time executable when it still exists.
    - Falls back to bare 'scribe' via PATH when the captured executable moved.
    - Never re-appends 'rec'; always runs "xxx rec".
    - Proper quoting for paths with spaces.
    - Multiple layers of pause and error messages so window NEVER closes without user seeing output.
    - Syntax-safe batch (no risky unquoted drive: expansions in conditions).
    """
    wrapper = Path.home() / ".scribe" / f"{LAUNCHER_NAME}.cmd"
    wrapper.parent.mkdir(parents=True, exist_ok=True)

    # fallback_exe: plain full path WITHOUT any args or surrounding quotes.
    # We quote at execution time to handle spaces in paths (for example, a user profile path).

    # Escape any " in the path for safe "set VAR=..." in batch
    fb_escaped = fallback_exe.replace('"', '""')
    content = (
        "@echo off\r\n"
        "title Scribe Quick Record\r\n"
        "setlocal EnableExtensions\r\n"
        "\r\n"
        "rem === BULLETPROOF Scribe Quick Record launcher ===\r\n"
        "rem Uses the stable executable captured at install time when available.\r\n"
        "rem Falls back to bare 'scribe' from PATH if that executable moved.\r\n"
        "\r\n"
        'set "FALLBACK=' + fb_escaped + '"\r\n'
        "\r\n"
        "rem Prefer explicit fallback (the scribe that was used to create this shortcut) if still valid.\r\n"
        "rem This makes the just-made desktop icon reliable right away.\r\n"
        'if exist "%FALLBACK%" (\r\n'
        '    set "TO_USE=%FALLBACK%"\r\n'
        ") else (\r\n"
        "    where scribe >nul 2>nul\r\n"
        "    if errorlevel 1 (\r\n"
        "        echo [Scribe Quick Record] ERROR: No working scribe found.\r\n"
        "        echo Run 'uv tool install ...' then recreate the shortcut.\r\n"
        "        pause\r\n"
        "        exit /b 1\r\n"
        "    ) else (\r\n"
        '        set "TO_USE=scribe"\r\n'
        "    )\r\n"
        ")\r\n"
        "\r\n"
        "set SCRIBE_FROM_SHORTCUT=1\r\n"
        'if "%TO_USE%"=="scribe" (\r\n'
        "    scribe rec %*\r\n"
        ") else (\r\n"
        '    "%TO_USE%" rec %*\r\n'
        ")\r\n"
        "\r\n"
        "set ERR=%ERRORLEVEL%\r\n"
        "\r\n"
        "echo.\r\n"
        "if %ERR% neq 0 (\r\n"
        "    echo [Exited with code %ERR%]\r\n"
        "    echo Common issues: OBS not running or WebSocket not configured. Try scribe rec --check.\r\n"
        ") else (\r\n"
        "    echo Finished.\r\n"
        ")\r\n"
        "\r\n"
        "echo.\r\n"
        "echo Press any key to close (deliberately kept open).\r\n"
        "pause >nul\r\n"
        "exit /b %ERR%\r\n"
    )
    wrapper.write_text(content, encoding="utf-8", newline="")
    return wrapper


def _is_ephemeral_resolution(resolved: str) -> bool:
    """Heuristic: does this look like a short-lived dev/venv path?"""
    lower = resolved.lower()
    # These are substring markers for detecting ephemeral install paths, not
    # temp-file creation, so S108 (insecure /tmp/ usage) does not apply.
    markers = (".venv", "\\src\\", "/src/", "\\temp\\", "/tmp/", "pip-req-build", "\\.cache\\")  # noqa: S108
    return any(m in lower for m in markers) or resolved.endswith((".py",))


def _install_windows(fallback_exe: str, desktop: bool) -> list[Path]:
    icon = _windows_icon_path()
    home = Path.home()

    # Keep the executable resolution in one stable per-user wrapper. Shortcuts and
    # taskbar pins can keep pointing here while the underlying installation moves.
    wrapper = _windows_record_wrapper(fallback_exe)

    # Target cmd.exe for a normal console window and custom taskbar icon, but run
    # only the stable wrapper. Do not bake a temporary or obsolete scribe path into
    # the .lnk itself.
    cmd_exe = os.environ.get("SYSTEMROOT", r"C:\Windows") + r"\System32\cmd.exe"
    lnk_arguments = f'/d /c ""{wrapper}""'

    locations = [_windows_start_menu_dir() / f"{LAUNCHER_NAME}.lnk"]
    if desktop:
        locations.append(_windows_desktop_dir() / f"{LAUNCHER_NAME}.lnk")
    pinned = _windows_pinned_taskbar_path()
    if pinned.exists():
        locations.append(pinned)

    created: list[Path] = []
    for lnk in locations:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        _create_windows_lnk(lnk, cmd_exe, lnk_arguments, home, icon)
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

    # Use bare "scribe" when possible for runtime PATH adaptability.
    # Embed a small defensive script that tries PATH first then fallback.
    # All embedded paths/args are shell-quoted to prevent word-split or injection
    # if the resolved target contains spaces or metacharacters.
    launch = resources / "launch.command"
    fallback_exec = " ".join(shlex.quote(t) for t in [target, *args])
    launch_content = f"""#!/bin/bash
set -e

# === Scribe Quick Record (macOS .app launcher) ===
# Prefers bare 'scribe' from PATH at runtime (uv tool installs, updates survive).
if command -v scribe >/dev/null 2>&1; then
    exec scribe rec
fi

# Fallback to the resolution captured at shortcut creation time (always quoted).
exec {fallback_exec}
"""

    launch.write_text(launch_content, encoding="utf-8")
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
    # Prefer bare "scribe" for PATH adaptability at runtime.
    # The .desktop Terminal=true will resolve via shell PATH.
    if target == "scribe" or shutil.which("scribe"):
        exec_line = "scribe rec"
    else:
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


def _create_linux_record_wrapper(fallback: list[str] | None = None) -> Path:
    """Create an adaptive bash wrapper for Linux (defensive, like Windows .cmd).

    Prefers 'scribe' on PATH at runtime. Embeds creation-time fallback when needed.
    All paths properly quoted.
    """
    wrapper = Path.home() / ".scribe" / f"{LAUNCHER_NAME}.sh"
    wrapper.parent.mkdir(parents=True, exist_ok=True)

    if fallback:
        fb_exec = " ".join(shlex.quote(t) for t in fallback)
        fallback_block = f"""if ! command -v scribe >/dev/null 2>&1; then
    echo "[Scribe Quick Record] 'scribe' not found on PATH; using creation-time fallback."
    exec {fb_exec} "$@"
fi
"""
    else:
        fallback_block = """if ! command -v scribe >/dev/null 2>&1; then
    echo "[Scribe Quick Record] 'scribe' not found on PATH."
    echo ""
    echo "Recommended (makes the launcher durable):"
    echo "  uv tool install --python 3.12 git+https://github.com/blisspixel/scribe.git"
    echo "  # ensure ~/.local/bin or equivalent is in PATH"
    echo ""
    echo "Then re-run the launcher or 'scribe shortcut'."
    echo ""
    read -p "Press Enter to close..."
    exit 1
fi
"""

    content = f"""#!/bin/bash
set +e

# === Scribe Quick Record (adaptive launcher for Linux) ===
# Prefers "scribe" from PATH (uv tool, etc.) at runtime.

if command -v scribe >/dev/null 2>&1; then
    exec scribe rec "$@"
fi

{fallback_block}

# If we reach here without exec, something unexpected; try bare anyway.
exec scribe rec "$@"
"""
    wrapper.write_text(content, encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def _install_linux(target: str, args: list[str], desktop: bool) -> list[Path]:
    icon = _linux_icon_path()
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(_packaged_icon_bytes("scribe.png"))

    # For robustness, use an adaptive wrapper script (like Windows)
    # Pass the creation tokens so wrapper can embed fallback when bare scribe not on PATH.
    fb_tokens = [target, *args] if target != "scribe" else None
    wrapper = _create_linux_record_wrapper(fb_tokens)
    # Exec the wrapper (it handles args)
    entry = _linux_desktop_entry(str(wrapper), [], icon)  # wrapper takes no extra target args
    # But to support name arg via .desktop edit, we can adjust; for now bare wrapper is fine
    # Simpler: keep using bare if possible, but since we generated wrapper, point to it.
    entry = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={LAUNCHER_NAME}\n"
        "Comment=Start a Scribe recording (auto-transcribes when you stop)\n"
        f"Exec={shlex.quote(str(wrapper))}\n"
        "Terminal=true\n"
        f"Icon={icon}\n"
        "Categories=AudioVideo;Utility;\n"
    )

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
    launcher_target, _ = _get_launcher_target_and_args()
    if is_windows():
        # Pass the resolved *exe* (without args) as fallback for the wrapper.
        # The wrapper always appends "rec" itself with proper quoting.
        if launcher_target == "scribe":
            fb_tokens = _get_scribe_command()
            fb_exe = fb_tokens[0]
        else:
            fb_exe = launcher_target
        return _install_windows(fb_exe, desktop)
    target, args = launcher_target, ["rec"]  # for other platforms
    if is_macos():
        return _install_macos(target, args, desktop)
    return _install_linux(target, args, desktop)


def _candidate_launcher_paths() -> list[Path]:
    """All paths the installer may have created on this OS (for removal).

    Includes stable wrappers and legacy artifacts so removal cleans up every launcher.
    """
    home = Path.home()
    if is_windows():
        return [
            home / ".scribe" / f"{LAUNCHER_NAME}.cmd",  # stable wrapper
            _windows_start_menu_dir() / f"{LAUNCHER_NAME}.lnk",
            _windows_desktop_dir() / f"{LAUNCHER_NAME}.lnk",
            _windows_pinned_taskbar_path(),
            home / "Desktop" / f"{LAUNCHER_NAME}.lnk",  # legacy (non-redirected)
        ]
    if is_macos():
        return [
            home / "Applications" / MACOS_APP_NAME,
            home / "Desktop" / MACOS_APP_NAME,
            home / "Applications" / f"{LAUNCHER_NAME}.command",  # legacy
            home / "Desktop" / f"{LAUNCHER_NAME}.command",  # legacy
            home / ".scribe" / f"{LAUNCHER_NAME}.command",  # staged adaptive
        ]
    return [
        _linux_applications_dir() / LINUX_DESKTOP_ID,
        home / "Desktop" / LINUX_DESKTOP_ID,
        home / ".scribe" / f"{LAUNCHER_NAME}.sh",  # adaptive wrapper
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
        launcher_target, _ = _get_launcher_target_and_args()
        # For advice, always look at the actual resolved (may be full path)
        resolved_tokens = _get_scribe_command()
        resolved_for_advice = resolved_tokens[0] if resolved_tokens else launcher_target
        created = install_quick_record_launcher(want_desktop)
    except Exception as e:
        cprint(f"[red]Could not install launcher:[/red] {e}")
        raise SystemExit(1) from e

    cprint("[green]Installed 'Quick Record' launcher:[/green]")
    for p in created:
        cprint(f"  [dim]{p}[/dim]")
    cprint()

    # Defensive guidance + taskbar QOL
    if _is_ephemeral_resolution(resolved_for_advice):
        cprint(
            "[yellow]Note:[/yellow] The resolved 'scribe' at creation time looks like a "
            "project/venv path. For a shortcut that 'just works' after updates, "
            "install globally first:\n"
            "  uv tool install --python 3.12 git+https://github.com/blisspixel/scribe.git\n"
            "  uv tool update-shell\n"
            "Then re-run `scribe shortcut --desktop`."
        )
        cprint()
    else:
        cprint(
            "[dim]Tip: For the most durable launcher, install via "
            "`uv tool install` (or equivalent) so 'scribe' is reliably on PATH.[/dim]"
        )
        cprint()

    cprint(f"[cyan]{_pin_hint()}[/cyan]")
    cprint("[dim]It runs `scribe rec`. Type `s` or `stop`, then press Enter.[/dim]")

    if is_windows():
        cprint()
        cprint(
            "[dim]Taskbar tip: drag the desktop .lnk to taskbar. If icon is generic after pinning,[/dim]"
        )
        cprint(
            "[dim]  right-click pinned item -> Properties -> Change Icon -> pick ~/.scribe/scribe.ico[/dim]"
        )
