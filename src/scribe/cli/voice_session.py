"""``scribe voice`` commands for the experimental Omarchy control plane.

These commands talk to the one resident ``VoiceTrayService``. They do not load
a second model. Linux voice stays experimental until a live Omarchy record
covers microphone selection, focus, insertion, cancellation, device loss, and
recovery.
"""

from __future__ import annotations

import importlib.util
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

import typer
from rich.console import Console

from scribe.utils.logging import console

voice_app = typer.Typer(
    name="voice",
    help="Experimental local voice controls. Linux use is not hardware-validated.",
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
)


def _spawn_owner() -> None:
    """Start one detached owner. The resident lock rejects a second process."""
    command = [sys.executable, "-m", "scribe", "voice", "serve"]
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(
            subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
        )
        subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            creationflags=creationflags,
        )
        return
    subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        start_new_session=True,
    )


def _transact(command: str, *, autostart: bool) -> dict[str, object]:
    from scribe.voice.control import ControlError, transact

    try:
        return transact(command, spawn=_spawn_owner if autostart else None)
    except ControlError as error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1) from error


def _print_response(payload: dict[str, object]) -> None:
    state = payload.get("state", "")
    status = payload.get("status", "")
    outcome = payload.get("outcome", "")
    transcript = payload.get("transcript", "")
    error = payload.get("error")
    parts = [str(part) for part in (outcome, state, status) if part]
    line = " ".join(parts) if parts else "ok" if payload.get("ok") else "failed"
    console.print(line)
    if transcript:
        preview = str(transcript)
        console.print(preview if len(preview) <= 240 else preview[:237] + "...")
    if error:
        console.print(f"[red]{error}[/red]")
    console.print("[dim]Experimental. This command did not validate Omarchy hardware.[/dim]")


def _run_client(command: str, *, autostart: bool) -> None:
    payload = _transact(command, autostart=autostart)
    _print_response(payload)
    if not payload.get("ok"):
        raise typer.Exit(1)


@voice_app.command("serve")
def serve_command(
    no_preload: bool = typer.Option(
        False,
        "--no-preload",
        help="Do not warm the local dictation model at startup",
    ),
) -> None:
    """Run the single local voice owner for compositor commands.

    Dictation is stored until an explicit copy, insert, or read. The microphone
    stays off until a dictate command. Cloud transcription is not available here.
    """
    raise typer.Exit(run_serve(console, preload=not no_preload))


@voice_app.command("dictate")
def dictate_command() -> None:
    """Start or finish dictation on the running owner."""
    _run_client("DICTATE", autostart=True)


@voice_app.command("cancel")
def cancel_command() -> None:
    """Discard the current recording or in-flight transcription."""
    _run_client("CANCEL", autostart=True)


@voice_app.command("copy")
def copy_command() -> None:
    """Copy the last transcript without sending keystrokes."""
    _run_client("COPY", autostart=True)


@voice_app.command("insert")
def insert_command() -> None:
    """Insert the last transcript because this command asked for it."""
    _run_client("INSERT", autostart=True)


@voice_app.command("read")
def read_command() -> None:
    """Read the last transcript aloud with the local voice."""
    _run_client("READ", autostart=True)


@voice_app.command("status")
def status_command() -> None:
    """Show the owner state. This starts the owner when it is not running."""
    _run_client("STATUS", autostart=True)


@voice_app.command("stop")
def stop_command() -> None:
    """Stop the resident owner when it is running."""
    _run_client("STOP", autostart=False)


@voice_app.command("overlay")
def overlay_command(
    once: bool = typer.Option(False, "--once", help="Print one panel and exit"),
) -> None:
    """Show the terminal voice panel. The panel does not own the microphone."""
    from scribe.voice.overlay import run_overlay

    def fetch() -> dict[str, object]:
        return _transact("STATUS", autostart=True)

    def send(command: str) -> object:
        return _transact(command, autostart=True)

    raise typer.Exit(run_overlay(console, fetch, send, once=once))


@voice_app.command("check")
def check_command() -> None:
    """Report install readiness. A success exit does not validate hardware."""
    raise typer.Exit(run_voice_check(console))


@voice_app.command("omarchy-install")
def omarchy_install_command(
    force: bool = typer.Option(
        False,
        "--force",
        help="Write the Hyprland marker blocks even when this is not Linux",
    ),
) -> None:
    """Add Scribe's marked Hyprland binds and autostart. Existing lines stay."""
    raise typer.Exit(run_omarchy_install(console, force=force))


@voice_app.command("omarchy-remove")
def omarchy_remove_command(
    force: bool = typer.Option(
        False,
        "--force",
        help="Edit the Hyprland marker blocks even when this is not Linux",
    ),
) -> None:
    """Remove only Scribe's marked Hyprland blocks. User data is kept."""
    raise typer.Exit(run_omarchy_remove(console, force=force))


