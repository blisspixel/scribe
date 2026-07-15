# Resident Voice Tray Utility Plan

## Status

Shipped and validated on Windows (real dictation, read-aloud, hotkeys, run-at-login):

- `scribe tray` runs a resident tray icon. Dictation and read-aloud default to
  **tap-to-toggle** (tap to start, tap again to stop); `--activation hold` keeps
  push-to-talk. Hotkey actions run on a dispatcher thread, not the keyboard-hook
  callback, and a watchdog recreates the listener if Windows silently removes the
  low-level hook.
- `scribe tray --check` reports dependencies, the resolved read-aloud backend, and
  macOS Input-Monitoring / Linux-Wayland permission caveats.
- `scribe tray --setup` pre-downloads the dictation model and a read-aloud voice
  (with byte-verified downloads) and saves the choice.
- `scribe tray --startup install|remove|status` runs the tray at login
  (Startup-folder `.lnk` / LaunchAgent / XDG autostart).
- The tray menu shows + remaps the hotkeys (F6-F12), sets read-aloud speed
  (0.5-2.0x), and toggles start-at-login, all live.
- STT: latency-first profiles (`balanced` → small, `accurate` → large-v3-turbo on
  12GB+), model preloaded at startup with a loading indicator.
- TTS: Kokoro (82M, ONNX) when installed (`scribe[kokoro]`), cached/warmed and
  pipelined for gap-free multi-paragraph reads, with a pyttsx3 system-voice
  fallback on any failure.

Automated tests cover the pure settings/state/dependency/CLI wiring plus the
toggle state machine, clipboard resilience, TTS backend/speed resolution, and
the startup install/remove round-trip. The **macOS and Linux hardware matrix**
(global hotkeys, permissions, tray backend, audio devices) is the remaining
manual-validation work.

## Goal

Add a resident Scribe tray/menu-bar utility that users can leave running all day:

- Hold a global hotkey to dictate into the currently focused text field.
- Press a second global hotkey to read the current selection aloud.
- Keep all default speech processing local and private.
- Use high-quality GPU acceleration on machines like an RTX 4090.
- Degrade cleanly on CPU-only, Apple Silicon, AMD, Intel, and Linux desktop setups.

This is the desktop shell around the existing `scribe listen` and `scribe say`
capabilities. It is not part of the batch transcription pipeline.

## Research Summary

### Tray Surface

Two realistic Python options:

- `pystray`: lightweight, tray-focused, and documented as supporting Windows,
  macOS, and Linux backends. Its own docs note that Windows and macOS have native
  tray support, while Linux backend choice depends on the desktop environment.
- PySide6 `QSystemTrayIcon`: more complete and better if Scribe later needs a real
  preferences window. Qt documents `isSystemTrayAvailable()`, context menus, and
  tray messages, but this adds a much larger GUI dependency.

Decision: start with `pystray` in a new optional `tray` extra. Keep PySide6 as the
fallback path only if the tray menu grows into a real settings UI.

Sources:

