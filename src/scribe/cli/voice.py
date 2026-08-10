"""Voice I/O mode: dictation (speech to type) and read-aloud (text to speech).

This is a deliberate, opt-in real-time mode that sits OUTSIDE the batch
transcription pipeline. The streaming exclusion still holds for that pipeline
(see the ROADMAP non-goals and ADR-008); voice I/O is a separate product
surface a user adopts on purpose.

The module separates pure, testable logic from runtime I/O. The pure parts,
utterance endpointing, the hotkey toggle, and turning a transcript or notes file
into speakable text, have no optional dependency and are unit-tested. The runtime
wrappers touch the microphone, keyboard, and a TTS engine; they live behind the
optional ``scribe[voice]`` extra and fail with a clear install message when a
dependency is absent.
"""

from __future__ import annotations

import queue
import re
import threading
import tomllib
import uuid
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rich.console import Console

VOICE_INSTALL_HINT = (
    "Voice I/O needs the optional extra. Install it with:\n"
    '  pip install "scribe[voice]"\n'
    "(provides sounddevice, pynput, pyperclip, and pyttsx3)."
)
MAX_DICTATION_SECONDS = 300


# --- Pure logic --------------------------------------------------------------


def frame_is_speech(rms: float, threshold: float) -> bool:
    """True when a frame's RMS energy clears the speech threshold."""
    return rms >= threshold


@dataclass
class UtteranceSegmenter:
    """Detects utterance boundaries from a stream of per-frame speech flags.

    An utterance opens once ``min_speech_frames`` consecutive speech frames are
    seen and closes after ``min_silence_frames`` consecutive silence frames. This
    is the endpointing for dictation, kept pure so it is testable with a synthetic
    flag stream instead of a live microphone.
    """

    min_speech_frames: int = 3
    min_silence_frames: int = 15
    _in_speech: bool = field(default=False, init=False)
    _speech_run: int = field(default=0, init=False)
    _silence_run: int = field(default=0, init=False)
    _start: int | None = field(default=None, init=False)
    _last_index: int = field(default=-1, init=False)

    def push(self, index: int, is_speech: bool) -> tuple[int, int] | None:
        """Feed one frame; return (start, end) when an utterance just closed."""
        self._last_index = index
        if is_speech:
            self._speech_run += 1
            self._silence_run = 0
            if not self._in_speech and self._speech_run >= self.min_speech_frames:
                self._in_speech = True
                self._start = index - self._speech_run + 1
            return None

        self._speech_run = 0
        if not self._in_speech:
            return None
        self._silence_run += 1
        if self._silence_run >= self.min_silence_frames:
            start = self._start if self._start is not None else index
            end = index - self._silence_run + 1
            self._reset_span()
            return (start, max(start, end))
        return None

    def flush(self) -> tuple[int, int] | None:
        """End of stream: emit a trailing utterance if one is still open."""
        if self._in_speech and self._start is not None:
            span = (self._start, self._last_index + 1)
            self._reset_span()
            return span
        return None

    def _reset_span(self) -> None:
        self._in_speech = False
        self._speech_run = 0
        self._silence_run = 0
        self._start = None

    def reset(self) -> None:
        """Fully reset, including the frame counter, between dictation buffers."""
        self._reset_span()
        self._last_index = -1


@dataclass
class HotkeyToggle:
    """Tracks listening on/off for a push-to-toggle dictation hotkey."""

    active: bool = False
    toggles: int = 0

    def toggle(self) -> bool:
        self.active = not self.active
        self.toggles += 1
        return self.active


_FRONTMATTER = re.compile(r"^---\n.*?\n---\n", re.DOTALL)
_HEADER = re.compile(r"^#{1,6}\s*")
_BULLET = re.compile(r"^[-*+]\s+")
_NUMBERED = re.compile(r"^\d+\.\s+")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_RULE_CHARS = set("-=_─-")  # hyphen, equals, underscore, box-rule, em-dash


