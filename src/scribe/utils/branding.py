"""Branding helpers for gradient CLI headers."""

from __future__ import annotations

import colorsys
import time

from rich.markup import escape

from scribe.utils.terminal_ui import get_terminal_ui_config


def _gradient_char_markup(text: str, start_hue: float, end_hue: float, bold: bool) -> str:
    if not text:
        return ""
    parts: list[str] = []
    n = len(text)
    for i, ch in enumerate(text):
        ratio = i / max(1, n - 1)
        hue = start_hue + (end_hue - start_hue) * ratio
        r, g, b = [int(v * 255) for v in colorsys.hsv_to_rgb(hue % 1.0, 0.85, 0.92)]
        if bold:
            parts.append(f"[bold rgb({r},{g},{b})]{escape(ch)}[/]")
        else:
            parts.append(f"[rgb({r},{g},{b})]{escape(ch)}[/]")
    return "".join(parts)


def brand_header_markup(
    text: str,
    fallback_color: str = "cyan",
    bold: bool = True,
    start_hue: float = 200 / 360,
    end_hue: float = 320 / 360,
    rotate_seconds: float = 12.0,
) -> str:
    """
    Return header markup with subtle gradient in full animation mode.

    Falls back to a simple solid color style on unsupported terminals.
    """
    cfg = get_terminal_ui_config()
    if not (
        cfg.animation_mode == "full"
        and cfg.capabilities.supports_advanced_effects
        and cfg.use_color
    ):
        if bold:
            return f"[bold {fallback_color}]{escape(text)}[/bold {fallback_color}]"
        return f"[{fallback_color}]{escape(text)}[/{fallback_color}]"

    hue_shift = (time.time() % rotate_seconds) / rotate_seconds
    return _gradient_char_markup(
        text=text,
        start_hue=start_hue + hue_shift,
        end_hue=end_hue + hue_shift,
        bold=bold,
    )
