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


# --- Runtime: read-aloud -----------------------------------------------------


def run_say(
    console: Console,
    path: Path,
    *,
    rate: int | None = None,
    voice: str | None = None,
) -> int:
    """Read a transcript or notes file aloud with a local TTS engine."""
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        return 1

    text = extract_speakable_text(path)
    if not text:
        console.print("[yellow]Nothing to read (the file had no speakable text).[/yellow]")
        return 1

    return _speak(console, path.name, text, rate=rate, voice=voice)


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

    console.print(f"[cyan]Reading {title} aloud...[/cyan]")
    engine.say(text)
    engine.runAndWait()
    console.print("[green]Done.[/green]")
    return 0


# --- Runtime: dictation ------------------------------------------------------


def run_listen(  # pragma: no cover - live microphone and keyboard I/O, exercised by hand
    console: Console,
    *,
    model: str | None = None,
    language: str | None = None,
    threshold: float = 0.012,
    sample_rate: int = 16000,
    frame_ms: int = 30,
) -> int:
    """Dictate: capture the microphone, transcribe each utterance, type the text.

    Uses a persistent faster-whisper model (loaded once) for low latency, the pure
    UtteranceSegmenter for endpointing, and the clipboard to inject text into the
    focused window. F9 toggles listening, Esc quits. This path needs a microphone
    and the voice extra, so it is exercised manually rather than in CI.
    """
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

    model_obj = _load_dictation_model(console, model)
    if model_obj is None:
        return 1

    import tempfile

    from scribe.utils.theme import ScribeTheme

    toggle = HotkeyToggle(active=True)
    segmenter = UtteranceSegmenter(
        min_speech_frames=max(1, 90 // frame_ms),  # ~90 ms of speech to open
        min_silence_frames=max(1, 600 // frame_ms),  # ~600 ms of silence to close
    )
    frame_samples = int(sample_rate * frame_ms / 1000)
    buffer: list[bytes] = []
    frame_index = 0
    stop = {"quit": False}

    def reset_buffer() -> None:
        nonlocal frame_index
        buffer.clear()
        frame_index = 0
        segmenter.reset()

    def transcribe_and_inject(pcm: bytes) -> None:
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
        if pyperclip is not None:
            pyperclip.copy(text + " ")
            controller = keyboard.Controller()
            with controller.pressed(keyboard.Key.ctrl):
                controller.press("v")
                controller.release("v")

    def on_press(key: object) -> None:
        if key == keyboard.Key.f9:
            state = toggle.toggle()
            if not state:
                # Drop any half-captured audio so it does not prepend to the next
                # utterance when dictation resumes.
                reset_buffer()
            console.print(f"[cyan]Dictation {'on' if state else 'paused'}[/cyan]")
        elif key == keyboard.Key.esc:
            stop["quit"] = True

    listener = keyboard.Listener(on_press=on_press)
    listener.start()

    console.print("[cyan]Dictation ready. Speak; F9 toggles, Esc quits.[/cyan]")
    try:
        with sd.RawInputStream(
            samplerate=sample_rate, blocksize=frame_samples, dtype="int16", channels=1
        ) as stream:
            while not stop["quit"]:
                data, _ = stream.read(frame_samples)
                if not toggle.active:
                    continue
                pcm = bytes(data)
                samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
                rms = float(np.sqrt(np.mean(samples**2))) if samples.size else 0.0
                buffer.append(pcm)
                span = segmenter.push(frame_index, frame_is_speech(rms, threshold))
                frame_index += 1
                if span is not None:
                    start, end = span
                    # end is exclusive (one past the last speech frame).
                    transcribe_and_inject(b"".join(buffer[start:end]))
                    reset_buffer()
            # Flush a final in-progress utterance so the last words are not lost
            # when the user quits mid-sentence.
            tail = segmenter.flush()
            if tail is not None:
                start, end = tail
                transcribe_and_inject(b"".join(buffer[start:end]))
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()

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
