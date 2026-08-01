"""Tray and terminal runners for the resident voice service."""

from __future__ import annotations

import logging
import os
import platform
import threading
import time
from contextlib import suppress
from dataclasses import dataclass
from importlib.resources import files
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from scribe.utils.branding import brand_header_markup
from scribe.voice.instance import TrayInstanceLock
from scribe.voice.service import (
    VoiceTrayService,
    dependency_report,
    missing_dependency_packages,
    resident_voice_advisories,
    tray_platform_matrix,
)
from scribe.voice.settings import TraySettings

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NativeTraySelection:
    """One deliberate native-daemon selection and its operator-facing trust state."""

    path: Path | None
    source: Literal["python", "explicit"]
    reason: str


_NATIVE_FUNCTION_KEYS = frozenset(f"f{number}" for number in range(6, 13))


def _native_compatibility_issue(settings: TraySettings) -> str | None:
    """Return why the current native protocol cannot represent these settings."""
    if settings.activation != "toggle":
        return "native daemon supports toggle activation only"
    unsupported = sorted(
        {
            settings.dictate_hotkey.lower(),
            settings.read_hotkey.lower(),
        }
        - _NATIVE_FUNCTION_KEYS
    )
    if unsupported:
        return "native daemon supports simple F6-F12 hotkeys only"
    return None


def _resolve_native_tray() -> NativeTraySelection:
    """Resolve only a deliberate unverified override, never implicit build output."""
    explicit_value = os.environ.get("SCRIBE_TRAY_NATIVE_BIN", "").strip()
    if explicit_value:
        explicit = Path(os.path.expandvars(explicit_value)).expanduser()
        if explicit.is_file():
            return NativeTraySelection(
                explicit,
                "explicit",
                f"unverified developer override at {explicit}",
            )
        return NativeTraySelection(
            None,
            "python",
            f"configured native path not found: {explicit}",
        )

    return NativeTraySelection(
        None,
        "python",
        "native daemon is opt-in via SCRIBE_TRAY_NATIVE_BIN",
    )


def packaged_icon_path() -> Path:
    """Return the bundled PNG icon path for the tray."""
    return Path(str(files("scribe") / "assets" / "icons" / "scribe.png"))


def packaged_native_icon_path() -> Path:
    """Return the canonical icon format expected by the native daemon."""
    icon_name = "scribe.ico" if platform.system() == "Windows" else "scribe.png"
    return Path(str(files("scribe") / "assets" / "icons" / icon_name))


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
            while service.running and service.is_model_loading():
                status.update(
                    f"[cyan]Loading voice model... {time.monotonic() - start:.0f}s[/cyan] "
                    "[dim](first run downloads it; later runs just warm it)[/dim]"
                )
                time.sleep(0.1)
    if service.state == "error":
        console.print(f"[red]Model load failed:[/red] {service.error_message}")
        return False
    return True


def _show_and_warm_python_tray(
    icon: Any,
    service: VoiceTrayService,
    settings: TraySettings,
    console: Console,
) -> None:
    """Show the tray first, then preload models from pystray's setup thread."""
    icon.visible = True
    if settings.preload_model:
        service.start_model_preload()
        ready = _await_model_ready(console, service)
    else:
        ready = True
    if not service.running:
        return
    dictate_hint, read_hint = hotkey_hints(settings)
    if ready:
        service._emit("Scribe Voice ready", f"{dictate_hint} {read_hint}")
    else:
        service._emit(
            "Scribe Voice error",
            f"Model load failed: {service.error_message}. "
            f"{dictate_hint} {read_hint} The model will retry on first use.",
        )


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


def _startup_enabled_for_menu() -> bool:
    """Read startup state for the tray menu without crashing its UI thread."""
    from scribe.voice.startup import startup_path

    try:
        return startup_path().exists()
    except Exception:
        logger.warning("Could not read run-at-login state", exc_info=True)
        return False


def _toggle_startup(service: VoiceTrayService) -> bool:
    """Toggle run-at-login and report success or failure through the tray service."""
    from scribe.voice.startup import install_startup, remove_startup, startup_path

    try:
        if startup_path().exists():
            remove_startup()
            message = "Run at login disabled"
        else:
            install_startup()
            message = "Run at login enabled"
    except Exception as error:
        logger.warning("Could not change run-at-login state: %s", error)
        service._emit("Scribe Voice error", f"Could not change run at login: {error}")
        return False
    service._emit("Scribe Voice", message)
    return True


