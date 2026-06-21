"""Tray and terminal runners for the resident voice service."""

from __future__ import annotations

import os
import platform
import time
from contextlib import suppress
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scribe.utils.branding import brand_header_markup
from scribe.voice.service import (
    VoiceTrayService,
    dependency_report,
    missing_dependency_packages,
    resident_voice_advisories,
)
from scribe.voice.settings import TraySettings

if TYPE_CHECKING:
    from rich.console import Console


def packaged_icon_path() -> Path:
    """Return the bundled PNG icon path for the tray."""
    return Path(str(files("scribe") / "assets" / "icons" / "scribe.png"))


def _await_model_ready(console: Console, service: VoiceTrayService) -> bool:  # pragma: no cover
    """Block with a live spinner until a preloaded model is ready.

    Returns True when the model is ready, False if loading failed. A true percent
    is not available for a weight load into VRAM (it is a few-second load once the
    model is cached, not a long download), so we show an elapsed-time spinner; the
    first-ever download still prints real percentages via Hugging Face.
    """
    import time

    start = time.monotonic()
    if service.is_model_loading():
        with console.status("[cyan]Loading voice model...[/cyan]", spinner="dots") as status:
            while service.is_model_loading():
                status.update(
                    f"[cyan]Loading voice model... {time.monotonic() - start:.0f}s[/cyan] "
                    "[dim](first run downloads it; later runs just warm it)[/dim]"
                )
                time.sleep(0.1)
    if service.state == "error":
        console.print(f"[red]Model load failed:[/red] {service.error_message}")
        return False
    return True


def hotkey_hints(settings: TraySettings) -> tuple[str, str]:
    """Return (dictate, read) one-line hints worded for the activation mode."""
    dictate_key = settings.dictate_hotkey.upper()
    read_key = settings.read_hotkey.upper()
    if settings.activation == "toggle":
        dictate = f"Tap {dictate_key} to start dictation, tap again to insert."
    else:
        dictate = f"Hold {dictate_key} to dictate, release to insert."
    read = f"Tap {read_key} to read the selection, tap again to stop."
    return dictate, read


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

    from scribe.voice.tts import (
        kokoro_assets_ready,
        kokoro_installed,
        resolve_tts_backend,
        resolve_tts_voice,
    )

    tts_backend = resolve_tts_backend(
        settings.tts_backend,
        kokoro_installed=kokoro_installed(),
        kokoro_ready=kokoro_assets_ready(),
    )
    if tts_backend == "kokoro":
        tts_desc = f"kokoro ({resolve_tts_voice(settings.tts_voice)}, {settings.tts_speed:g}x)"
    elif settings.tts_backend in ("auto", "kokoro"):
        tts_desc = "pyttsx3 (system voice; run `scribe tray --setup` for the Kokoro voice)"
    else:
        tts_desc = f"pyttsx3 (system voice, {settings.tts_speed:g}x)"

    console.print()
    console.print(f"[cyan]profile[/cyan] {settings.profile}")
    console.print(f"[cyan]activation[/cyan] {settings.activation}")
    console.print(f"[cyan]dictate[/cyan] {settings.dictate_hotkey}")
    console.print(f"[cyan]read[/cyan] {settings.read_hotkey}")
    console.print(f"[cyan]inject[/cyan] {settings.inject}")
    console.print(f"[cyan]read-aloud[/cyan] {tts_desc}")

    advisories = resident_voice_advisories(
        platform.system(),
        inject=settings.inject,
        session_type=os.environ.get("XDG_SESSION_TYPE", ""),
        wayland_display=os.environ.get("WAYLAND_DISPLAY", ""),
    )
    if advisories:
        console.print()
        for advisory in advisories:
            style = "yellow" if advisory.level == "warning" else "cyan"
            console.print(f"[{style}]{advisory.level:7}[/{style}] {advisory.message}")

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


def _brand_windows_process() -> None:  # pragma: no cover - Windows shell branding
    """Tag the process so Windows shows 'Scribe Voice' (not 'Python') on toasts
    and the taskbar, by setting an explicit AppUserModelID."""
    if platform.system() != "Windows":
        return
    with suppress(Exception):
        import ctypes

        # getattr keeps the type checker happy on non-Windows runners, where
        # ctypes has no ``windll`` attribute (this branch never runs there anyway).
        windll = getattr(ctypes, "windll", None)
        if windll is not None:
            windll.shell32.SetCurrentProcessExplicitAppUserModelID("Scribe.Voice")


