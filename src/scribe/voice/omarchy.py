"""Personal Omarchy Hyprland marker blocks for Scribe voice.

Scribe edits only the marked region of the user files ``bindings.lua`` and
``autostart.lua``. Packaged files under ``/usr/share/omarchy`` are never
touched. The chords avoid Omarchy dictation's F9 and Super+Ctrl+X. They also
avoid Right Alt, which many users remap for layout switching or compose.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MARKER_START = "-- scribe-omarchy-voice: start"
MARKER_END = "-- scribe-omarchy-voice: end"
AUTOSTART_START = "-- scribe-omarchy-voice: autostart"
AUTOSTART_END = "-- scribe-omarchy-voice: autostart-end"

# String dispatchers become hl.dsp.exec_cmd. The overlay command is split by
# omarchy-launch-tui into command and args. A `{ tui = "scribe voice overlay" }`
# table would quote the whole string as one -e argument and fail to launch.
BINDINGS_BLOCK = """-- scribe-omarchy-voice: start
-- Scribe voice is experimental. Confirm these chords with Super+K before relying on them.
-- F9 and Super+Ctrl+X stay with Omarchy dictation (Voxtype).
-- Scribe also avoids Right Alt, which many users remap for layout switching or compose.
o.bind("SUPER + ALT + D", "Scribe dictate", "scribe voice dictate")
o.bind("SUPER + ALT + SHIFT + D", "Scribe cancel dictation", "scribe voice cancel")
o.bind("SUPER + ALT + Y", "Scribe copy transcript", "scribe voice copy")
o.bind("SUPER + ALT + I", "Scribe insert transcript", "scribe voice insert")
o.bind("SUPER + ALT + A", "Scribe read transcript", "scribe voice read")
o.bind("SUPER + ALT + O", "Scribe voice overlay", "omarchy-launch-tui scribe voice overlay")
-- scribe-omarchy-voice: end
"""

AUTOSTART_BLOCK = """-- scribe-omarchy-voice: autostart
o.launch_on_start("scribe voice serve")
-- scribe-omarchy-voice: autostart-end
"""

_FORBIDDEN_BIND_FRAGMENTS = ("f9", "alt_r", "super + ctrl + x", "{ tui =")


@dataclass(frozen=True)
class VoiceCheckReport:
    """Read-only install report. ``hardware_validated`` is always false."""

    experimental: bool
    hardware_validated: bool
    python_ok: bool
    sounddevice_available: bool
    omarchy_detected: bool
    bindings_installed: bool
    autostart_installed: bool
    lines: tuple[str, ...]


def upsert_marked_block(text: str, start: str, end: str, block: str) -> str:
    """Insert or replace one marked block and leave every other line in place."""
    replacement = block.strip() + "\n"
    start_at = text.find(start)
    end_at = text.find(end)
    if start_at != -1 and end_at != -1 and end_at >= start_at:
        prefix = text[:start_at].rstrip("\n")
        suffix = text[end_at + len(end) :].lstrip("\n")
        pieces = [part for part in (prefix, replacement.rstrip("\n"), suffix) if part]
        joined = "\n".join(pieces)
        return joined if joined.endswith("\n") else joined + "\n"
    base = text
    if base and not base.endswith("\n"):
        base += "\n"
    if base and not base.endswith("\n\n"):
        base += "\n"
    return base + replacement


def remove_marked_block(text: str, start: str, end: str) -> str:
    """Remove one marked block. A file without the markers is returned unchanged."""
    start_at = text.find(start)
    end_at = text.find(end)
    if start_at == -1 or end_at == -1 or end_at < start_at:
        return text
    prefix = text[:start_at].rstrip("\n")
    suffix = text[end_at + len(end) :].lstrip("\n")
    if prefix and suffix:
        joined = prefix + "\n\n" + suffix
    else:
        joined = prefix or suffix
    if joined and not joined.endswith("\n"):
        joined += "\n"
    return joined


def bindings_are_safe(block: str = BINDINGS_BLOCK) -> bool:
    """Return True when the generated binds avoid Omarchy's dictation chords."""
    bind_lines = [line.lower() for line in block.splitlines() if "o.bind(" in line.lower()]
    joined = "\n".join(bind_lines)
    return not any(fragment in joined for fragment in _FORBIDDEN_BIND_FRAGMENTS)