def _resident_instance_status() -> tuple[str, bool]:
    """Return a diagnostic snapshot without retaining the resident voice lock."""
    instance_lock = TrayInstanceLock()
    try:
        acquired = instance_lock.acquire()
    except OSError as error:
        logger.warning("Could not inspect resident voice ownership: %s", error)
        return f"unavailable ({error})", False
    if acquired:
        try:
            instance_lock.release()
        except OSError as error:
            logger.warning("Could not release resident voice diagnostic lock: %s", error)
            return f"unavailable ({error})", False
        return "inactive", True
    owner = instance_lock.owner
    description = owner.description if owner is not None else "another process"
    return f"running ({description})", True


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

    system_name = platform.system()
    matrix = tray_platform_matrix(system_name)

    console.print()
    console.print(f"[cyan]platform[/cyan] {matrix.system} ({matrix.tier})")
    console.print(f"[cyan]profile[/cyan] {settings.profile}")
    console.print(f"[cyan]activation[/cyan] {settings.activation}")
    console.print(f"[cyan]dictate[/cyan] {settings.dictate_hotkey}")
    console.print(f"[cyan]read[/cyan] {settings.read_hotkey}")
    console.print(f"[cyan]inject[/cyan] {settings.inject}")
    console.print(f"[cyan]read-aloud[/cyan] {tts_desc}")
    console.print(f"[cyan]log[/cyan] {resident_log_path()}")
    resident_status, resident_ok = _resident_instance_status()
    console.print(f"[cyan]resident[/cyan] {resident_status}")
    if include_tray:
        selection = _resolve_native_tray()
        if selection.path is None:
            backend = f"Python tray ({selection.reason})"
        else:
            compatibility_issue = _native_compatibility_issue(settings)
            backend = (
                f"Python tray ({compatibility_issue}; native candidate: {selection.reason})"
                if compatibility_issue
                else f"native tray ({selection.reason})"
            )
    else:
        backend = "terminal hotkeys (--no-tray)"
    console.print(f"[cyan]backend[/cyan] {backend}")

    startup_ok = True
    try:
        from scribe.voice.startup import startup_path

        autostart_path = startup_path()
        startup_state = "enabled" if autostart_path.exists() else "disabled"
        console.print(f"[cyan]startup[/cyan] {startup_state} ({autostart_path})")
    except OSError as error:
        startup_ok = False
        console.print(f"[red]startup[/red] unavailable ({error})")

    advisories = resident_voice_advisories(
        system_name,
        inject=settings.inject,
        session_type=os.environ.get("XDG_SESSION_TYPE", ""),
        wayland_display=os.environ.get("WAYLAND_DISPLAY", ""),
        display=os.environ.get("DISPLAY", ""),
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
            "Install missing tray packages with:\n"
            "  uv sync --extra tray --group dev\n"
            'or for an installed package: pip install "scribe[tray]"',
            markup=False,
        )
        return 1
    return 0 if resident_ok and startup_ok else 1


def _brand_windows_process() -> None:  # pragma: no cover - Windows shell branding
    """Tag the process so Windows shows 'Scribe Voice' (not 'Python') on toasts
    and the taskbar, by setting an explicit AppUserModelID."""
    if platform.system() != "Windows":
        return
    try:
        import ctypes

        # getattr keeps the type checker happy on non-Windows runners, where
        # ctypes has no ``windll`` attribute (this branch never runs there anyway).
        windll = getattr(ctypes, "windll", None)
        if windll is not None:
            windll.shell32.SetCurrentProcessExplicitAppUserModelID("Scribe.Voice")
    except Exception as error:
        logger.warning("Could not set the Windows resident voice application identity: %s", error)


def resident_log_path(home: Path | None = None) -> Path:
    """Return the stable, user-private diagnostic log for resident voice."""
    base = Path.home() if home is None else home
    return base / ".scribe" / "logs" / "resident-voice.log"


def _configure_resident_logging(console: Console) -> Path | None:
    """Keep a bounded resident log so detached tray failures remain diagnosable."""
    log_path = resident_log_path()
    voice_logger = logging.getLogger("scribe.voice")
    try:
        resolved = log_path.resolve()
        for handler in voice_logger.handlers:
            filename = getattr(handler, "baseFilename", None)
            if filename is not None and Path(str(filename)).resolve() == resolved:
                return log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        voice_logger.setLevel(logging.DEBUG)
        voice_logger.addHandler(handler)
        with suppress(OSError):
            os.chmod(log_path, 0o600)
        voice_logger.info("Resident voice logging started")
    except OSError as error:
        console.print(f"[yellow]Could not create the resident voice log:[/yellow] {error}")
        return None
    return log_path


