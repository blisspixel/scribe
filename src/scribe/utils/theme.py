"""
Scribe CLI Theme System - 2026 Modern Design Language

A minimal, monochromatic design system inspired by modern CLI tools
like Claude Code, GitHub CLI, and Warp.

DESIGN PHILOSOPHY:
──────────────────
2026 CLI design is characterized by restraint:
- Monochromatic base (white/gray hierarchy)
- Single accent color used sparingly
- Typography and spacing over color
- Terminal-native aesthetic

This theme draws inspiration from:
- Claude Code (minimal, blue accent)
- GitHub CLI (gray scale, subtle highlights)
- Warp (modern terminal, restrained palette)
- Vercel CLI (black/white with minimal accent)
"""

from dataclasses import dataclass

from rich.style import Style
from rich.theme import Theme


@dataclass
class ScribeTheme:
    """
    Scribe's visual design system.
    
    Minimal, monochromatic with a single accent color.
    """

    # ═══════════════════════════════════════════════════════════════════════
    # ACCENT COLOR - Used sparingly for emphasis
    # ═══════════════════════════════════════════════════════════════════════

    # Blue accent - modern, professional, universal
    # Similar to Claude Code, GitHub, VS Code
    ACCENT = "#6b9fff"          # Soft blue - primary accent
    ACCENT_DIM = "#4a7fd4"      # Dimmed accent for borders

    # ═══════════════════════════════════════════════════════════════════════
    # SEMANTIC COLORS - Meaning-based, used only when necessary
    # ═══════════════════════════════════════════════════════════════════════

    SUCCESS = "#6bc46b"         # Green - success states only
    WARNING = "#d4a84b"         # Amber - warnings only
    ERROR = "#e05252"           # Red - errors only

    # ═══════════════════════════════════════════════════════════════════════
    # GRAY SCALE - Primary visual hierarchy
    # ═══════════════════════════════════════════════════════════════════════

    # Text hierarchy (most important visual system)
    TEXT_PRIMARY = "#e8e8e8"    # Primary text - high contrast
    TEXT_SECONDARY = "#a0a0a0"  # Secondary text - labels, descriptions
    TEXT_MUTED = "#606060"      # Muted text - hints, timestamps

    # ═══════════════════════════════════════════════════════════════════════
    # LEGACY ALIASES - For backward compatibility
    # ═══════════════════════════════════════════════════════════════════════

    PRIMARY = ACCENT
    PRIMARY_BRIGHT = ACCENT
    PRIMARY_DIM = ACCENT_DIM
    SECONDARY = TEXT_SECONDARY
    SECONDARY_BRIGHT = TEXT_PRIMARY
    SUCCESS_BRIGHT = SUCCESS
    WARNING_BRIGHT = WARNING
    ERROR_BRIGHT = ERROR
    INFO = ACCENT
    INFO_BRIGHT = ACCENT
    AI_ACCENT = ACCENT
    AI_BRIGHT = ACCENT
    PATH = TEXT_SECONDARY
    CODE = TEXT_PRIMARY
    BORDER = "#404040"
    BORDER_BRIGHT = "#505050"
    PROGRESS_BAR = ACCENT
    PROGRESS_COMPLETE = SUCCESS
    RECORDING = ERROR
    RECORDING_PULSE = ERROR

    @classmethod
    def get_rich_theme(cls) -> Theme:
        """Get a Rich Theme object for use with Rich console."""
        return Theme({
            "primary": Style(color=cls.ACCENT),
            "primary.bright": Style(color=cls.ACCENT),
            "primary.dim": Style(color=cls.ACCENT_DIM),
            "secondary": Style(color=cls.TEXT_SECONDARY),
            "success": Style(color=cls.SUCCESS),
            "warning": Style(color=cls.WARNING),
            "error": Style(color=cls.ERROR),
            "info": Style(color=cls.ACCENT),
            "text": Style(color=cls.TEXT_PRIMARY),
            "text.secondary": Style(color=cls.TEXT_SECONDARY),
            "text.muted": Style(color=cls.TEXT_MUTED),
            "dim": Style(color=cls.TEXT_MUTED),
        })


class Styles:
    """Pre-defined Rich markup strings for common UI patterns."""

    DONE = f"[bold {ScribeTheme.SUCCESS}]done[/bold {ScribeTheme.SUCCESS}]"
    ERROR = f"[bold {ScribeTheme.ERROR}]error[/bold {ScribeTheme.ERROR}]"
    WARNING = f"[bold {ScribeTheme.WARNING}]warning[/bold {ScribeTheme.WARNING}]"
    INFO = f"[{ScribeTheme.ACCENT}]info[/{ScribeTheme.ACCENT}]"
    WORKING = f"[{ScribeTheme.TEXT_SECONDARY}]"
    COMPLETE = f"[{ScribeTheme.SUCCESS}]"
    RECORDING = f"[bold {ScribeTheme.ERROR}]rec[/bold {ScribeTheme.ERROR}]"
    AI = f"[{ScribeTheme.ACCENT}]ai[/{ScribeTheme.ACCENT}]"


PANEL_BORDER = ScribeTheme.ACCENT_DIM
PANEL_BORDER_SUCCESS = ScribeTheme.SUCCESS
PANEL_BORDER_ERROR = ScribeTheme.ERROR
PANEL_BORDER_WARNING = ScribeTheme.WARNING


def styled(text: str, style: str) -> str:
    """Wrap text in Rich markup with the given style."""
    color = getattr(ScribeTheme, style.upper(), ScribeTheme.TEXT_PRIMARY)
    return f"[{color}]{text}[/{color}]"


def status_line(status: str, message: str, detail: str | None = None) -> str:
    """Format a status line with consistent styling."""
    status_styles = {
        "done": (ScribeTheme.SUCCESS, "done"),
        "error": (ScribeTheme.ERROR, "error"),
        "warning": (ScribeTheme.WARNING, "warn"),
        "info": (ScribeTheme.ACCENT, "info"),
        "working": (ScribeTheme.TEXT_SECONDARY, "..."),
    }

    color, label = status_styles.get(status.lower(), (ScribeTheme.TEXT_PRIMARY, status))

    result = f"[{color}]{label}[/{color}] {message}"
    if detail:
        result += f" [{ScribeTheme.TEXT_MUTED}]{detail}[/{ScribeTheme.TEXT_MUTED}]"

    return result


def file_link(label: str, path: str) -> str:
    """Format a clickable file link with consistent styling.
    
    Args:
        label: Label text (e.g., "Meme:", "Transcript:")
        path: File path
        
    Returns:
        Rich-formatted string with clickable link
    """
    # Convert Windows backslashes to forward slashes for file:// URLs
    url_path = str(path).replace("\\", "/")
    return f"[{ScribeTheme.ACCENT}]{label}[/{ScribeTheme.ACCENT}] [link=file:///{url_path}][{ScribeTheme.TEXT_PRIMARY}]{path}[/{ScribeTheme.TEXT_PRIMARY}][/link]"
