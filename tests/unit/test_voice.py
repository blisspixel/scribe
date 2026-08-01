"""Tests for the pure voice-I/O logic (cli/voice.py).

The microphone, keyboard, and TTS engine are not exercised here; those are thin
runtime wrappers behind the optional voice extra and are tested by hand. What is
covered is the platform-independent logic: utterance endpointing, the hotkey
toggle, and turning a transcript or notes file into speakable text.
"""

import wave

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scribe.cli.voice import (
    HotkeyToggle,
    UtteranceSegmenter,
    extract_speakable_text,
    frame_is_speech,
    speakable_from_markdown,
    write_wav,
)


def _run(flags: list[bool], **kw) -> list[tuple[int, int]]:
    seg = UtteranceSegmenter(**kw)
    spans = []
    for i, f in enumerate(flags):
        span = seg.push(i, f)
        if span is not None:
            spans.append(span)
    tail = seg.flush()
    if tail is not None:
        spans.append(tail)
    return spans


def test_frame_is_speech_threshold():
    assert frame_is_speech(0.05, 0.01) is True
    assert frame_is_speech(0.005, 0.01) is False
    assert frame_is_speech(0.01, 0.01) is True


def test_segmenter_detects_one_utterance():
    # 4 speech frames, then 3 silence frames closes it.
    flags = [True, True, True, True, False, False, False]
    spans = _run(flags, min_speech_frames=3, min_silence_frames=3)
    assert spans == [(0, 4)]


def test_segmenter_ignores_blips_shorter_than_min_speech():
    # A single speech frame surrounded by silence never opens an utterance.
    flags = [False, True, False, False, False]
    assert _run(flags, min_speech_frames=3, min_silence_frames=2) == []


def test_segmenter_handles_two_utterances():
    flags = [True, True, True, False, False, False, True, True, True, False, False, False]
    spans = _run(flags, min_speech_frames=2, min_silence_frames=3)
    assert len(spans) == 2
    assert spans[0][0] == 0
    assert spans[1][0] == 6


def test_segmenter_flush_emits_trailing_utterance():
    # Speech that never falls silent is emitted on flush.
    flags = [True, True, True, True]
    spans = _run(flags, min_speech_frames=2, min_silence_frames=5)
    assert spans == [(0, 4)]


@given(st.lists(st.booleans(), min_size=0, max_size=60))
def test_segmenter_spans_are_well_formed(flags):
    spans = _run(flags, min_speech_frames=2, min_silence_frames=3)
    for start, end in spans:
        assert 0 <= start <= end <= len(flags)


def test_resolve_listen_mode():
    from scribe.cli.voice import resolve_listen_mode

    assert resolve_listen_mode(None) == "toggle"  # default: tap on/off
    assert resolve_listen_mode("HOLD") == "hold"
    assert resolve_listen_mode("Toggle") == "toggle"
    assert resolve_listen_mode("continuous") == "continuous"
    with pytest.raises(ValueError, match="--mode"):
        resolve_listen_mode("magic")


def test_resolve_inject_method():
    from scribe.cli.voice import resolve_inject_method

    assert resolve_inject_method(None) == "paste"  # default
    assert resolve_inject_method("Type") == "type"
    with pytest.raises(ValueError, match="--inject"):
        resolve_inject_method("magic")


def test_resolve_say_source():
    from pathlib import Path

    from scribe.cli.voice import resolve_say_source

    assert resolve_say_source(Path("x.md"), False, False) == "file"
    assert resolve_say_source(None, True, False) == "selection"
    assert resolve_say_source(None, False, True) == "clipboard"
    with pytest.raises(ValueError, match="Provide a file"):
        resolve_say_source(None, False, False)
    with pytest.raises(ValueError, match="only one"):
        resolve_say_source(Path("x.md"), True, False)


def test_clean_spoken_text():
    from scribe.cli.voice import clean_spoken_text

    assert clean_spoken_text("  hello\n\n  world \t") == "hello world"
    assert clean_spoken_text("") == ""


def test_clipboard_copy_retries_transient_failures(monkeypatch):
    import sys
    import types

    from scribe.cli import voice

    calls = {"n": 0}
    fake = types.ModuleType("pyperclip")

    def copy(value):
        calls["n"] += 1
        if calls["n"] < 3:  # fail twice, then succeed (transient OpenClipboard)
            raise RuntimeError("Error calling OpenClipboard")

    fake.copy = copy  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyperclip", fake)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    assert voice.clipboard_copy("x", attempts=5) is True
    assert calls["n"] == 3


def test_clipboard_copy_gives_up_after_attempts(monkeypatch):
    import sys
    import types

    from scribe.cli import voice

    fake = types.ModuleType("pyperclip")

    def always_fail(value):
        raise RuntimeError("OpenClipboard")

    fake.copy = always_fail  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyperclip", fake)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    assert voice.clipboard_copy("x", attempts=3) is False


