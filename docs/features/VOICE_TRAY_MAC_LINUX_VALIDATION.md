# macOS and Linux Voice Tray Validation Plan

Status: live hardware evidence pending. Scribe 2.11.0 adds the experimental
Omarchy compositor path in source. That release does not complete this record.

This file is a validation plan, not a record of completed platform testing. The
repository has automated advisory and failure-message coverage, but it does not
contain reproducible artifacts proving the resident tray, global hotkeys,
microphone, selection read-aloud, text injection, startup behavior, or the
`scribe voice` compositor path on macOS or Linux hardware. README and ROADMAP
therefore describe Windows as the only live-validated resident-voice platform.
`scribe voice check` is not allowed to mark Linux voice validated.

## Automated Evidence Available

Automated evidence in the Scribe 2.9.3 baseline:

- `tray_platform_matrix` classifies Windows as `validated`, macOS/Linux as
  `experimental`, and other systems as `unsupported`.
- `scribe tray --check` prints `platform` (system + tier), dependency markers,
  backend trust state, startup enablement path, and readiness advisories without
  requiring paid services or network keys.
- macOS advisories cover Input Monitoring, Microphone, LaunchAgent run-at-login,
  and Accessibility when `inject=type`.
- Linux advisories distinguish headless (no false X11 support claim), X11
  (AppIndicator / `--no-tray` note), Wayland (Hyprland and Omarchy dictation-key
  caveat, portal GlobalShortcuts, and XDG autostart that does not create a
  Hyprland binding).
- Unit tests cover matrix tiers, headless contradiction guards, Wayland/X11
  branches, macOS permission and Accessibility copy, and check presentation of
  `platform` / `startup` lines.
- The complete Python tray is the default. The native Go source prototype remains
  explicit opt-in and is not a substitute for this platform matrix.

Automated evidence does **not** satisfy the completion rule below.

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

The representative Wayland record is Omarchy: Arch, Hyprland, and Quickshell.
Wayland global hooks are not assumed to work. Record:

- Omarchy version, Hyprland session, Quickshell, Python version reported by
  `scribe doctor`, and the exact `uv tool install --python 3.12` command.
- The exact `scribe tray --check` advisory.
- Whether Quickshell showed a tray icon. Absence is an expected result, not a
  failed parity check.
- Confirmation that F9, Super+Ctrl+X, and Right Alt push-to-talk still belong to
  Omarchy dictation when that backend is installed.
- A tested terminal workflow for transcription and `scribe rec --check`. Do not
  count an XDG autostart file as a Hyprland binding.
- Startup, microphone, read-aloud, and text-injection limitations observed live.
  Do not treat `wtype` as success while Super is held.
- The exact `scribe voice check` output. It must keep the path experimental and
  must not be described as hardware validation. These compositor checks are
  required and are not done:
  - microphone selection on the running owner
  - a focus change while dictation is active
  - correct-target insertion into the focused window, including a terminal paste
  - cancellation that discards audio or an in-flight transcript
  - device loss and recovery
  - the overlay showing `MICROPHONE ON` only while the microphone is open, and
    `$XDG_STATE_HOME/scribe/voice-status.txt` (default
`~/.local/state/scribe/voice-status.txt`) matching that state
- Whether Super+K showed a collision with Super+Alt+D, Super+Alt+Shift+D,
  Super+Alt+Y, Super+Alt+I, Super+Alt+A, or Super+Alt+O.
- Copy without keystrokes, explicit insert, and explicit local read-aloud of the
  stored transcript. A second `scribe voice serve` must not load another model.

## Completion Rule

Do not mark the macOS/Linux roadmap item complete until each claimed environment
has a dated record with the fields above and its failures have actionable recovery
copy. If a platform cannot support a core flow, document the limitation and a
tested fallback instead of calling it validated.
