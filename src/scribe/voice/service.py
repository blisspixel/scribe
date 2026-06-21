"""Long-running voice service for tray and no-tray resident modes."""

from __future__ import annotations

import importlib.util
import queue
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
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

VoiceTrayState = Literal["idle", "recording", "transcribing", "speaking", "error", "stopped"]


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


def dependency_report(*, include_tray: bool) -> list[DependencyStatus]:
    """Return optional dependency availability for the requested resident mode."""
    deps = [*VOICE_DEPENDENCIES]
    if include_tray:
        deps.extend(TRAY_DEPENDENCIES)
    return [
        DependencyStatus(dependency=dep, available=importlib.util.find_spec(dep.module) is not None)
        for dep in deps
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
            "Windows tray, hotkeys, and startup are CI-validated",
        )
    if system == "Darwin":
        return TrayPlatformMatrix(
            system,
            "experimental",
            "macOS tray is experimental: grant Input Monitoring and Microphone "
            "privacy permissions; hardware matrix is not CI-proven",
        )
    if system == "Linux":
        return TrayPlatformMatrix(
            system,
            "experimental",
            "Linux tray is experimental: requires a graphical session (X11 or Wayland); "
            "Wayland global hotkeys are unreliable",
        )
    return TrayPlatformMatrix(
        system,
        "unsupported",
        f"Resident tray is not validated on {system}",
    )


