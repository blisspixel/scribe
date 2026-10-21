"""Status-line emphasis that follows the terminal theme.

The moving highlight uses the accent and dim roles. It does not invent colours.
"""

from __future__ import annotations

from rich.markup import escape


def shimmer_markup(
    text: str,
    phase: float,
    base_color: str = "dim",
    highlight_color: str = "blue",
    width: float = 0.28,
) -> str:
    """Mark characters near ``phase`` with the accent and leave the rest dim."""
    del base_color, highlight_color
    if not text:
        return ""

    position = phase % 1.0
    band = max(0.05, min(0.9, width))
    count = len(text)
    rendered: list[str] = []
    for index, character in enumerate(text):
        place = index / max(1, count - 1)
        distance = min(
            abs(place - position),
            abs(place - (position - 1.0)),
            abs(place - (position + 1.0)),
        )
        if distance <= band / 2:
            rendered.append(f"[blue]{escape(character)}[/]")
        else:
            rendered.append(f"[dim]{escape(character)}[/]")
    return "".join(rendered)