def speakable_from_markdown(text: str) -> str:
    """Turn transcript or notes text (markdown or plain) into a spoken-word string.

    Drops YAML frontmatter, code fences, horizontal rules, and the leading
    markdown markers so a TTS engine reads the words and not the syntax.
    """
    # Normalize newlines first so the frontmatter and fence handling work the same
    # on CRLF (Windows) files as on LF; otherwise frontmatter would leak into speech.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _FRONTMATTER.sub("", text)
    out: list[str] = []
    in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not stripped:
            continue
        if len(stripped) >= 3 and set(stripped) <= _RULE_CHARS:
            continue  # horizontal rule or separator
        stripped = _HEADER.sub("", stripped)
        stripped = _BULLET.sub("", stripped)
        stripped = _NUMBERED.sub("", stripped)
        stripped = _LINK.sub(r"\1", stripped)
        stripped = stripped.replace("**", "").replace("__", "").replace("`", "")
        out.append(stripped)
    return " ".join(out).strip()


def extract_speakable_text(path: Path) -> str:
    """Read a .txt or .md file and return its speakable text."""
    return speakable_from_markdown(path.read_text(encoding="utf-8"))


def write_wav(path: Path, pcm16: bytes, sample_rate: int) -> None:
    """Write 16-bit mono PCM to a WAV file (used to hand utterances to a backend)."""
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm16)


# --- Pure option resolution --------------------------------------------------

LISTEN_MODES = ("toggle", "hold", "continuous")
INJECT_METHODS = ("paste", "type")


def resolve_listen_mode(value: str | None) -> str:
    """Validate the dictation mode.

    ``toggle`` (tap to start, tap again to insert) is the default and matches how
    Windows Voice Access and macOS hands-free dictation work. ``hold`` is
    push-to-talk; ``continuous`` is always-listening with silence endpointing.
    """
    resolved = (value or "toggle").strip().lower()
    if resolved not in LISTEN_MODES:
        raise ValueError(f"--mode must be one of {', '.join(LISTEN_MODES)}, got '{value}'")
    return resolved


def resolve_inject_method(value: str | None) -> str:
    """Validate the text-injection method. ``paste`` is the default."""
    resolved = (value or "paste").strip().lower()
    if resolved not in INJECT_METHODS:
        raise ValueError(f"--inject must be one of {', '.join(INJECT_METHODS)}, got '{value}'")
    return resolved


def resolve_say_source(path: Path | None, use_selection: bool, use_clipboard: bool) -> str:
    """Pick exactly one read-aloud source: a file, the selection, or the clipboard."""
    chosen = [
        name
        for name, on in (
            ("file", path is not None),
            ("selection", use_selection),
            ("clipboard", use_clipboard),
        )
        if on
    ]
    if not chosen:
        raise ValueError("Provide a file to read, or use --selection or --clipboard.")
    if len(chosen) > 1:
        raise ValueError("Choose only one of: a file, --selection, or --clipboard.")
    return chosen[0]


def clean_spoken_text(text: str) -> str:
    """Collapse whitespace so selected/clipboard text reads naturally."""
    return " ".join(text.split())


def clipboard_copy(value: str, *, attempts: int = 5) -> bool:  # pragma: no cover - clipboard I/O
    """Copy to the clipboard, retrying transient failures.

    On Windows ``OpenClipboard`` fails intermittently when another process holds
    the clipboard (common right after the user copied something). Without a retry,
    a single transient failure silently drops a dictation, so retry briefly.
    """
    import time

    try:
        import pyperclip
    except ImportError:
        return False
    for index in range(attempts):
        try:
            pyperclip.copy(value)
            return True
        except Exception:
            if index == attempts - 1:
                return False
            time.sleep(0.05)
    return False


def clipboard_paste(*, attempts: int = 5) -> str | None:  # pragma: no cover - clipboard I/O
    """Read the clipboard, retrying transient Windows failures. None on failure."""
    import time

    try:
        import pyperclip
    except ImportError:
        return None
    for index in range(attempts):
        try:
            result = pyperclip.paste()
            return result if isinstance(result, str) else None
        except Exception:
            if index == attempts - 1:
                return None
            time.sleep(0.05)
    return None