def run_serve(console: Console, *, preload: bool) -> int:
    """Own resident voice until stop. A second launch exits without a new model."""
    from scribe.voice.control import ControlServer, control_token_path, write_token
    from scribe.voice.instance import TrayInstanceLock
    from scribe.voice.service import VoiceTrayService
    from scribe.voice.settings import resolve_tray_settings
    from scribe.voice.tray import _configure_resident_logging

    printer = console
    instance_lock = TrayInstanceLock()
    try:
        acquired = instance_lock.acquire()
    except OSError as error:
        printer.print(f"[red]Could not protect resident voice from duplicates:[/red] {error}")
        return 1
    if not acquired:
        owner = instance_lock.owner
        description = owner.description if owner is not None else "another process"
        printer.print(
            f"[yellow]Scribe Voice is already running ({description}).[/yellow] "
            "This launch will exit without loading another model."
        )
        return 0

    server: ControlServer | None = None
    service: VoiceTrayService | None = None
    try:
        _configure_resident_logging(printer)
        settings = resolve_tray_settings(preload=preload)
        service = VoiceTrayService(settings, printer, explicit_insert=True)
        service.set_mic_announcer(_announce_microphone)
        service.set_text_inserter(_hyprland_inserter())
        if not service.start_session(preload_model=settings.preload_model):
            return 1
        token = secrets.token_urlsafe(32)
        token_path = control_token_path()
        write_token(token_path, token)
        server = ControlServer(service, token_path.with_name("voice-control.sock"), token)
        server.start()
        instance_lock.retain_until_process_exit()
        printer.print("[cyan]Scribe voice owner is listening.[/cyan]")
        printer.print(
            "[dim]Experimental local voice. The microphone stays off until dictate. "
            "Cloud transcription is not used. Ctrl+C stops this owner.[/dim]"
        )
        while service.running:
            time.sleep(0.25)
        return 0 if service.stop() else 1
    except KeyboardInterrupt:
        if service is None:
            return 0
        return 0 if service.stop() else 1
    finally:
        if server is not None:
            server.close()
        if service is not None and service.running:
            service.stop()


def run_voice_check(console: Console) -> int:
    """Print the readiness report. Missing sounddevice or Python is a failure."""
    from scribe.voice.omarchy import build_voice_check

    config_dir = _hypr_config_dir()
    bindings = _read_if_file(config_dir / "bindings.lua")
    autostart = _read_if_file(config_dir / "autostart.lua")
    report = build_voice_check(
        python_version=sys.version_info[:2],
        sounddevice_available=importlib.util.find_spec("sounddevice") is not None,
        omarchy_detected=bool(os.environ.get("OMARCHY_PATH"))
        or Path("/usr/share/omarchy").exists(),
        bindings_text=bindings,
        autostart_text=autostart,
    )
    for line in report.lines:
        console.print(line)
    if not report.python_ok or not report.sounddevice_available:
        return 1
    return 0


def run_omarchy_install(console: Console, *, force: bool) -> int:
    """Install marker blocks on Linux, or anywhere when ``force`` is set."""
    if sys.platform != "linux" and not force:
        console.print(
            "[yellow]omarchy-install edits Hyprland files on Linux.[/yellow] "
            "Re-run with --force to write the marker blocks on this machine."
        )
        return 2
    from scribe.voice.omarchy import install_voice_files

    bindings, autostart = install_voice_files(_hypr_config_dir())
    console.print(f"[green]Updated[/green] {bindings}")
    console.print(f"[green]Updated[/green] {autostart}")
    console.print(
        "[dim]Confirm the chords with Super+K, then run hyprctl reload and "
        "hyprctl configerrors. This install is not a hardware validation.[/dim]"
    )
    return 0


def run_omarchy_remove(console: Console, *, force: bool) -> int:
    """Remove marker blocks and leave the rest of the Hyprland files in place."""
    if sys.platform != "linux" and not force:
        console.print(
            "[yellow]omarchy-remove edits Hyprland files on Linux.[/yellow] "
            "Re-run with --force to edit the marker blocks on this machine."
        )
        return 2
    from scribe.voice.omarchy import remove_voice_files

    bindings, autostart = remove_voice_files(_hypr_config_dir())
    console.print(f"[green]Removed Scribe voice markers from[/green] {bindings}")
    console.print(f"[green]Removed Scribe voice markers from[/green] {autostart}")
    console.print("[dim]~/.scribe user data was left in place.[/dim]")
    return 0


def _hypr_config_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else Path.home() / ".config"
    return base / "hypr"


def _read_if_file(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def _announce_microphone(active: bool) -> None:
    from scribe.voice.control import restrict_private

    path = Path.home() / ".scribe" / "voice-status.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("MICROPHONE ON\n" if active else "MICROPHONE OFF\n", encoding="utf-8")
    restrict_private(path)
    message = "Scribe MICROPHONE ON" if active else "Scribe microphone off"
    urgency = "critical" if active else "low"
    for command in (
        ["omarchy-notification-send", "-u", urgency, message],
        ["notify-send", "-u", urgency, "Scribe", message],
    ):
        try:
            completed = subprocess.run(command, check=False, capture_output=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0:
            return


def _hyprland_inserter() -> Callable[[str], str]:
    from scribe.cli.voice import clipboard_copy
    from scribe.voice.wayland_paste import make_hyprland_inserter, read_hypr_window_class

    def run(argv: list[str]) -> int:
        try:
            completed = subprocess.run(argv, check=False, capture_output=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            return 1
        return int(completed.returncode)

    def run_capture(argv: list[str]) -> tuple[int, str]:
        try:
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return 1, ""
        return int(completed.returncode), completed.stdout

    return make_hyprland_inserter(
        copy=clipboard_copy,
        run=run,
        read_class=lambda: read_hypr_window_class(run_capture),
        sleep=time.sleep,
    )