- [pystray usage docs](https://pystray.readthedocs.io/en/latest/usage.html)
- [Qt for Python QSystemTrayIcon docs](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html)

### Global Hotkeys

Scribe already depends on `pynput` for voice I/O. `pynput.keyboard.GlobalHotKeys`
is the right first implementation for Windows, macOS, and X11 Linux because it
matches the existing stack and avoids platform-specific code at the start.

Platform constraints:

- Windows has a native `RegisterHotKey` API and hotkey registration can fail when
  another application already owns the combination. Scribe must report conflicts
  clearly and allow users to change hotkeys.
- macOS requires user-granted keyboard monitoring permissions for apps that
  monitor keyboard input while another app is focused. A packaged app also needs
  microphone usage text in its app metadata.
- Wayland is the hard case. The modern direction is the XDG Desktop Portal
  GlobalShortcuts interface, but support varies by compositor and desktop
  environment. Scribe should support X11 through `pynput` first, then add a
  portal-backed Wayland adapter when practical. Until then, Linux Wayland users
  should be able to bind desktop shortcuts to explicit Scribe commands.

Sources:

- [pynput keyboard hotkey docs](https://pynput.readthedocs.io/en/latest/keyboard.html)
- [Microsoft RegisterHotKey docs](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey)
- [Apple Input Monitoring user guide](https://support.apple.com/guide/mac-help/control-access-to-input-monitoring-on-mac-mchl4cedafb6/mac)
- [Apple NSMicrophoneUsageDescription docs](https://developer.apple.com/documentation/BundleResources/Information-Property-List/NSMicrophoneUsageDescription)
- [XDG GlobalShortcuts portal docs](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.GlobalShortcuts.html)

### Speech To Text

For dictation, Scribe should keep the model loaded while the tray app runs. Cold
loading on every utterance is the wrong user experience, especially when a 4090
can keep a high-quality Whisper model resident.

Use the existing hardware-adaptive backend direction:

- NVIDIA GPU: faster-whisper through CTranslate2. This is already Scribe's best
  path, and faster-whisper documents lower memory use, strong speed, and CPU/GPU
  quantization support.
- CPU-only: faster-whisper int8 with smaller models.
- Apple Silicon: route through the existing MLX backend when voice support is
  wired to the backend registry.
- AMD/Intel/portable fallback: route through whisper.cpp where installed.

Default voice profiles:

| Profile | Target | Suggested model behavior |
|---|---|---|
| `fast` | CPU and older machines | `base` or `small`, int8 where needed |
| `balanced` | default for most users | GPU `small` or `medium`; CPU `base` |
| `accurate` | RTX 4090 and other high-VRAM GPUs | preload `large-v3-turbo` or `large-v3` |

On an RTX 4090, the tray utility should default to `balanced` for latency but offer
an obvious `accurate` profile. The exact default should be chosen after local
benchmarking on short utterances, because interactive dictation cares about
release-to-text latency more than batch throughput.

Sources:

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- [whisper.cpp](https://github.com/ggml-org/whisper.cpp)

### Endpointing And VAD

Push-to-hold dictation should be the default. The key press and release define the
recording window, which is simpler, safer, and easier to reason about than
always-on listening.

Continuous mode still needs real voice activity detection. The current RMS
threshold is acceptable as a simple fallback, but Silero VAD is a better default
for continuous mode because it is lightweight and optimized for CPU use.

Sources:

- [Silero VAD](https://github.com/snakers4/silero-vad)
- [PyTorch Silero VAD page](https://pytorch.org/hub/snakers4_silero-vad_vad/)

### Text Injection

Keep both injection methods:

- `paste`: default. It is faster and more reliable for long text. Scribe must
  restore the clipboard after injection.
- `type`: privacy-friendly alternative for users who do not want clipboard use.
  It is slower and more fragile, especially for long paragraphs or non-US keyboard
  layouts.

The tray menu should expose the active injection mode and allow switching it.

### Read Selection Aloud

Use a dedicated read-aloud hotkey by default instead of double-tapping the
dictation key. Double-tap gestures are harder to discover, harder to test, and
more prone to conflicts with push-to-hold behavior.

Recommended defaults:

- `F9`: hold to dictate.
- `F8`: read current selection aloud.
- `Esc`: cancel active dictation or speech playback where Scribe owns the active
  operation.

The implementation should use the existing selection-copy pattern, restore the
clipboard, and then feed cleaned text into the TTS adapter.

### Text To Speech

Keep `pyttsx3` as the baseline because it is offline and wraps native engines
across Windows, macOS, and Linux. Add an optional higher-quality local TTS adapter
later, most likely Piper, behind a separate extra and explicit voice download.

Sources:

- [pyttsx3](https://github.com/nateshmbhat/pyttsx3)
- [Piper](https://github.com/rhasspy/piper)
- [eSpeak NG](https://github.com/espeak-ng/espeak-ng)

## Product Design

### Commands

Add:

```bash
scribe tray
scribe tray --no-tray              # hotkeys only, useful on minimal Linux setups
scribe tray --profile accurate
scribe tray --dictate-hotkey f9
scribe tray --read-hotkey f8
scribe tray --check                # dependency and config diagnostics
```

Keep:

```bash
scribe listen
scribe say --selection
```

The existing commands remain the testable, scriptable primitives. The tray app is
intended to become the resident controller once the live desktop validation is
strong enough.

### Tray Menu

Menu items:

- Status: idle, model loading, listening, transcribing, speaking, paused, error.
- Dictation: enabled or paused.
- Profile: fast, balanced, accurate.
- Injection: paste or type.
- Read selection now.
- Open config.
- Run doctor.
- Start at login.
- Quit.

The tray icon should change state or show a short notification when the mic is
active. A visible mic-active cue is a hard requirement.

### Configuration

Add a `[voice.tray]` table in `~/.scribe/config.toml`:

```toml
[voice.tray]
enabled = false
start_at_login = false
dictate_hotkey = "f9"
read_hotkey = "f8"
profile = "balanced"
inject = "paste"
stt_backend = "auto"
stt_model = "auto"
tts_backend = "pyttsx3"
tts_voice = ""
show_notifications = true
```

All settings must also be overrideable by CLI flags.

## Architecture

### New Modules

```text
src/scribe/voice/
  __init__.py
  settings.py          # config model and hotkey parsing
  service.py           # long-running voice service state machine
  stt.py               # voice STT adapter over Scribe local backends
  tts.py               # pyttsx3 adapter, future Piper adapter
  inject.py            # paste/type injection and clipboard restore
  selection.py         # selection capture and cleanup
  hotkeys.py           # pynput adapter, future platform adapters
  tray.py              # pystray UI adapter
```

Keep `src/scribe/cli/voice.py` as a compatibility wrapper over the shared service
logic where possible.

### State Machine

The resident service should have explicit states:

```text
starting -> idle -> recording -> transcribing -> injecting -> idle
                 -> speaking -> idle
                 -> paused
                 -> error
```

Rules:

- Only one active operation at a time.
- Read-aloud interrupts only if configured, otherwise it is ignored while
  dictation is active.
- Quit stops listeners, audio streams, and TTS cleanly.
- Any hotkey failure leaves the tray running with a visible error.

### Model Lifecycle

Use lazy preload by default:

1. Tray starts quickly.
2. First dictation loads the selected model.
3. Optional `preload_model = true` loads at tray startup for users who prefer
   zero first-use delay.

On RTX 4090 class hardware, an `accurate` profile can keep a large model resident.
On constrained machines, model unload should be available from the menu.

## Platform Plan

### Windows

Priority platform for the first implementation.

- Tray through `pystray`.
- Hotkeys through `pynput`; add a native `RegisterHotKey` adapter only if pynput
  proves unreliable.
- Startup through a user Startup folder shortcut or HKCU Run entry. Prefer the
  existing shortcut infrastructure where possible.
- Use faster-whisper CUDA when available.

### macOS

Support, but expect a packaging pass.

- Tray/menu bar through `pystray`.
- Hotkeys through `pynput`.
- Document and diagnose Input Monitoring and Microphone permissions.
- A packaged `.app` should include microphone usage text in Info.plist.
- Apple Silicon voice STT should eventually route through the MLX backend.

### Linux

Support in tiers:

- X11: `pystray` plus `pynput`.
- Wayland with portal support: future GlobalShortcuts adapter.
- Wayland without portal support: `scribe tray --no-tray` plus documented desktop
  shortcuts bound to `scribe listen` or small one-shot commands.

Linux should never pretend global hotkeys are universally reliable.

## Security And Privacy

Hard requirements:

- No always-on mic by default.
- No cloud STT or cloud TTS unless explicitly configured.
- Visible active-microphone state.
- Clipboard restored after paste injection and selection capture.
- Clear warning before using dictation near terminals, password fields, or remote
  admin sessions.
- No hidden startup install. `start_at_login` must be explicitly enabled.
- Logs must not include dictated text or selected text by default.

## Implementation Phases

### Phase 1: Shared Voice Service

- Prototype baseline: pure settings, hotkey normalization, config precedence, and service
  status logic live under `src/scribe/voice/`.
- Prototype baseline: unit tests cover hotkey parsing, state transitions, dependency
  diagnostics, config precedence, and CLI check wiring.
- Verified in tests: existing `scribe listen` and `scribe say` behavior remains unchanged.

### Phase 2: Better Dictation Backend

- Shipped: latency-first voice profiles `fast`/`balanced`/`accurate` (small /
  large-v3-turbo on 12GB+), preloaded at startup and kept resident.
- Remaining: route dictation through Scribe's local backend registry instead of
  hardcoding faster-whisper.
- Remaining: short-utterance latency benchmark/diagnostic output.
- Remaining: Silero VAD for continuous mode, with RMS fallback.

### Phase 3: Tray App

- Shipped: `scribe tray` with `pystray`; tray states, pause/resume, quit.
- Shipped: tap-to-toggle (and hold) activation; the hook callback only enqueues,
  with a dispatcher thread + listener watchdog for hotkey reliability.
- Shipped: tray menu shows + remaps the hotkeys (F6-F12), sets read-aloud speed,
  and toggles start-at-login; same-hotkey collisions are rejected.
- Shipped: live I/O paths stay behind the `scribe[tray]`/`scribe[kokoro]` extras.
- Source prototype: the Go tray is explicit opt-in through
  `SCRIBE_TRAY_NATIVE_BIN`, supports toggle activation and F6-F12 keys, uses the
  canonical icon, authenticates to Python, and must signal readiness after both
  hotkeys register. It returns to Python on daemon launch, readiness, or exit failure.
- Blocked for automatic packaging: the Go tray does not yet provide the Python
  menu, desktop-notification, hold-activation, or actionable error-detail surface.
- Removed: the "Read selection now" menu item (opening the menu steals focus, so
  it could not capture a live selection - the read hotkey is the reliable path).
- Remaining: validate OS-level hotkey conflicts and permission failures on the
  macOS/Linux matrix.

### Phase 4: Startup And Doctor

- Shipped: `scribe tray --startup install/remove/status` and a tray "Start at
  login" toggle (Startup `.lnk` / LaunchAgent / XDG autostart).
- Shipped: `scribe doctor` voice-readiness check (opt-in, shown only when voice
  deps are installed) plus the macOS/Wayland advisories in `scribe tray --check`.
- Remaining: per-check microphone-available / configured-backend-available probes
  in `scribe doctor`.

### Phase 5: Packaging

- Shipped: `uv tool install "scribe[tray,kokoro]"` is the developer/power-user path.
- Shipped: run-at-login uses the existing shortcut/launcher mechanism.
- Later: evaluate packaged app builds with PyInstaller per OS (not blocking the
  Python tool path).

Sources:

- [PyInstaller usage docs](https://pyinstaller.org/en/stable/usage.html)
- [Microsoft Run and RunOnce registry keys](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys)

## Test Plan

Automated:

- Unit tests for settings, hotkey normalization, config precedence, state machine,
  injection decision logic, and selection cleanup.
- Socket-level tests for authentication, readiness, command gating, read stop, and
  shutdown; Go tests for F6-F12 mapping, collision rejection, and authentication.
- Routing tests prove source artifacts are not selected implicitly, incompatible
  native settings stay on Python, and failed native readiness does not start model
  preload before fallback.
- Mocked integration tests for tray menu callbacks.
- Mocked STT/TTS adapters so CI does not need a microphone, speaker, or GPU.
- Coverage stays above the existing 80 percent CI gate.

Manual matrix:

- Windows 11 with RTX 4090, CUDA faster-whisper, `balanced` and `accurate`.
- Windows CPU-only fallback.
- macOS Apple Silicon with permissions reset and re-granted.
- Linux X11.
- Linux Wayland with documented fallback behavior.

Manual scenarios:

- Tap `F9` (dictate, tap again to insert) in Notepad, browser text field,
  Slack/Teams, VS Code; confirm it does not type into a terminal/password field.
- Tap `F8` with selected text in browser, PDF viewer, and editor; tap again to stop.
- Remap the dictate/read keys from the tray menu and confirm they take effect live.
- Change read-aloud speed from the tray menu and on the next read.
- Enable/disable "Start at login" and confirm the tray launches at next login.
- Hotkey conflict / same-key rejection.
- Clipboard preservation; clipboard wedged → typing fallback.
- No microphone; missing optional dependencies; GPU unavailable after startup.

## Validation Criteria

Met on Windows:

- [x] `scribe tray` starts cleanly when optional deps are missing and prints an
      actionable install hint.
- [x] On an RTX 4090, dictation uses a preloaded model and inserts text into the
      focused app; feedback shows in the tray/terminal.
- [x] CPU-only path falls back to a smaller int8 model.
- [x] The read hotkey speaks the selection and restores clipboard state.
- [x] Read-aloud stop is prompt; multi-paragraph reads are gap-free.
- [x] Hotkey conflicts (same key) are rejected without crashing.
- [x] `scribe listen` and `scribe say` still work standalone.
- [x] Lint, type checks, and coverage-gated tests pass in CI.

Pending on macOS and Linux:
- [x] Non-live advisory tests identify Wayland, headless-session, and macOS permission constraints.
- [ ] Record reproducible live tray, hotkey, read-aloud, startup, and audio-device evidence on macOS Aqua.
- [ ] Record reproducible live tray, hotkey, read-aloud, startup, and audio-device evidence on Linux X11.
- [ ] Verify and document the supported fallback workflow on Linux Wayland.

## Open Decisions

- Decided: `balanced` defaults to `small` (latency-first) and `accurate` to
  `large-v3-turbo` on 12GB+ GPUs.
- Decided: ship Kokoro as the optional high-quality TTS (`scribe[kokoro]`) with a
  pyttsx3 fallback; Piper remains a possible future `scribe[tts-piper]` extra.
- Whether to use `pystray` long-term or move to PySide6 if a real preferences UI
  becomes substantial.
- Whether Wayland GlobalShortcuts should be implemented directly in Python or
  deferred until a stable helper library is worth adopting.