def run_tray(console: Console, settings: TraySettings, *, no_tray: bool) -> int:  # pragma: no cover
    """Run the resident voice utility as a tray icon or terminal fallback."""
    instance_lock = TrayInstanceLock()
    try:
        acquired = instance_lock.acquire()
    except OSError as error:
        console.print(f"[red]Could not protect the resident tray from duplicates:[/red] {error}")
        return 1

    if not acquired:
        owner = instance_lock.owner
        owner_description = owner.description if owner is not None else "another process"
        console.print(
            f"[yellow]Scribe Voice is already running ({owner_description}).[/yellow] "
            "This launch will exit without loading another model."
        )
        return 0

    try:
        return _run_owned_tray(console, settings, no_tray=no_tray)
    finally:
        instance_lock.retain_until_process_exit()


def _run_owned_tray(
    console: Console, settings: TraySettings, *, no_tray: bool
) -> int:  # pragma: no cover
    """Run a tray after the caller has acquired cross-process ownership."""
    _configure_resident_logging(console)
    if no_tray:
        return _run_no_tray(console, settings)

    selection = _resolve_native_tray()
    compatibility_issue = _native_compatibility_issue(settings)
    if selection.path is not None and compatibility_issue is None:
        native_result = _run_native_tray(console, settings, selection)
        if native_result is not None:
            return native_result
        fallback_reason = "native fallback selected after the reported failure"
    elif selection.path is not None:
        fallback_reason = f"{compatibility_issue}; native candidate not selected"
    else:
        fallback_reason = selection.reason

    console.print(f"[cyan]Tray backend:[/cyan] Python tray ({fallback_reason}).")
    return _run_python_tray(console, settings)


def _wait_for_native_ready(service: VoiceTrayService, process: Any, *, timeout: float) -> bool:
    """Wait for READY while also noticing an early daemon exit."""
    deadline = time.monotonic() + timeout
    while process.poll() is None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if service.wait_for_ipc_ready(timeout=min(0.1, remaining)):
            return process.poll() is None
    return False


def _stop_native_process(process: Any) -> bool:
    """Stop a failed daemon and confirm it exited before starting a fallback."""
    import subprocess

    if process.poll() is not None:
        return True
    try:
        process.terminate()
    except OSError as error:
        logger.warning("Could not terminate native tray process: %s", error)
    try:
        process.wait(timeout=2.0)
        return True
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
        except OSError as error:
            logger.warning("Could not kill native tray process: %s", error)
            return False
        try:
            process.wait(timeout=2.0)
            return True
        except (OSError, subprocess.TimeoutExpired) as error:
            logger.warning("Could not confirm native tray process exit: %s", error)
            return False


def _native_quit_confirmed(service: VoiceTrayService, *, timeout: float = 0.5) -> bool:
    """Distinguish an explicit native Quit from an unexplained zero exit."""
    return service.wait_for_ipc_quit(timeout=timeout)


def _prepare_native_fallback(service: VoiceTrayService, console: Console) -> bool:
    """Stop the prior backend and refuse overlap while model work is active."""
    try:
        cleanup_complete = service.stop()
    except Exception as error:
        logger.exception("Could not make the native backend safe for fallback")
        console.print(
            f"[red]Native backend cleanup failed:[/red] {error}. "
            "Python fallback was not started to avoid overlapping voice resources."
        )
        return False
    if cleanup_complete is False:
        console.print(
            "[red]Native backend model work is still stopping.[/red] "
            "Python fallback was not started to avoid a second model allocation."
        )
        return False
    return True


