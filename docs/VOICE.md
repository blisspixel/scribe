# Resident Voice Guide

Scribe's opt-in voice mode provides speech-to-type, local read-aloud, and an
always-available tray. It is separate from the batch transcription pipeline.

## Install and verify

In a cloned checkout:

```bash
uv sync --locked --extra tray
uv run scribe tray --setup
uv run scribe tray --check
```

For the higher-quality local Kokoro voice:

```bash
uv sync --locked --extra tray --extra kokoro
uv run scribe tray --setup
```

For a non-project Python environment, install `scribe[tray]` and optionally
`scribe[kokoro]` using that environment's package installer.

`tray --setup` downloads the selected dictation model, prepares read-aloud assets,
and writes the resulting settings to `~/.scribe/config.toml`. `tray --check` is
read-only and reports dependencies, backend selection, platform advisories,
startup state, resident ownership, and the local diagnostic log path.

## Start the tray

```bash
scribe tray
scribe tray --no-tray
scribe tray --activation hold
scribe tray --profile accurate
scribe tray --no-preload
scribe tray --speed 1.2
```

Defaults:

- Tap F9 to start dictation; tap F9 again to transcribe and insert.
- Tap F8 to read the current selection; tap again to stop playback.
- The dictation model warms after the tray becomes visible.
- The Python tray menu can remap F6 through F12, change read speed, pause hotkeys,
  and toggle run-at-login.
- Each capture stops at five minutes to bound memory if a stop gesture is missed.

`--no-tray` keeps the same hotkeys but uses a visible terminal. It is useful when
the desktop does not provide a compatible tray host.

## Single-instance and resource contract

`scribe tray`, `scribe tray --no-tray`, and legacy `scribe listen` share one
stable per-user operating-system lock. The lock path is independent of a virtual
environment or installation version. A repeated launch reports the current owner
and exits before registering another global hook or loading another model.

The ownership lock is not released from an `atexit` handler. It remains open for
the operating system to release at actual process termination. Scribe will not
start a Python fallback while prior native control, microphone capture, hotkey
hooks, managed threads, model work, read-aloud, or explicit model release remains
unconfirmed. Failed cleanup retains the resource for another shutdown attempt. A
failed or slow CTranslate2 unload is visible and bounded; process exit remains the
final GPU resource boundary.

Resident callbacks use a fixed 32-action backlog. If a faulty hook, audio device,
or authenticated native client fills it, Scribe discards stale intent, stops the
active capture, and reports the recovery instead of growing memory without bound.

The native tray is a source prototype, not an official packaged artifact. Scribe
selects it only through an explicit `SCRIBE_TRAY_NATIVE_BIN` developer path. The
daemon must authenticate, register both hotkeys, and signal readiness. Loss of its
authenticated control connection is treated as failure, not as a healthy tray.

## Legacy voice commands

```bash
# Speech to type
scribe listen
scribe listen --mode hold
scribe listen --mode continuous
scribe listen --inject type
scribe listen --model small --language en

# Read aloud
scribe say transcript.txt
scribe say --selection
scribe say --clipboard
scribe say notes.md --speed 1.2
```

`listen` and the tray cannot run together because both need the same resident
ownership slot. Prefer the tray for daily use; `listen` remains useful for direct
terminal workflows.

Kokoro runs locally on CPU when installed and prepared. If it is unavailable or
fails, Scribe reports the issue and can fall back to the system voice.

## Run at login

```bash
scribe tray --startup install
scribe tray --startup status
scribe tray --startup remove
```

Run-at-login is user-scoped:

| Platform | Mechanism |
|---|---|
| Windows | Per-user Startup folder shortcut |
| macOS | User LaunchAgent |
| Linux | XDG autostart desktop entry |

The tray menu exposes the same toggle on the full Python backend.

## Platform status

Windows is the live-validated default. macOS and Linux use the same Python
implementation but remain experimental until the hardware validation matrix is
complete.

| Platform | Required checks |
|---|---|
| Windows | Run `scribe tray --check`; verify microphone, hotkeys, tray, and startup |
| macOS | Grant Input Monitoring and Microphone to the launching binary; typed injection also needs Accessibility; fully quit and relaunch after permission changes |
| Linux X11 | Use a graphical `DISPLAY`; ensure the desktop has an AppIndicator or StatusNotifier host, or use `--no-tray` |
| Linux Wayland | Global hooks vary by compositor; prefer desktop shortcuts or an X11 session when hooks are unreliable |
| Headless or SSH | Tray icons and global desktop hotkeys are unsupported |

Record live macOS and Linux results in the
[validation matrix](features/VOICE_TRAY_MAC_LINUX_VALIDATION.md). The original
design and remaining prototype work are in the
[resident tray plan](features/VOICE_TRAY_UTILITY_PLAN.md).

## Diagnostics and recovery

Start with:

```bash
scribe tray --check
scribe doctor
```

Detached tray events are written to
`~/.scribe/logs/resident-voice.log`. The log rotates at 1 MB and retains three
backups. Files and the containing Scribe directory are restricted to the current
user where the operating system supports permission modes.

Common recovery steps:

1. Read the exact `tray --check` failure and install the listed optional package.
2. Confirm the operating system permissions for the same binary that launches
   Scribe at login.
3. Quit the existing tray through its menu before changing installation paths.
4. Run `scribe tray --startup status` and remove stale launch configuration if it
   points at an obsolete install.
5. Check `nvidia-smi` and the resident log if GPU memory remains allocated after
   the Scribe process has exited.

Do not terminate arbitrary Python processes based only on their executable name.
If manual cleanup is unavoidable, identify the verified Scribe process tree first.
