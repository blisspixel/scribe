"""Long-running voice service for tray and no-tray resident modes."""

from __future__ import annotations

import contextlib
import hmac
import importlib.util
import logging
import queue
import secrets
import socket
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from scribe.cli.voice import (
    VOICE_INSTALL_HINT,
    clean_spoken_text,
    paste_modifier_name,
    write_wav,
)
from scribe.models.gpu import GPUConfig
from scribe.voice.settings import HotkeySpec, TraySettings, model_for_profile

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)

VoiceTrayState = Literal["idle", "recording", "transcribing", "speaking", "error", "stopped"]
MAX_DICTATION_SECONDS = 300
MAX_PENDING_ACTIONS = 32


@dataclass(frozen=True)
class Dependency:
    """One optional runtime dependency checked before starting the tray."""

    module: str
    package: str
    purpose: str
    required_for_tray: bool = False


@dataclass(frozen=True)
class DependencyStatus:
    """Availability result for an optional dependency."""

    dependency: Dependency
    available: bool


VOICE_DEPENDENCIES: tuple[Dependency, ...] = (
    Dependency("sounddevice", "sounddevice", "microphone capture"),
    Dependency("pynput", "pynput", "global hotkeys and text injection"),
    Dependency("pyperclip", "pyperclip", "clipboard paste and selection capture"),
    Dependency("pyttsx3", "pyttsx3", "offline read-aloud"),
)
TRAY_DEPENDENCIES: tuple[Dependency, ...] = (
    Dependency("pystray", "pystray", "system tray icon", required_for_tray=True),
    Dependency("PIL.Image", "Pillow", "tray icon loading", required_for_tray=True),
)


def _module_available(module: str) -> bool:
    """Return whether an optional module can be discovered safely.

    ``find_spec("PIL.Image")`` raises when the parent ``PIL`` package is absent.
    That is an expected missing-extra state, not a tray diagnostic failure.
    """
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def dependency_report(*, include_tray: bool) -> list[DependencyStatus]:
    """Return optional dependency availability for the requested resident mode."""
    deps = [*VOICE_DEPENDENCIES]
    if include_tray:
        deps.extend(TRAY_DEPENDENCIES)
    return [
        DependencyStatus(dependency=dep, available=_module_available(dep.module)) for dep in deps
    ]


def missing_dependency_packages(*, include_tray: bool) -> list[str]:
    """Return package names that must be installed before resident voice can run."""
    missing = [
        status.dependency.package
        for status in dependency_report(include_tray=include_tray)
        if not status.available
    ]
    return sorted(set(missing))


@dataclass(frozen=True)
class ReadinessAdvisory:
    """One environment-readiness note for the resident voice hotkeys.

    These are not dependency problems. Global hotkeys and the microphone need
    OS-level grants (macOS), a supported display protocol (Linux Wayland vs X11),
    or a keyboard-layout caveat (``type`` injection) that installing a package
    cannot prove. They surface as guidance in ``scribe tray --check`` and
    ``scribe doctor`` rather than hard failures.
    """

    level: Literal["info", "warning"]
    message: str


TrayValidationTier = Literal["validated", "experimental", "unsupported"]


@dataclass(frozen=True)
class TrayPlatformMatrix:
    """Hardware-matrix validation tier for the resident tray utility."""

    system: str
    tier: TrayValidationTier
    headline: str


def tray_platform_matrix(system: str) -> TrayPlatformMatrix:
    """Return the validation tier for ``scribe tray`` on this OS."""
    if system == "Windows":
        return TrayPlatformMatrix(
            system,
            "validated",
            "Windows tray, hotkeys, and startup are live-validated",
        )
    if system == "Darwin":
        return TrayPlatformMatrix(
            system,
            "experimental",
            "macOS tray is experimental: live hardware matrix not yet recorded; "
            "grant Input Monitoring and Microphone under Privacy & Security",
        )
    if system == "Linux":
        return TrayPlatformMatrix(
            system,
            "experimental",
            "Linux tray is experimental: live hardware matrix not yet recorded. "
            "Wayland sessions such as Omarchy do not get pynput global hotkeys. "
            "`scribe voice` is a separate experimental compositor path",
        )
    return TrayPlatformMatrix(
        system,
        "unsupported",
        f"Resident tray is not supported on {system}; use `scribe listen` / "
        f"`scribe say` only where a display session allows it",
    )


def graphical_session_detected(
    *,
    display: str = "",
    wayland_display: str = "",
    session_type: str = "",
) -> bool:
    """Return True when a Linux graphical session is likely present.

    Require a display socket env var (``DISPLAY`` or ``WAYLAND_DISPLAY``).
    ``session_type`` / ``XDG_SESSION_TYPE`` alone is not enough: SSH and some
    headless units leave a stale session type without a usable local display.
    """
    _ = session_type
    return bool(display.strip() or wayland_display.strip())


def tray_environment_advisories(
    system: str,
    *,
    display: str = "",
    wayland_display: str = "",
    session_type: str = "",
) -> list[ReadinessAdvisory]:
    """Platform-matrix and display-session notes for tray readiness."""
    advisories: list[ReadinessAdvisory] = []
    matrix = tray_platform_matrix(system)
    if matrix.tier != "validated":
        advisories.append(ReadinessAdvisory("warning", matrix.headline))

    if system == "Linux" and not graphical_session_detected(
        display=display,
        wayland_display=wayland_display,
        session_type=session_type,
    ):
        advisories.append(
            ReadinessAdvisory(
                "warning",
                "Linux: no DISPLAY or WAYLAND_DISPLAY detected; the tray icon and "
                "global hotkeys require a local graphical session (not SSH/headless).",
            )
        )
    return advisories


def resident_voice_advisories(
    system: str,
    *,
    inject: str = "paste",
    session_type: str = "",
    wayland_display: str = "",
    display: str = "",
) -> list[ReadinessAdvisory]:
    """Environment-readiness notes for resident voice, by OS and injection mode.

    Pure: the OS name, injection mode, and the relevant environment values are
    injected so the decision is unit-testable without a real desktop. This is the
    "determinism for plumbing" half of the agentic balance - a fixed, reviewable
    rule, not model judgment.
    """
    advisories: list[ReadinessAdvisory] = tray_environment_advisories(
        system,
        display=display,
        wayland_display=wayland_display,
        session_type=session_type,
    )

    if system == "Darwin":
        advisories.append(
            ReadinessAdvisory(
                "warning",
                "macOS: grant Input Monitoring (global hotkeys) and Microphone "
                "(dictation) to your terminal or the packaged app under System "
                "Settings > Privacy & Security, then fully quit and relaunch it. "
                "Without Input Monitoring, hotkeys may never fire; without "
                "Microphone, dictation reports a capture error instead of inserting text.",
            )
        )
        advisories.append(
            ReadinessAdvisory(
                "info",
                "macOS run-at-login uses a user LaunchAgent "
                "(`scribe tray --startup install`); remove with "
                "`scribe tray --startup remove`.",
            )
        )
    elif system == "Linux":
        is_graphical = graphical_session_detected(
            display=display,
            wayland_display=wayland_display,
            session_type=session_type,
        )
        is_wayland = session_type.strip().lower() == "wayland" or bool(wayland_display.strip())
        # Headless warnings already come from tray_environment_advisories; do not
        # claim X11 hotkey support when no graphical session was detected.
        if is_graphical and is_wayland:
            advisories.append(
                ReadinessAdvisory(
                    "warning",
                    "Linux/Wayland detected: pynput cannot register Hyprland bindings, "
                    "and portal GlobalShortcuts support varies by desktop. On Omarchy, "
                    "leave F9 and Super+Ctrl+X for Omarchy dictation. `scribe voice` "
                    "adds experimental compositor chords and a terminal overlay; a "
                    "check does not validate hardware. Use the terminal for "
                    "transcription and OBS recording.",
                )
            )
        elif is_graphical:
            advisories.append(
                ReadinessAdvisory(
                    "info",
                    "Linux/X11: a local DISPLAY is present so pynput global hotkeys "
                    "may work, but the platform matrix is still experimental. "
                    "Some desktops need an AppIndicator / StatusNotifier host for "
                    "the tray icon (GNOME often needs an extension); otherwise use "
                    "`scribe tray --no-tray`.",
                )
            )
        advisories.append(
            ReadinessAdvisory(
                "info",
                "Linux run-at-login writes an XDG autostart entry "
                "(`~/.config/autostart` via `scribe tray --startup install`). "
                "On Omarchy that entry does not create a Hyprland binding; personal "
                "binds belong in `~/.config/hypr/bindings.lua`, not under "
                "`/usr/share/omarchy`.",
            )
        )

    if inject.strip().lower() == "type":
        if system == "Darwin":
            advisories.append(
                ReadinessAdvisory(
                    "warning",
                    "macOS inject=type also needs Accessibility permission for the "
                    "same app under Privacy & Security so keystrokes can reach other "
                    "windows; inject=paste avoids that path when the clipboard works.",
                )
            )
        advisories.append(
            ReadinessAdvisory(
                "warning",
                "inject=type sends raw keystrokes and can mis-type on non-US "
                "keyboard layouts or in apps that intercept keys; inject=paste is "
                "more reliable for long or non-ASCII text.",
            )
        )

    return advisories


