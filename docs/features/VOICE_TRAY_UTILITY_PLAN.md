# Resident Voice Tray Utility Plan

## Status

Initial prototype baseline in the tree:

- `scribe tray --check` validates optional voice and tray dependencies.
- `scribe tray` starts a resident tray icon with push-to-talk dictation and
  read-selection hotkeys on environments where the optional dependencies,
  desktop backend, and OS permissions allow it.
- `scribe tray --no-tray` runs the same hotkeys from a terminal for debugging and
  environments without a tray backend.
- Voice profiles choose local STT defaults by detected GPU capacity, with
  RTX 4090-class defaults and CPU fallback paths that still need more real-world
  latency and reliability validation.

This is not yet a claim that the resident utility is stable across every OS,
permission model, desktop shell, keyboard layout, audio device, or tray backend.
Automated tests cover the pure settings, state, dependency, and CLI wiring. Live
microphone capture, global hotkeys, tray behavior, clipboard injection/restore,
and TTS remain manual-matrix work until proven on real machines.

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

- Remaining: route dictation through Scribe's local backend registry instead of hardcoding
  faster-whisper.
- Prototype baseline: voice profiles `fast`, `balanced`, `accurate`.
- Remaining: add short-utterance benchmark command or diagnostic output for model
  latency.
- Remaining: add Silero VAD for continuous mode, with RMS fallback.

### Phase 3: Tray App

- Prototype baseline: `scribe tray` with `pystray`.
- Prototype baseline: tray states, menu actions, pause/resume, read-now, and quit.
- Prototype baseline: default hotkeys and same-hotkey validation.
- Prototype baseline: live I/O paths stay behind the `scribe[tray]` optional extra.
- Remaining: validate OS-level hotkey conflicts and permission failures on the
  manual matrix; `pynput` cannot guarantee conflict detection on every desktop.

### Phase 4: Startup And Doctor

- Add `scribe tray --startup install/remove/status`.
- Extend `scribe doctor` with voice-tray checks:
  - optional deps installed
  - microphone available
  - hotkey listener available
  - configured backend available
  - macOS permission hints
  - Linux Wayland warning and portal detection

### Phase 5: Packaging

- Keep `uv tool install "scribe[tray,voice]"` as the developer and power-user path.
- Add OS launchers through the existing shortcut mechanism.
- Later, evaluate packaged app builds with PyInstaller per OS. PyInstaller requires
  building separately on each target OS, so this should not block the Python tool
  path.

Sources:

- [PyInstaller usage docs](https://pyinstaller.org/en/stable/usage.html)
- [Microsoft Run and RunOnce registry keys](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys)

## Test Plan

Automated:

- Unit tests for settings, hotkey normalization, config precedence, state machine,
  injection decision logic, and selection cleanup.
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

- Hold `F9` in Notepad, browser text field, Slack/Teams, VS Code, and terminal.
- Press `F8` with selected text in browser, PDF viewer, editor, and terminal.
- Hotkey conflict.
- Clipboard preservation.
- Startup install and uninstall.
- No microphone.
- Missing optional dependencies.
- GPU unavailable after startup.

## Validation Criteria Before Calling It Stable

- `scribe tray` starts without a terminal-facing stack trace when optional deps are
  missing, and prints an actionable install hint.
- On Windows with an RTX 4090, local dictation can use a preloaded high-quality
  GPU model and insert text into the focused app.
- On CPU-only machines, dictation works with a smaller int8 model or clearly says
  why it cannot.
- Read-selection hotkey speaks selected text and restores clipboard state.
- Tray state visibly changes during mic capture and speech playback.
- Hotkey conflicts are reported without crashing the tray.
- `scribe listen` and `scribe say` still work as standalone CLI commands.
- Lint, type checks, and coverage-gated tests pass in CI.

## Open Decisions

- Whether `balanced` should default to `small`, `medium`, or `large-v3-turbo` on
  high-VRAM NVIDIA GPUs. Decide with measured short-utterance latency on the 4090.
- Whether to use `pystray` long-term or move to PySide6 if preferences UI becomes
  substantial.
- Whether Piper should be first-class in the initial tray release or a follow-up
  `scribe[tts-piper]` extra.
- Whether Wayland GlobalShortcuts should be implemented directly in Python or
  deferred until a stable helper library is worth adopting.
