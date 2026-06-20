"""Long-running voice service for tray and no-tray resident modes."""

from __future__ import annotations

import importlib.util
import platform
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from scribe.cli.voice import VOICE_INSTALL_HINT, clean_spoken_text, write_wav
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
        self.state: VoiceTrayState = "idle"
        self.error_message: str | None = None
        self.paused = False
        self.running = False

        self._state_lock = threading.RLock()
        self._callbacks: list[Callable[[VoiceTrayState], None]] = []
        self._listener: Any | None = None
        self._stream: Any | None = None
        self._audio_buffer: list[bytes] = []
        self._model: Any | None = None
        self._model_name: str | None = None
        self._worker: threading.Thread | None = None

    @property
    def status_text(self) -> str:
        """Human-readable status for the tray menu and terminal fallback."""
        if self.paused:
            return "Paused"
        if self.state == "error" and self.error_message:
            return f"Error: {self.error_message}"
        return {
            "idle": "Ready",
            "recording": "Recording",
            "transcribing": "Transcribing",
            "speaking": "Reading selection",
            "error": "Error",
            "stopped": "Stopped",
        }[self.state]

    def add_status_callback(self, callback: Callable[[VoiceTrayState], None]) -> None:
        """Register a callback invoked whenever the service state changes."""
        self._callbacks.append(callback)

    def set_paused(self, paused: bool) -> None:
        """Pause or resume hotkey actions without shutting the service down."""
        with self._state_lock:
            self.paused = paused
            if paused:
                self.hotkeys.reset()
                if self.state == "recording":
                    self._finish_recording()
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
        if preload_model:
            self._start_worker(self._preload_model_worker)
        self._set_state("idle")
        return True

    def stop(self) -> None:  # pragma: no cover
        """Stop hotkeys, audio capture, and pending resident service state."""
        self.running = False
        self.paused = False
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.stop()
        if self._stream is not None:
            self._stop_stream()
        self._set_state("stopped")

    def read_selection_now(self) -> bool:  # pragma: no cover
        """Start the selection read-aloud worker."""
        if self.paused:
            return False
        return self._start_worker(self._read_selection_and_speak)

    def _notify(self) -> None:
        for callback in self._callbacks:
            callback(self.state)

    def _set_state(self, state: VoiceTrayState, error: str | None = None) -> None:
        with self._state_lock:
            self.state = state
            self.error_message = error
        self._notify()

    def _on_press(self, key: object) -> None:  # pragma: no cover
        key_name = key_name_from_object(key)
        if key_name is None:
            return
        if self.paused:
            return
        dictate_started, read_started = self.hotkeys.press(key_name)
        if dictate_started:
            self._begin_recording()
            return
        if read_started and self.state != "recording":
            self.read_selection_now()

    def _on_release(self, key: object) -> None:  # pragma: no cover
        key_name = key_name_from_object(key)
        if key_name is None:
            return
        dictate_stopped = self.hotkeys.release(key_name)
        if dictate_stopped and self.state == "recording":
            self._finish_recording()

    def _begin_recording(self) -> None:  # pragma: no cover
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
                channels=1,
                dtype="int16",
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as e:
            self._stream = None
            self._set_state("error", f"microphone unavailable: {e}")
            return
        self._set_state("recording")

    def _audio_callback(
        self,
        indata: Any,
        frames: int,
        time_info: object,
        status: object,
    ) -> None:  # pragma: no cover
        _ = (frames, time_info, status)
        with self._state_lock:
            self._audio_buffer.append(bytes(indata))

    def _finish_recording(self) -> None:  # pragma: no cover
        self._stop_stream()
        with self._state_lock:
            pcm = b"".join(self._audio_buffer)
            self._audio_buffer = []
        min_bytes = int(self.settings.sample_rate * 2 * self.settings.min_audio_seconds)
        if len(pcm) < min_bytes:
            self._set_state("idle")
            return
        self._start_worker(self._transcribe_and_inject, pcm)

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

    def _preload_model_worker(self) -> None:  # pragma: no cover
        self._load_model()
        if self.state != "error":
            self._set_state("idle")

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
        self._set_state("idle")

    def _load_model(self) -> Any:  # pragma: no cover
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
        self.console.print(
            f"[cyan]Loading voice model {model_name} on {device} ({compute_type})...[/cyan]"
        )
        self._model = WhisperModel(model_name, device=device, compute_type=compute_type)
        return self._model

    def _inject_text(self, text: str) -> None:  # pragma: no cover
        try:
            import pyperclip
            from pynput import keyboard
        except ImportError as e:
            raise RuntimeError("text injection dependencies are missing") from e

        output = text
        if self.settings.append_space and output and not output.endswith((" ", "\n", "\t")):
            output += " "

        controller = keyboard.Controller()
        if self.settings.inject == "type":
            controller.type(output)
            return

        prior: str | None = None
        if self.settings.restore_clipboard:
            try:
                prior = pyperclip.paste()
            except Exception:
                prior = None

        try:
            pyperclip.copy(output)
            modifier = keyboard.Key.cmd if platform.system() == "Darwin" else keyboard.Key.ctrl
            with controller.pressed(modifier):
                controller.press("v")
                controller.release("v")
        finally:
            if prior is not None:
                time.sleep(0.15)
                with suppress(Exception):
                    pyperclip.copy(prior)

    def _read_selection_and_speak(self) -> None:  # pragma: no cover
        self._set_state("speaking")
        text = self._read_selection_text()
        if text:
            self._speak_text(text)
        self._set_state("idle")

    def _read_selection_text(self) -> str:  # pragma: no cover
        try:
            import pyperclip
            from pynput import keyboard
        except ImportError as e:
            raise RuntimeError("selection read-aloud dependencies are missing") from e

        prior: str | None = None
        should_restore = False
        if self.settings.restore_clipboard:
            try:
                prior = pyperclip.paste()
                should_restore = True
            except Exception:
                prior = None

        sentinel = f"__SCRIBE_SELECTION_SENTINEL_{uuid.uuid4()}__"
        try:
            pyperclip.copy(sentinel)
        except Exception as e:
            raise RuntimeError("clipboard unavailable for selection capture") from e

        raw = ""
        try:
            controller = keyboard.Controller()
            modifier = keyboard.Key.cmd if platform.system() == "Darwin" else keyboard.Key.ctrl
            with controller.pressed(modifier):
                controller.press("c")
                controller.release("c")
            time.sleep(0.15)
            raw = pyperclip.paste() or ""
            text = "" if raw == sentinel else clean_spoken_text(raw)
        finally:
            if should_restore and prior is not None:
                with suppress(Exception):
                    pyperclip.copy(prior)
            elif raw == sentinel:
                with suppress(Exception):
                    pyperclip.copy("")
        return text

    def _speak_text(self, text: str) -> None:  # pragma: no cover
        try:
            import pyttsx3
        except ImportError as e:
            raise RuntimeError("pyttsx3 is not installed") from e

        engine = pyttsx3.init()
        if self.settings.tts_rate is not None:
            engine.setProperty("rate", self.settings.tts_rate)
        if self.settings.tts_voice:
            needle = self.settings.tts_voice.lower()
            for candidate in engine.getProperty("voices"):
                haystack = (
                    f"{getattr(candidate, 'name', '')} {getattr(candidate, 'id', '')}".lower()
                )
                if needle in haystack:
                    engine.setProperty("voice", candidate.id)
                    break
        engine.say(text)
        engine.runAndWait()
