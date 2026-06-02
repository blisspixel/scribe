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

    assert resolve_listen_mode(None) == "hold"  # default
    assert resolve_listen_mode("HOLD") == "hold"
    assert resolve_listen_mode("continuous") == "continuous"
    with pytest.raises(ValueError, match="--mode"):
        resolve_listen_mode("toggle")


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

    monkeypatch.setattr(voice, "_read_clipboard", lambda console: "")
    assert voice.run_say(Console(), None, use_clipboard=True) == 1


def test_run_say_selection_dispatch(monkeypatch):
    from rich.console import Console

    from scribe.cli import voice

    monkeypatch.setattr(voice, "_read_selection", lambda console: "")
    assert voice.run_say(Console(), None, use_selection=True) == 1


def test_run_say_empty_text_returns_before_tts(tmp_path):
    # Frontmatter + a code fence only -> no speakable text, so it returns 1
    # without ever importing or invoking the TTS engine (no audio in tests).
    from rich.console import Console

    from scribe.cli.voice import run_say

    f = tmp_path / "empty.md"
    f.write_text("---\nx: 1\n---\n```\ncode only\n```\n", encoding="utf-8")
    assert run_say(Console(), f) == 1


def test_write_wav_roundtrip(tmp_path):
    pcm = (1234).to_bytes(2, "little", signed=True) * 100  # 100 samples
    out = tmp_path / "a.wav"
    write_wav(out, pcm, 16000)
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000
        assert w.getnframes() == 100