def paste_modifier_name(system: str | None = None) -> str:
    """Name of the clipboard modifier key for copy/paste injection.

    macOS uses Cmd for copy/paste; Windows and Linux use Ctrl. Kept pure (the OS
    name is injectable) so the platform decision is unit-testable without a real
    keyboard, and so every injection/selection path resolves the modifier the same
    way instead of hand-rolling the ``platform.system()`` check per call site.
    """
    import platform as _platform

    resolved = system if system is not None else _platform.system()
    return "cmd" if resolved == "Darwin" else "ctrl"


def _modifier_key(keyboard: Any) -> Any:  # pragma: no cover - trivial pynput mapping
    """Map :func:`paste_modifier_name` to the matching ``pynput`` key object."""
    return keyboard.Key.cmd if paste_modifier_name() == "cmd" else keyboard.Key.ctrl


# --- Runtime: read-aloud -----------------------------------------------------


def run_say(
    console: Console,
    path: Path | None = None,
    *,
    rate: int | None = None,
    voice: str | None = None,
    speed: float | None = None,
    use_selection: bool = False,
    use_clipboard: bool = False,
) -> int:
    """Read a file, the current selection, or the clipboard aloud with a local voice."""
    try:
        source = resolve_say_source(path, use_selection, use_clipboard)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return 1

    if source == "file":
        if path is None or not path.exists():
            console.print(f"[red]File not found: {path}[/red]")
            return 1
        title = path.name
        try:
            text = extract_speakable_text(path)
        except (OSError, UnicodeError) as error:
            console.print(f"[red]Could not read {path}:[/red] {error}")
            return 1
    elif source == "clipboard":
        title = "clipboard"
        text = _read_clipboard(console)
    else:
        title = "selection"
        text = _read_selection(console)

    if not text:
        console.print("[yellow]Nothing to read.[/yellow]")
        return 1

    return _speak(console, title, text, rate=rate, voice=voice, speed=speed)


def _read_clipboard(console: Console) -> str:  # pragma: no cover - clipboard I/O
    try:
        import pyperclip
    except ImportError:
        console.print(VOICE_INSTALL_HINT, markup=False)
        return ""
    try:
        return clean_spoken_text(pyperclip.paste() or "")
    except Exception as error:
        console.print(f"[red]Could not read the clipboard:[/red] {error}")
        return ""


def _read_selection(console: Console) -> str:  # pragma: no cover - keyboard/clipboard I/O
    """Copy the current selection (Ctrl+C / Cmd+C) and return it as speakable text."""
    try:
        import time

        import pyperclip
        from pynput import keyboard
    except ImportError:
        console.print(VOICE_INSTALL_HINT, markup=False)
        return ""

    prior: str | None = None
    should_restore = False
    try:
        prior = pyperclip.paste()
        should_restore = True
    except Exception as error:
        console.print(f"[red]Could not read the clipboard before copying:[/red] {error}")
        return ""

    sentinel = f"__SCRIBE_SELECTION_SENTINEL_{uuid.uuid4()}__"
    try:
        pyperclip.copy(sentinel)
    except Exception as error:
        console.print(f"[red]Could not prepare the clipboard for selection capture:[/red] {error}")
        return ""

    raw = ""
    try:
        controller = keyboard.Controller()
        with controller.pressed(_modifier_key(keyboard)):
            controller.press("c")
            controller.release("c")
        time.sleep(0.15)  # give the OS a moment to populate the clipboard
        raw = pyperclip.paste() or ""
        return "" if raw == sentinel else clean_spoken_text(raw)
    except Exception as error:
        console.print(f"[red]Could not copy the current selection:[/red] {error}")
        return ""
    finally:
        if should_restore and prior is not None:
            try:
                pyperclip.copy(prior)
            except Exception as error:
                console.print(f"[yellow]Could not restore the clipboard:[/yellow] {error}")
        elif raw == sentinel:
            try:
                pyperclip.copy("")
            except Exception as error:
                console.print(
                    f"[yellow]Could not clear selection clipboard state:[/yellow] {error}"
                )


