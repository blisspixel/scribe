"""
Scribe CLI Theme System - 2026 Modern Design Language

A minimal, monochromatic design system inspired by modern CLI tools
like GitHub CLI and Warp.

DESIGN PHILOSOPHY:
──────────────────
2026 CLI design is characterized by restraint:
- Monochromatic base (white/gray hierarchy)
- Single accent color used sparingly
- Typography and spacing over color
- Terminal-native aesthetic

This theme draws inspiration from:
- GitHub CLI (gray scale, subtle highlights)
- Warp (modern terminal, restrained palette)
- Vercel CLI (black/white with minimal accent)
"""

from dataclasses import dataclass
from pathlib import Path

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

    # Terminal blue. The accent follows the terminal theme.
    ACCENT = "blue"
    ACCENT_DIM = "blue"

    # ═══════════════════════════════════════════════════════════════════════
    # SEMANTIC COLORS - Meaning-based, used only when necessary
    # ═══════════════════════════════════════════════════════════════════════

    SUCCESS = "green"
    WARNING = "yellow"
    ERROR = "red"
    INFO = "cyan"

    # ═══════════════════════════════════════════════════════════════════════
    # TEXT - The terminal's own foreground, with dim for secondary text
    # ═══════════════════════════════════════════════════════════════════════

    TEXT_PRIMARY = "default"
    TEXT_SECONDARY = "dim"
    TEXT_MUTED = "dim"

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
    INFO_BRIGHT = INFO
    AI_ACCENT = ACCENT
    AI_BRIGHT = ACCENT
    PATH = TEXT_SECONDARY
    CODE = TEXT_PRIMARY
    BORDER = "dim"
    BORDER_BRIGHT = "dim"
    PROGRESS_BAR = ACCENT
    PROGRESS_COMPLETE = SUCCESS
    RECORDING = ERROR
    RECORDING_PULSE = ERROR

    @classmethod
    def _style(cls, role: str, *, bold: bool = False) -> Style:
        if role == "dim":
            return Style(dim=True, bold=bold)
        if role == "default":
            return Style(bold=bold)
        return Style(color=role, bold=bold)

    @classmethod
    def get_rich_theme(cls) -> Theme:
        """Get a Rich Theme object for use with Rich console."""
        return Theme(
            {
                "primary": cls._style(cls.ACCENT),
                "primary.bright": cls._style(cls.ACCENT, bold=True),
                "primary.dim": cls._style(cls.ACCENT),
                "secondary": cls._style(cls.TEXT_SECONDARY),
                "success": cls._style(cls.SUCCESS),
                "warning": cls._style(cls.WARNING),
                "error": cls._style(cls.ERROR),
                "info": cls._style(cls.INFO),
                "text": cls._style(cls.TEXT_PRIMARY),
                "text.secondary": cls._style(cls.TEXT_SECONDARY),
                "text.muted": cls._style(cls.TEXT_MUTED),
                "dim": cls._style(cls.TEXT_MUTED),
            }
        )


class Styles:
    """Pre-defined Rich markup strings for common UI patterns."""

    DONE = f"[bold {ScribeTheme.SUCCESS}]done[/bold {ScribeTheme.SUCCESS}]"
    ERROR = f"[bold {ScribeTheme.ERROR}]error[/bold {ScribeTheme.ERROR}]"
    WARNING = f"[bold {ScribeTheme.WARNING}]warning[/bold {ScribeTheme.WARNING}]"
    INFO = f"[{ScribeTheme.INFO}]info[/{ScribeTheme.INFO}]"
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
        "info": (ScribeTheme.INFO, "info"),
        "working": (ScribeTheme.TEXT_SECONDARY, "..."),
    }

    color, label = status_styles.get(status.lower(), (ScribeTheme.TEXT_PRIMARY, status))

    result = f"[{color}]{label}[/{color}] {message}"
    if detail:
        result += f" [{ScribeTheme.TEXT_MUTED}]{detail}[/{ScribeTheme.TEXT_MUTED}]"

    return result


def file_uri(path: str | Path) -> str:
    """Build a percent-encoded ``file://`` URI that terminals can click.

    Uses ``Path.as_uri()`` so spaces and other special characters are encoded
    correctly (e.g. ``a b.txt`` -> ``a%20b.txt``) on Windows, macOS, and Linux.
    Without encoding, a space in the path breaks the OSC 8 hyperlink and the
    terminal stops treating it as clickable.

    Args:
        path: File path (relative or absolute).

    Returns:
        A ``file://`` URI string.
    """
    p = Path(path)
    try:
        # as_uri() requires an absolute path; resolve() also normalizes it.
        # strict=False (default) means the file does not need to exist yet.
        return p.resolve().as_uri()
    except (ValueError, OSError):
        # Best-effort fallback if resolution fails for an unusual path.
        return "file:///" + str(p).replace("\\", "/")


def file_link(label: str, path: str) -> str:
    """Format a clickable file link with consistent styling.

    Args:
        label: Label text (e.g., "Meme:", "Transcript:")
        path: File path

    Returns:
        Rich-formatted string with clickable link
    """
    return f"[{ScribeTheme.ACCENT}]{label}[/{ScribeTheme.ACCENT}] [link={file_uri(path)}][{ScribeTheme.TEXT_PRIMARY}]{path}[/{ScribeTheme.TEXT_PRIMARY}][/link]"
