"""Static Scribe wordmark.

The wordmark is one accent colour, drawn once. It is not animated and it is
not printed before help or before a command starts work.
"""

from __future__ import annotations

import os
import sys

from rich.console import Console
from rich.text import Text

BANNER_ART = (
    "  ███████╗ ██████╗██████╗ ██╗██████╗ ███████╗\n"
    "  ██╔════╝██╔════╝██╔══██╗██║██╔══██╗██╔════╝\n"
    "  ███████╗██║     ██████╔╝██║██████╔╝█████╗  \n"
    "  ╚════██║██║     ██╔══██╗██║██╔══██╗██╔══╝  \n"
    "  ███████║╚██████╗██║  ██║██║██████╔╝███████╗\n"
    "  ╚══════╝ ╚═════╝╚═╝  ╚═╝╚═╝╚═════╝ ╚══════╝"
)

_ASCII_BANNER_TRANSLATION = str.maketrans(
    {
        "█": "#",
        "╔": "+",
        "╗": "+",
        "╚": "+",
        "╝": "+",
        "═": "=",
        "║": "|",
    }
)

_OFF_VALUES = {"0", "off", "false", "no"}


def _banner_art() -> str:
    """Use the block wordmark, or ASCII when the stream cannot encode it."""
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        BANNER_ART.encode(encoding)
    except UnicodeEncodeError:
        return BANNER_ART.translate(_ASCII_BANNER_TRANSLATION)
    return BANNER_ART


def banner_allowed() -> bool:
    """Return whether the static wordmark may be drawn.

    Colour off, a pipe, CI, and ``SCRIBE_BANNER=off`` print nothing. There is
    no plain-text substitute in those cases.
    """
    if os.environ.get("SCRIBE_BANNER", "").strip().lower() in _OFF_VALUES:
        return False
    if os.environ.get("CI"):
        return False
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("FORCE_COLOR", "").strip().lower() in _OFF_VALUES:
        return False
    stdout = sys.stdout
    isatty = getattr(stdout, "isatty", None)
    return bool(isatty and isatty())


def show_banner(console: Console, art: str | None = None) -> bool:
    """Draw the static wordmark in the accent colour.

    Returns True when the wordmark was printed.
    """
    if not banner_allowed():
        return False
    picture = art if art is not None else _banner_art()
    console.print(Text(picture, style="bold blue"))
    return True
