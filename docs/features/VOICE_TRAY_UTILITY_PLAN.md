# Resident Voice Tray Status and Plan

## Current status

The resident voice utility is implemented and live-validated on Windows. macOS
and Linux use the same Python architecture but remain experimental until the
hardware records in
[VOICE_TRAY_MAC_LINUX_VALIDATION.md](VOICE_TRAY_MAC_LINUX_VALIDATION.md) are
complete.

This document records the shipped design and remaining work. It is not a promise
that every desktop, compositor, audio device, or accessibility configuration has
been validated.

## Shipped user contract

`scribe tray` provides a user-scoped resident service with:

- Tap-to-toggle dictation on F9 by default, with hold activation available.
- Tap-to-toggle selection read-aloud on F8.
- Local speech-to-text and local text-to-speech by default.
- Configurable F6 through F12 hotkeys, read speed, activation, and profiles.
- Bounded capture duration and bounded action backlog.
- Optional model preload after the tray is ready.
- Run-at-login install, status, and removal commands.
- A read-only `scribe tray --check` readiness report.
- A visible `--no-tray` terminal fallback.

The legacy `scribe listen` and `scribe say` commands remain supported for direct
terminal workflows. They share resident ownership with the tray and cannot claim
the same global controls concurrently.

## Python implementation

The production implementation lives in `src/scribe/voice/`:

- `service.py` coordinates hotkeys, capture, transcription, injection, read-aloud,
  recovery, and shutdown.
- `tray.py` implements the tray surface and menu actions.
- `instance.py` owns the per-user operating-system lock and process identity.
- `settings.py` validates voice settings and platform advisories.
- `setup.py` prepares local models and read-aloud assets.
- `startup.py` manages user-scoped run-at-login entries.
- `tts.py` selects, warms, and controls local read-aloud backends.

The Python tray uses pystray and pynput through optional extras. Kokoro ONNX is the
preferred optional local voice when installed and prepared. The system voice is a
reported fallback when Kokoro is unavailable or fails.

## Lifecycle and safety properties

Only one resident voice owner is allowed per user. The stable operating-system
lock is independent of a particular virtual environment, so installing a new
Scribe version does not permit a duplicate hotkey or microphone owner.

The service does not claim successful shutdown until hotkey hooks, active capture,
managed work, read-aloud, native control, and model release reach a safe boundary.
The operating system releases the ownership lock at actual process termination.

Hotkey callbacks enqueue work rather than performing model or clipboard work on
the hook thread. The action backlog is fixed at 32 entries. Overflow is surfaced
and stale capture intent is stopped instead of allowing unbounded memory growth.

Each capture stops after five minutes if the user misses the stop gesture. Text
injection preserves and restores clipboard content where the platform permits it.
Device and permission failures are reported rather than silently changing the
input or data boundary.

## Platform boundary

| Platform | Current tier | Important constraints |
|---|---|---|
| Windows | Validated | Verify microphone, hotkeys, tray host, and Startup shortcut on the target machine |
| macOS | Experimental | Requires Microphone and Input Monitoring; typed injection also requires Accessibility |
| Linux X11 | Experimental | Needs a graphical display and a compatible tray or AppIndicator host |
| Linux Wayland | Experimental | Global hooks vary by compositor; desktop shortcuts or `--no-tray` may be required |
| Headless or SSH | Unsupported for tray | No desktop tray or global focused-window contract |

Automated tests simulate platform advice and lifecycle failure paths. They do not
replace live permission, audio-device, compositor, startup, and application
integration testing.

## Native prototype boundary

`cmd/scribe-tray/` contains a Go tray-control prototype. It is not automatically
selected, packaged, or distributed. Developers must opt in through the documented
native binary path. The Python service requires the native controller to
authenticate, register required hotkeys, and signal readiness. Loss of the
authenticated control channel is a failure.

`crates/scribe-audio-core/` contains a Rust audio-core prototype for bounded media
operations. It is built and checked in CI, but it is not bundled into the Python
wheel and does not replace the Python voice service.

Neither prototype is an official downloadable native application. Signing,
checksums, embedded source identity, and release provenance are required before
native binaries are distributed.

## Remaining work in priority order

### 1. Complete live macOS and Linux validation

Run the dated matrix for macOS, Linux X11, and representative Wayland behavior.
Capture sanitized evidence for permissions, microphone and speaker devices,
hotkeys, tray visibility, injection, read-aloud, startup, clean shutdown, and
failure recovery.

This comes first because the current implementation and automated tests cannot
prove the operating system will grant or route those desktop capabilities.

### 2. Fix findings from the live matrix

Treat a missing core capability as a documented limitation unless a small,
maintainable platform adapter can supply it. Provide a tested fallback instead of
claiming unsupported parity.

### 3. Reduce service orchestration complexity

Separate capture, injection, read-aloud, and shutdown coordination behind smaller
tested boundaries while preserving the current single-instance and bounded-queue
contracts.

### 4. Decide the native distribution strategy

After the Python path is validated, decide whether native components materially
improve reliability enough to justify packaging and signing work. Do not ship a
native binary merely because prototype source exists.

## Completion criteria

Resident voice can be called validated on a platform only when a dated record for
an exact Scribe commit demonstrates:

- Clean install and `scribe tray --check`.
- Permission denial and recovery.
- Dictation start, stop, transcription, and injection in at least two apps.
- Read-aloud start, stop, and clipboard restoration.
- Hotkey conflict, pause, remap, and duplicate-process behavior.
- Run-at-login install, launch, status, and removal.
- Clean shutdown with no retained microphone, hook, process, or accelerator owner.
- Sanitized evidence without user paths, secrets, participant names, or company
  data.

Version baseline: Scribe 2.9.2.
