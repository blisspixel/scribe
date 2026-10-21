"""Single-accent header text.

Headers use the terminal's blue. They do not sweep hues or animate.
"""

from __future__ import annotations

from rich.markup import escape


def brand_header_markup(
    text: str,
    fallback_color: str = "blue",
    bold: bool = True,
    start_hue: float = 200 / 360,
    end_hue: float = 320 / 360,
    rotate_seconds: float = 12.0,
) -> str:
    """Return header markup in one accent colour.

    The hue and rotation arguments are accepted so older callers keep working.
    They do not change the colour.
    """
    del start_hue, end_hue, rotate_seconds
    named = {"blue", "cyan", "green", "yellow", "red"}
    color = fallback_color if fallback_color in named else "blue"
    if bold:
        return f"[bold {color}]{escape(text)}[/bold {color}]"
    return f"[{color}]{escape(text)}[/{color}]"