def key_name_from_object(key: object) -> str | None:
    """Convert a pynput key object into the names used by ``HotkeySpec``."""
    char = getattr(key, "char", None)
    if isinstance(char, str) and char:
        return char.lower()
    name = getattr(key, "name", None)
    if not isinstance(name, str):
        return None
    lowered = name.lower()
    if lowered in {"ctrl_l", "ctrl_r", "ctrl"}:
        return "ctrl"
    if lowered in {"alt_l", "alt_r", "alt", "alt_gr"}:
        return "alt"
    if lowered in {"shift_l", "shift_r", "shift"}:
        return "shift"
    if lowered in {"cmd_l", "cmd_r", "cmd", "super"}:
        return "cmd"
    if lowered == "space":
        return "space"
    if lowered == "enter":
        return "enter"
    if lowered == "esc":
        return "esc"
    if lowered.startswith("f") and lowered[1:].isdigit():
        return lowered
    if len(lowered) == 1:
        return lowered
    return None


class HotkeyState:
    """Tracks active key chords and one-shot activation edges."""

    def __init__(self, dictate: HotkeySpec, read: HotkeySpec) -> None:
        self._dictate = dictate
        self._read = read
        self._pressed: set[str] = set()
        self._dictate_active = False
        self._read_active = False

    @property
    def pressed(self) -> frozenset[str]:
        return frozenset(self._pressed)

    def press(self, key: str) -> tuple[bool, bool]:
        """Register a key press and return ``(dictate_started, read_started)``."""
        self._pressed.add(key)
        dictate_now = self._dictate.parts <= self._pressed
        read_now = self._read.parts <= self._pressed
        dictate_started = dictate_now and not self._dictate_active
        read_started = read_now and not self._read_active
        self._dictate_active = dictate_now
        self._read_active = read_now
        return dictate_started, read_started

    def release(self, key: str) -> bool:
        """Register release and return True when the dictation chord ended."""
        self._pressed.discard(key)
        was_dictate = self._dictate_active
        self._dictate_active = self._dictate.parts <= self._pressed
        self._read_active = self._read.parts <= self._pressed
        return was_dictate and not self._dictate_active

    def reset(self) -> None:
        self._pressed.clear()
        self._dictate_active = False
        self._read_active = False


