"""Terminal overlay for the Omarchy voice owner.

The panel polls the resident service. It does not open the microphone or load
a model. Rich is the guaranteed surface because Foot is Omarchy's default
terminal. A separate GTK or Quickshell window is not part of this path.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text

_LOCAL_KEYS = {
    "d": "DICTATE",
    "x": "CANCEL",
    "y": "COPY",
    "i": "INSERT",
    "a": "READ",
}


def render_overlay(snapshot: Mapping[str, Any]) -> Panel:
    """Build the voice panel for one status snapshot."""
    state = str(snapshot.get("state") or "unknown")
    recording = bool(snapshot.get("recording")) or state == "recording"
    status = str(snapshot.get("status") or state)
    transcript = str(snapshot.get("transcript") or "").strip()
    error = snapshot.get("error")
    if recording:
        banner = Text(" MICROPHONE ON ", style="bold white on red")
        border = "red"
    elif state == "transcribing":
        banner = Text(" PROCESSING. Microphone is off. ", style="bold black on yellow")
        border = "yellow"
    elif state == "speaking":
        banner = Text(" READING ALOUD. Microphone is off. ", style="bold white on blue")
        border = "blue"
    elif state == "error":
        banner = Text(" ERROR. Microphone is off. ", style="bold white on red")
        border = "red"
    else:
        banner = Text(" microphone off ", style="bold white on green")
        border = "green"

    preview = transcript if transcript else "(no transcript yet)"
    if len(preview) > 500:
        preview = preview[:497] + "..."
    rows: list[Any] = [
        Align.center(banner),
        Text(""),
        Text(status, style="bold"),
        Text(preview),
    ]
    if error:
        rows.append(Text(str(error), style="red"))
    rows.extend(
        [
            Text(""),
            Text("Compositor chords, if installed and still free:"),
            Text("  Super+Alt+D dictate    Super+Alt+Shift+D cancel"),
            Text("  Super+Alt+Y copy       Super+Alt+I insert"),
            Text("  Super+Alt+A read       Super+Alt+O this overlay"),
            Text("This window: d dictate, x cancel, y copy, i insert, a read, q close"),
            Text(
                "Experimental local voice. This panel is not a hardware validation.",
                style="dim",
            ),
        ]
    )
    return Panel(Group(*rows), title="Scribe voice", border_style=border, padding=(1, 2))


def overlay_plain_text(snapshot: Mapping[str, Any], *, width: int = 78) -> str:
    """Render one panel through Rich and return the plain terminal text."""
    console = Console(width=width, record=True, force_terminal=True, color_system=None)
    console.print(render_overlay(snapshot))
    return console.export_text()


def run_overlay(
    console: Console,
    fetch_status: Callable[[], Mapping[str, Any]],
    send_command: Callable[[str], object],
    *,
    once: bool = False,
    sleep: Callable[[float], None] = time.sleep,
    read_key: Callable[[], str | None] | None = None,
) -> int:
    """Refresh the overlay until the user closes it. ``once`` prints a single frame."""

    def frame() -> Panel:
        try:
            snapshot = fetch_status()
        except Exception as error:
            snapshot = {
                "state": "offline",
                "status": f"Resident voice is not running ({error})",
                "recording": False,
                "transcript": "",
                "error": str(error),
            }
        return render_overlay(snapshot)

    if once or not console.is_terminal:
        console.print(frame())
        if not once and not console.is_terminal:
            console.print(
                "[dim]Overlay input needs a terminal. Compositor chords still work.[/dim]"
            )
        return 0

    from rich.live import Live

    key_reader = read_key or _read_key
    with Live(frame(), console=console, screen=True, refresh_per_second=4) as live:
        while True:
            sleep(0.25)
            key = key_reader()
            if key == "q":
                return 0
            command = _LOCAL_KEYS.get(key or "")
            if command is not None:
                try:
                    send_command(command)
                except Exception as error:
                    console.print(f"[red]Voice command failed:[/red] {error}")
            live.update(frame())


def _read_key() -> str | None:
    """Return one lowercase key when stdin has one waiting, else None."""
    import sys

    if not sys.stdin.isatty():
        return None
    if sys.platform == "win32":
        import msvcrt

        if not msvcrt.kbhit():
            return None
        value = msvcrt.getwch()
        return value.lower() if value else None
    else:
        import select

        readable, _writable, _errors = select.select([sys.stdin], [], [], 0)
        if not readable:
            return None
        value = sys.stdin.read(1)
        return value.lower() if value else None
