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
and writes the resulting settings to the [user config file](STORAGE.md). `tray --check` is
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
| Linux Wayland | pynput does not register compositor bindings. Portal GlobalShortcuts support varies by desktop |
| Omarchy | `scribe voice` is the experimental compositor path. Leave F9, Super+Ctrl+X, and Right Alt push-to-talk to Omarchy dictation. A check exit is not hardware validation |
| Headless or SSH | Tray icons and global desktop hotkeys are unsupported |

## Omarchy

Omarchy already has a dictation path. When a backend such as Voxtype or
Superwhisper is installed, F9 is push-to-talk, Super+Ctrl+X toggles dictation,
and holding Right Alt starts it. Scribe must not take those keys.

`scribe voice` is the experimental local path for this desktop. It talks to the
one resident `VoiceTrayService`. It does not open a second microphone and it
does not load a second model. Cloud transcription is not a command on this
path. The microphone stays off until `scribe voice dictate` or Super+Alt+D.
Recording state is visible in three places: a red `MICROPHONE ON` banner in
`scribe voice overlay`, the exact text `MICROPHONE ON` in
`$XDG_STATE_HOME/scribe/voice-status.txt` (default
`~/.local/state/scribe/voice-status.txt`), and a critical notification. Processing, reading,
and errors say the microphone is off.

Install the tray extra, then add only the marked user blocks:

```bash
uv tool install --force --python 3.12 \
  "scribe[tray] @ git+https://github.com/blisspixel/scribe.git@v2.12.0"
scribe voice check
scribe voice omarchy-install
```

From a checkout, `bash packaging/linux/omarchy/install.sh` does both steps.
`bash packaging/linux/omarchy/uninstall.sh` runs `scribe voice omarchy-remove`
and `uv tool uninstall scribe`. XDG Scribe directories and legacy `~/.scribe` are left in place; see
[storage paths](STORAGE.md). Upgrade by running
the install script again. The scripts are not a package-index submission and
they are not a tested Omarchy installation.

The installed chords, which you must confirm with Super+K, are:

| Chord | Action |
|---|---|
| Super+Alt+D | Start or finish dictation |
| Super+Alt+Shift+D | Cancel and discard |
| Super+Alt+Y | Copy the last transcript without keystrokes |
| Super+Alt+I | Insert the last transcript into the focused window |
| Super+Alt+A | Read the last transcript with the local voice |
| Super+Alt+O | Open the terminal overlay |

The overlay launcher is `omarchy-launch-tui scribe voice overlay`. Inside the
overlay, `d`, `x`, `y`, `i`, `a`, and `q` dictate, cancel, copy, insert, read,
and close the panel. Closing the panel does not stop the owner. `scribe voice
stop` does. A second `scribe voice serve` exits without loading another model.

Insert copies the transcript, then asks Hyprland to paste with
`hl.dsp.send_key_state` down and up. Terminals such as Foot use Ctrl+Shift+V.
The transcript is never placed in the dispatcher string. `wtype` is not used.
If Hyprland does not confirm the paste, the command fails even when the
clipboard holds the text.

`scribe voice check` prints Python, sounddevice, and whether the marker blocks
are present. It does not open the microphone. `hardware_validated` stays false.
Exit 0 is not a tested Omarchy installation. Microphone selection, focus
changes, correct-target insertion, cancellation, device loss, and recovery are
still required before this path leaves experimental.

The resident tray still cannot see Hyprland keypresses. `scribe tray --startup
install` writes an XDG autostart file only. That file does not add a binding,
and Quickshell is not assumed to show a tray icon. `scribe voice serve` is the
autostart line the marker block adds to `~/.config/hypr/autostart.lua`.

Use `scribe` in Foot for file transcription and `scribe rec` for OBS recording.
A personal recording bind, if you want one, stays separate from the voice chords:

```lua
o.bind("SUPER + ALT + R", "Check Scribe recording", "scribe rec --check")
```

Confirm that chord is free with Super+K as well. Do not edit the packaged files
under `/usr/share/omarchy`; an update replaces them. After saving
`~/.config/hypr/bindings.lua`, run `hyprctl reload` and `hyprctl configerrors`.

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
the [platform state log](STORAGE.md) , `resident-voice.log` . The log rotates at 1 MB
and retains three
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
