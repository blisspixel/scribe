"""Explicit text insertion through Hyprland, matching Omarchy's clipboard path.

Omarchy's ``clipboard.lua`` sends ``hl.dsp.send_key_state`` down and up. A
virtual keyboard such as ``wtype`` is not used: a held Super key merges into
that injected chord. The transcript itself never enters the dispatcher string.
"""

from __future__ import annotations

import json
from collections.abc import Callable

# Substrings of Hyprland window classes that paste with Ctrl+Shift+V.
_TERMINAL_MARKERS = (
    "foot",
    "alacritty",
    "ghostty",
    "kitty",
    "konsole",
    "wezterm",
    "gnome-terminal",
    "kgx",
    "xterm",
)


def paste_mods_for_class(class_name: str) -> str:
    """Return the Hyprland modifier string for a paste into this window class."""
    lowered = class_name.strip().lower()
    if any(marker in lowered for marker in _TERMINAL_MARKERS):
        return "CTRL SHIFT"
    return "CTRL"


def send_key_state_expression(*, mods: str, key: str, state: str) -> str:
    """Build one Hyprland dispatcher expression. Arguments are fixed tokens."""
    if mods not in {"CTRL", "CTRL SHIFT"} or key != "V" or state not in {"down", "up"}:
        raise ValueError("refusing to build an unexpected Hyprland key expression")
    return f'hl.dsp.send_key_state({{ mods = "{mods}", key = "{key}", state = "{state}" }})'


def read_hypr_window_class(run_capture: Callable[[list[str]], tuple[int, str]]) -> str:
    """Read ``hyprctl activewindow -j``, the call Omarchy's window scripts use."""
    code, output = run_capture(["hyprctl", "activewindow", "-j"])
    if code != 0 or not output.strip():
        return ""
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return ""
    if not isinstance(value, dict):
        return ""
    class_name = value.get("class")
    return class_name if isinstance(class_name, str) else ""


def make_hyprland_inserter(
    *,
    copy: Callable[[str], bool],
    run: Callable[[list[str]], int],
    read_class: Callable[[], str],
    sleep: Callable[[float], None],
) -> Callable[[str], str]:
    """Return an inserter that copies text, then asks Hyprland to paste it.

    The result is ``inserted`` when both key states were dispatched, ``copied``
    when the clipboard holds the text but Hyprland did not confirm the paste,
    and ``copy_failed`` when the clipboard write failed.
    """

    def insert(text: str) -> str:
        if not copy(text):
            return "copy_failed"
        mods = paste_mods_for_class(read_class())
        for state in ("down", "up"):
            expression = send_key_state_expression(mods=mods, key="V", state=state)
            if run(["hyprctl", "dispatch", expression]) != 0:
                return "copied"
            if state == "down":
                sleep(0.05)
        return "inserted"

    return insert