def _speak(  # pragma: no cover - drives the local TTS engine; no audio device in CI
    console: Console,
    title: str,
    text: str,
    *,
    rate: int | None,
    voice: str | None,
    speed: float | None = None,
) -> int:
    """Speak ``text`` with the best available backend (Kokoro if set up, else pyttsx3).

    Backend selection is adaptive: Kokoro is used when installed and its voice
    files are present, otherwise the OS voice. Isolated so the engine I/O stays
    out of CI.
    """
    from scribe.config_file import load_config_file_strict
    from scribe.voice.tts import (
        kokoro_assets_ready,
        kokoro_installed,
        make_speaker,
        resolve_tts_backend,
        resolve_tts_speed,
    )

    # Read the resident-voice config so `scribe say` honors the same TTS backend,
    # voice, and speed the tray uses (CLI flags still override).
    try:
        tray_table = load_config_file_strict().get("voice", {})
    except (OSError, tomllib.TOMLDecodeError) as error:
        console.print(f"[red]Could not read resident voice settings safely:[/red] {error}")
        return 1
    tray_cfg = tray_table.get("tray", {}) if isinstance(tray_table, dict) else {}
    configured_backend = tray_cfg.get("tts_backend") if isinstance(tray_cfg, dict) else None
    configured_voice = tray_cfg.get("tts_voice") if isinstance(tray_cfg, dict) else None
    configured_speed = tray_cfg.get("tts_speed") if isinstance(tray_cfg, dict) else None
    effective_speed = resolve_tts_speed(speed if speed is not None else configured_speed)

    try:
        backend = resolve_tts_backend(
            configured_backend,
            kokoro_installed=kokoro_installed(),
            kokoro_ready=kokoro_assets_ready(),
        )
        speaker = make_speaker(
            backend,
            voice=voice or configured_voice,
            rate=rate,
            speed=effective_speed,
            console=console,
        )
    except ImportError:
        console.print(VOICE_INSTALL_HINT, markup=False)
        return 1
    except Exception as error:
        console.print(f"[red]Could not initialize read-aloud:[/red] {error}")
        return 1

    # Esc stops playback mid-sentence. The pynput listener runs on its own thread,
    # so speaker.stop() interrupts the blocking speak() below.
    listener = None
    playback_failures: list[str] = []
    try:
        from pynput import keyboard

        def _on_press(key: object) -> None:
            if key == keyboard.Key.esc:
                try:
                    speaker.stop()
                except Exception as error:
                    playback_failures.append(str(error))
                    console.print(f"[red]Could not stop read-aloud:[/red] {error}")

        listener = keyboard.Listener(on_press=_on_press)
        listener.start()
        console.print("[dim](Esc to stop)[/dim]")
    except ImportError:
        pass
    except Exception as error:
        console.print(
            f"[yellow]Could not register Esc to stop playback:[/yellow] {error}. "
            "Read-aloud will continue without that shortcut."
        )
        listener = None

    console.print(f"[cyan]Reading {title} aloud...[/cyan]")
    exit_code = 0
    try:
        speaker.speak(text)
    except Exception as e:
        console.print(f"[red]Read-aloud failed: {e}[/red]")
        exit_code = 1
    finally:
        if listener is not None:
            try:
                listener.stop()
            except Exception as error:
                console.print(f"[yellow]Could not stop the playback hotkey:[/yellow] {error}")
                exit_code = 1
        try:
            speaker.close()
        except Exception as error:
            console.print(f"[yellow]Could not close read-aloud cleanly:[/yellow] {error}")
            exit_code = 1
    if playback_failures:
        exit_code = 1
    if exit_code == 0:
        console.print("[green]Done.[/green]")
    return exit_code


# --- Runtime: dictation ------------------------------------------------------


