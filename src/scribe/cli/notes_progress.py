"""Visible note phases without a stream of progress log lines."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn


@contextmanager
def notes_progress(console: Console) -> Iterator[Callable[[str], None]]:
    """Refresh one terminal line; redirected output gets one line per transition."""
    started = time.monotonic()
    if not console.is_terminal:

        def report(phase: str) -> None:
            console.print(
                f"Notes: {phase} | elapsed {time.monotonic() - started:.0f}s", markup=False
            )

        yield report
        return

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.description}"),
        TextColumn("elapsed"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
        refresh_per_second=4,
    ) as progress:
        task = progress.add_task("Preparing notes", total=None)

        def update(phase: str) -> None:
            progress.update(task, description=phase)

        yield update