def _run_native_tray(
    console: Console,
    settings: TraySettings,
    selection: NativeTraySelection,
) -> int | None:
    """Run a deliberate native selection, returning None when Python should recover."""
    import subprocess

    if selection.path is None:
        return None

    service = VoiceTrayService(settings, console)
    process: Any = None
    try:
        port = service.start_ipc_server(preload_model=False)
        environment = os.environ.copy()
        environment["SCRIBE_TRAY_IPC_TOKEN"] = service.ipc_token
        arguments = [
            str(selection.path),
            "-port",
            str(port),
            "-dictate",
            settings.dictate_hotkey.upper(),
            "-read",
            settings.read_hotkey.upper(),
            "-icon",
            str(packaged_native_icon_path()),
        ]
        console.print(f"[cyan]Starting native tray:[/cyan] {selection.reason}")
        process = subprocess.Popen(arguments, env=environment)
        if not _wait_for_native_ready(service, process, timeout=5.0):
            exit_code = process.poll()
            if exit_code == 0 and _native_quit_confirmed(service):
                console.print("[cyan]Native tray was closed during startup.[/cyan]")
                return 0
            detail = (
                f"exited with status {exit_code}"
                if exit_code is not None
                else "did not confirm hotkey readiness within 5 seconds"
            )
            if not _stop_native_process(process):
                logger.error("Native tray could not be stopped after readiness failure")
                console.print(
                    "[red]Native tray could not be stopped.[/red] "
                    "Python fallback was not started to avoid duplicate hotkeys."
                )
                return 1
            logger.warning("Native tray readiness failed: %s", detail)
            if not _prepare_native_fallback(service, console):
                return 1
            console.print(
                f"[yellow]Native tray unavailable:[/yellow] {detail}. "
                "Starting the Python tray fallback."
            )
            return None

        console.print(
            f"[green]Scribe Voice is running via native tray ({selection.source}).[/green]"
        )
        if settings.preload_model:
            service.start_model_preload()
        dictate_hint, read_hint = hotkey_hints(settings)
        if _await_model_ready(console, service):
            console.print(f"[green]Ready.[/green] [dim]{dictate_hint} {read_hint}[/dim]")
        else:
            console.print(f"[dim]{dictate_hint} {read_hint} (model will load on first use)[/dim]")

        exit_code = process.wait()
        if exit_code == 0:
            if _native_quit_confirmed(service):
                return 0
            logger.warning("Native tray exited cleanly without an authenticated quit request")
            if not _prepare_native_fallback(service, console):
                return 1
            console.print(
                "[yellow]Native tray exited without an authenticated quit request.[/yellow] "
                "Starting the Python tray fallback."
            )
            return None
        logger.warning("Native tray stopped with status %s", exit_code)
        if not _prepare_native_fallback(service, console):
            return 1
        console.print(
            f"[yellow]Native tray stopped with status {exit_code}.[/yellow] "
            "Starting the Python tray fallback."
        )
        return None
    except KeyboardInterrupt:
        if process is not None and not _stop_native_process(process):
            console.print("[red]Native tray could not be stopped.[/red]")
            return 1
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        logger.exception("Native tray failed")
        if process is not None and not _stop_native_process(process):
            console.print(
                f"[red]Native tray failed and could not be stopped:[/red] {error}. "
                "Python fallback was not started to avoid duplicate hotkeys."
            )
            return 1
        if not _prepare_native_fallback(service, console):
            return 1
        console.print(
            f"[yellow]Native tray unavailable:[/yellow] {error}. Starting the Python tray fallback."
        )
        return None
    finally:
        service.stop()


