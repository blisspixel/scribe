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

import re
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
_RULE_CHARS = set("-=_─—")  # hyphen, equals, underscore, box-rule, em-dash


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

LISTEN_MODES = ("hold", "continuous")
INJECT_METHODS = ("paste", "type")


def resolve_listen_mode(value: str | None) -> str:
    """Validate the dictation mode. ``hold`` (push-to-talk) is the default."""
    resolved = (value or "hold").strip().lower()
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


# --- Runtime: read-aloud -----------------------------------------------------


def run_say(
    console: Console,
    path: Path | None = None,
    *,
    rate: int | None = None,
    voice: str | None = None,
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
        text = extract_speakable_text(path)
    elif source == "clipboard":
        title = "clipboard"
        text = _read_clipboard(console)
    else:
        title = "selection"
        text = _read_selection(console)

    if not text:
        console.print("[yellow]Nothing to read.[/yellow]")
        return 1

    return _speak(console, title, text, rate=rate, voice=voice)


def _read_clipboard(console: Console) -> str:  # pragma: no cover - clipboard I/O
    try:
        import pyperclip
    except ImportError:
        console.print(VOICE_INSTALL_HINT, markup=False)
        return ""
    try:
        return clean_spoken_text(pyperclip.paste() or "")
    except Exception:
        return ""


def _read_selection(console: Console) -> str:  # pragma: no cover - keyboard/clipboard I/O
    """Copy the current selection (Ctrl+C / Cmd+C) and return it as speakable text."""
    try:
        import platform
        import time

        import pyperclip
        from pynput import keyboard
    except ImportError:
        console.print(VOICE_INSTALL_HINT, markup=False)
        return ""

    controller = keyboard.Controller()
    modifier = keyboard.Key.cmd if platform.system() == "Darwin" else keyboard.Key.ctrl
    with controller.pressed(modifier):
        controller.press("c")
        controller.release("c")
    time.sleep(0.15)  # give the OS a moment to populate the clipboard
    try:
        return clean_spoken_text(pyperclip.paste() or "")
    except Exception:
        return ""


def _speak(  # pragma: no cover - drives the local TTS engine; no audio device in CI
    console: Console,
    title: str,
    text: str,
    *,
    rate: int | None,
    voice: str | None,
) -> int:
    """Speak ``text`` with pyttsx3 (isolated so the engine I/O stays out of CI)."""
    try:
        import pyttsx3
    except ImportError:
        console.print(VOICE_INSTALL_HINT, markup=False)
        return 1

    engine = pyttsx3.init()
    if rate is not None:
        engine.setProperty("rate", rate)
    if voice:
        for candidate in engine.getProperty("voices"):
            haystack = f"{getattr(candidate, 'name', '')} {getattr(candidate, 'id', '')}".lower()
            if voice.lower() in haystack:
                engine.setProperty("voice", candidate.id)
                break

    # Esc stops playback mid-sentence. The pynput listener runs on its own thread, so
    # engine.stop() interrupts the blocking runAndWait below.
    listener = None
    try:
        from pynput import keyboard

        def _on_press(key: object) -> None:
            if key == keyboard.Key.esc:
                engine.stop()

        listener = keyboard.Listener(on_press=_on_press)
        listener.start()
        console.print("[dim](Esc to stop)[/dim]")
    except ImportError:
        pass

    console.print(f"[cyan]Reading {title} aloud...[/cyan]")
    engine.say(text)
    engine.runAndWait()
    if listener is not None:
        listener.stop()
    console.print("[green]Done.[/green]")
    return 0


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
    """Dictate: capture the microphone, transcribe, and inject the text at the cursor.

    Two modes: ``hold`` (push-to-talk; hold F9, speak, release to transcribe) and
    ``continuous`` (always listening with silence endpointing; F9 pauses). Injection
    is ``paste`` (via the clipboard, restored on exit) or ``type`` (keystrokes at the
    cursor). A persistent faster-whisper model keeps latency low. This path needs a
    microphone and the voice extra, so it is exercised manually rather than in CI.
    """
    try:
        mode = resolve_listen_mode(mode)
        inject = resolve_inject_method(inject)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
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

    controller = keyboard.Controller()
    frame_samples = int(sample_rate * frame_ms / 1000)
    buffer: list[bytes] = []
    frame_index = 0
    # In hold mode we capture only while the key is held; continuous starts active.
    state = {"quit": False, "recording": mode == "continuous"}
    segmenter = UtteranceSegmenter(
        min_speech_frames=max(1, 90 // frame_ms),  # ~90 ms of speech to open
        min_silence_frames=max(1, 600 // frame_ms),  # ~600 ms of silence to close
    )

    def reset_capture() -> None:
        nonlocal frame_index
        buffer.clear()
        frame_index = 0
        segmenter.reset()

    def inject_text(text: str) -> None:
        if inject == "type":
            controller.type(text + " ")
            return
        if pyperclip is not None:
            pyperclip.copy(text + " ")
            with controller.pressed(keyboard.Key.ctrl):
                controller.press("v")
                controller.release("v")

    def transcribe(pcm: bytes) -> None:
        if not pcm:
            return
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            write_wav(tmp_path, pcm, sample_rate)
            segments, _ = model_obj.transcribe(str(tmp_path), language=language, beam_size=5)
            text = " ".join(seg.text.strip() for seg in segments).strip()
        finally:
            tmp_path.unlink(missing_ok=True)
        if not text:
            return
        console.print(f"  [{ScribeTheme.TEXT_PRIMARY}]{text}[/{ScribeTheme.TEXT_PRIMARY}]")
        inject_text(text)

    def on_press(key: object) -> None:
        if key == keyboard.Key.esc:
            state["quit"] = True
            return
        if mode == "hold" and key == keyboard.Key.f9 and not state["recording"]:
            state["recording"] = True
            reset_capture()
        elif mode == "continuous" and key == keyboard.Key.f9:
            state["recording"] = not state["recording"]
            if not state["recording"]:
                reset_capture()
            console.print(f"[cyan]Dictation {'on' if state['recording'] else 'paused'}[/cyan]")

    def on_release(key: object) -> None:
        if mode == "hold" and key == keyboard.Key.f9 and state["recording"]:
            state["recording"] = False
            transcribe(b"".join(buffer))
            reset_capture()

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()

    # When pasting, dictation owns the clipboard; remember the user's contents so we
    # can restore them on exit instead of silently clobbering them.
    prior_clipboard: str | None = None
    if inject == "paste" and pyperclip is not None:
        try:
            prior_clipboard = pyperclip.paste()
        except Exception:
            prior_clipboard = None

    if mode == "hold":
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
    try:
        with sd.RawInputStream(
            samplerate=sample_rate, blocksize=frame_samples, dtype="int16", channels=1
        ) as stream:
            while not state["quit"]:
                data, _ = stream.read(frame_samples)
                if not state["recording"]:
                    continue
                pcm = bytes(data)
                if mode == "hold":
                    # The key press/release defines the utterance; just accumulate.
                    buffer.append(pcm)
                    continue
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
                buffer.append(pcm)
                span = segmenter.push(frame_index, frame_is_speech(rms, threshold))
                frame_index += 1
                if span is not None:
                    start, end = span  # end is exclusive (one past last speech frame)
                    transcribe(b"".join(buffer[start:end]))
                    reset_capture()
            # Continuous mode: flush a final in-progress utterance on quit.
            if mode == "continuous":
                tail = segmenter.flush()
                if tail is not None:
                    start, end = tail
                    transcribe(b"".join(buffer[start:end]))
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
        if inject == "paste" and pyperclip is not None and prior_clipboard is not None:
            import contextlib

            with contextlib.suppress(Exception):
                pyperclip.copy(prior_clipboard)

    console.print("[green]Dictation stopped.[/green]")
    return 0


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
