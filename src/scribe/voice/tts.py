"""Read-aloud (text-to-speech) backends for Scribe voice mode.

Two backends, chosen adaptively:

- ``pyttsx3``: zero-download OS-native voices. Always available with the voice
  extra; the safe fallback that needs no model files or network.
- ``kokoro``: a high-quality 82M neural voice via ``kokoro-onnx`` (ONNX runtime,
  runs on CPU). An optional upgrade behind the ``scribe[kokoro]`` extra whose
  model/voice files download during setup.

Design follows the repo's split: the pure helpers here (backend resolution, the
voice catalog, asset paths and readiness checks) have no optional dependency and
are unit-tested. The ``Speaker`` implementations touch audio hardware and the
optional packages, so they are guarded defensively and exercised by hand.

Adaptive rule: ``auto`` uses Kokoro when the package is installed *and* its model
files are present, otherwise pyttsx3. An explicit Kokoro request that cannot be
satisfied degrades to pyttsx3 with a warning rather than failing - read-aloud
should never hard-error just because an optional upgrade is missing.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)

TTS_BACKENDS = ("auto", "kokoro", "pyttsx3")

# Kokoro v1.0 ONNX assets. Kept here so setup, readiness checks, and the adapter
# all agree on the filenames, sizes, and download sources.
KOKORO_MODEL_FILE = "kokoro-v1.0.onnx"
KOKORO_VOICES_FILE = "voices-v1.0.bin"
_KOKORO_RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
KOKORO_MODEL_URL = f"{_KOKORO_RELEASE}/{KOKORO_MODEL_FILE}"
KOKORO_VOICES_URL = f"{_KOKORO_RELEASE}/{KOKORO_VOICES_FILE}"
# Floor sizes (bytes) used only to reject truncated/partial downloads; the real
# files are far larger (~310MB model, ~26MB voices).
_KOKORO_MODEL_MIN_BYTES = 50_000_000
_KOKORO_VOICES_MIN_BYTES = 1_000_000

DEFAULT_KOKORO_VOICE = "af_heart"


@dataclass(frozen=True)
class TtsVoiceChoice:
    """One selectable Kokoro voice for the setup picker."""

    voice_id: str
    label: str


# A curated subset of Kokoro's catalogue for the setup picker. The full set ships
# inside the voices file; these are the well-regarded defaults across accents and
# genders so the wizard stays short. Any valid Kokoro id still works via config.
KOKORO_VOICE_CHOICES: tuple[TtsVoiceChoice, ...] = (
    TtsVoiceChoice("af_heart", "American English - female (Heart, warm)"),
    TtsVoiceChoice("af_bella", "American English - female (Bella)"),
    TtsVoiceChoice("am_michael", "American English - male (Michael)"),
    TtsVoiceChoice("am_adam", "American English - male (Adam)"),
    TtsVoiceChoice("bf_emma", "British English - female (Emma)"),
    TtsVoiceChoice("bm_george", "British English - male (George)"),
)

# First letter of a Kokoro voice id encodes accent/language: a=American English,
# b=British English. Map to the lang code kokoro-onnx expects; default en-us.
_KOKORO_LANG_BY_PREFIX = {"a": "en-us", "b": "en-gb"}


def kokoro_lang_for_voice(voice_id: str) -> str:
    """Return the kokoro-onnx ``lang`` code implied by a voice id prefix."""
    prefix = voice_id[:1].lower() if voice_id else ""
    return _KOKORO_LANG_BY_PREFIX.get(prefix, "en-us")


def resolve_tts_voice(value: str | None) -> str:
    """Normalize a configured Kokoro voice id, falling back to the default."""
    cleaned = (value or "").strip()
    return cleaned or DEFAULT_KOKORO_VOICE


DEFAULT_TTS_SPEED = 1.0
MIN_TTS_SPEED = 0.5
MAX_TTS_SPEED = 2.0


def resolve_tts_speed(value: float | str | None) -> float:
    """Clamp a read-aloud speed multiplier to a sane range (default 1.0).

    1.0 is natural pace; 1.2 is a common comfortable-fast setting. Bad/blank input
    falls back to 1.0. Pure so it is unit-tested.
    """
    if value is None or value == "":
        return DEFAULT_TTS_SPEED
    try:
        speed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_TTS_SPEED
    if not math.isfinite(speed):
        return DEFAULT_TTS_SPEED
    return max(MIN_TTS_SPEED, min(MAX_TTS_SPEED, speed))


def kokoro_dir(home: Path | None = None) -> Path:
    """Directory holding the downloaded Kokoro model and voice files."""
    from scribe.paths import data_dir, legacy_dir

    directory = data_dir(home) / "voices" / "kokoro"
    legacy = legacy_dir(home) / "voices" / "kokoro"
    if not _kokoro_directory_ready(directory) and _kokoro_directory_ready(legacy):
        return legacy
    return directory


def kokoro_asset_paths(home: Path | None = None) -> tuple[Path, Path]:
    """Return (model_path, voices_path) for the Kokoro assets."""
    directory = kokoro_dir(home)
    return directory / KOKORO_MODEL_FILE, directory / KOKORO_VOICES_FILE


def _file_ready(path: Path, min_bytes: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= min_bytes
    except OSError:
        return False


def kokoro_assets_ready(home: Path | None = None) -> bool:
    """True when both Kokoro asset files are present and look complete."""
    return _kokoro_directory_ready(kokoro_dir(home))


def _kokoro_directory_ready(directory: Path) -> bool:
    return _file_ready(directory / KOKORO_MODEL_FILE, _KOKORO_MODEL_MIN_BYTES) and _file_ready(
        directory / KOKORO_VOICES_FILE, _KOKORO_VOICES_MIN_BYTES
    )


def kokoro_installed() -> bool:
    """True when the optional ``kokoro-onnx`` package is importable."""
    import importlib.util

    return importlib.util.find_spec("kokoro_onnx") is not None


def resolve_tts_backend(
    value: str | None,
    *,
    kokoro_installed: bool,
    kokoro_ready: bool,
) -> str:
    """Pick the concrete TTS backend ('kokoro' or 'pyttsx3').

    Pure and adaptive: ``auto`` prefers Kokoro only when it is both installed and
    has its model files; otherwise pyttsx3. An explicit ``kokoro`` request that
    cannot be satisfied degrades to pyttsx3 (the caller surfaces a hint) so
    read-aloud never hard-fails on a missing optional upgrade.
    """
    requested = (value or "auto").strip().lower()
    if requested not in TTS_BACKENDS:
        requested = "auto"
    kokoro_ok = kokoro_installed and kokoro_ready
    if requested == "pyttsx3":
        return "pyttsx3"
    if requested == "kokoro":
        return "kokoro" if kokoro_ok else "pyttsx3"
    return "kokoro" if kokoro_ok else "pyttsx3"


def split_for_speech(text: str, max_chars: int = 400) -> list[str]:
    """Split text into speakable chunks at sentence boundaries.

    Kokoro synthesizes one bounded span at a time; chunking also makes playback
    interruptible between sentences. Sentences are grouped greedily up to
    ``max_chars`` and kept whole even when a single sentence runs a little over -
    chopping mid-sentence sounds wrong. Only a pathologically long run (no
    punctuation, e.g. pasted data) past ``max_chars * 3`` is hard-wrapped so it
    cannot overflow the model. Pure so it is unit-tested without audio.
    """
    if max_chars <= 0:
        raise ValueError("speech chunk size must be positive")
    collapsed = " ".join(text.split())
    if not collapsed:
        return []
    hard_cap = max_chars * 3
    sentences = re.split(r"(?<=[.!?])\s+", collapsed)
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for sentence in sentences:
        piece = sentence.strip()
        if not piece:
            continue
        if len(piece) > hard_cap:
            # Pathologically long with no sentence breaks: flush, then hard-wrap.
            flush()
            for start in range(0, len(piece), max_chars):
                chunks.append(piece[start : start + max_chars])
            continue
        if current and len(current) + 1 + len(piece) > max_chars:
            flush()
        current = f"{current} {piece}".strip()
    flush()
    return chunks


# --- Runtime speakers --------------------------------------------------------


class Speaker(Protocol):
    """A read-aloud engine that can speak a string and be stopped mid-playback."""

    def speak(self, text: str) -> None:  # pragma: no cover - interface
        """Speak ``text`` (blocking until done or stopped)."""

    def stop(self) -> None:  # pragma: no cover - interface
        """Interrupt any in-progress playback. Safe to call from another thread."""

    def close(self) -> None:  # pragma: no cover - interface
        """Release engine resources."""


class Pyttsx3Speaker:  # pragma: no cover - drives the OS TTS engine; no audio in CI
    """OS-native read-aloud via pyttsx3 (the always-available fallback)."""

    def __init__(
        self, *, rate: int | None = None, voice: str | None = None, speed: float = 1.0
    ) -> None:
        import pyttsx3

        self._engine = pyttsx3.init()
        self._stop_event = threading.Event()
        if rate is not None:
            self._engine.setProperty("rate", rate)
        elif speed != 1.0:
            # Scale the engine's own default words/min by the speed multiplier.
            try:
                base = int(self._engine.getProperty("rate"))
                self._engine.setProperty("rate", int(base * resolve_tts_speed(speed)))
            except Exception as error:
                logger.warning("Could not apply system voice speed: %s", error)
        if voice:
            needle = voice.lower()
            for candidate in self._engine.getProperty("voices"):
                haystack = (
                    f"{getattr(candidate, 'name', '')} {getattr(candidate, 'id', '')}".lower()
                )
                if needle in haystack:
                    self._engine.setProperty("voice", candidate.id)
                    break

    def speak(self, text: str) -> None:
        if self._stop_event.is_set():
            return
        self._engine.say(text)
        if self._stop_event.is_set():
            self._engine.stop()
            return
        self._engine.runAndWait()

    def stop(self) -> None:
        self._stop_event.set()
        self._engine.stop()

    def close(self) -> None:
        self.stop()


_kokoro_models: dict[str, Any] = {}
_kokoro_lock = threading.Lock()


def load_kokoro(home: Path | None = None) -> Any:  # pragma: no cover - loads ONNX model
    """Return a cached Kokoro model, loading it once per asset path.

    The ONNX model takes ~1-2s to load; building a fresh model on every read made
    read-aloud feel sluggish. Cache it (guarded by a lock) so the first read pays
    the cost and every later read is instant.
    """
    from kokoro_onnx import Kokoro

    model_path, voices_path = kokoro_asset_paths(home)
    key = str(model_path)
    with _kokoro_lock:
        model = _kokoro_models.get(key)
        if model is None:
            model = Kokoro(str(model_path), str(voices_path))
            _kokoro_models[key] = model
        return model


def unload_kokoro(*, timeout: float = 2.0) -> int:
    """Drop cached neural voice models without hanging behind a stuck load."""
    import gc

    if timeout < 0:
        raise ValueError("Kokoro unload timeout cannot be negative")
    if not _kokoro_lock.acquire(timeout=timeout):
        raise TimeoutError("neural voice model is still loading")
    try:
        models = list(_kokoro_models.values())
        _kokoro_models.clear()
    finally:
        _kokoro_lock.release()
    count = len(models)
    models.clear()
    gc.collect()
    return count


class KokoroSpeaker:  # pragma: no cover - loads ONNX model, plays audio; manual test
    """High-quality neural read-aloud via kokoro-onnx, played through sounddevice."""

    def __init__(
        self,
        *,
        voice: str = DEFAULT_KOKORO_VOICE,
        rate: int | None = None,
        speed: float = 1.0,
        home: Path | None = None,
    ) -> None:
        self._kokoro = load_kokoro(home)
        self._voice = resolve_tts_voice(voice)
        # Validate the voice id up front: an unknown/typo'd id (or a pyttsx3-style
        # system voice name passed via --voice) would otherwise raise at synth
        # time and crash playback. Fall back to a known-good voice instead.
        try:
            available = set(self._kokoro.get_voices())
            if self._voice not in available:
                self._voice = (
                    DEFAULT_KOKORO_VOICE
                    if DEFAULT_KOKORO_VOICE in available
                    else next(iter(sorted(available)), DEFAULT_KOKORO_VOICE)
                )
        except Exception as error:
            logger.warning("Could not validate Kokoro voice selection: %s", error)
        self._lang = kokoro_lang_for_voice(self._voice)
        # Kokoro takes a speed multiplier natively. Prefer an explicit speed; fall
        # back to deriving one from a pyttsx3-style words/min rate for callers that
        # only pass --rate.
        if speed != 1.0 or rate is None:
            self._speed = resolve_tts_speed(speed)
        else:
            self._speed = resolve_tts_speed(rate / 200.0)
        # Event (not a bool) so a stop() on the listener thread is seen by the
        # speak() loop running on the worker thread without races.
        self._stop_event = threading.Event()

    def _synth(self, chunk: str) -> Any:
        """Return (samples, sample_rate) for one chunk."""
        return self._kokoro.create(chunk, voice=self._voice, speed=self._speed, lang=self._lang)

    def speak(self, text: str) -> None:
        import sounddevice as sd

        # Note: a fresh speaker is built per read, so the event starts un-set; do
        # NOT clear() here - a clear() would erase a stop() that arrives in the
        # window between the worker deciding to speak and this method running.
        chunks = split_for_speech(text)
        # Look-ahead pipeline: synthesize chunk N+1 WHILE chunk N is playing, so
        # there is no synth gap (dead air) between sentences/paragraphs.
        pending: Any = None
        for index, chunk in enumerate(chunks):
            if self._stop_event.is_set():
                break
            samples, sample_rate = pending if pending is not None else self._synth(chunk)
            if self._stop_event.is_set():
                break
            sd.play(samples, sample_rate)
            # Re-check immediately: stop() may have run its sd.stop() just BEFORE
            # this play started (so it was a no-op). Abort the freshly-started
            # playback instead of letting the whole chunk finish.
            if self._stop_event.is_set():
                sd.stop()
                break
            # Prefetch the next chunk during this chunk's playback.
            pending = None
            if index + 1 < len(chunks) and not self._stop_event.is_set():
                try:
                    pending = self._synth(chunks[index + 1])
                except Exception as error:
                    logger.warning("Kokoro prefetch failed; retrying synchronously: %s", error)
            sd.wait()

    def stop(self) -> None:
        self._stop_event.set()
        import sounddevice as sd

        sd.stop()

    def close(self) -> None:
        self.stop()


def make_speaker(
    backend: str,
    *,
    voice: str | None = None,
    rate: int | None = None,
    speed: float = 1.0,
    home: Path | None = None,
    console: Console | None = None,
) -> Speaker:  # pragma: no cover - constructs runtime engines
    """Create a Speaker for the resolved backend, degrading to pyttsx3 on failure.

    ``backend`` should already be concrete ('kokoro' or 'pyttsx3'); callers get
    there via :func:`resolve_tts_backend`. If Kokoro construction fails for any
    reason (missing package, bad model file, no ONNX runtime) we fall back to
    pyttsx3 so read-aloud still works.
    """
    if backend == "kokoro":
        try:
            return KokoroSpeaker(
                voice=voice or DEFAULT_KOKORO_VOICE, rate=rate, speed=speed, home=home
            )
        except Exception as e:
            if console is not None:
                console.print(
                    f"[yellow]Kokoro voice unavailable ({e}); using the system voice.[/yellow]"
                )
    return Pyttsx3Speaker(rate=rate, voice=voice, speed=speed)