def graphical_session_detected(
    *,
    display: str = "",
    wayland_display: str = "",
    session_type: str = "",
) -> bool:
    """Return True when a Linux graphical session is likely present."""
    if display.strip():
        return True
    if wayland_display.strip():
        return True
    return session_type.strip().lower() in ("x11", "wayland")


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
                "Settings > Privacy & Security, then restart it. Until granted, "
                "F9/F8 and mic capture silently do nothing.",
            )
        )
    elif system == "Linux":
        is_wayland = session_type.strip().lower() == "wayland" or bool(wayland_display.strip())
        if is_wayland:
            advisories.append(
                ReadinessAdvisory(
                    "warning",
                    "Linux/Wayland detected: global hotkeys via pynput are "
                    "unreliable here. Use `scribe tray --no-tray` and bind a "
                    "desktop shortcut to `scribe listen` / `scribe say --selection`, "
                    "or run an X11 session.",
                )
            )
        else:
            advisories.append(
                ReadinessAdvisory(
                    "info",
                    "Linux/X11: global hotkeys via pynput are supported; a local "
                    "display is still required (not headless/SSH without X).",
                )
            )

    if inject.strip().lower() == "type":
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

    def __init__(self, settings: TraySettings, console: Console) -> None:
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
        self._callbacks: list[Callable[[VoiceTrayState], None]] = []
        self._listener: Any | None = None
        self._stream: Any | None = None
        self._audio_buffer: list[bytes] = []
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
        self._actions: queue.Queue[Callable[[], object] | None] = queue.Queue()
        self._dispatcher: threading.Thread | None = None
        self._dictating = False
        # Serializes model loads so a preload thread and a first dictation cannot
        # both construct the model (double load / VRAM waste).
        self._model_lock = threading.Lock()
        self._watchdog: threading.Thread | None = None

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

    def set_notifier(self, notifier: Callable[[str, str], None] | None) -> None:
        """Set a user-facing notifier (title, message), e.g. tray notifications."""
        self._notifier = notifier

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

        dictate = key if role == "dictate" else self.dictate_hotkey
        read = key if role == "read" else self.read_hotkey
        if dictate == read:
            self._emit("Scribe Voice", "Dictate and read keys must differ")
            return False
        try:
            dictate_spec = parse_hotkey(dictate)
            read_spec = parse_hotkey(read)
        except ValueError:
            return False
        self.dictate_hotkey = dictate
        self.read_hotkey = read
        self.hotkeys = HotkeyState(dictate_spec, read_spec)  # listener reads this live
        self._dictating = False
        self._persist_hotkeys()
        self._emit("Scribe Voice", f"{role.capitalize()} key -> {key.upper()}")
        return True

    def _persist_hotkeys(self) -> None:
        from scribe.config_file import load_config_file, save_config_file

        with suppress(Exception):
            config = load_config_file()
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
            with suppress(Exception):
                notifier(title, message)
                return
        with suppress(Exception):
            self.console.print(f"[cyan]{title}[/cyan] [dim]{message}[/dim]")

    def add_status_callback(self, callback: Callable[[VoiceTrayState], None]) -> None:
        """Register a callback invoked whenever the service state changes."""
        self._callbacks.append(callback)

    def set_paused(self, paused: bool) -> None:
        """Pause or resume hotkey actions without shutting the service down.

        Pausing mid-recording discards the in-progress capture (rather than
        injecting a surprise partial dictation). Stream teardown happens OUTSIDE
        the state lock: holding it across stream.stop() would deadlock against the
        audio callback, which needs the same lock.
        """
        discard = False
        with self._state_lock:
            self.paused = paused
            if paused:
                self.hotkeys.reset()
                self._dictating = False
                discard = self.state == "recording"
        if discard:
            self._stop_stream()
            with self._state_lock:
                self._audio_buffer = []
            self._set_state("idle")
        self._notify()

    def toggle_pause(self) -> bool:
        """Toggle pause state and return the new state."""
        self.set_paused(not self.paused)
        return self.paused

    def start_hotkeys(self, *, preload_model: bool = False) -> bool:  # pragma: no cover
        """Start the global hotkey listener."""
        missing = missing_dependency_packages(include_tray=False)
        if missing:
            self.console.print(VOICE_INSTALL_HINT, markup=False)
            self.console.print(f"Missing packages: {', '.join(missing)}")
            return False

        try:
            from pynput import keyboard
        except ImportError:
            self.console.print(VOICE_INSTALL_HINT, markup=False)
            return False

        try:
            self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            self._listener.start()
        except Exception as e:
            if self._listener is not None:
                with suppress(Exception):
                    self._listener.stop()
            self.running = False
            self._listener = None
            self._set_state("error", f"hotkey listener unavailable: {e}")
            self.console.print(
                "[red]Could not start global hotkeys.[/red] "
                "Check OS keyboard-monitoring permissions or change the hotkeys."
            )
            return False

        self.running = True
        self._dispatcher = threading.Thread(target=self._dispatch_loop, daemon=True)
        self._dispatcher.start()
        self._watchdog = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog.start()
        self._set_state("idle")
        if preload_model:
            # Preload on its OWN thread, not the shared worker slot: otherwise a
            # dictation in the first few seconds (while the model loads) cannot
            # start its transcription worker and is silently dropped.
            self.model_loading = True
            self._notify()
            threading.Thread(target=self._preload_model_worker, daemon=True).start()
        return True

    def stop(self) -> None:  # pragma: no cover
        """Stop hotkeys, audio capture, and pending resident service state."""
        self.running = False
        self.paused = False
        self._actions.put(None)  # unblock the dispatcher so it can exit
        listener = self._listener
        self._listener = None
        if listener is not None:
            with suppress(Exception):
                listener.stop()
        if self._stream is not None:
            self._stop_stream()
        # Join background threads so no transcription/injection runs after stop.
        for thread in (self._dispatcher, self._worker):
            if thread is not None and thread.is_alive():
                thread.join(timeout=2.0)
        self.state = "stopped"
        self.error_message = None
        self._notify()

    def _dispatch_loop(self) -> None:  # pragma: no cover
        """Run hotkey actions off the listener thread, one at a time, in order."""
        while self.running:
            try:
                action = self._actions.get(timeout=0.2)
            except queue.Empty:
                continue
            if action is None:
                return
            try:
                action()
            except Exception as e:
                self._set_state("error", str(e))
                self._emit("Scribe Voice error", str(e))

    def _watchdog_loop(self) -> None:  # pragma: no cover
        """Recreate the global hotkey listener if its thread ever dies.

        Windows can silently remove a low-level keyboard hook (e.g. if any hook
        callback ever times out), after which the listener thread exits. A pynput
        Listener cannot be restarted, so we build a fresh one. Cheap insurance for
        a utility meant to run all day.
        """
        while self.running:
            time.sleep(2.0)
            listener = self._listener
            if listener is None or listener.is_alive():
                continue
            with suppress(Exception):
                from pynput import keyboard

                fresh = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
                fresh.start()
                self._listener = fresh
                self.hotkeys.reset()
                self._dictating = False
                self._emit("Scribe Voice", "Hotkeys reconnected")

    def read_selection_now(self) -> bool:  # pragma: no cover
        """Start the selection read-aloud worker."""
        if self.paused or not self.running:
            return False
        if not self._start_worker(self._read_selection_and_speak):
            self._emit("Scribe Voice", "Busy - finish the current action first")
            return False
        return True

    def _notify(self) -> None:
        for callback in list(self._callbacks):  # snapshot: callbacks may run cross-thread
            with suppress(Exception):
                callback(self.state)

    def _set_state(self, state: VoiceTrayState, error: str | None = None) -> None:
        with self._state_lock:
            self.state = state
            self.error_message = error
        self._notify()

    def _return_to_idle(self) -> None:
        """Go idle only if still running, so a worker finishing after stop() does
        not clobber the terminal 'stopped' state."""
        if self.running:
            self._set_state("idle")

    def _on_press(self, key: object) -> None:  # pragma: no cover
        key_name = key_name_from_object(key)
        if key_name is None:
            return
        if self.paused:
            return
        dictate_started, read_started = self.hotkeys.press(key_name)
        # IMPORTANT: this runs inside the global keyboard hook. Do only fast,
        # in-memory work here and enqueue device/heavy actions - opening the mic on
        # this thread breaks subsequent key capture on Windows.
        if dictate_started:
            if self.settings.activation == "toggle":
                # tap toggles: stop+transcribe if dictating, else start.
                if self._dictating:
                    self._dictating = False
                    self._actions.put(self._finish_recording)
                else:
                    self._dictating = True
                    self._actions.put(self._begin_recording)
            elif not self._dictating:
                # hold: press starts; release stops (handled below).
                self._dictating = True
                self._actions.put(self._begin_recording)
            return
        if read_started:
            # Same key reads the selection and stops playback mid-sentence,
            # matching macOS Speak Selection and Edge Read Aloud. stop_speaking is
            # instant (sets an event), so it is safe inline.
            if self.state == "speaking":
                self.stop_speaking()
            elif not self._dictating:
                self._actions.put(self.read_selection_now)

    def _on_release(self, key: object) -> None:  # pragma: no cover
        key_name = key_name_from_object(key)
        if key_name is None:
            return
        # Always clear the chord so the next press is a fresh edge, but only act on
        # the release in hold (push-to-talk) mode. In toggle mode the press handles
        # both start and stop, so releasing the key must not end dictation.
        dictate_stopped = self.hotkeys.release(key_name)
        if self.settings.activation != "hold":
            return
        if dictate_stopped and self._dictating:
            self._dictating = False
            self._actions.put(self._finish_recording)

    def stop_speaking(self) -> None:  # pragma: no cover
        """Interrupt read-aloud playback (the same hotkey that started it)."""
        engine = self._tts_engine
        if engine is not None:
            with suppress(Exception):
                engine.stop()

    def _begin_recording(self) -> None:  # pragma: no cover
        if not self.running:
            return
        if self.state in {"recording", "transcribing", "speaking"}:
            return
        try:
            import sounddevice as sd
        except ImportError:
            self.console.print(VOICE_INSTALL_HINT, markup=False)
            return

        self._audio_buffer = []
        try:
            self._stream = sd.RawInputStream(
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
            self._stream.start()
        except Exception as e:
            self._stream = None
            self._dictating = False
            self._set_state("error", f"microphone unavailable: {e}")
            self._emit("Scribe Voice", f"Microphone unavailable: {e}")
            return
        self._set_state("recording")
        verb = "tap to insert" if self.settings.activation == "toggle" else "release to insert"
        self._emit("Scribe Voice", f"Recording... speak, then {verb}")

    def _audio_callback(
        self,
        indata: Any,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:  # pragma: no cover
        _ = (frames, time_info, status)
        # No lock here: list.append is atomic under the GIL, and keeping this
        # callback as short as possible is what keeps the keyboard hook alive.
        # _finish_recording stops the stream before reading the buffer.
        self._audio_buffer.append(bytes(indata))

    def _finish_recording(self) -> None:  # pragma: no cover
        self._stop_stream()
        with self._state_lock:
            # Finishing when we are not actually recording (a stale/duplicate
            # action after a mic error or stop) must not clobber that state.
            if self.state != "recording":
                self._audio_buffer = []
                return
            pcm = b"".join(self._audio_buffer)
            self._audio_buffer = []
        min_bytes = int(self.settings.sample_rate * 2 * self.settings.min_audio_seconds)
        if len(pcm) < min_bytes:
            self._return_to_idle()
            return
        # If a worker is somehow still busy, don't get stuck in "recording": reset.
        if not self._start_worker(self._transcribe_and_inject, pcm):
            self._return_to_idle()

    def _stop_stream(self) -> None:  # pragma: no cover
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        with suppress(Exception):
            stream.stop()
        with suppress(Exception):
            stream.close()

    def _start_worker(self, target: Callable[..., None], *args: object) -> bool:  # pragma: no cover
        with self._state_lock:
            if self._worker is not None and self._worker.is_alive():
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
            self._set_state("error", str(e))
            self._emit("Scribe Voice error", str(e))

    def _preload_model_worker(self) -> None:  # pragma: no cover
        # State is already "idle"; just warm the model. Do NOT force idle on
        # completion - a dictation may have started while we were loading.
        try:
            self._load_model(quiet=True)
            self._warm_tts()
        except Exception as e:
            self._set_state("error", str(e))
        finally:
            self.model_loading = False
            self._notify()

    def _warm_tts(self) -> None:  # pragma: no cover
        """Warm the Kokoro model at startup so the first read-aloud is instant."""
        from scribe.voice.tts import (
            kokoro_assets_ready,
            kokoro_installed,
            load_kokoro,
            resolve_tts_backend,
        )

        backend = resolve_tts_backend(
            self.settings.tts_backend,
            kokoro_installed=kokoro_installed(),
            kokoro_ready=kokoro_assets_ready(),
        )
        if backend == "kokoro":
            with suppress(Exception):
                load_kokoro()

    def _transcribe_and_inject(self, pcm: bytes) -> None:  # pragma: no cover
        self._set_state("transcribing")
        model = self._load_model()
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
            tmp_path.unlink(missing_ok=True)

        if text:
            self._inject_text(text)
            self._emit("Inserted", text if len(text) <= 120 else text[:117] + "...")
        else:
            self._emit("Scribe Voice", "No speech detected")
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
                clipboard_copy(prior)

    def _read_selection_and_speak(self) -> None:  # pragma: no cover
        self._set_state("speaking")
        text = self._read_selection_text()
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
                clipboard_copy(prior)
            elif raw == sentinel:
                clipboard_copy("")
        return text

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
        self._tts_engine = speaker
        try:
            speaker.speak(text)
        except Exception as e:
            # A runtime synth/playback failure (bad model, device gone) must not
            # permanently break read-aloud. Fall back to the system voice once.
            with suppress(Exception):
                speaker.close()
            if backend == "kokoro":
                self.console.print(
                    f"[yellow]Neural voice failed ({e}); using the system voice.[/yellow]"
                )
                fallback = make_speaker(
                    "pyttsx3", rate=self.settings.tts_rate, speed=self.tts_speed
                )
                self._tts_engine = fallback
                with suppress(Exception):
                    fallback.speak(text)
                with suppress(Exception):
                    fallback.close()
            else:
                raise
        finally:
            self._tts_engine = None
