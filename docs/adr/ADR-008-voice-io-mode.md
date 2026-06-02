# ADR-008: Voice I/O as a deliberate mode outside the batch pipeline

## Status

Accepted (2026-06).

## Context

Scribe's batch pipeline has an explicit non-goal: no real-time or streaming
transcription, because batch file processing is simpler and more reliable
(ROADMAP, Explicit Non-Goals). Two voice features are nonetheless strong quality-
of-life wins for a local-first tool: global-hotkey dictation (speak, have the text
typed into the focused window) and read-aloud (a transcript or notes file spoken
back by a local TTS engine). Both are inherently real-time, so adding them naively
would contradict the stated non-goal.

## Decision

Add voice I/O as a separate, opt-in product mode rather than a feature of the batch
pipeline, and scope the streaming non-goal to the batch pipeline specifically.

- New `cli/voice.py` with `scribe listen` (dictation) and `scribe say` (read-aloud).
- The correctness-critical logic is pure and unit-tested: `UtteranceSegmenter`
  (silence-based endpointing), `HotkeyToggle` (push-to-toggle state), and
  `speakable_from_markdown` (turning a transcript or notes file into spoken text).
- The runtime wrappers touch the microphone (sounddevice), keyboard (pynput),
  clipboard (pyperclip), and a local offline TTS engine (pyttsx3). They ship behind
  the optional `scribe[voice]` extra and fail with a clear install message when a
  dependency is absent; nothing else in Scribe depends on them.
- Dictation loads a single faster-whisper model once and reuses it per utterance
  for low latency, and injects text via the clipboard. F9 toggles, Esc quits.

The ROADMAP non-goal is reworded: real-time/streaming is held out of the **batch
pipeline**; voice I/O is a distinct surface adopted on purpose, not drift.

## Consequences

- The batch pipeline keeps its simplicity guarantee; voice I/O does not touch it.
- The feature degrades cleanly: without the extra (or a microphone) the commands
  explain what to install and exit, rather than failing elsewhere.
- Honesty on testing: the live microphone, hotkey, and TTS paths cannot run in CI,
  so they are exercised manually. The pure endpointing, toggle, and text-extraction
  logic is covered by unit tests and a property test, which is the part where
  correctness actually matters.
- Limitations stated plainly: dictation currently uses faster-whisper (NVIDIA/CPU);
  routing it through the mlx-whisper and whisper.cpp backends is future work.
  Read-aloud uses the offline pyttsx3 voice; a higher-quality online voice
  (for example edge-tts) can be added later behind a flag without changing the mode.
