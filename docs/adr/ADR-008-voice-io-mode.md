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
- Limitations stated plainly: dictation and read-aloud depend on the installed
  local backend and the host's desktop permissions. Live microphone, hotkey, and
  TTS behavior still requires platform validation.

## Update (2026-06): v2 refinement

A review of established voice-typing and read-aloud tools (Wispr Flow, superwhisper,
WhisperWriter, OpenWhispr, the macOS Speak-Selection feature) and the security review
of v1 led to three changes, none of which alter the mode's place outside the batch
pipeline:

- Dictation moved to a push-to-activate model (the v1 always-on default was
  dropped, removing the always-on-microphone exposure the security review flagged).
  The current default is **tap-to-toggle** (`--mode toggle`: tap F9 to start, tap
  again to insert), matching Windows Voice Access and macOS hands-free dictation;
  `--mode hold` keeps push-to-hold and `--mode continuous` keeps always-listening.
- Text injection is selectable with `--inject paste|type`: `paste` (via the
  clipboard, restored on exit) stays the reliable default; `type` inserts at the
  cursor with keystrokes and never touches the clipboard.
- `scribe say` gained `--selection` (copy the current selection, then read it, the
  macOS Speak-Selection pattern) and `--clipboard`, with Esc to stop playback. The
  file argument is now optional.

The option-resolution logic is pure and unit-tested; the live microphone, keyboard,
and TTS paths remain manual-only.

## Update (2026-08): resident tray and local Kokoro

The separate mode now also includes `scribe tray`, a single-instance resident
surface around the same dictation and read-aloud capabilities. Tap-to-toggle is
the default activation, with hold and continuous modes still explicit options.
The optional `tray` extra supplies the desktop tray, and the optional `kokoro`
extra supplies a higher-quality local ONNX voice with a reported system-voice
fallback.

Windows is live-validated. macOS and Linux remain experimental pending the dated
permission, device, hotkey, tray, injection, startup, and shutdown matrix. The Go
tray is an explicit source prototype and is not an automatically selected or
officially distributed binary.
