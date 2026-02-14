"""Lightweight monochrome shimmer text rendering for terminal status lines."""

from __future__ import annotations

from rich.markup import escape


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    color = hex_color.strip().lstrip("#")
    if len(color) != 6:
        return (96, 96, 96)
    try:
        return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
    except ValueError:
        return (96, 96, 96)


def _rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"#{r:02x}{g:02x}{b:02x}"


def shimmer_markup(
    text: str,
    phase: float,
    base_color: str = "#606060",
    highlight_color: str = "#d0d0ff",
    width: float = 0.28,
) -> str:
    """
    Build per-character Rich markup with a moving shimmer highlight.

    Args:
        text: Raw text to render.
        phase: Sweep position in [0, 1).
        base_color: Default text color.
        highlight_color: Highlight sweep color.
        width: Relative sweep width (0-1).
    """
    if not text:
        return ""

    p = phase % 1.0
    width = max(0.05, min(0.9, width))
    base_r, base_g, base_b = _hex_to_rgb(base_color)
    hi_r, hi_g, hi_b = _hex_to_rgb(highlight_color)

    n = len(text)
    rendered: list[str] = []

    for i, ch in enumerate(text):
        pos = i / max(1, n - 1)
        dist = min(abs(pos - p), abs(pos - (p - 1.0)), abs(pos - (p + 1.0)))
        intensity = max(0.0, 1.0 - (dist / width)) ** 2.2
        rgb = (
            int(base_r + (hi_r - base_r) * intensity),
            int(base_g + (hi_g - base_g) * intensity),
            int(base_b + (hi_b - base_b) * intensity),
        )
        rendered.append(f"[{_rgb_to_hex(rgb)}]{escape(ch)}[/]")

    return "".join(rendered)

