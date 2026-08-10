"""Tests for the pure text-to-speech backend logic (voice/tts.py).

The Speaker implementations drive audio hardware and optional packages and are
exercised by hand; what is covered here is the platform-independent logic:
backend selection, voice/lang resolution, asset paths and readiness, and the
sentence chunker.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scribe.voice.tts import (
    DEFAULT_KOKORO_VOICE,
    KOKORO_MODEL_FILE,
    KOKORO_VOICE_CHOICES,
    KOKORO_VOICES_FILE,
    kokoro_asset_paths,
    kokoro_assets_ready,
    kokoro_dir,
    kokoro_lang_for_voice,
    resolve_tts_backend,
    resolve_tts_speed,
    resolve_tts_voice,
    split_for_speech,
    unload_kokoro,
)


def test_resolve_tts_speed_clamps_and_defaults() -> None:
    assert resolve_tts_speed(None) == 1.0
    assert resolve_tts_speed("") == 1.0
    assert resolve_tts_speed("nonsense") == 1.0
    assert resolve_tts_speed(1.2) == 1.2
    assert resolve_tts_speed("1.5") == 1.5
    assert resolve_tts_speed(5.0) == 2.0  # clamped to max
    assert resolve_tts_speed(0.1) == 0.5  # clamped to min
    assert resolve_tts_speed(float("nan")) == 1.0
    assert resolve_tts_speed(float("inf")) == 1.0


def test_unload_kokoro_clears_all_cached_models() -> None:
    from scribe.voice import tts

    tts._kokoro_models.clear()
    tts._kokoro_models["first"] = object()
    tts._kokoro_models["second"] = object()

    assert unload_kokoro() == 2
    assert tts._kokoro_models == {}


def test_unload_kokoro_is_bounded_behind_an_active_load() -> None:
    from scribe.voice import tts

    assert tts._kokoro_lock.acquire(blocking=False)
    try:
        with pytest.raises(TimeoutError, match="still loading"):
            unload_kokoro(timeout=0)
    finally:
        tts._kokoro_lock.release()


def test_split_for_speech_rejects_nonpositive_chunk_size() -> None:
    with pytest.raises(ValueError, match="must be positive"):
        split_for_speech("hello", max_chars=0)


def test_system_speaker_stop_before_speak_prevents_late_playback(monkeypatch) -> None:
    import sys
    import types

    from scribe.voice.tts import Pyttsx3Speaker

    events: list[str] = []

    class Engine:
        def say(self, _text: str) -> None:
            events.append("say")

        def runAndWait(self) -> None:
            events.append("run")

        def stop(self) -> None:
            events.append("stop")

    module = types.ModuleType("pyttsx3")
    module.init = lambda: Engine()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyttsx3", module)
    speaker = Pyttsx3Speaker()

    speaker.stop()
    speaker.speak("must remain silent")

    assert events == ["stop"]


def test_resolve_tts_backend_auto_prefers_kokoro_only_when_ready() -> None:
    # auto: Kokoro only when both installed and its model files are present.
    assert resolve_tts_backend("auto", kokoro_installed=True, kokoro_ready=True) == "kokoro"
    assert resolve_tts_backend("auto", kokoro_installed=True, kokoro_ready=False) == "pyttsx3"
    assert resolve_tts_backend("auto", kokoro_installed=False, kokoro_ready=True) == "pyttsx3"
    assert resolve_tts_backend(None, kokoro_installed=False, kokoro_ready=False) == "pyttsx3"


def test_resolve_tts_backend_explicit_kokoro_degrades_when_unavailable() -> None:
    # An explicit kokoro request still falls back rather than hard-failing.
    assert resolve_tts_backend("kokoro", kokoro_installed=True, kokoro_ready=True) == "kokoro"
    assert resolve_tts_backend("kokoro", kokoro_installed=True, kokoro_ready=False) == "pyttsx3"
    assert resolve_tts_backend("kokoro", kokoro_installed=False, kokoro_ready=False) == "pyttsx3"


def test_resolve_tts_backend_explicit_pyttsx3_never_uses_kokoro() -> None:
    assert resolve_tts_backend("pyttsx3", kokoro_installed=True, kokoro_ready=True) == "pyttsx3"


def test_resolve_tts_backend_unknown_value_is_treated_as_auto() -> None:
    assert resolve_tts_backend("banana", kokoro_installed=True, kokoro_ready=True) == "kokoro"


def test_resolve_tts_voice_defaults() -> None:
    assert resolve_tts_voice(None) == DEFAULT_KOKORO_VOICE
    assert resolve_tts_voice("  ") == DEFAULT_KOKORO_VOICE
    assert resolve_tts_voice("am_michael") == "am_michael"


def test_kokoro_lang_for_voice_by_prefix() -> None:
    assert kokoro_lang_for_voice("af_heart") == "en-us"  # American
    assert kokoro_lang_for_voice("bm_george") == "en-gb"  # British
    assert kokoro_lang_for_voice("") == "en-us"  # default
    assert kokoro_lang_for_voice("zz_unknown") == "en-us"  # default


def test_kokoro_asset_paths_use_given_home(tmp_path: Path) -> None:
    directory = kokoro_dir(tmp_path)
    assert directory == tmp_path / ".scribe" / "voices" / "kokoro"
    model_path, voices_path = kokoro_asset_paths(tmp_path)
    assert model_path.name == KOKORO_MODEL_FILE
    assert voices_path.name == KOKORO_VOICES_FILE


def test_kokoro_assets_ready_requires_both_files_at_size(tmp_path: Path) -> None:
    model_path, voices_path = kokoro_asset_paths(tmp_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)

    assert kokoro_assets_ready(tmp_path) is False  # nothing yet

    # A too-small (truncated) model file must not count as ready.
    model_path.write_bytes(b"\x00" * 1024)
    voices_path.write_bytes(b"\x00" * (2 * 1024 * 1024))
    assert kokoro_assets_ready(tmp_path) is False

    # Big enough to clear the floors -> ready.
    model_path.write_bytes(b"\x00" * (51 * 1024 * 1024))
    assert kokoro_assets_ready(tmp_path) is True


def test_split_for_speech_empty_and_whitespace() -> None:
    assert split_for_speech("") == []
    assert split_for_speech("   \n  ") == []


def test_split_for_speech_groups_sentences_under_limit() -> None:
    text = "Hello there. How are you? I am fine."
    chunks = split_for_speech(text, max_chars=100)
    assert chunks == ["Hello there. How are you? I am fine."]


def test_split_for_speech_breaks_on_sentence_boundary_when_over_limit() -> None:
    text = "One two three four. Five six seven eight."
    chunks = split_for_speech(text, max_chars=20)
    assert chunks == ["One two three four.", "Five six seven eight."]
    assert all(len(c) <= 21 for c in chunks)


def test_split_for_speech_keeps_a_slightly_long_sentence_whole() -> None:
    # A sentence a little over the target is NOT chopped mid-word.
    text = "word " * 30  # 150 chars, one run, no sentence breaks
    chunks = split_for_speech(text.strip(), max_chars=100)
    assert chunks == [text.strip()]


def test_split_for_speech_hard_wraps_a_pathologically_long_run() -> None:
    # Past max_chars * 3 with no punctuation -> hard-wrapped so it cannot overflow.
    text = "x" * 350
    chunks = split_for_speech(text, max_chars=100)
    assert len(chunks) == 4
    assert "".join(chunks) == text


def test_kokoro_voice_catalog_is_non_empty_and_well_formed() -> None:
    assert KOKORO_VOICE_CHOICES
    assert any(choice.voice_id == DEFAULT_KOKORO_VOICE for choice in KOKORO_VOICE_CHOICES)
    for choice in KOKORO_VOICE_CHOICES:
        assert choice.voice_id and choice.label
