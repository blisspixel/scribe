"""Root help screen: start here, then grouped commands."""

from __future__ import annotations

_START_HERE: tuple[tuple[str, str], ...] = (
    ("scribe init", "first-run setup"),
    ("scribe doctor", "check models, cache and devices"),
    ("scribe meeting.mp4", "transcribe a file"),
)

_GROUPS: tuple[tuple[str, str], ...] = (
    ("Transcribe", "transcribe, url, batch, music, clean, query, vocab"),
    ("Record", "rec, record, shortcut"),
    ("Notes", "notes, compare, health"),
    ("Voice", "listen, tray, voice, say"),
    ("Extras", "joke, meme"),
    ("Setup", "init, doctor, info, support-bundle, version, help"),
)


def root_help_text(version: str) -> str:
    """Plain root help. Visible lines stay within 80 columns and 25 lines."""
    command_width = max(len(command) for command, _description in _START_HERE)
    lines = [f"scribe {version}", "", "Start here:"]
    for command, description in _START_HERE:
        lines.append(f"  {command.ljust(command_width)}  {description}")
    lines.append("")
    label_width = max(len(name) for name, _commands in _GROUPS)
    for name, commands in _GROUPS:
        lines.append(f"{name + ':':<{label_width + 1}}  {commands}")
    lines.extend(["", "scribe <command> -h for options"])
    return "\n".join(lines)
