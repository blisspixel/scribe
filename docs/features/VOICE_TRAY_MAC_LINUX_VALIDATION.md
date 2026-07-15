# macOS and Linux Voice Tray Validation Plan

Status: live hardware evidence pending as of 2026-07-15.

This file is a validation plan, not a record of completed platform testing. The
repository has automated advisory and failure-message coverage, but it does not
contain reproducible artifacts proving the resident tray, global hotkeys,
microphone, selection read-aloud, text injection, or startup behavior on macOS or
Linux hardware. README and ROADMAP therefore describe Windows as the only
live-validated resident-tray platform.

## Automated Evidence Available

- `tray_platform_matrix` classifies macOS and Linux as experimental.
- `scribe tray --check` reports the selected backend and local dependency state.
- macOS output explains Input Monitoring and Microphone permission requirements.
- Linux output distinguishes X11, Wayland, graphical, and headless sessions.
- Unit tests cover those advisories without claiming that hardware behavior passed.
- The complete Python tray is the default. The native Go source prototype remains
  explicit opt-in and is not a substitute for this platform matrix.

## Required macOS Record

Record all of the following in one reproducible run:

- Date, Scribe commit, macOS version, hardware model, Python version, and install command.
- Input Monitoring and Microphone permission state before and after grants.
- Menu-bar icon visibility, status changes, pause/resume, live F6-F12 remapping,
  read speed, quit, and start-at-login behavior.
- Dictation start/stop, transcription, and paste/type injection in at least two applications.
- Selection read-aloud start/stop and clipboard restoration.
- Microphone and speaker device names, local STT backend, TTS backend, and profile.
- `scribe tray --check` output with secrets and user paths removed.
- Recovery behavior for denied permissions, unavailable audio, and hotkey conflict.

## Required Linux X11 Record

Record all of the following in one reproducible run:

- Date, Scribe commit, distribution/version, desktop environment, X11 session,
  Python version, and install command.
- Tray or AppIndicator implementation and whether an extra desktop extension is required.
- Icon visibility, status changes, pause/resume, live F6-F12 remapping, read speed,
  quit, and XDG start-at-login behavior.
- Dictation, selection read-aloud, clipboard restoration, and paste/type injection
  in at least two applications.
- PipeWire or PulseAudio source and sink names, local STT backend, TTS backend, and profile.
- `scribe tray --check` output with secrets and user paths removed.
- Recovery behavior for missing display, unavailable audio, and hotkey conflict.

## Required Linux Wayland Record

Wayland global hooks are not assumed to work. Record:

- Distribution/version, compositor, desktop environment, and portal availability.
- The exact `scribe tray --check` advisory.
- Whether the icon is available through AppIndicator or another supported mechanism.
- A tested desktop-shortcut or `--no-tray` workflow that does not promise unreliable
  global hotkeys.
- Startup, microphone, read-aloud, and text-injection limitations observed live.

## Completion Rule

Do not mark the macOS/Linux roadmap item complete until each claimed environment
has a dated record with the fields above and its failures have actionable recovery
copy. If a platform cannot support a core flow, document the limitation and a
tested fallback instead of calling it validated.