def run_listen(  # pragma: no cover - live microphone and keyboard I/O, exercised by hand
    console: Console,
    *,
    model: str | None = None,
    language: str | None = None,
    mode: str = "hold",
    inject: str = "paste",
    threshold: float = 0.012,
    sample_rate: int = 16000,
    frame_ms: int = 30,
) -> int:
    """Run legacy resident dictation while enforcing one voice process per user."""
    from scribe.voice.instance import TrayInstanceLock

    try:
        mode = resolve_listen_mode(mode)
        inject = resolve_inject_method(inject)
    except ValueError as error:
        console.print(f"[red]{error}[/red]")
        return 1

    instance_lock = TrayInstanceLock()
    try:
        acquired = instance_lock.acquire()
    except OSError as error:
        console.print(f"[red]Could not establish resident voice ownership:[/red] {error}")
        return 1
    if not acquired:
        owner = instance_lock.owner
        description = owner.description if owner is not None else "another process"
        console.print(
            f"[yellow]Scribe resident voice is already running ({description}).[/yellow] "
            "This launch will exit without registering another hotkey listener or "
            "loading another model."
        )
        return 0

    try:
        return _run_owned_listen(
            console,
            model=model,
            language=language,
            mode=mode,
            inject=inject,
            threshold=threshold,
            sample_rate=sample_rate,
            frame_ms=frame_ms,
        )
    finally:
        instance_lock.retain_until_process_exit()