def test_paste_modifier_name_is_per_os():
    # macOS copies/pastes with Cmd; Windows and Linux use Ctrl. Dictation's default
    # paste injection and selection-copy both depend on this, so a regression here
    # silently breaks "hold F9 to dictate" on a Mac (Ctrl+V pastes nothing there).
    from scribe.cli.voice import paste_modifier_name

    assert paste_modifier_name("Darwin") == "cmd"
    assert paste_modifier_name("Windows") == "ctrl"
    assert paste_modifier_name("Linux") == "ctrl"
    # An unknown/empty platform falls back to Ctrl rather than failing.
    assert paste_modifier_name("") == "ctrl"


def test_hotkey_toggle():
    t = HotkeyToggle(active=True)
    assert t.toggle() is False
    assert t.toggle() is True
    assert t.toggles == 2


def test_speakable_strips_frontmatter_and_markdown():
    md = (
        "---\n"
        "backend: faster-whisper\n"
        "speakers: [SPEAKER_00]\n"
        "---\n"
        "# Meeting Notes\n"
        "\n"
        "- **Decision:** ship it\n"
        "1. Follow up with [the team](http://x)\n"
        "`code`\n"
    )
    spoken = speakable_from_markdown(md)
    assert "backend:" not in spoken
    assert "#" not in spoken and "**" not in spoken and "`" not in spoken
    assert "Meeting Notes" in spoken
    assert "Decision: ship it" in spoken
    assert "Follow up with the team" in spoken


def test_speakable_strips_crlf_frontmatter():
    # Windows CRLF frontmatter must still be stripped, not spoken.
    md = "---\r\nbackend: faster-whisper\r\n---\r\n# Title\r\n\r\nHello world\r\n"
    spoken = speakable_from_markdown(md)
    assert "backend:" not in spoken
    assert "Title" in spoken and "Hello world" in spoken


def test_speakable_skips_rules_and_code_fences():
    text = "Title\n" + "-" * 80 + "\n```\nprint(1)\n```\nBody line"
    spoken = speakable_from_markdown(text)
    assert "Title" in spoken
    assert "Body line" in spoken
    assert "print(1)" not in spoken
    assert "----" not in spoken


def test_extract_speakable_text_reads_file(tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("# H\n\nHello world\n", encoding="utf-8")
    assert extract_speakable_text(p) == "H Hello world"


def test_run_say_missing_file(tmp_path):
    from rich.console import Console

    from scribe.cli.voice import run_say

    assert run_say(Console(), tmp_path / "nope.txt") == 1


def test_run_say_clipboard_dispatch(monkeypatch):
    from rich.console import Console

    from scribe.cli import voice

    monkeypatch.setattr(voice, "_read_clipboard", lambda _c: "")
    assert voice.run_say(Console(), None, use_clipboard=True) == 1


def test_run_say_selection_dispatch(monkeypatch):
    from rich.console import Console

    from scribe.cli import voice

    monkeypatch.setattr(voice, "_read_selection", lambda _c: "")
    assert voice.run_say(Console(), None, use_selection=True) == 1


def test_run_say_empty_text_returns_before_tts(tmp_path):
    # Frontmatter + a code fence only -> no speakable text, so it returns 1
    # without ever importing or invoking the TTS engine (no audio in tests).
    from rich.console import Console

    from scribe.cli.voice import run_say

    f = tmp_path / "empty.md"
    f.write_text("---\nx: 1\n---\n```\ncode only\n```\n", encoding="utf-8")
    assert run_say(Console(), f) == 1


def test_speak_reports_backend_initialization_failure(monkeypatch):
    from rich.console import Console

    from scribe.cli import voice
    from scribe.voice import tts

    monkeypatch.setattr(tts, "resolve_tts_backend", lambda *_args, **_kwargs: "pyttsx3")
    monkeypatch.setattr(tts, "kokoro_installed", lambda: False)
    monkeypatch.setattr(tts, "kokoro_assets_ready", lambda: False)
    monkeypatch.setattr(
        tts,
        "make_speaker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audio service down")),
    )
    console = Console(record=True)

    result = voice._speak(console, "test", "hello", rate=None, voice=None)

    assert result == 1
    assert "Could not initialize read-aloud" in console.export_text()


def test_speak_surfaces_invalid_voice_config(monkeypatch):
    import tomllib

    from rich.console import Console

    from scribe import config_file
    from scribe.cli import voice

    monkeypatch.setattr(
        config_file,
        "load_config_file_strict",
        lambda: (_ for _ in ()).throw(tomllib.TOMLDecodeError("bad table", "[bad", 0)),
    )
    console = Console(record=True)

    result = voice._speak(console, "test", "hello", rate=None, voice=None)

    assert result == 1
    assert "Could not read resident voice settings safely" in console.export_text()