def run_tray(console: Console, settings: TraySettings, *, no_tray: bool) -> int:  # pragma: no cover
    """Run the resident voice utility as a tray icon or terminal fallback."""
    if no_tray:
        return _run_no_tray(console, settings)
    _brand_windows_process()
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

    # Desktop notifications are the only visible cue once the tray detaches from
    # the console, so route the service's user-facing messages to them.
    def _notify(title: str, message: str) -> None:
        # Echo to the console too: if the tray was launched from a terminal, the
        # user sees the same feedback there, not only as a transient notification.
        console.print(f"[cyan]{title}[/cyan] [dim]{message}[/dim]")
        if settings.show_notifications:
            with suppress(Exception):
                icon.notify(message, title)

    service.set_notifier(_notify)

    def update_menu(_state: object) -> None:
        icon.title = f"Scribe Voice - {service.status_text}"
        icon.update_menu()

    def pause_resume(_icon: object, _item: object) -> None:
        service.toggle_pause()
        update_menu(service.state)

    def quit_icon(icon_obj: Any, _item: object) -> None:
        service.stop()
        icon_obj.stop()

    def _startup_enabled(_item: object = None) -> bool:
        from scribe.voice.startup import is_startup_enabled

        try:
            return is_startup_enabled()
        except Exception:
            return False

    def toggle_startup(_icon: object, _item: object) -> None:
        from scribe.voice.startup import install_startup, remove_startup

        with suppress(Exception):
            remove_startup() if _startup_enabled() else install_startup()
        update_menu(service.state)

    def _speed_item(value: float) -> Any:
        def _set(_icon: object, _item: object) -> None:
            service.set_speed(value)
            update_menu(service.state)

        return pystray.MenuItem(
            f"{value:g}x",
            _set,
            checked=lambda _item, v=value: abs(service.tts_speed - v) < 0.001,
            radio=True,
        )

    speed_menu = pystray.Menu(*[_speed_item(v) for v in (0.8, 1.0, 1.2, 1.5, 2.0)])

    def _hotkey_item(role: str, key: str) -> Any:
        def _set(_icon: object, _item: object) -> None:
            service.set_hotkey(role, key)
            update_menu(service.state)

        def _is_current(_item: object, r: str = role, k: str = key) -> bool:
            current = service.dictate_hotkey if r == "dictate" else service.read_hotkey
            return current == k

        return pystray.MenuItem(key.upper(), _set, checked=_is_current, radio=True)

    hotkey_choices = ("f6", "f7", "f8", "f9", "f10", "f11", "f12")
    dictate_menu = pystray.Menu(*[_hotkey_item("dictate", k) for k in hotkey_choices])
    read_menu = pystray.Menu(*[_hotkey_item("read", k) for k in hotkey_choices])

    icon.menu = pystray.Menu(
        pystray.MenuItem(lambda _item: f"Status: {service.status_text}", None, enabled=False),
        pystray.MenuItem(
            lambda _item: f"Dictate (tap): {service.dictate_hotkey.upper()}", dictate_menu
        ),
        pystray.MenuItem(lambda _item: f"Read (tap): {service.read_hotkey.upper()}", read_menu),
        pystray.MenuItem("Read speed", speed_menu),
        pystray.MenuItem(
            lambda _item: "Resume hotkeys" if service.paused else "Pause hotkeys",
            pause_resume,
        ),
        pystray.MenuItem("Start at login", toggle_startup, checked=_startup_enabled),
        pystray.MenuItem("Quit Scribe Voice", quit_icon),
    )
    console.print("[green]Scribe Voice is running in the tray.[/green]")
    # Withhold the "tap F9/F8" hint until the preloaded model is actually ready, so
    # we never claim readiness while still loading. Wait BEFORE wiring live menu
    # updates so no tray method is called before icon.run().
    dictate_hint, read_hint = hotkey_hints(settings)
    if _await_model_ready(console, service):
        console.print(f"[green]Ready.[/green] [dim]{dictate_hint} {read_hint}[/dim]")
    else:
        console.print(f"[dim]{dictate_hint} {read_hint} (model will load on first use)[/dim]")
    service.add_status_callback(update_menu)
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
    # Hold the "ready" banner until the preloaded model is actually warm.
    _await_model_ready(console, service)
    console.print("[green]Resident voice hotkeys are active.[/green]")
    dictate_hint, read_hint = hotkey_hints(settings)
    console.print(f"[cyan]Dictate:[/cyan] {dictate_hint}")
    console.print(f"[cyan]Read:[/cyan] {read_hint}")
    console.print("[dim]Press Ctrl+C in this terminal to quit.[/dim]")

    try:
        while service.running:
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
    return 0