def _run_owned_listen(  # pragma: no cover - live microphone and keyboard I/O
    console: Console,
    *,
    model: str | None = None,
    language: str | None = None,
    mode: str = "hold",
    inject: str = "paste",
    threshold: float = 0.012,
    sample_rate: int = 16000,
    frame_ms: int = 30,
) -> int:
    """Dictate: capture the microphone, transcribe, and inject the text at the cursor.

    Two modes: ``hold`` (push-to-talk; hold F9, speak, release to transcribe) and
    ``continuous`` (always listening with silence endpointing; F9 pauses). Injection
    is ``paste`` (via the clipboard, restored after each insertion) or ``type``
    (keystrokes at the cursor). A persistent faster-whisper model keeps latency low.
    This path needs a microphone and the voice extra, so it is exercised manually
    rather than in CI.
    """
    try:
        mode = resolve_listen_mode(mode)
        inject = resolve_inject_method(inject)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        return 1
    if sample_rate <= 0 or frame_ms <= 0 or threshold < 0:
        console.print(
            "[red]Invalid dictation capture settings:[/red] sample rate and frame length "
            "must be positive, and threshold cannot be negative."
        )
        return 1

    try:
        import numpy as np
        import sounddevice as sd
        from pynput import keyboard
    except ImportError:
        console.print(VOICE_INSTALL_HINT, markup=False)
        return 1

    try:
        import pyperclip
    except ImportError:
        pyperclip = None

    if inject == "paste" and pyperclip is None:
        console.print(VOICE_INSTALL_HINT, markup=False)
        return 1

    model_obj = _load_dictation_model(console, model)
    if model_obj is None:
        return 1

    import tempfile

    from scribe.utils.theme import ScribeTheme

    try:
        controller = keyboard.Controller()
    except Exception as error:
        console.print(f"[red]Could not initialize text injection:[/red] {error}")
        _unload_dictation_model(model_obj, console)
        return 1
    frame_samples = max(1, int(sample_rate * frame_ms / 1000))
    max_capture_frames = max(1, int(MAX_DICTATION_SECONDS * 1000 / frame_ms))
    buffer: list[bytes] = []
    frame_index = 0
    # hold captures only while F9 is held; toggle captures between taps; continuous
    # starts active and uses silence endpointing.
    state = {"quit": False, "recording": mode == "continuous"}
    segmenter = UtteranceSegmenter(
        min_speech_frames=max(1, 90 // frame_ms),  # ~90 ms of speech to open
        min_silence_frames=max(1, 600 // frame_ms),  # ~600 ms of silence to close
    )
    transcription_queue: queue.Queue[bytes | None] = queue.Queue(maxsize=2)
    transcription_failures: list[str] = []

    def reset_capture() -> None:
        nonlocal frame_index
        buffer.clear()
        frame_index = 0
        segmenter.reset()

    def inject_text(text: str) -> None:
        output = text + " "
        if inject == "type":
            controller.type(output)
            return
        prior = clipboard_paste()
        if prior is None:
            console.print(
                "[yellow]Could not preserve the current clipboard; "
                "falling back to typed insertion.[/yellow]"
            )
            controller.type(output)
            return
        if not clipboard_copy(output):
            console.print(
                "[yellow]Clipboard paste was unavailable; falling back to typed insertion.[/yellow]"
            )
            controller.type(output)
            return
        try:
            # macOS pastes with Cmd+V, not Ctrl+V; resolve per-OS so dictation's
            # default paste mode actually inserts text on a Mac, matching the tray.
            with controller.pressed(_modifier_key(keyboard)):
                controller.press("v")
                controller.release("v")
        finally:
            import time

            time.sleep(0.15)
            if not clipboard_copy(prior):
                console.print(
                    "[yellow]Could not restore the clipboard after dictation; "
                    "your previous clipboard contents may have changed.[/yellow]"
                )

    def transcribe(pcm: bytes) -> None:
        if not pcm:
            console.print("[yellow](no audio captured - speak after starting dictation)[/yellow]")
            return
        console.print("[dim]transcribing...[/dim]")
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            write_wav(tmp_path, pcm, sample_rate)
            segments, _ = model_obj.transcribe(str(tmp_path), language=language, beam_size=5)
            text = " ".join(seg.text.strip() for seg in segments).strip()
            if not text:
                console.print("[yellow](no speech detected)[/yellow]")
                return
            console.print(f"  [{ScribeTheme.TEXT_PRIMARY}]{text}[/{ScribeTheme.TEXT_PRIMARY}]")
            inject_text(text)
        except Exception as error:
            transcription_failures.append(str(error))
            console.print(f"[red]Dictation failed:[/red] {error}")
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError as error:
                    message = f"could not remove temporary dictation audio: {error}"
                    transcription_failures.append(message)
                    console.print(f"[yellow]Dictation cleanup warning:[/yellow] {message}")

    def submit_transcription(pcm: bytes) -> None:
        try:
            transcription_queue.put_nowait(pcm)
        except queue.Full:
            message = "transcription queue is full; this utterance was not processed"
            transcription_failures.append(message)
            console.print(f"[red]Dictation failed:[/red] {message}")

    def transcription_worker() -> None:
        while True:
            pcm = transcription_queue.get()
            if pcm is None:
                return
            transcribe(pcm)

    def on_press(key: object) -> None:
        if key == keyboard.Key.esc:
            state["quit"] = True
            return
        if mode == "toggle" and key == keyboard.Key.f9:
            if not state["recording"]:
                state["recording"] = True
                reset_capture()
                console.print("[cyan]* recording... tap F9 again to insert[/cyan]")
            else:
                state["recording"] = False
                submit_transcription(b"".join(buffer))
                reset_capture()
        elif mode == "hold" and key == keyboard.Key.f9 and not state["recording"]:
            state["recording"] = True
            reset_capture()
            console.print("[cyan]* recording... release F9 to insert[/cyan]")
        elif mode == "continuous" and key == keyboard.Key.f9:
            state["recording"] = not state["recording"]
            if not state["recording"]:
                reset_capture()
            console.print(f"[cyan]Dictation {'on' if state['recording'] else 'paused'}[/cyan]")

    def on_release(key: object) -> None:
        if mode == "hold" and key == keyboard.Key.f9 and state["recording"]:
            state["recording"] = False
            submit_transcription(b"".join(buffer))
            reset_capture()

    try:
        worker = threading.Thread(
            target=transcription_worker,
            daemon=True,
            name="scribe-listen-transcription",
        )
        worker.start()
    except Exception as error:
        console.print(f"[red]Could not start the transcription worker:[/red] {error}")
        _unload_dictation_model(model_obj, console)
        return 1

    listener: Any | None = None
    try:
        listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        listener.start()
        is_alive = getattr(listener, "is_alive", None)
        if callable(is_alive) and not is_alive():
            raise RuntimeError("dictation hotkey listener exited during startup")
    except Exception as error:
        console.print(f"[red]Could not start the dictation hotkey:[/red] {error}")
        listener_stopped = listener is None or _stop_listen_listener(listener, console)
        worker_stopped = _stop_listen_worker(transcription_queue, worker, console)
        if worker_stopped and listener_stopped:
            _unload_dictation_model(model_obj, console)
        return 1

    if mode == "toggle":
        console.print(
            "[bold cyan]DICTATION READY[/bold cyan] - tap F9 to start, tap again to insert. "
            "Esc quits."
        )
    elif mode == "hold":
        console.print(
            "[bold cyan]DICTATION READY[/bold cyan] - hold F9 to talk, release to insert. "
            "Esc quits."
        )
    else:
        console.print(
            "[bold cyan]DICTATION LIVE[/bold cyan] - your speech is inserted into the focused "
            "window. F9 pauses, Esc quits."
        )
    console.print(
        "[yellow]Keep focus on a text field; do not dictate near a terminal or "
        "password field.[/yellow]"
    )
    exit_code = 0
    try:
        with sd.RawInputStream(
            samplerate=sample_rate, blocksize=frame_samples, dtype="int16", channels=1
        ) as stream:
            while not state["quit"]:
                data, _ = stream.read(frame_samples)
                if not state["recording"]:
                    continue
                pcm = bytes(data)
                if mode in ("hold", "toggle"):
                    # The key taps/hold define the utterance window; just accumulate.
                    # toggle transcribes on the second tap (in on_press), hold on
                    # release - neither needs silence endpointing.
                    buffer.append(pcm)
                    if len(buffer) >= max_capture_frames:
                        state["recording"] = False
                        console.print(
                            f"[yellow]Dictation reached the {MAX_DICTATION_SECONDS}-second "
                            "safety limit and was stopped.[/yellow]"
                        )
                        submit_transcription(b"".join(buffer))
                        reset_capture()
                    continue
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
                buffer.append(pcm)
                span = segmenter.push(frame_index, frame_is_speech(rms, threshold))
                frame_index += 1
                if span is not None:
                    start, end = span  # end is exclusive (one past last speech frame)
                    submit_transcription(b"".join(buffer[start:end]))
                    reset_capture()
                elif len(buffer) >= max_capture_frames:
                    tail = segmenter.flush()
                    if tail is not None:
                        start, end = tail
                        submit_transcription(b"".join(buffer[start:end]))
                    console.print(
                        f"[yellow]Continuous dictation reached the {MAX_DICTATION_SECONDS}-second "
                        "segment limit and started a new segment.[/yellow]"
                    )
                    reset_capture()
            # Continuous mode: flush a final in-progress utterance on quit.
            if mode == "continuous":
                tail = segmenter.flush()
                if tail is not None:
                    start, end = tail
                    submit_transcription(b"".join(buffer[start:end]))
    except KeyboardInterrupt:
        pass
    except Exception as error:
        console.print(f"[red]Microphone capture failed:[/red] {error}")
        exit_code = 1
    finally:
        if not _stop_listen_listener(listener, console):
            exit_code = 1
        worker_stopped = _stop_listen_worker(transcription_queue, worker, console)
        if not worker_stopped or not _unload_dictation_model(model_obj, console):
            exit_code = 1

    console.print("[green]Dictation stopped.[/green]")
    return 1 if transcription_failures else exit_code


def _stop_listen_listener(
    listener: Any,
    console: Console,
    *,
    timeout: float = 2.0,
) -> bool:
    """Stop and confirm the legacy global hook before releasing other resources."""
    failures: list[str] = []
    try:
        listener.stop()
    except Exception as error:
        failures.append(f"stop failed: {error}")

    join = getattr(listener, "join", None)
    if callable(join) and listener is not threading.current_thread():
        try:
            join(timeout=max(0.0, timeout))
        except Exception as error:
            failures.append(f"join failed: {error}")

    is_alive = getattr(listener, "is_alive", None)
    if callable(is_alive):
        try:
            alive: bool | None = bool(is_alive())
        except Exception as error:
            alive = None
            failures.append(f"status check failed: {error}")
    else:
        alive = None
    if alive:
        failures.append("listener thread is still alive")
    cleanup_complete = alive is False or (alive is None and not failures)
    if failures:
        console.print(
            "[yellow]Could not confirm dictation hotkey shutdown:[/yellow] " + "; ".join(failures)
        )
    return cleanup_complete


def _stop_listen_worker(
    work_queue: queue.Queue[bytes | None],
    worker: threading.Thread,
    console: Console,
    *,
    timeout: float = 30.0,
) -> bool:
    """Stop the legacy transcription worker without allowing shutdown to hang."""
    enqueue_timeout = min(1.0, max(0.0, timeout))
    try:
        work_queue.put(None, timeout=enqueue_timeout)
    except queue.Full:
        dropped = 0
        while True:
            try:
                pending = work_queue.get_nowait()
            except queue.Empty:
                break
            if pending is not None:
                dropped += 1
        work_queue.put_nowait(None)
        console.print(
            f"[yellow]Discarded {dropped} queued dictation utterance(s) during shutdown.[/yellow]"
        )

    try:
        worker.join(timeout=max(0.0, timeout))
        alive = worker.is_alive()
    except Exception as error:
        console.print(f"[red]Could not confirm transcription worker shutdown:[/red] {error}")
        return False
    if alive:
        console.print(
            "[red]The transcription worker did not stop in time.[/red] "
            "Scribe will exit without unloading a model that is still in use."
        )
        return False
    return True


def _load_dictation_model(  # pragma: no cover - loads a real model, hardware dependent
    console: Console, model: str | None
) -> Any | None:
    """Load a persistent faster-whisper model for dictation, or report why not."""
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        console.print(
            'faster-whisper is required for dictation. Install with: pip install "scribe"'
        )
        return None

    from scribe.models.gpu import GPUConfig

    gpu = GPUConfig.detect()
    model_size = model or ("base" if not gpu.has_gpu else "small")
    device = "cuda" if gpu.has_gpu else "cpu"
    compute_type = "float16" if gpu.has_gpu else "int8"
    console.print(f"[cyan]Loading dictation model ({model_size}, {device})...[/cyan]")
    try:
        return WhisperModel(model_size, device=device, compute_type=compute_type)
    except Exception as e:
        console.print(f"[red]Could not load dictation model: {e}[/red]")
        return None


def _unload_dictation_model(
    model_obj: Any,
    console: Console,
    *,
    timeout: float = 2.0,
) -> bool:
    """Release a legacy model without letting a backend hang process shutdown."""
    import gc

    backend = getattr(model_obj, "model", None)
    unload_model = getattr(backend, "unload_model", None)
    if not callable(unload_model):
        del backend
        gc.collect()
        return True

    errors: list[Exception] = []

    def unload() -> None:
        try:
            unload_model()
        except Exception as error:
            errors.append(error)

    cleanup = threading.Thread(
        target=unload,
        daemon=True,
        name="scribe-listen-model-unload",
    )
    try:
        cleanup.start()
        cleanup.join(timeout=max(0.0, timeout))
        alive = cleanup.is_alive()
    except Exception as error:
        console.print(f"[yellow]Could not run voice model cleanup:[/yellow] {error}")
        return False
    if alive:
        console.print(
            f"[yellow]Voice model cleanup did not finish within {max(0.0, timeout):g} "
            "seconds; Scribe will exit without starting another resident backend.[/yellow]"
        )
        return False
    del backend
    gc.collect()
    if errors:
        console.print(f"[yellow]Could not explicitly unload the voice model:[/yellow] {errors[0]}")
        return False
    return True