def test_speak_returns_failure_when_speaker_cleanup_fails(monkeypatch):
    import sys
    import types

    from rich.console import Console

    from scribe.cli import voice
    from scribe.voice import tts

    class Speaker:
        def speak(self, _text):
            return None

        def close(self):
            raise RuntimeError("engine would not close")

    class Listener:
        def __init__(self, **_kwargs):
            return None

        def start(self):
            return None

        def stop(self):
            return None

    keyboard = types.ModuleType("keyboard")
    keyboard.Key = types.SimpleNamespace(esc=object())
    keyboard.Listener = Listener
    pynput = types.ModuleType("pynput")
    pynput.keyboard = keyboard
    monkeypatch.setitem(sys.modules, "pynput", pynput)
    monkeypatch.setattr(tts, "resolve_tts_backend", lambda *_args, **_kwargs: "pyttsx3")
    monkeypatch.setattr(tts, "kokoro_installed", lambda: False)
    monkeypatch.setattr(tts, "kokoro_assets_ready", lambda: False)
    monkeypatch.setattr(tts, "make_speaker", lambda *_args, **_kwargs: Speaker())
    console = Console(record=True)

    result = voice._speak(console, "test", "hello", rate=None, voice=None)

    assert result == 1
    assert "Could not close read-aloud cleanly" in console.export_text()
    assert "Done" not in console.export_text()


def test_run_listen_exits_before_model_load_when_resident_voice_is_owned(
    monkeypatch,
):
    from types import SimpleNamespace

    from rich.console import Console

    from scribe.cli import voice
    from scribe.voice import instance

    class DuplicateLock:
        owner = SimpleNamespace(description="PID 42, Scribe 2.8.1")

        def acquire(self):
            return False

        def release(self):
            raise AssertionError("a lock that was not acquired must not be released")

    monkeypatch.setattr(instance, "TrayInstanceLock", DuplicateLock)
    monkeypatch.setattr(
        voice,
        "_run_owned_listen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("duplicate launch reached model setup")
        ),
    )
    console = Console(record=True)

    assert voice.run_listen(console) == 0
    output = console.export_text()
    assert "already running" in output
    assert "without registering another hotkey listener" in output


def test_run_listen_retains_resident_voice_lock_until_process_exit(monkeypatch):
    from rich.console import Console

    from scribe.cli import voice
    from scribe.voice import instance

    retained: list[bool] = []

    class AcquiredLock:
        owner = None

        def acquire(self):
            return True

        def retain_until_process_exit(self):
            retained.append(True)

    monkeypatch.setattr(instance, "TrayInstanceLock", AcquiredLock)
    monkeypatch.setattr(voice, "_run_owned_listen", lambda *_args, **_kwargs: 7)

    assert voice.run_listen(Console(record=True)) == 7
    assert retained == [True]


def test_legacy_dictation_model_is_explicitly_unloaded():
    from types import SimpleNamespace

    from rich.console import Console

    from scribe.cli.voice import _unload_dictation_model

    unloaded: list[bool] = []
    model = SimpleNamespace(model=SimpleNamespace(unload_model=lambda: unloaded.append(True)))

    assert _unload_dictation_model(model, Console(record=True)) is True
    assert unloaded == [True]


def test_legacy_dictation_model_unload_failure_is_visible():
    from types import SimpleNamespace

    from rich.console import Console

    from scribe.cli.voice import _unload_dictation_model

    model = SimpleNamespace(
        model=SimpleNamespace(
            unload_model=lambda: (_ for _ in ()).throw(RuntimeError("CUDA still busy"))
        )
    )
    console = Console(record=True)

    assert _unload_dictation_model(model, console) is False
    assert "Could not explicitly unload the voice model" in console.export_text()


def test_legacy_worker_shutdown_is_bounded_when_inference_is_stuck():
    import queue

    from rich.console import Console

    from scribe.cli.voice import _stop_listen_worker

    class StuckWorker:
        def join(self, timeout=None):
            assert timeout == 0

        def is_alive(self):
            return True

    work_queue = queue.Queue(maxsize=2)
    console = Console(record=True)

    assert _stop_listen_worker(work_queue, StuckWorker(), console, timeout=0) is False
    assert work_queue.get_nowait() is None
    assert "did not stop in time" in console.export_text()


def test_legacy_worker_shutdown_discards_full_pending_queue_for_sentinel():
    import queue

    from rich.console import Console

    from scribe.cli.voice import _stop_listen_worker

    class StuckWorker:
        def join(self, timeout=None):
            assert timeout == 0

        def is_alive(self):
            return True

    work_queue = queue.Queue(maxsize=2)
    work_queue.put_nowait(b"first")
    work_queue.put_nowait(b"second")
    console = Console(record=True)

    assert _stop_listen_worker(work_queue, StuckWorker(), console, timeout=0) is False
    assert work_queue.get_nowait() is None
    assert "Discarded 2 queued dictation utterance" in console.export_text()


def test_write_wav_roundtrip(tmp_path):
    pcm = (1234).to_bytes(2, "little", signed=True) * 100  # 100 samples
    out = tmp_path / "a.wav"
    write_wav(out, pcm, 16000)
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000
        assert w.getnframes() == 100
