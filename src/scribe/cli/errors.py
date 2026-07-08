"""Shared CLI error reporting for Typer commands."""

from __future__ import annotations

import os
import sys
from contextlib import suppress
from typing import NoReturn

import typer

from scribe.exceptions import ScribeError
from scribe.utils.logging import console, get_current_log_file, get_logger
from scribe.utils.theme import ScribeTheme

logger = get_logger(__name__)


def exit_on_cli_error(exc: BaseException, *, log_unexpected: bool = True) -> NoReturn:
    """Print a user-facing message and exit with code 1.

    On Windows we force a final input() so desktop/shortcut launches
    never silently disappear on error.
    """
    if isinstance(exc, ScribeError):
        console.print(f"\n[bold {ScribeTheme.ERROR}]Error:[/bold {ScribeTheme.ERROR}] {exc}")
        if exc.context:
            user_ctx = {k: v for k, v in exc.context.items() if k != "phase"}
            if user_ctx:
                console.print(f"[dim]Context: {user_ctx}[/dim]")
    else:
        console.print(
            f"\n[bold {ScribeTheme.ERROR}]Unexpected error:[/bold {ScribeTheme.ERROR}] {exc}"
        )
        if log_unexpected:
            logger.exception("Unexpected CLI error")

    log_file = get_current_log_file()
    if log_file is not None:
        console.print(f"[dim]Log file: {log_file}[/dim]")
    console.print(
        "[dim]Next: run `scribe doctor` to check setup. "
        "Use `scribe support-bundle` when sharing diagnostics.[/dim]"
    )

    if sys.platform == "win32" and os.environ.get("SCRIBE_FROM_SHORTCUT"):
        # Guarantees the window stays for desktop/taskbar .lnk launches; a
        # closed stdin (EOFError) or Ctrl-C just lets the window close.
        with suppress(EOFError, KeyboardInterrupt):
            input("\n[Press Enter to close this window]")

    raise typer.Exit(1) from exc
