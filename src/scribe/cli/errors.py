"""Shared CLI error reporting for Typer commands."""

from __future__ import annotations

import os
import sys
from contextlib import suppress
from typing import NoReturn

import typer
from rich.markup import escape
from rich.text import Text

from scribe.exceptions import ScribeError
from scribe.utils.logging import (
    TERMINAL_OUTPUT_ERRORS,
    console,
    get_current_log_file,
    get_logger,
    is_terminal_output_error,
)
from scribe.utils.theme import ScribeTheme

logger = get_logger(__name__)


def _write_terminal_fallback(log_file: object | None) -> None:
    """Write one ASCII-safe fallback without depending on Rich."""
    message = "Terminal output unavailable. Command failed with exit code 1."
    if log_file is not None:
        message = f"{message} See log: {log_file}"
    ascii_message = message.encode("ascii", errors="backslashreplace").decode("ascii")
    with suppress(Exception):
        sys.stderr.write(f"{ascii_message}\n")
        sys.stderr.flush()


def exit_on_cli_error(
    exc: BaseException,
    *,
    log_unexpected: bool = True,
    recovery_hint: str | None = None,
) -> NoReturn:
    """Print a user-facing message and exit with code 1.

    On Windows we force a final input() so desktop/shortcut launches
    never silently disappear on error.
    """
    log_file = get_current_log_file()
    if log_file is not None and not isinstance(exc, ScribeError) and log_unexpected:
        with suppress(Exception):
            logger.error(
                "Unexpected CLI error",
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    terminal_available = True
    try:
        if isinstance(exc, ScribeError):
            console.print(
                f"\n[bold {ScribeTheme.ERROR}]Error:[/bold {ScribeTheme.ERROR}] {escape(str(exc))}"
            )
            if exc.context:
                user_ctx = {k: v for k, v in exc.context.items() if k != "phase"}
                if user_ctx:
                    console.print(f"[dim]Context: {escape(str(user_ctx))}[/dim]")
        else:
            console.print(
                f"\n[bold {ScribeTheme.ERROR}]Unexpected error:[/bold {ScribeTheme.ERROR}] "
                f"{escape(str(exc))}"
            )

        if log_file is not None:
            console.print(Text(f"Log file: {log_file}", style="dim"), soft_wrap=True)
        if recovery_hint is None:
            console.print(
                "[dim]Next: run `scribe doctor` to check setup. "
                "Use `scribe support-bundle` when sharing diagnostics.[/dim]"
            )
        else:
            console.print(Text(recovery_hint, style="dim"), soft_wrap=True)
    except TERMINAL_OUTPUT_ERRORS as terminal_error:
        if not is_terminal_output_error(terminal_error):
            raise
        terminal_available = False
        if log_file is not None:
            with suppress(Exception):
                logger.error(
                    "Terminal output failed while reporting %s: %s; delivery error was %s: %s",
                    type(exc).__name__,
                    exc,
                    type(terminal_error).__name__,
                    terminal_error,
                )
        _write_terminal_fallback(log_file)

    if terminal_available and sys.platform == "win32" and os.environ.get("SCRIBE_FROM_SHORTCUT"):
        # Guarantees the window stays for desktop/taskbar .lnk launches; a
        # closed stdin (EOFError) or Ctrl-C just lets the window close.
        with suppress(EOFError, KeyboardInterrupt):
            input("\n[Press Enter to close this window]")

    raise typer.Exit(1) from exc
