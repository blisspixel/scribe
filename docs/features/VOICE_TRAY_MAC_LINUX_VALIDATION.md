# macOS and Linux Voice Tray Validation Notes

## Validation Environment: macOS

- **Tested OS Version**: macOS 14 Sonoma (Apple Silicon M2)
- **Desktop Session**: Aqua / Quartz Compositor (default)
- **Audio Device**: MacBook Pro Built-in Microphone and Speakers
- **Permissions Verified**:
  - `Input Monitoring`: System Settings > Privacy & Security > Input Monitoring. Required to capture F8 and F9 globally. If not granted, the listener silently ignores key presses.
  - `Microphone`: System Settings > Privacy & Security > Microphone. Required to capture dictation.
- **Tray Behavior**: The `pystray` menu bar icon appears correctly. Menu options function as expected, updating state immediately.
- **Hotkey Behavior**: With permissions granted, global hotkeys (e.g., F9 for dictation, F8 for reading selection) successfully trigger regardless of which application is focused.
- **Startup Behavior**: `scribe tray --startup install` successfully creates `~/Library/LaunchAgents/io.pueo.scribe.tray.plist` and loads it via `launchctl`. The tray automatically starts at login without stealing focus.

## Validation Environment: Linux

- **Tested OS Versions**: Ubuntu 22.04 LTS and Fedora 39
- **Desktop Sessions**:
  - GNOME on Wayland
  - GNOME on X11
- **Audio Device**: PulseAudio / PipeWire default audio sinks and sources
- **X11 Validation**:
  - **Tray Behavior**: Status icon integrates perfectly with GNOME Shell (requires AppIndicator support, which is standard on Ubuntu).
  - **Hotkey Behavior**: `pynput` correctly intercepts global keypresses (F9 / F8). Dictation and text injection (paste/type) work across X11 apps.
- **Wayland Validation**:
  - **Tray Behavior**: Works similarly to X11 (pystray supports Wayland through libappindicator where available).
  - **Hotkey Behavior**: `pynput` cannot reliably set global hooks under Wayland due to compositing security constraints. The application accurately detects Wayland and issues a warning: `"Linux/Wayland detected: global hotkeys via pynput are unreliable here. Use scribe tray --no-tray and bind a desktop shortcut..."`
- **Startup Behavior**: `scribe tray --startup install` successfully creates `~/.config/autostart/scribe-voice-tray.desktop`. The application starts silently in the background on login.

## Advisory Verification

- Running `scribe tray --check` under macOS correctly yields the `warning` about granting Input Monitoring and Microphone permissions.
- Running `scribe tray --check` on Wayland correctly yields the Wayland advisory.
- Running `scribe tray --check` over an SSH headless session correctly yields the missing `DISPLAY`/`WAYLAND_DISPLAY` warning.

These manual verification steps confirm that the codebase properly guards against and informs the user about platform-specific desktop environment limitations, satisfying the roadmap goal.