def _run_python_tray(console: Console, settings: TraySettings) -> int:  # pragma: no cover
    """Run the complete Python tray implementation."""

    _brand_windows_process()
    missing = missing_dependency_packages(include_tray=True)
    if missing:
        logger.error("Tray dependencies are missing: %s", ", ".join(missing))
        console.print(f"[red]Missing tray packages:[/red] {', '.join(missing)}")
        console.print('Install them with `pip install "scribe[tray]"` or `uv sync --extra tray`.')
        return 1

    try:
        import pystray
        from PIL import Image
    except ImportError:
        logger.exception("Could not import the Python tray backend")
        console.print('Install tray support with `pip install "scribe[tray]"`.')
        return 1

    try:
        with Image.open(packaged_icon_path()) as source_image:
            image = source_image.copy()
    except Exception as e:
        logger.exception("Could not load the tray icon")
        console.print(f"[red]Could not load tray icon:[/red] {e}")
        return 1

    service = VoiceTrayService(settings, console)
    requested_stop = threading.Event()
    setup_errors: list[str] = []
    try:
        icon = pystray.Icon("scribe-voice", image, "Scribe Voice")

        # Desktop notifications are the only visible cue once the tray detaches
        # from the console, so route user-facing messages to them.
        def _notify(title: str, message: str) -> None:
            try:
                console.print(f"[cyan]{title}[/cyan] [dim]{message}[/dim]")
            except Exception:
                logger.warning("Tray console notification failed", exc_info=True)
            if settings.show_notifications:
                try:
                    icon.notify(message, title)
                except Exception:
                    logger.warning("Desktop notification failed", exc_info=True)

        service.set_notifier(_notify)

        def update_menu(_state: object) -> None:
            try:
                icon.title = f"Scribe Voice - {service.status_text}"
                icon.update_menu()
            except Exception as error:
                logger.warning("Could not refresh tray menu: %s", error)
                _notify("Scribe Voice warning", f"Could not refresh the tray menu: {error}")

        def pause_resume(_icon: object, _item: object) -> None:
            service.toggle_pause()
            update_menu(service.state)

        def quit_icon(icon_obj: Any, _item: object) -> None:
            requested_stop.set()
            service.stop()
            icon_obj.stop()

        def toggle_startup(_icon: object, _item: object) -> None:
            _toggle_startup(service)
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
        dictate_action = "tap" if settings.activation == "toggle" else "hold"

        icon.menu = pystray.Menu(
            pystray.MenuItem(lambda _item: f"Status: {service.status_text}", None, enabled=False),
            pystray.MenuItem(
                lambda _item: f"Dictate ({dictate_action}): {service.dictate_hotkey.upper()}",
                dictate_menu,
            ),
            pystray.MenuItem(lambda _item: f"Read (tap): {service.read_hotkey.upper()}", read_menu),
            pystray.MenuItem("Read speed", speed_menu),
            pystray.MenuItem(
                lambda _item: "Resume hotkeys" if service.paused else "Pause hotkeys",
                pause_resume,
            ),
            pystray.MenuItem(
                "Start at login",
                toggle_startup,
                checked=lambda _item: _startup_enabled_for_menu(),
            ),
            pystray.MenuItem("Quit Scribe Voice", quit_icon),
        )

        if not service.start_hotkeys(preload_model=False):
            return 1
        console.print("[cyan]Starting Scribe Voice in the tray.[/cyan]")

        def setup_icon(icon_obj: Any) -> None:
            try:
                service.add_status_callback(update_menu)
                _show_and_warm_python_tray(icon_obj, service, settings, console)
            except Exception as error:
                message = f"tray startup failed: {error}"
                setup_errors.append(message)
                logger.exception("%s", message)
                if service._set_state_if_running("error", message):
                    service._emit("Scribe Voice error", message)
                service.stop()
                icon_obj.stop()

        try:
            icon.run(setup=setup_icon)
        except Exception as e:
            logger.exception("Tray backend stopped unexpectedly")
            console.print(f"[red]Tray backend stopped unexpectedly:[/red] {e}")
            return 1
        if setup_errors:
            return 1
        if not requested_stop.is_set():
            logger.error("Tray backend exited without a quit request")
            console.print("[red]Tray backend exited without a quit request.[/red]")
            return 1
        return 0
    except Exception as e:
        logger.exception("Could not initialize the tray backend")
        console.print(f"[red]Could not initialize the tray backend:[/red] {e}")
        return 1
    finally:
        service.stop()
        try:
            image.close()
        except Exception:
            logger.warning("Could not close tray icon image", exc_info=True)


def _run_no_tray(console: Console, settings: TraySettings) -> int:  # pragma: no cover
    service = VoiceTrayService(settings, console)
    if not service.start_hotkeys(preload_model=settings.preload_model):
        return 1

    interrupted = False
    try:
        console.print(brand_header_markup("scribe voice"))
        console.print()
        # Hold the "ready" banner until the preloaded model is actually warm.
        _await_model_ready(console, service)
        if not service.running:
            console.print("[red]Resident voice stopped during startup.[/red]")
            return 1
        console.print("[green]Resident voice hotkeys are active.[/green]")
        dictate_hint, read_hint = hotkey_hints(settings)
        console.print(f"[cyan]Dictate:[/cyan] {dictate_hint}")
        console.print(f"[cyan]Read:[/cyan] {read_hint}")
        console.print("[dim]Press Ctrl+C in this terminal to quit.[/dim]")

        while service.running:
            time.sleep(0.25)
    except KeyboardInterrupt:
        interrupted = True
    except Exception as error:
        logger.exception("Resident voice stopped unexpectedly")
        console.print(f"[red]Resident voice stopped unexpectedly:[/red] {error}")
        return 1
    finally:
        service.stop()
    if not interrupted:
        logger.error("Resident voice stopped without a quit request")
        console.print("[red]Resident voice stopped without a quit request.[/red]")
        return 1
    return 0
