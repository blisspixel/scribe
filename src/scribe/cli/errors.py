"""Shared CLI error reporting for Typer commands."""

from __future__ import annotations

from typing import NoReturn

import typer

from scribe.exceptions import ScribeError
from scribe.utils.logging import console, get_logger
from scribe.utils.theme import ScribeTheme

logger = get_logger(__name__)


def exit_on_cli_error(exc: BaseException, *, log_unexpected: bool = True) -> NoReturn:
    """Print a user-facing message and exit with code 1."""
    if isinstance(exc, ScribeError):
        console.print(f"\n[bold {ScribeTheme.ERROR}]Error:[/bold {ScribeTheme.ERROR}] {exc}")
        if exc.context:
            console.print(f"[dim]Context: {exc.context}[/dim]")
    else:
        console.print(
            f"\n[bold {ScribeTheme.ERROR}]Unexpected error:[/bold {ScribeTheme.ERROR}] {exc}"
        )
        if log_unexpected:
            logger.exception("Unexpected CLI error")
    raise typer.Exit(1) from exc