class VoiceTrayService:
    """Resident voice service used by the tray icon and no-tray fallback."""

    def __init__(
        self, settings: TraySettings, console: Console, *, explicit_insert: bool = False
    ) -> None:
        self.settings = settings
        self.console = console
        self.hotkeys = HotkeyState(settings.dictate_spec, settings.read_spec)
        # Live (mutable) hotkeys so the tray can change them at runtime.
        self.dictate_hotkey = settings.dictate_hotkey
        self.read_hotkey = settings.read_hotkey
        self.state: VoiceTrayState = "idle"
        self.error_message: str | None = None
        self.paused = False
        self.running = False
        # Live read-aloud speed multiplier; the tray menu can change it between
        # reads. Initialized from config/CLI.
        self.tts_speed = settings.tts_speed
        # True while the STT model is being warmed (preload). The tray shows a
        # loading indicator and withholds the "ready" message until this clears.
        self.model_loading = False

        self._state_lock = threading.RLock()
        self._stop_lock = threading.RLock()
        self._shutdown_warning_emitted = False
        self._callbacks: list[Callable[[VoiceTrayState], None]] = []
        self._listener: Any | None = None
        self._stream: Any | None = None
        self._audio_buffer: list[bytes] = []
        self._audio_bytes = 0
        self._capture_limit_queued = False
        self._audio_status_warning_queued = False
        # Typed Any (not Any | None) so mypy does not narrow the post-lock
        # double-check to "unreachable" - another thread may set it under the lock.
        self._model: Any = None
        self._model_name: str | None = None
        self._worker: threading.Thread | None = None
        self._tts_engine: Any | None = None
        # Optional user-facing notifier (e.g. tray desktop notifications). When
        # unset, user-facing cues fall back to the console (visible in --no-tray).
        self._notifier: Callable[[str, str], None] | None = None
        # Hotkey actions run on this dispatcher, NOT the listener thread. Opening
        # the mic or doing device work inside the low-level keyboard hook callback
        # breaks subsequent key capture on Windows, so the callback only enqueues.
        # ``_dictating`` is the synchronous toggle intent (set in the callback) so
        # rapid taps toggle correctly even though the action runs asynchronously.
        self._actions: queue.Queue[Callable[[], object] | None] = queue.Queue(
            maxsize=MAX_PENDING_ACTIONS
        )
        self._action_overflow = threading.Event()
        self._dispatcher: threading.Thread | None = None
        self._dictating = False
        # Serializes model loads so a preload thread and a first dictation cannot
        # both construct the model (double load / VRAM waste).
        self._model_lock = threading.Lock()
        self._model_use_lock = threading.Lock()
        self._model_users = 0
        self._model_unload_thread: threading.Thread | None = None
        self._model_unload_result: list[Exception | None] | None = None
        self._model_unload_target: Any = None
        self._model_unload_timeout_reported = False
        self._preload_thread: threading.Thread | None = None
        self._watchdog: threading.Thread | None = None
        self._watchdog_stop = threading.Event()
        self._watchdog_error_message: str | None = None
        self._watchdog_failures = 0
        self._watchdog_next_retry = 0.0

        self._ipc_socket: Any = None
        self._ipc_conn: Any = None
        self._ipc_send_lock = threading.Lock()
        self._ipc_thread: threading.Thread | None = None
        self._ipc_token: str | None = None
        self._ipc_ready = threading.Event()
        self._ipc_quit_requested = threading.Event()
        self._ipc_disconnected = threading.Event()
        # Windows tray injection stays the default. The Omarchy owner sets
        # explicit_insert so a finished dictation is stored, not pasted.
        self.explicit_insert = explicit_insert
        self.last_transcript = ""
        self._cancel_requested = False
        self._mic_announcer: Callable[[bool], None] | None = None
        self._text_inserter: Callable[[str], str] | None = None

    @property
    def status_text(self) -> str:
        """Human-readable status for the tray menu and terminal fallback."""
        if self.paused:
            return "Paused"
        if self.state == "error" and self.error_message:
            return f"Error: {self.error_message}"
        if self.model_loading and self.state == "idle":
            return "Loading model..."
        return {
            "idle": "Ready",
            "recording": "Recording",
            "transcribing": "Transcribing",
            "speaking": "Reading selection",
            "error": "Error",
            "stopped": "Stopped",
        }[self.state]

    def is_model_loading(self) -> bool:
        """Whether the STT model is still warming (used by the tray loading spinner).

        A method (not a bare attribute read) so callers polling it in a loop are
        not subject to static literal-narrowing of the flag, which another thread
        clears.
        """
        return self.model_loading

    def _is_running(self) -> bool:
        """Read live running state without static narrowing across worker calls."""
        return self.running

    def set_notifier(self, notifier: Callable[[str, str], None] | None) -> None:
        """Set a user-facing notifier (title, message), e.g. tray notifications."""
        self._notifier = notifier

    def set_mic_announcer(self, announcer: Callable[[bool], None] | None) -> None:
        """Report microphone open and closed. The Windows tray leaves this unset."""
        self._mic_announcer = announcer

    def set_text_inserter(self, inserter: Callable[[str], str] | None) -> None:
        """Replace pynput paste for an explicit insert. The callback returns a status."""
        self._text_inserter = inserter

    def _announce_mic(self, active: bool) -> None:
        announcer = self._mic_announcer
        if announcer is None:
            return
        try:
            announcer(active)
        except Exception:
            logger.warning("Microphone announcer failed", exc_info=True)

    def snapshot(self) -> dict[str, object]:
        """Return a JSON-ready view of resident voice. It does not open the microphone."""
        with self._state_lock:
            return {
                "state": self.state,
                "status": self.status_text,
                "recording": self.state == "recording",
                "paused": self.paused,
                "transcript": self.last_transcript,
                "error": self.error_message,
                "model_loading": self.model_loading,
                "explicit_insert": self.explicit_insert,
            }

    def run_exclusive(self, action: Callable[[], str], *, timeout: float = 8.0) -> str:
        """Run one resident action on the dispatcher and wait for its status string."""
        dispatcher = self._dispatcher
        if (
            dispatcher is None
            or not dispatcher.is_alive()
            or dispatcher is threading.current_thread()
        ):
            return action()

        done = threading.Event()
        box: list[object] = []

        def wrapped() -> None:
            try:
                box.append(action())
            except Exception as error:
                box.append(error)
            finally:
                done.set()

        if not self._queue_action(wrapped):
            return "busy"
        if not done.wait(timeout):
            return "timeout"
        if not box:
            return "timeout"
        result = box[0]
        if isinstance(result, Exception):
            raise result
        return str(result)

    def set_speed(self, speed: float) -> None:
        """Set the read-aloud speed multiplier for subsequent reads (live)."""
        from scribe.voice.tts import resolve_tts_speed

        self.tts_speed = resolve_tts_speed(speed)
        self._emit("Scribe Voice", f"Read speed {self.tts_speed:g}x")

    def set_hotkey(self, role: str, key: str) -> bool:
        """Change the 'dictate' or 'read' hotkey live and persist it.

        Returns False (with a notification) if the choice would collide with the
        other hotkey or is unparseable.
        """
        from scribe.voice.settings import parse_hotkey

        if role not in {"dictate", "read"}:
            self._emit("Scribe Voice error", f"Unknown hotkey role: {role}")
            return False

        dictate = key if role == "dictate" else self.dictate_hotkey
        read = key if role == "read" else self.read_hotkey
        if dictate == read:
            self._emit("Scribe Voice", "Dictate and read keys must differ")
            return False
        try:
            dictate_spec = parse_hotkey(dictate)
            read_spec = parse_hotkey(read)
        except ValueError as error:
            self._emit("Scribe Voice error", str(error))
            return False

        previous = (
            self.dictate_hotkey,
            self.read_hotkey,
            self.hotkeys,
            self._dictating,
        )
        self.dictate_hotkey = dictate
        self.read_hotkey = read
        self.hotkeys = HotkeyState(dictate_spec, read_spec)  # listener reads this live
        self._dictating = False
        try:
            self._persist_hotkeys()
        except Exception as error:
            (
                self.dictate_hotkey,
                self.read_hotkey,
                self.hotkeys,
                self._dictating,
            ) = previous
            logger.warning("Could not persist voice hotkeys: %s", error)
            self._emit(
                "Scribe Voice error",
                f"Could not save hotkey; the change was not applied: {error}",
            )
            return False
        self._emit("Scribe Voice", f"{role.capitalize()} key -> {key.upper()}")
        return True

    def _persist_hotkeys(self) -> None:
        from scribe.config_file import load_config_file_strict, save_config_file

        config = load_config_file_strict()
        if not isinstance(config.get("voice"), dict):
            config["voice"] = {}
        tray = config["voice"].get("tray")
        if not isinstance(tray, dict):
            tray = {}
        tray["dictate_hotkey"] = self.dictate_hotkey
        tray["read_hotkey"] = self.read_hotkey
        config["voice"]["tray"] = tray
        save_config_file(config)

    def _emit(self, title: str, message: str) -> None:
        """Surface a user-facing cue via the notifier, or the console as fallback.

        Without this, tray hotkey actions are invisible (the console is detached),
        so a started recording, an empty result, or a mic error all look like
        "nothing happened".
        """
        notifier = self._notifier
        if notifier is not None:
            try:
                notifier(title, message)
                return
            except Exception:
                logger.warning("Voice notifier failed", exc_info=True)
        try:
            self.console.print(f"[cyan]{title}[/cyan] [dim]{message}[/dim]")
        except Exception:
            logger.exception("Could not surface voice message: %s: %s", title, message)

    def add_status_callback(self, callback: Callable[[VoiceTrayState], None]) -> None:
        """Register a callback invoked whenever the service state changes."""
        self._callbacks.append(callback)

    def set_paused(self, paused: bool) -> None:
        """Pause or resume hotkey actions without shutting the service down.

        Pausing mid-recording discards the in-progress capture (rather than
        injecting a surprise partial dictation). Stream teardown happens OUTSIDE
        the state lock because stream.stop() may wait for an in-progress audio
        callback before returning.
        """
        discard = False
        with self._state_lock:
            self.paused = paused
            if paused:
                self.hotkeys.reset()
                self._dictating = False
                discard = self.state == "recording"
        if discard:
            stream_stopped = self._stop_stream()
            with self._state_lock:
                self._audio_buffer = []
                self._audio_bytes = 0
                self._capture_limit_queued = False
                self._audio_status_warning_queued = False
            if stream_stopped:
                self._set_state_if_running("idle")
            else:
                message = "microphone stream could not be closed safely while pausing"
                if self._set_state_if_running("error", message):
                    self._emit("Scribe Voice error", message)
        self._notify()

    def toggle_pause(self) -> bool:
        """Toggle pause state and return the new state."""
        self.set_paused(not self.paused)
        return self.paused

    def start_ipc_server(self, *, preload_model: bool = False) -> int:
        """Start the IPC socket server for the Go tray daemon and return the bound port."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            sock.settimeout(0.2)
        except OSError:
            sock.close()
            raise
        port = sock.getsockname()[1]

        self._ipc_socket = sock
        self._actions = queue.Queue(maxsize=MAX_PENDING_ACTIONS)
        self._action_overflow.clear()
        self.running = True
        self._shutdown_warning_emitted = False
        self._watchdog_error_message = None
        self._ipc_token = secrets.token_urlsafe(32)
        self._ipc_ready.clear()
        self._ipc_quit_requested.clear()
        self._ipc_disconnected.clear()
        try:
            self._start_runtime_threads(watch_hotkeys=False)
            self._ipc_thread = threading.Thread(
                target=self._ipc_server_loop,
                daemon=True,
                name="scribe-voice-ipc",
            )
            self._ipc_thread.start()
        except Exception as error:
            self.stop()
            raise RuntimeError(f"could not start resident voice threads: {error}") from error

        if preload_model:
            self.start_model_preload()

        return int(port)

    def start_session(self, *, preload_model: bool = False) -> bool:
        """Start the resident owner without a pynput global hook.

        Compositor clients use the separate control socket. This does not open
        the microphone and it does not replace the native-tray TCP server.
        """
        missing = [
            package
            for package in missing_dependency_packages(include_tray=False)
            if package != "pynput"
        ]
        if "sounddevice" in missing:
            logger.error("Resident voice dependencies are missing: %s", ", ".join(missing))
            self.console.print(VOICE_INSTALL_HINT, markup=False)
            self.console.print(f"Missing packages: {', '.join(missing)}")
            return False
        optional = [package for package in missing if package != "sounddevice"]
        if optional:
            self.console.print(
                f"[yellow]Optional voice packages missing:[/yellow] {', '.join(optional)}"
            )

        try:
            self._actions = queue.Queue(maxsize=MAX_PENDING_ACTIONS)
            self._action_overflow.clear()
            self.running = True
            self._shutdown_warning_emitted = False
            self._watchdog_error_message = None
            self._start_runtime_threads(watch_hotkeys=False)
        except Exception as error:
            self.stop()
            message = f"resident voice threads unavailable: {error}"
            self._set_state("error", message)
            self._emit("Scribe Voice error", message)
            return False

        self._set_state("idle")
        if preload_model:
            self.start_model_preload()
        return True

    def _start_runtime_threads(self, *, watch_hotkeys: bool) -> None:
        """Start action dispatch and hotkey recovery as one managed lifecycle."""
        self._dispatcher = threading.Thread(
            target=self._dispatch_loop,
            daemon=True,
            name="scribe-voice-actions",
        )
        self._dispatcher.start()
        if watch_hotkeys:
            self._watchdog_stop.clear()
            self._watchdog = threading.Thread(
                target=self._watchdog_loop,
                daemon=True,
                name="scribe-voice-watchdog",
            )
            self._watchdog.start()
        else:
            self._watchdog = None

    @property
    def ipc_token(self) -> str:
        """Return the process-scoped capability required by the native daemon."""
        if self._ipc_token is None:
            raise RuntimeError("Native tray IPC server is not running")
        return self._ipc_token

    def wait_for_ipc_ready(self, *, timeout: float) -> bool:
        """Wait a bounded time for an authenticated daemon to register its controls."""
        return self._ipc_ready.wait(timeout)

    def wait_for_ipc_quit(self, *, timeout: float) -> bool:
        """Wait for an authenticated native daemon to request a clean shutdown."""
        return self._ipc_quit_requested.wait(timeout)

    def wait_for_ipc_disconnect(self, *, timeout: float) -> bool:
        """Wait for a ready native daemon to lose its authenticated connection."""
        return self._ipc_disconnected.wait(timeout)

    def start_model_preload(self) -> None:
        """Warm resident models after the owning tray surface is ready."""
        with self._state_lock:
            if self.model_loading or not self.running:
                return
            self.model_loading = True
            preload_thread = threading.Thread(
                target=self._preload_model_worker,
                daemon=True,
                name="scribe-voice-preload",
            )
            self._preload_thread = preload_thread
        self._notify()
        try:
            preload_thread.start()
        except Exception as error:
            with self._state_lock:
                self.model_loading = False
                if self._preload_thread is preload_thread:
                    self._preload_thread = None
            message = f"model preload could not start: {error}"
            logger.warning("Voice %s", message)
            if self._set_state_if_running("error", message):
                self._emit("Scribe Voice error", message)

    def _ipc_server_loop(self) -> None:
        """Listen for one authenticated native tray daemon at a time."""
        server = self._ipc_socket
        while self.running:
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            except OSError as error:
                if self.running:
                    logger.warning("Native tray IPC listener stopped: %s", error)
                break

            peer_ready = False
            try:
                with conn, conn.makefile("r", encoding="utf-8") as stream:
                    conn.settimeout(2.0)
                    auth_line = stream.readline(512)
                    if not self._ipc_auth_matches(auth_line):
                        logger.warning("Rejected unauthenticated native tray IPC peer")
                        continue

                    # The inherited pipe capability is single-use. Closing the
                    # listener and clearing the token prevents peer replacement.
                    self._ipc_token = None
                    with contextlib.suppress(OSError):
                        server.close()
                    conn.settimeout(None)
                    conn.sendall(b"AUTH OK\n")
                    with self._ipc_send_lock:
                        self._ipc_conn = conn

                    while self.running:
                        line = stream.readline(128)
                        if not line:
                            break
                        if not line.endswith("\n"):
                            logger.warning("Rejected oversized native tray IPC command")
                            break
                        cmd = line.strip()
                        if cmd == "READY":
                            peer_ready = True
                            self._ipc_ready.set()
                            self._notify()
                        elif not peer_ready:
                            logger.warning("Ignored native tray command before READY")
                        elif cmd == "DICTATE":
                            was_dictating = self._dictating
                            action = (
                                self._finish_recording if was_dictating else self._begin_recording
                            )
                            if self._queue_action(action):
                                self._dictating = not was_dictating
                        elif cmd == "READ":
                            if self.state == "speaking":
                                self.stop_speaking()
                            elif not self._dictating:
                                self._queue_action(self.read_selection_now)
                        elif cmd == "QUIT":
                            self._ipc_quit_requested.set()
                            self.stop()
                            break
                        else:
                            logger.warning("Ignored unknown native tray IPC command")
            except (OSError, UnicodeError) as error:
                if self.running:
                    logger.warning("Native tray IPC peer disconnected: %s", error)
            finally:
                with self._ipc_send_lock:
                    if self._ipc_conn is conn:
                        self._ipc_conn = None
                if peer_ready:
                    self._ipc_ready.clear()
                    if self.running and not self._ipc_quit_requested.is_set():
                        self._ipc_disconnected.set()

    def _ipc_auth_matches(self, auth_line: str) -> bool:
        """Return True only for an exact capability line, without crashing on length.

        ``hmac.compare_digest`` raises ``TypeError`` when string lengths differ.
        A wrong-length probe must reject the peer and keep the accept loop alive.
        """
        token = self._ipc_token
        if token is None or not auth_line.endswith("\n"):
            return False
        expected = f"AUTH {token}\n"
        if len(auth_line) != len(expected):
            return False
        return hmac.compare_digest(auth_line, expected)

    def start_hotkeys(self, *, preload_model: bool = False) -> bool:  # pragma: no cover
        """Start the global hotkey listener."""
        missing = missing_dependency_packages(include_tray=False)
        if missing:
            logger.error("Resident voice dependencies are missing: %s", ", ".join(missing))
            self.console.print(VOICE_INSTALL_HINT, markup=False)
            self.console.print(f"Missing packages: {', '.join(missing)}")
            return False

        try:
            from pynput import keyboard
        except ImportError:
            logger.exception("Could not import the global hotkey backend")
            self.console.print(VOICE_INSTALL_HINT, markup=False)
            return False

        try:
            self._actions = queue.Queue(maxsize=MAX_PENDING_ACTIONS)
            self._action_overflow.clear()
            self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._listener.start()
            is_alive = getattr(self._listener, "is_alive", None)
            if callable(is_alive) and not is_alive():
                raise RuntimeError("hotkey listener exited during startup")
        except Exception as e:
            logger.exception("Could not start the global hotkey listener")
            cleanup_complete = True
            if self._listener is not None:
                cleanup_complete = self._stop_hotkey_listener(self._listener)
            self.running = False
            message = f"hotkey listener unavailable: {e}"
            if not cleanup_complete:
                message += "; failed listener cleanup remains unconfirmed"
            self._set_state("error", message)
            self.console.print(
                "[red]Could not start global hotkeys.[/red] "
                "Check OS keyboard-monitoring permissions or change the hotkeys."
            )
            if not cleanup_complete:
                self.console.print(
                    "[red]Global hotkey cleanup is incomplete.[/red] "
                    "Process exit remains the final resource boundary."
                )
            return False

        self.running = True
        self._shutdown_warning_emitted = False
        self._watchdog_error_message = None
        try:
            self._start_runtime_threads(watch_hotkeys=True)
        except Exception as error:
            self.stop()
            message = f"resident voice threads unavailable: {error}"
            self._set_state("error", message)
            self._emit("Scribe Voice error", message)
            return False
        self._set_state("idle")
        if preload_model:
            # Preload on its OWN thread, not the shared worker slot: otherwise a
            # dictation in the first few seconds (while the model loads) cannot
            # start its transcription worker and is silently dropped.
            self.start_model_preload()
        return True

    def stop(self) -> bool:  # pragma: no cover
        """Stop hotkeys, audio capture, and pending resident service state."""
        with self._stop_lock:
            return self._stop_locked()

    def _stop_locked(self) -> bool:  # pragma: no cover
        """Perform one serialized shutdown and report resource quiescence."""
        cleanup_failures: list[str] = []
        with self._state_lock:
            self.running = False
            self.paused = False
            self._dictating = False
            self.hotkeys.reset()
        self._watchdog_stop.set()
        self._announce_mic(False)
        with suppress(queue.Full):
            self._actions.put_nowait(None)  # wake the dispatcher when capacity remains
        # If the queue is full, ``running`` is already false and the dispatcher's
        # bounded get timeout still lets it exit.
        with self._ipc_send_lock:
            ipc_conn = self._ipc_conn
            self._ipc_conn = None
        if ipc_conn is not None:
            try:
                ipc_conn.shutdown(socket.SHUT_RDWR)
            except OSError as error:
                logger.warning("Could not shut down native tray connection: %s", error)
            try:
                ipc_conn.close()
            except OSError as error:
                logger.warning("Could not close native tray connection: %s", error)
        ipc_socket = self._ipc_socket
        self._ipc_socket = None
        if ipc_socket is not None:
            try:
                ipc_socket.close()
            except OSError as error:
                logger.warning("Could not close native tray listener: %s", error)
        listener = self._listener
        if listener is not None and not self._stop_hotkey_listener(listener):
            cleanup_failures.append("global hotkey listener")
        self.stop_speaking()
        microphone_checked_before_join = self._stream is not None
        if microphone_checked_before_join and not self._stop_stream():
            cleanup_failures.append("microphone stream")
        with self._state_lock:
            self._audio_buffer = []
            self._audio_bytes = 0
            self._capture_limit_queued = False
            self._audio_status_warning_queued = False
        # Join background threads so no transcription/injection runs after stop.
        current_thread = threading.current_thread()
        managed_threads = (
            ("_dispatcher", self._dispatcher),
            ("_worker", self._worker),
            ("_preload_thread", self._preload_thread),
            ("_watchdog", self._watchdog),
            ("_ipc_thread", self._ipc_thread),
        )
        active_threads: list[str] = []
        for attribute, thread in managed_threads:
            if thread is None:
                continue
            if thread is current_thread:
                if attribute != "_ipc_thread":
                    active_threads.append(getattr(thread, "name", attribute))
                continue
            try:
                if thread.is_alive():
                    thread.join(timeout=2.0)
                alive = thread.is_alive()
            except Exception as error:
                alive = True
                thread_name = getattr(thread, "name", attribute)
                logger.warning("Could not join voice thread %s: %s", thread_name, error)
                self._emit(
                    "Scribe Voice warning",
                    f"Could not confirm voice thread shutdown ({thread_name}): {error}",
                )
            if alive:
                thread_name = getattr(thread, "name", attribute)
                logger.warning("Voice thread did not stop within 2 seconds: %s", thread_name)
                active_threads.append(thread_name)
            elif getattr(self, attribute) is thread:
                setattr(self, attribute, None)
        if (
            not microphone_checked_before_join
            and self._stream is not None
            and not self._stop_stream()
        ):
            cleanup_failures.append("microphone stream")
        model_released = self._unload_model_if_unused()
        try:
            from scribe.voice.tts import unload_kokoro

            unload_kokoro()
        except Exception as error:
            cleanup_failures.append("neural voice cache")
            logger.warning("Could not release the neural voice cache: %s", error)
            self._emit(
                "Scribe Voice warning",
                f"Could not release the neural voice cache: {error}",
            )
        with self._model_use_lock:
            active_model_users = self._model_users
        if not model_released and active_model_users == 0:
            cleanup_failures.append("resident dictation model")
        with self._state_lock:
            if self._tts_engine is not None:
                cleanup_failures.append("read-aloud engine")
        cleanup_complete = not active_threads and active_model_users == 0 and not cleanup_failures
        if not cleanup_complete and not self._shutdown_warning_emitted:
            self._shutdown_warning_emitted = True
            details = [*active_threads, *cleanup_failures]
            if active_model_users:
                details.append(f"{active_model_users} active model operation(s)")
            message = (
                "Resident voice cleanup is incomplete "
                f"({', '.join(details)}); another backend will not be started in this process."
            )
            logger.error("%s", message)
            self._emit("Scribe Voice warning", message)
        self._ipc_token = None
        self._ipc_ready.clear()
        self._watchdog_error_message = None
        self._watchdog_failures = 0
        self._watchdog_next_retry = 0.0
        with self._state_lock:
            self.state = "stopped"
            self.error_message = None
        self._notify()
        return cleanup_complete

    def _stop_hotkey_listener(self, listener: Any) -> bool:
        """Stop and confirm one global hook before allowing another backend."""
        failures: list[str] = []
        try:
            listener.stop()
        except Exception as error:
            failures.append(f"stop failed: {error}")
            logger.warning("Could not stop hotkey listener: %s", error)

        join = getattr(listener, "join", None)
        if callable(join) and listener is not threading.current_thread():
            try:
                join(timeout=2.0)
            except Exception as error:
                failures.append(f"join failed: {error}")
                logger.warning("Could not join hotkey listener: %s", error)

        is_alive = getattr(listener, "is_alive", None)
        if callable(is_alive):
            try:
                alive: bool | None = bool(is_alive())
            except Exception as error:
                alive = None
                failures.append(f"status check failed: {error}")
                logger.warning("Could not inspect hotkey listener shutdown: %s", error)
        else:
            alive = None

        cleanup_complete = alive is False or (alive is None and not failures)
        if alive:
            failures.append("listener thread is still alive")
            logger.warning("Hotkey listener did not stop within 2 seconds")
        if cleanup_complete:
            with self._state_lock:
                if self._listener is listener:
                    self._listener = None
        if failures:
            self._emit(
                "Scribe Voice warning",
                f"Global hotkey shutdown reported problems ({'; '.join(failures)}).",
            )
        return cleanup_complete

    def _dispatch_loop(self) -> None:  # pragma: no cover
        """Run hotkey actions off the listener thread, one at a time, in order."""
        while self.running:
            if self._action_overflow.is_set():
                self._recover_action_overflow()
                continue
            try:
                action = self._actions.get(timeout=0.2)
            except queue.Empty:
                continue
            if action is None:
                return
            try:
                action()
            except Exception as e:
                self._report_action_error(e)

    def _queue_action(self, action: Callable[[], object]) -> bool:
        """Queue bounded resident work without blocking an OS callback thread."""
        try:
            self._actions.put_nowait(action)
        except queue.Full:
            self._dictating = False
            self._action_overflow.set()
            return False
        return True

    def _recover_action_overflow(self) -> None:
        """Discard stale action intent and leave capture in a known visible state."""
        self._action_overflow.clear()
        while True:
            try:
                self._actions.get_nowait()
            except queue.Empty:
                break
        self._dictating = False
        stream_stopped = self._stop_stream()
        with self._state_lock:
            self._audio_buffer = []
            self._audio_bytes = 0
            self._capture_limit_queued = False
            self._audio_status_warning_queued = False
        message = "Too many voice actions arrived; pending actions were discarded. Try again."
        if not stream_stopped:
            message += " Microphone cleanup is still incomplete."
        logger.error("%s", message)
        if self._set_state_if_running("error", message):
            self._emit("Scribe Voice error", message)

    def _report_action_error(self, error: Exception) -> None:
        """Report dispatcher failures without overwriting a completed shutdown."""
        logger.error("Voice action failed: %s", error)
        if self._set_state_if_running("error", str(error)):
            self._emit("Scribe Voice error", str(error))
        else:
            logger.warning("Voice action failed during shutdown: %s", error)

    def _watchdog_loop(self) -> None:  # pragma: no cover
        """Recreate the global hotkey listener if its thread ever dies.

        Windows can silently remove a low-level keyboard hook (e.g. if any hook
        callback ever times out), after which the listener thread exits. A pynput
        Listener cannot be restarted, so we build a fresh one. Cheap insurance for
        a utility meant to run all day.
        """
        while self.running:
            if self._watchdog_stop.wait(2.0):
                return
            listener = self._listener
            if listener is None:
                continue
            try:
                if listener.is_alive():
                    previous_error = self._watchdog_error_message
                    if previous_error is not None and previous_error.startswith(
                        "hotkey watchdog could not inspect listener:"
                    ):
                        self._watchdog_error_message = None
                        if self.error_message == previous_error:
                            self._set_state_if_running("idle")
                        if self.running:
                            self._emit("Scribe Voice", "Hotkey monitoring recovered")
                    continue
            except Exception as error:
                message = f"hotkey watchdog could not inspect listener: {error}"
                if self._watchdog_error_message != message:
                    self._watchdog_error_message = message
                    logger.warning("%s", message)
                    if self._set_state_if_running("error", message):
                        self._emit("Scribe Voice error", message)
                continue
            now = time.monotonic()
            if now < self._watchdog_next_retry:
                continue
            if self._reconnect_hotkeys():
                self._watchdog_failures = 0
                self._watchdog_next_retry = 0.0
                continue
            self._watchdog_failures += 1
            retry_delay = min(60.0, float(2 ** min(self._watchdog_failures, 6)))
            self._watchdog_next_retry = time.monotonic() + retry_delay

    def _reconnect_hotkeys(self) -> bool:  # pragma: no cover
        """Replace a dead listener and make any recovery failure visible."""
        # Serialize listener creation with stop(). Without this boundary, shutdown
        # can inspect the old dead listener and return just before the watchdog
        # publishes a new live hook, leaving an unowned global listener behind.
        if not self._stop_lock.acquire(timeout=0.2):
            return False
        try:
            if not self.running or self._watchdog_stop.is_set():
                return False
            fresh: Any | None = None
            try:
                from pynput import keyboard

                fresh = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
                fresh.start()
                is_alive = getattr(fresh, "is_alive", None)
                if callable(is_alive) and not is_alive():
                    raise RuntimeError("hotkey listener exited during reconnect")
            except Exception as error:
                if fresh is not None:
                    cleanup_complete = self._stop_hotkey_listener(fresh)
                    if not cleanup_complete:
                        with self._state_lock:
                            self._listener = fresh
                message = f"hotkey reconnect failed: {error}"
                if self._watchdog_error_message != message:
                    self._watchdog_error_message = message
                    logger.warning("%s", message)
                    if self._set_state_if_running("error", message):
                        self._emit("Scribe Voice error", message)
                return False

            with self._state_lock:
                publish_listener = self.running and not self._watchdog_stop.is_set()
                if publish_listener:
                    self._listener = fresh
                    self.hotkeys.reset()
                    self._dictating = False

            if not publish_listener:
                cleanup_complete = self._stop_hotkey_listener(fresh)
                if not cleanup_complete:
                    with self._state_lock:
                        self._listener = fresh
                return False
        finally:
            self._stop_lock.release()

        previous_watchdog_error = self._watchdog_error_message
        self._watchdog_error_message = None
        if previous_watchdog_error is not None:
            with self._state_lock:
                recover = (
                    self.running
                    and self.state == "error"
                    and self.error_message == previous_watchdog_error
                )
            if recover:
                self._set_state_if_running("idle")
        if self._is_running():
            self._emit("Scribe Voice", "Hotkeys reconnected")
            return True
        return False

    def read_selection_now(self) -> bool:  # pragma: no cover
        """Start the selection read-aloud worker."""
        if self.paused or not self.running:
            return False
        if not self._start_worker(self._read_selection_and_speak):
            self._emit("Scribe Voice", "Busy - finish the current action first")
            return False
        return True

    def _notify(self) -> None:
        with self._ipc_send_lock:
            ipc_conn = self._ipc_conn
            if ipc_conn is not None:
                try:
                    ipc_conn.sendall(f"STATE:{self.state}\n".encode())
                except Exception as error:
                    logger.warning("Could not send native tray state: %s", error)
                    if self._ipc_conn is ipc_conn:
                        self._ipc_conn = None
                    try:
                        ipc_conn.shutdown(socket.SHUT_RDWR)
                    except OSError as shutdown_error:
                        logger.debug(
                            "Native tray connection was already shut down: %s", shutdown_error
                        )
                    try:
                        ipc_conn.close()
                    except OSError as close_error:
                        logger.warning(
                            "Could not close failed native tray connection: %s", close_error
                        )
                    if (
                        self.running
                        and self._ipc_ready.is_set()
                        and not self._ipc_quit_requested.is_set()
                    ):
                        self._ipc_ready.clear()
                        self._ipc_disconnected.set()
        for callback in list(self._callbacks):  # snapshot: callbacks may run cross-thread
            try:
                callback(self.state)
            except Exception:
                logger.warning("Voice state callback failed", exc_info=True)

    def _set_state(self, state: VoiceTrayState, error: str | None = None) -> None:
        with self._state_lock:
            self.state = state
            self.error_message = error
        self._notify()

    def _set_state_if_running(self, state: VoiceTrayState, error: str | None = None) -> bool:
        """Set state only while live, preventing shutdown races from reviving it."""
        with self._state_lock:
            if not self.running:
                return False
            self.state = state
            self.error_message = error
        self._notify()
        return True

    def _return_to_idle(self) -> None:
        """Go idle only if still running, so a worker finishing after stop() does
        not clobber the terminal 'stopped' state."""
        self._set_state_if_running("idle")

    def _on_press(self, key: object) -> None:  # pragma: no cover
        key_name = key_name_from_object(key)
        if key_name is None:
            return
        if not self.running or self.paused:
            return
        dictate_started, read_started = self.hotkeys.press(key_name)
        # IMPORTANT: this runs inside the global keyboard hook. Do only fast,
        # in-memory work here and enqueue device/heavy actions - opening the mic on
        # this thread breaks subsequent key capture on Windows.
        if dictate_started:
            if self.settings.activation == "toggle":
                # tap toggles: stop+transcribe if dictating, else start.
                if self._dictating:
                    if self._queue_action(self._finish_recording):
                        self._dictating = False
                else:
                    if self._queue_action(self._begin_recording):
                        self._dictating = True
            elif not self._dictating:
                # hold: press starts; release stops (handled below).
                if self._queue_action(self._begin_recording):
                    self._dictating = True
            return
        if read_started:
            # Same key reads the selection and stops playback mid-sentence,
            # matching macOS Speak Selection and Edge Read Aloud. stop_speaking is
            # instant (sets an event), so it is safe inline.
            if self.state == "speaking":
                self.stop_speaking()
            elif not self._dictating:
                self._queue_action(self.read_selection_now)

    def _on_release(self, key: object) -> None:  # pragma: no cover
        key_name = key_name_from_object(key)
        if key_name is None or not self.running:
            return
        # Always clear the chord so the next press is a fresh edge, but only act on
        # the release in hold (push-to-talk) mode. In toggle mode the press handles
        # both start and stop, so releasing the key must not end dictation.
        dictate_stopped = self.hotkeys.release(key_name)
        if self.settings.activation != "hold":
            return
        if dictate_stopped and self._dictating:
            if self._queue_action(self._finish_recording):
                self._dictating = False

    def stop_speaking(self) -> None:  # pragma: no cover
        """Interrupt read-aloud playback (the same hotkey that started it)."""
        with self._state_lock:
            engine = self._tts_engine
        if engine is not None:
            try:
                engine.stop()
            except Exception as error:
                logger.warning("Could not stop voice playback: %s", error)
                self._emit("Scribe Voice error", f"Could not stop read-aloud: {error}")

    def _begin_recording(self) -> None:  # pragma: no cover
        with self._state_lock:
            cleanup_blocked = False
            if not self.running:
                return
            if self.paused:
                self._dictating = False
                unavailable = "Hotkeys are paused"
            elif self.state == "recording":
                return
            elif self._stream is not None:
                self._dictating = False
                unavailable = "Microphone cleanup is incomplete; restart Scribe Voice"
                cleanup_blocked = True
            elif self.state in {"transcribing", "speaking"}:
                self._dictating = False
                unavailable = "Busy - finish the current action first"
            else:
                unavailable = None
        if unavailable is not None:
            if cleanup_blocked:
                self._set_state_if_running("error", unavailable)
                self._emit("Scribe Voice error", unavailable)
            else:
                self._emit("Scribe Voice", unavailable)
            return
        try:
            import sounddevice as sd
        except ImportError:
            self._dictating = False
            message = "microphone support is not installed"
            logger.error("Voice %s", message)
            self._set_state_if_running("error", message)
            self._emit("Scribe Voice error", f"{message}. {VOICE_INSTALL_HINT}")
            return

        with self._state_lock:
            self._audio_buffer = []
            self._audio_bytes = 0
            self._capture_limit_queued = False
            self._audio_status_warning_queued = False
            self._cancel_requested = False
        stream: Any | None = None
        started = False
        try:
            stream = sd.RawInputStream(
                samplerate=self.settings.sample_rate,
                # ~100ms blocks so the audio callback fires ~10x/sec instead of
                # constantly. A high-frequency callback that holds the GIL starves
                # the global low-level keyboard hook past Windows' hook timeout,
                # which then silently removes it (hotkeys go dead mid-recording).
                blocksize=max(1, self.settings.sample_rate // 10),
                channels=1,
                dtype="int16",
                callback=self._audio_callback,
            )
            stream.start()
            started = True
        except Exception as e:
            logger.exception("Could not start microphone capture")
            close_error: Exception | None = None
            if stream is not None:
                try:
                    stream.close()
                except Exception as error:
                    close_error = error
                    logger.warning("Could not close failed microphone stream: %s", error)
                    with self._state_lock:
                        if self._stream is None:
                            self._stream = stream
            self._dictating = False
            message = f"Microphone unavailable: {e}"
            if close_error is not None:
                message += f"; failed stream cleanup: {close_error}"
            if self._set_state_if_running("error", message):
                self._emit("Scribe Voice error", message)
            return

        with self._state_lock:
            accepted = (
                self.running
                and not self.paused
                and self.state not in {"recording", "transcribing", "speaking"}
                and self._stream is None
            )
            if accepted:
                self._stream = stream
                self.state = "recording"
                self.error_message = None
            else:
                self._dictating = False
        if not accepted:
            cancelled_close_error: Exception | None = None
            if started:
                try:
                    stream.stop()
                except Exception as stop_error:
                    logger.warning("Could not stop cancelled microphone stream: %s", stop_error)
            try:
                stream.close()
            except Exception as error:
                cancelled_close_error = error
                logger.warning("Could not close cancelled microphone stream: %s", error)
                with self._state_lock:
                    if self._stream is None:
                        self._stream = stream
            if cancelled_close_error is not None:
                message = f"cancelled microphone cleanup failed: {cancelled_close_error}"
                if self._set_state_if_running("error", message):
                    self._emit("Scribe Voice error", message)
            elif self.running:
                self._emit("Scribe Voice", "Recording was cancelled because voice state changed")
            return

        self._notify()
        if self.explicit_insert:
            cue = (
                "MICROPHONE ON. Speak, then finish dictation to transcribe. "
                "Text stays in Scribe until you copy, insert, or read it."
            )
        else:
            verb = "tap to insert" if self.settings.activation == "toggle" else "release to insert"
            cue = f"Recording... speak, then {verb}"
        self._emit("Scribe Voice", cue)
        self._announce_mic(True)

    def _audio_callback(
        self,
        indata: Any,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:  # pragma: no cover
        _ = (frames, time_info)
        if not self.running or self.state != "recording":
            return
        # No lock here: list.append is atomic under the GIL, and keeping this
        # callback as short as possible is what keeps the keyboard hook alive.
        # _finish_recording stops the stream before reading the buffer.
        chunk = bytes(indata)
        max_bytes = self.settings.sample_rate * 2 * MAX_DICTATION_SECONDS
        remaining = max(0, max_bytes - self._audio_bytes)
        if remaining:
            bounded = chunk[:remaining]
            self._audio_buffer.append(bounded)
            self._audio_bytes += len(bounded)
        if status and not self._audio_status_warning_queued:
            self._audio_status_warning_queued = True
            status_text = str(status)
            self._queue_action(lambda: self._report_audio_status(status_text))
        if self._audio_bytes >= max_bytes and not self._capture_limit_queued:
            self._capture_limit_queued = True
            self._dictating = False
            self._queue_action(self._finish_recording_at_limit)

    def _report_audio_status(self, status: str) -> None:
        if self.running:
            self._emit(
                "Scribe Voice warning",
                f"Microphone capture reported dropped or overflowed audio: {status}",
            )

    def _finish_recording_at_limit(self) -> None:
        if self.running and self.state == "recording":
            self._emit(
                "Scribe Voice warning",
                f"Dictation reached the {MAX_DICTATION_SECONDS}-second safety limit and was stopped.",
            )
        self._finish_recording()

    def _finish_recording(self) -> None:  # pragma: no cover
        stream_stopped = self._stop_stream()
        self._announce_mic(False)
        with self._state_lock:
            # Finishing when we are not actually recording (a stale/duplicate
            # action after a mic error or stop) must not clobber that state.
            if self.state != "recording":
                self._audio_buffer = []
                self._audio_bytes = 0
                self._capture_limit_queued = False
                self._audio_status_warning_queued = False
                return
            pcm = b"".join(self._audio_buffer)
            self._audio_buffer = []
            self._audio_bytes = 0
            self._capture_limit_queued = False
            self._audio_status_warning_queued = False
        if not stream_stopped:
            message = "dictation was discarded because the microphone could not close safely"
            if self._set_state_if_running("error", message):
                self._emit("Scribe Voice error", message)
            return
        min_bytes = int(self.settings.sample_rate * 2 * self.settings.min_audio_seconds)
        if len(pcm) < min_bytes:
            self._return_to_idle()
            self._emit(
                "Scribe Voice",
                "No usable audio captured. Speak a little longer and try again.",
            )
            return
        # If a worker is somehow still busy, don't get stuck in "recording": reset.
        if not self._start_worker(self._transcribe_and_inject, pcm):
            self._return_to_idle()
            self._emit(
                "Scribe Voice error",
                "Dictation was not transcribed because Scribe Voice is still busy.",
            )

    def _stop_stream(self) -> bool:  # pragma: no cover
        """Stop and close the microphone stream, retaining it when close is uncertain."""
        with self._state_lock:
            stream = self._stream
        if stream is None:
            return True
        failures: list[str] = []
        try:
            stream.stop()
        except Exception as error:
            logger.warning("Could not stop microphone stream: %s", error)
            failures.append(f"stop failed: {error}")
        try:
            stream.close()
        except Exception as error:
            logger.warning("Could not close microphone stream: %s", error)
            failures.append(f"close failed: {error}")
        else:
            with self._state_lock:
                if self._stream is stream:
                    self._stream = None
        if failures:
            self._emit(
                "Scribe Voice warning",
                f"Microphone cleanup was incomplete ({'; '.join(failures)}).",
            )
        return not failures

    def _start_worker(self, target: Callable[..., None], *args: object) -> bool:  # pragma: no cover
        with self._state_lock:
            if not self.running or (self._worker is not None and self._worker.is_alive()):
                return False
            self._worker = threading.Thread(
                target=self._run_worker, args=(target, args), daemon=True
            )
            self._worker.start()
            return True

    def _run_worker(
        self, target: Callable[..., None], args: tuple[object, ...]
    ) -> None:  # pragma: no cover
        try:
            target(*args)
        except Exception as e:
            logger.exception("Voice worker failed")
            if self._set_state_if_running("error", str(e)):
                self._emit("Scribe Voice error", str(e))
            else:
                logger.warning("Voice worker failed during shutdown: %s", e)

    def _preload_model_worker(self) -> None:  # pragma: no cover
        # State is already "idle"; just warm the model. Do NOT force idle on
        # completion - a dictation may have started while we were loading.
        try:
            if not self.running:
                return
            with self._use_model(quiet=True):
                pass
            if self.running:
                self._warm_tts()
        except Exception as e:
            if self._set_state_if_running("error", str(e)):
                self._emit("Scribe Voice error", f"Model preload failed: {e}")
        finally:
            with self._state_lock:
                self.model_loading = False
                if self._preload_thread is threading.current_thread():
                    self._preload_thread = None
            self._notify()

    def _warm_tts(self) -> None:  # pragma: no cover
        """Warm the Kokoro model at startup so the first read-aloud is instant."""
        from scribe.voice.tts import (
            kokoro_assets_ready,
            kokoro_installed,
            load_kokoro,
            resolve_tts_backend,
            unload_kokoro,
        )

        backend = resolve_tts_backend(
            self.settings.tts_backend,
            kokoro_installed=kokoro_installed(),
            kokoro_ready=kokoro_assets_ready(),
        )
        if backend == "kokoro":
            try:
                load_kokoro()
                if not self.running:
                    unload_kokoro()
            except Exception as error:
                if self.running:
                    logger.warning("Neural voice warmup failed: %s", error)
                    self._emit(
                        "Scribe Voice warning",
                        f"Neural voice warmup failed ({error}); read-aloud will retry and "
                        "use the system voice if needed.",
                    )
                else:
                    logger.warning("Neural voice cleanup after shutdown failed: %s", error)

    def _transcribe_and_inject(self, pcm: bytes) -> None:  # pragma: no cover
        if not self._set_state_if_running("transcribing"):
            return
        with self._use_model() as model:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            try:
                write_wav(tmp_path, pcm, self.settings.sample_rate)
                segments, _info = model.transcribe(
                    str(tmp_path),
                    language=self.settings.language,
                    beam_size=5,
                    vad_filter=True,
                )
                text = clean_spoken_text(" ".join(seg.text.strip() for seg in segments))
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError as error:
                    logger.warning("Could not remove temporary dictation audio: %s", error)
                    self._emit(
                        "Scribe Voice warning",
                        f"Could not remove temporary dictation audio: {error}",
                    )

        if not self._is_running():
            return

        self.deliver_transcript(text)
        self._return_to_idle()

    def deliver_transcript(self, text: str) -> str:
        """Store or insert one finished transcript without loading a model.

        Returns ``cancelled``, ``empty``, ``stored``, or ``inserted``. Explicit
        insert, used by the Omarchy owner, never calls ``_inject_text``.
        """
        cleaned = clean_spoken_text(text)
        with self._state_lock:
            cancelled = self._cancel_requested
            if cancelled:
                self._cancel_requested = False
        if not self._is_running():
            return "stopped"
        if cancelled:
            self._emit("Scribe Voice", "Dictation cancelled")
            return "cancelled"
        if not cleaned:
            self._emit("Scribe Voice", "No speech detected")
            return "empty"

        preview = cleaned if len(cleaned) <= 120 else cleaned[:117] + "..."
        with self._state_lock:
            self.last_transcript = cleaned
        if self.explicit_insert:
            self._emit("Transcript ready", preview)
            return "stored"

        self._inject_text(cleaned)
        self._emit("Inserted", preview)
        return "inserted"

    def request_dictation(self) -> str:
        """Queue a dictate toggle on the existing capture path."""
        if not self.running:
            return "stopped"
        if self.paused:
            self._emit("Scribe Voice", "Voice is paused")
            return "paused"
        if self.state in {"transcribing", "speaking"}:
            self._emit("Scribe Voice", "Busy - finish the current action first")
            return "busy"
        stopping = self._dictating or self.state == "recording"
        action = self._finish_recording if stopping else self._begin_recording
        if not self._queue_action(action):
            return "busy"
        self._dictating = not stopping
        return "stopping" if stopping else "starting"

    def cancel_capture(self) -> str:
        """Drop the current capture or mark an in-flight transcription as cancelled."""
        self.stop_speaking()
        with self._state_lock:
            state = self.state
            self._dictating = False
            if state == "transcribing":
                self._cancel_requested = True
                pending = "cancel_requested"
            elif state == "recording":
                pending = "recording"
            elif state == "speaking":
                pending = "speaking"
            else:
                pending = "idle"
        if pending == "cancel_requested":
            self._emit("Scribe Voice", "Cancelling transcription")
            return "cancel_requested"
        if pending == "speaking":
            self._emit("Scribe Voice", "Stopped read-aloud")
            return "stopped_speaking"
        if pending != "recording":
            return "idle"

        stopped = self._stop_stream()
        with self._state_lock:
            self._audio_buffer = []
            self._audio_bytes = 0
            self._capture_limit_queued = False
            self._audio_status_warning_queued = False
            self._cancel_requested = False
        self._announce_mic(False)
        if not stopped:
            message = "microphone stream could not be closed safely while cancelling"
            if self._set_state_if_running("error", message):
                self._emit("Scribe Voice error", message)
            return "error"
        self._return_to_idle()
        self._emit("Scribe Voice", "Recording cancelled. Microphone off.")
        return "cancelled"

    def copy_last_transcript(self) -> bool:
        """Copy the stored transcript. This does not send keystrokes."""
        from scribe.cli.voice import clipboard_copy

        with self._state_lock:
            text = self.last_transcript
        if not text.strip():
            self._emit("Scribe Voice", "No transcript to copy")
            return False
        if not clipboard_copy(text):
            self._emit("Scribe Voice error", "Could not copy the transcript")
            return False
        preview = text if len(text) <= 120 else text[:117] + "..."
        self._emit("Copied", preview)
        return True

    def insert_last_transcript(self) -> str:
        """Insert the stored transcript only because a client asked for it."""
        with self._state_lock:
            text = self.last_transcript
        if not text.strip():
            self._emit("Scribe Voice", "No transcript to insert")
            return "empty"
        preview = text if len(text) <= 120 else text[:117] + "..."
        inserter = self._text_inserter
        if inserter is not None:
            try:
                outcome = inserter(text)
            except Exception as error:
                logger.warning("Text inserter failed: %s", error)
                self._emit("Scribe Voice error", f"Could not insert text: {error}")
                return "failed"
            if outcome == "inserted":
                self._emit("Inserted", preview)
            elif outcome == "copied":
                self._emit(
                    "Scribe Voice",
                    "Transcript is on the clipboard. Compositor paste was not confirmed.",
                )
            else:
                self._emit("Scribe Voice error", "Could not copy the transcript")
            return outcome
        try:
            self._inject_text(text)
        except Exception as error:
            logger.warning("Text insertion failed: %s", error)
            self._emit("Scribe Voice error", f"Could not insert text: {error}")
            return "failed"
        self._emit("Inserted", preview)
        return "inserted"

    def read_last_transcript(self) -> str:
        """Speak the stored transcript locally. This does not capture a selection."""
        with self._state_lock:
            text = self.last_transcript
            state = self.state
            running = self.running
        if not running:
            return "stopped"
        if state == "speaking":
            self.stop_speaking()
            self._emit("Scribe Voice", "Stopped read-aloud")
            return "stopped"
        if not text.strip():
            self._emit("Scribe Voice", "No transcript to read")
            return "empty"
        if not self._start_worker(self._speak_stored_transcript):
            self._emit("Scribe Voice", "Busy - finish the current action first")
            return "busy"
        return "accepted"

    def _speak_stored_transcript(self) -> None:
        if not self._set_state_if_running("speaking"):
            return
        with self._state_lock:
            text = self.last_transcript
        if text and self.running:
            preview = text if len(text) <= 120 else text[:117] + "..."
            self._emit("Reading transcript", preview)
            self._speak_text(text)
        else:
            self._emit("Scribe Voice", "No transcript to read")
        self._return_to_idle()

    def _load_model(self, *, quiet: bool = False) -> Any:  # pragma: no cover
        # Single check under the lock so a preload thread and the first dictation
        # never both build the model. The lock is uncontended on the hot path and
        # _load_model is called once per utterance (not per frame), so always
        # taking it is cheap. ``quiet`` suppresses the console line when a caller
        # (preload) renders its own loading spinner.
        with self._model_lock:
            if self._model is not None:
                return self._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as e:
                raise RuntimeError("faster-whisper is not installed") from e

            gpu = GPUConfig.detect()
            model_name = model_for_profile(self.settings.profile, gpu, self.settings.stt_model)
            device = "cuda" if gpu.has_gpu and gpu.cuda_available else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"
            self._model_name = model_name
            if not quiet:
                self.console.print(
                    f"[cyan]Loading voice model {model_name} on {device} ({compute_type})...[/cyan]"
                )
            self._model = WhisperModel(model_name, device=device, compute_type=compute_type)
            return self._model

    @contextmanager
    def _use_model(self, *, quiet: bool = False) -> Iterator[Any]:  # pragma: no cover
        """Keep the resident model loaded until one complete operation finishes."""
        with self._model_use_lock:
            if not self.running:
                raise RuntimeError("resident voice stopped before model use")
            self._model_users += 1
        try:
            yield self._load_model(quiet=quiet)
        finally:
            with self._model_use_lock:
                self._model_users -= 1
                should_unload = self._model_users == 0 and not self.running
            if should_unload:
                self._unload_model()

    def _unload_model_if_unused(self) -> bool:  # pragma: no cover
        """Unload now only when no preload or transcription operation owns the model."""
        with self._model_use_lock:
            if self._model_users != 0:
                return False
        return self._unload_model()

    def _unload_model(self) -> bool:  # pragma: no cover
        """Release the CTranslate2 model without allowing backend cleanup to hang."""
        import gc

        unload_thread: threading.Thread | None = None
        unload_result: list[Exception | None] | None = None
        unload_target: Any = None
        with self._model_lock:
            model = self._model
            if model is None:
                return True
            unload_thread = self._model_unload_thread
            unload_result = self._model_unload_result
            unload_target = self._model_unload_target
            if unload_thread is None:
                backend = getattr(model, "model", None)
                unload_model = getattr(backend, "unload_model", None)
                if not callable(unload_model):
                    self._model = None
                    self._model_name = None
                    del model
                    del backend
                    gc.collect()
                    return True

                result_holder: list[Exception | None] = []
                unload_result = result_holder

                def run_unload() -> None:
                    try:
                        unload_model()
                    except Exception as error:
                        result_holder.append(error)
                    else:
                        result_holder.append(None)

                unload_thread = threading.Thread(
                    target=run_unload,
                    daemon=True,
                    name="scribe-voice-model-unload",
                )
                unload_target = model
                self._model_unload_thread = unload_thread
                self._model_unload_result = unload_result
                self._model_unload_target = model
                self._model_unload_timeout_reported = False
                try:
                    unload_thread.start()
                except Exception as error:
                    self._model_unload_thread = None
                    self._model_unload_result = None
                    self._model_unload_target = None
                    logger.warning("Could not start voice model cleanup: %s", error)
                    self._emit(
                        "Scribe Voice warning",
                        f"Could not start voice model cleanup: {error}",
                    )
                    return False

        if unload_thread is None or unload_result is None:
            logger.error("Voice model cleanup state was incomplete")
            return False
        try:
            unload_thread.join(timeout=2.0)
            unload_alive = unload_thread.is_alive()
        except Exception as error:
            logger.warning("Could not inspect voice model cleanup: %s", error)
            self._emit(
                "Scribe Voice warning",
                f"Could not confirm voice model cleanup: {error}",
            )
            return False
        if unload_alive:
            if not self._model_unload_timeout_reported:
                self._model_unload_timeout_reported = True
                logger.error("Voice model cleanup did not finish within 2 seconds")
                self._emit(
                    "Scribe Voice warning",
                    "Voice model cleanup did not finish within 2 seconds; "
                    "another resident backend will not be started.",
                )
            return False

        if len(unload_result) == 1:
            unload_error = unload_result[0]
        else:
            unload_error = RuntimeError("model cleanup thread ended without reporting a result")

        with self._model_lock:
            if self._model_unload_thread is unload_thread:
                self._model_unload_thread = None
                self._model_unload_result = None
                self._model_unload_target = None
                self._model_unload_timeout_reported = False
            if unload_error is None and self._model is unload_target:
                self._model = None
                self._model_name = None
        gc.collect()
        if unload_error is not None:
            logger.warning("Could not explicitly unload the voice model: %s", unload_error)
            self._emit(
                "Scribe Voice warning",
                f"Could not explicitly release the voice model: {unload_error}",
            )
            return False
        return True

    def _inject_text(self, text: str) -> None:  # pragma: no cover
        try:
            from pynput import keyboard
        except ImportError as e:
            raise RuntimeError("text injection dependencies are missing") from e

        from scribe.cli.voice import clipboard_copy, clipboard_paste

        output = text
        if self.settings.append_space and output and not output.endswith((" ", "\n", "\t")):
            output += " "

        controller = keyboard.Controller()
        if self.settings.inject == "type":
            controller.type(output)
            return

        prior = clipboard_paste() if self.settings.restore_clipboard else None

        if self.settings.restore_clipboard and prior is None:
            self._emit(
                "Scribe Voice warning",
                "Could not preserve the clipboard; using typed insertion instead.",
            )
            controller.type(output)
            return

        if not clipboard_copy(output):
            # Clipboard is wedged; fall back to typing so the dictation is not lost.
            controller.type(output)
            return
        try:
            modifier = keyboard.Key.cmd if paste_modifier_name() == "cmd" else keyboard.Key.ctrl
            with controller.pressed(modifier):
                controller.press("v")
                controller.release("v")
        finally:
            if prior is not None:
                time.sleep(0.15)
                if not clipboard_copy(prior):
                    self._clipboard_restore_failed("text insertion")

    def _read_selection_and_speak(self) -> None:  # pragma: no cover
        if not self._set_state_if_running("speaking"):
            return
        text = self._read_selection_text()
        if not self.running:
            return
        if text:
            self._emit("Reading selection", text if len(text) <= 120 else text[:117] + "...")
            self._speak_text(text)
        else:
            self._emit("Scribe Voice", "No text selected to read")
        self._return_to_idle()

    def _read_selection_text(self) -> str:  # pragma: no cover
        try:
            from pynput import keyboard
        except ImportError as e:
            raise RuntimeError("selection read-aloud dependencies are missing") from e

        from scribe.cli.voice import clipboard_copy, clipboard_paste

        prior = clipboard_paste() if self.settings.restore_clipboard else None
        if self.settings.restore_clipboard and prior is None:
            raise RuntimeError("clipboard unavailable before selection capture")
        should_restore = prior is not None

        sentinel = f"__SCRIBE_SELECTION_SENTINEL_{uuid.uuid4()}__"
        if not clipboard_copy(sentinel):
            raise RuntimeError("clipboard unavailable for selection capture")

        raw = ""
        try:
            controller = keyboard.Controller()
            modifier = keyboard.Key.cmd if paste_modifier_name() == "cmd" else keyboard.Key.ctrl
            with controller.pressed(modifier):
                controller.press("c")
                controller.release("c")
            time.sleep(0.15)
            raw = clipboard_paste() or ""
            text = "" if raw == sentinel else clean_spoken_text(raw)
        finally:
            if should_restore and prior is not None:
                if not clipboard_copy(prior):
                    self._clipboard_restore_failed("selection capture")
            elif raw == sentinel:
                if not clipboard_copy(""):
                    self._clipboard_restore_failed("selection capture")
        return text

    def _clipboard_restore_failed(self, operation: str) -> None:
        message = (
            f"Could not restore the clipboard after {operation}; your previous "
            "clipboard contents may have changed."
        )
        logger.warning("%s", message)
        self._emit("Scribe Voice warning", message)

    def _speak_text(self, text: str) -> None:  # pragma: no cover
        from scribe.voice.tts import (
            kokoro_assets_ready,
            kokoro_installed,
            make_speaker,
            resolve_tts_backend,
        )

        backend = resolve_tts_backend(
            self.settings.tts_backend,
            kokoro_installed=kokoro_installed(),
            kokoro_ready=kokoro_assets_ready(),
        )
        speaker = make_speaker(
            backend,
            voice=self.settings.tts_voice,
            rate=self.settings.tts_rate,
            speed=self.tts_speed,
            console=self.console,
        )
        # Expose the speaker so a second read-hotkey tap can stop playback; stop()
        # runs on the listener thread and unblocks the blocking speak() below.
        active_speaker: Any | None = None
        with self._state_lock:
            if self.running:
                active_speaker = speaker
                self._tts_engine = speaker
        if active_speaker is None:
            self._close_speaker(speaker)
            return
        try:
            try:
                speaker.speak(text)
            except Exception as error:
                # A runtime synth/playback failure (bad model, device gone) must not
                # permanently break read-aloud. Fall back to the system voice once.
                if backend != "kokoro":
                    raise
                self._close_speaker(speaker)
                active_speaker = None
                self._emit(
                    "Scribe Voice warning",
                    f"Neural voice failed ({error}); using the system voice.",
                )
                if not self._is_running():
                    return
                fallback = make_speaker(
                    "pyttsx3", rate=self.settings.tts_rate, speed=self.tts_speed
                )
                with self._state_lock:
                    if self._is_running():
                        active_speaker = fallback
                        self._tts_engine = fallback
                    else:
                        active_speaker = None
                if active_speaker is None:
                    self._close_speaker(fallback)
                    return
                fallback.speak(text)
        finally:
            if active_speaker is not None:
                self._close_speaker(active_speaker)
            with self._state_lock:
                if self._tts_engine is active_speaker:
                    self._tts_engine = None

    def _close_speaker(self, speaker: Any) -> None:
        try:
            speaker.close()
        except Exception as error:
            logger.warning("Could not close voice playback: %s", error)
            self._emit("Scribe Voice warning", f"Could not close voice playback: {error}")
