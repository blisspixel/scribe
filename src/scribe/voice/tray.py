"""Tray and terminal runners for the resident voice service."""

from __future__ import annotations

import time
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scribe.utils.branding import brand_header_markup
from scribe.voice.service import VoiceTrayService, dependency_report, missing_dependency_packages
from scribe.voice.settings import TraySettings

if TYPE_CHECKING:
    from rich.console import Console


def packaged_icon_path() -> Path:
    """Return the bundled PNG icon path for the tray."""
    return Path(str(files("scribe") / "assets" / "icons" / "scribe.png"))


def run_tray_check(console: Console, settings: TraySettings, *, include_tray: bool) -> int:
    """Print dependency and configuration diagnostics without starting hotkeys."""
    console.print(brand_header_markup("scribe voice tray"))
    console.print()
    for status in dependency_report(include_tray=include_tray):
        marker = "ok" if status.available else "missing"
        style = "green" if status.available else "red"
        console.print(
            f"[{style}]{marker:7}[/{style}] {status.dependency.package} "
            f"[dim]- {status.dependency.purpose}[/dim]"
        )

    console.print()
    console.print(f"[cyan]profile[/cyan] {settings.profile}")
    console.print(f"[cyan]dictate[/cyan] {settings.dictate_hotkey}")
    console.print(f"[cyan]read[/cyan] {settings.read_hotkey}")
    console.print(f"[cyan]inject[/cyan] {settings.inject}")

    missing = missing_dependency_packages(include_tray=include_tray)
    if missing:
        console.print()
        console.print(
            "[yellow]Install missing tray packages with:[/yellow]\n"
            "  uv sync --extra tray --group dev\n"
            'or for an installed package: pip install "scribe[tray]"',
            markup=False,
        )
        return 1
    return 0


def run_tray(console: Console, settings: TraySettings, *, no_tray: bool) -> int:  # pragma: no cover
    """Run the resident voice utility as a tray icon or terminal fallback."""
    if no_tray:
        return _run_no_tray(console, settings)
    missing = missing_dependency_packages(include_tray=True)
    if missing:
        console.print(f"[red]Missing tray packages:[/red] {', '.join(missing)}")
        console.print('Install them with `pip install "scribe[tray]"` or `uv sync --extra tray`.')
        return 1

    try:
        import pystray
        from PIL import Image
    except ImportError:
        console.print('Install tray support with `pip install "scribe[tray]"`.')
        return 1

    try:
        image = Image.open(packaged_icon_path())
    except Exception as e:
        console.print(f"[red]Could not load tray icon:[/red] {e}")
        return 1

    service = VoiceTrayService(settings, console)
    if not service.start_hotkeys(preload_model=settings.preload_model):
        return 1

    icon = pystray.Icon("scribe-voice", image, "Scribe Voice")

    def update_menu(_state: object) -> None:
        icon.title = f"Scribe Voice - {service.status_text}"
        icon.update_menu()

    def pause_resume(_icon: object, _item: object) -> None:
        service.toggle_pause()
        update_menu(service.state)

    def read_now(_icon: object, _item: object) -> None:
        service.read_selection_now()
        update_menu(service.state)

    def quit_icon(icon_obj: Any, _item: object) -> None:
        service.stop()
        icon_obj.stop()

    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda _item: f"Status: {service.status_text}", None, enabled=False),
        pystray.MenuItem(
            lambda _item: "Resume hotkeys" if service.paused else "Pause hotkeys",
            pause_resume,
        ),
        pystray.MenuItem("Read selection now", read_now),
        pystray.MenuItem("Quit Scribe Voice", quit_icon),
    )
    service.add_status_callback(update_menu)
    console.print("[green]Scribe Voice is running in the tray.[/green]")
    console.print(
        f"[dim]Hold {settings.dictate_hotkey.upper()} to dictate. "
        f"Press {settings.read_hotkey.upper()} to read selected text.[/dim]"
    )
    try:
        icon.run()
        return 0
    except Exception as e:
        console.print(f"[red]Tray backend stopped unexpectedly:[/red] {e}")
        return 1
    finally:
        service.stop()


def _run_no_tray(console: Console, settings: TraySettings) -> int:  # pragma: no cover
    service = VoiceTrayService(settings, console)
    if not service.start_hotkeys(preload_model=settings.preload_model):
        return 1

    console.print(brand_header_markup("scribe voice"))
    console.print()
    console.print("[green]Resident voice hotkeys are active.[/green]")
    console.print(
        f"[cyan]Dictate:[/cyan] hold {settings.dictate_hotkey.upper()}, speak, release to type."
    )
    console.print(f"[cyan]Read:[/cyan] select text and press {settings.read_hotkey.upper()}.")
    console.print("[dim]Press Ctrl+C in this terminal to quit.[/dim]")

    try:
        while service.running:
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
    return 0