def install_voice_files(config_dir: Path) -> tuple[Path, Path]:
    """Write the user Hyprland marker blocks. Existing lines outside them stay."""
    if not bindings_are_safe():
        raise RuntimeError("refusing to install a Scribe bind that collides with Omarchy dictation")
    config_dir.mkdir(parents=True, exist_ok=True)
    bindings_path = config_dir / "bindings.lua"
    autostart_path = config_dir / "autostart.lua"
    bindings_existing = _read(bindings_path)
    autostart_existing = _read(autostart_path)
    if not bindings_existing:
        bindings_existing = (
            "-- Personal Hyprland binds. Omarchy loads this file after its defaults.\n"
            "-- Scribe only owns the marked voice block.\n"
        )
    if not autostart_existing:
        autostart_existing = (
            "-- Personal Hyprland autostart. Scribe only owns the marked voice block.\n"
        )
    bindings_path.write_text(
        upsert_marked_block(bindings_existing, MARKER_START, MARKER_END, BINDINGS_BLOCK),
        encoding="utf-8",
    )
    autostart_path.write_text(
        upsert_marked_block(autostart_existing, AUTOSTART_START, AUTOSTART_END, AUTOSTART_BLOCK),
        encoding="utf-8",
    )
    return bindings_path, autostart_path


def remove_voice_files(config_dir: Path) -> tuple[Path, Path]:
    """Strip Scribe's marker blocks without deleting the Hyprland files."""
    bindings_path = config_dir / "bindings.lua"
    autostart_path = config_dir / "autostart.lua"
    if bindings_path.is_file():
        bindings_path.write_text(
            remove_marked_block(
                bindings_path.read_text(encoding="utf-8"), MARKER_START, MARKER_END
            ),
            encoding="utf-8",
        )
    if autostart_path.is_file():
        autostart_path.write_text(
            remove_marked_block(
                autostart_path.read_text(encoding="utf-8"),
                AUTOSTART_START,
                AUTOSTART_END,
            ),
            encoding="utf-8",
        )
    return bindings_path, autostart_path


def build_voice_check(
    *,
    python_version: tuple[int, int],
    sounddevice_available: bool,
    omarchy_detected: bool,
    bindings_text: str,
    autostart_text: str,
) -> VoiceCheckReport:
    """Describe install readiness. This function cannot mark hardware as validated."""
    python_ok = python_version[0] == 3 and 11 <= python_version[1] <= 14
    bindings_installed = MARKER_START in bindings_text and MARKER_END in bindings_text
    autostart_installed = AUTOSTART_START in autostart_text and AUTOSTART_END in autostart_text
    lines = [
        "Scribe voice on Linux is experimental.",
        "This check does not open the microphone and does not validate hardware.",
        "Not demonstrated here: microphone selection, focus changes, correct-target "
        "insertion, cancellation, device loss, and recovery.",
        f"Python {python_version[0]}.{python_version[1]} is "
        + (
            "inside Scribe's 3.11 through 3.14 range."
            if python_ok
            else "outside Scribe's 3.11 through 3.14 range."
        ),
        "sounddevice is " + ("importable." if sounddevice_available else "not installed."),
        "Omarchy was " + ("detected." if omarchy_detected else "not detected."),
        "Hyprland voice binds are " + ("present." if bindings_installed else "not installed."),
        "Hyprland voice autostart is " + ("present." if autostart_installed else "not installed."),
        "Cloud transcription stays opt-in and is not used by this voice path.",
        "A zero exit from this check is not a tested Omarchy installation.",
    ]
    return VoiceCheckReport(
        experimental=True,
        hardware_validated=False,
        python_ok=python_ok,
        sounddevice_available=sounddevice_available,
        omarchy_detected=omarchy_detected,
        bindings_installed=bindings_installed,
        autostart_installed=autostart_installed,
        lines=tuple(lines),
    )


def _read(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")
