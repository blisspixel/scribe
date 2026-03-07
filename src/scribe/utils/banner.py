"""
Animated ASCII banner for Scribe CLI.

Renders a gradient-colored wordmark with optional sweep animation,
building on Scribe's existing branding and terminal UI systems.
"""

from __future__ import annotations

import colorsys
import os
import time

from rich.console import Console
from rich.live import Live
from rich.markup import escape
from rich.text import Text

from scribe.utils.terminal_ui import TerminalUIConfig, get_terminal_ui_config
from scribe.utils.theme import ScribeTheme

# ─── ASCII Wordmark ─────────────────────────────────────────────────────
# ANSI Shadow block font — bold 6-line design inspired by GitHub Copilot CLI.
# Uses █ (full block) for fills and ╔═╗║╚╝ (double-line box-drawing) for edges.

BANNER_ART = (
    "  ███████╗ ██████╗██████╗ ██╗██████╗ ███████╗\n"
    "  ██╔════╝██╔════╝██╔══██╗██║██╔══██╗██╔════╝\n"
    "  ███████╗██║     ██████╔╝██║██████╔╝█████╗  \n"
    "  ╚════██║██║     ██╔══██╗██║██╔══██╗██╔══╝  \n"
    "  ███████║╚██████╗██║  ██║██║██████╔╝███████╗\n"
    "  ╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝╚═════╝ ╚══════╝"
)

# Brand hue range matching branding.py: blue (200deg) to purple (320deg)
_START_HUE = 200 / 360
_END_HUE = 320 / 360
_MUTED_COLOR = ScribeTheme.TEXT_MUTED


def _ease_out_cubic(t: float) -> float:
    """Ease-out cubic for smooth animation deceleration."""
    return 1.0 - (1.0 - t) ** 3


def colorize_banner(
    art: str,
    sweep_progress: float = 1.0,
    start_hue: float = _START_HUE,
    end_hue: float = _END_HUE,
    muted_color: str = _MUTED_COLOR,
) -> str:
    """
    Apply gradient coloring to ASCII art with sweep position.

    Args:
        art: Multi-line ASCII art string.
        sweep_progress: 0.0 (all muted) to 1.0 (fully colored).
        start_hue: Starting hue for gradient (0.0-1.0).
        end_hue: Ending hue for gradient (0.0-1.0).
        muted_color: Rich color string for characters not yet swept.

    Returns:
        Rich markup string with per-character gradient coloring.
    """
    lines = art.split("\n")
    if not lines:
        return ""

    max_width = max(len(line) for line in lines)
    if max_width == 0:
        return art

    result_lines: list[str] = []
    for line in lines:
        parts: list[str] = []
        for col, ch in enumerate(line):
            if ch == " ":
                parts.append(" ")
                continue

            col_ratio = col / max(1, max_width - 1)

            if col_ratio <= sweep_progress:
                hue = start_hue + (end_hue - start_hue) * col_ratio
                r, g, b = [
                    int(v * 255)
                    for v in colorsys.hsv_to_rgb(hue % 1.0, 0.85, 0.92)
                ]
                parts.append(f"[bold rgb({r},{g},{b})]{escape(ch)}[/]")
            else:
                parts.append(f"[{muted_color}]{escape(ch)}[/{muted_color}]")

        result_lines.append("".join(parts))

    return "\n".join(result_lines)


def render_banner_plain(art: str) -> str:
    """Return banner as plain text with no color markup."""
    return art


def render_banner_static(art: str) -> str:
    """Return banner with full gradient applied (sweep_progress=1.0)."""
    return colorize_banner(art, sweep_progress=1.0)


def _is_banner_enabled() -> bool:
    """Check SCRIBE_BANNER env var — enabled by default."""
    val = os.environ.get("SCRIBE_BANNER", "").strip().lower()
    return val not in ("off", "false", "0", "no")


def show_banner(console: Console, art: str = BANNER_ART) -> bool:
    """
    Display the banner with appropriate styling for the terminal.

    Picks animated, static, or plain rendering based on terminal
    capabilities and user preferences.

    Returns True if the banner was displayed, False if skipped.
    """
    if not _is_banner_enabled():
        return False

    cfg = get_terminal_ui_config()

    if not cfg.capabilities.is_tty or cfg.capabilities.is_ci:
        return False

    console.print()

    if not cfg.use_color:
        console.print(render_banner_plain(art))
    elif (
        cfg.animation_mode == "full"
        and cfg.capabilities.supports_advanced_effects
    ):
        _animate_sweep(console, art, cfg, duration=1.5)
    elif (
        cfg.animation_mode == "light"
        and cfg.capabilities.supports_advanced_effects
    ):
        _animate_sweep(console, art, cfg, duration=0.5)
    else:
        console.print(Text.from_markup(render_banner_static(art)))

    return True


def _animate_sweep(
    console: Console,
    art: str,
    cfg: TerminalUIConfig,
    duration: float = 1.5,
) -> None:
    """Animate a gradient sweep across the banner using Rich Live."""
    try:
        total_frames = max(1, int(duration * cfg.fps))

        with Live(
            Text.from_markup(colorize_banner(art, sweep_progress=0.0)),
            console=console,
            refresh_per_second=cfg.fps,
            transient=True,
        ) as live:
            for frame in range(total_frames + 1):
                progress = frame / total_frames
                eased = _ease_out_cubic(progress)
                markup = colorize_banner(art, sweep_progress=eased)
                live.update(Text.from_markup(markup))
                time.sleep(cfg.frame_delay)

        # Print final static version permanently
        console.print(Text.from_markup(render_banner_static(art)))

    except Exception:
        # Fallback to static on any animation error
        console.print(Text.from_markup(render_banner_static(art)))
