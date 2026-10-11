"""One-time recording-consent acknowledgement for the record commands.

Recording laws vary by jurisdiction and some require all-party consent. Scribe
cannot know the user's situation, so before the first recording it shows a short
notice and asks the user to confirm they will obtain any legally required consent.
The acknowledgement is stored in the user data directory; legacy markers remain readable.

This is a responsible-use guardrail, not legal advice. It is deliberately
non-blocking in non-interactive contexts (scheduled jobs, CI) where prompting is
impossible: there it prints a one-line reminder and proceeds, and an operator can
silence even that with ``SCRIBE_ASSUME_CONSENT=1``.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import typer

if TYPE_CHECKING:
    from rich.console import Console

CONSENT_NOTICE = (
    "Scribe records audio to your local machine. Recording laws vary by location, "
    "and some places require consent from everyone on the call before you record. "
    "Some US states (for example California, Florida, Illinois, Pennsylvania, "
    "Massachusetts, and Washington, among others) and many countries require "
    "all-party consent. You are responsible for obtaining any consent the law "
    "requires and for following local rules. This is not legal advice."
)

_ONE_LINE = (
    "Recording. Ensure you have any legally required consent (laws vary; some places "
    "need all-party consent). Not legal advice. Set SCRIBE_ASSUME_CONSENT=1 to silence."
)


def consent_marker_path() -> Path:
    """Location of the one-time recording-consent acknowledgement marker."""
    from scribe.paths import data_dir

    return data_dir() / "recording_consent_ack"


def _assumed() -> bool:
    return os.getenv("SCRIBE_ASSUME_CONSENT", "").strip().lower() in ("1", "true", "yes")


def ensure_recording_consent(console: Console) -> bool:
    """Return True if recording may proceed, asking for consent once if interactive.

    - Already acknowledged (marker present) or ``SCRIBE_ASSUME_CONSENT`` set: proceed.
    - Non-interactive (no TTY): print a one-line reminder and proceed, since a
      scheduled or piped run cannot answer a prompt.
    - Interactive and not yet acknowledged: show the notice and ask once. On yes,
      record the acknowledgement and proceed; on no, do not record.
    """
    from scribe.paths import legacy_dir

    if (
        _assumed()
        or consent_marker_path().exists()
        or (legacy_dir() / "recording_consent_ack").exists()
    ):
        return True

    if not sys.stdin.isatty():
        console.print(f"[yellow]{_ONE_LINE}[/yellow]")
        return True

    console.print()
    console.print(f"[yellow]{CONSENT_NOTICE}[/yellow]")
    console.print("[dim]This prompt is shown only once.[/dim]")
    confirmed = typer.confirm(
        "Do you confirm that you will obtain any legally required consent before recording?",
        default=False,
    )
    if not confirmed:
        console.print("[red]Recording cancelled.[/red]")
        return False

    try:
        marker = consent_marker_path()
        marker.parent.mkdir(parents=True, exist_ok=True)
        # Keep the acknowledgement private.
        with contextlib.suppress(OSError):
            os.chmod(marker.parent, 0o700)
        marker.write_text("acknowledged\n", encoding="utf-8")
        with contextlib.suppress(OSError):
            os.chmod(marker, 0o600)
    except OSError:
        # If we cannot persist the acknowledgement, proceed anyway; the user has
        # confirmed in this session. They may just be asked again next time.
        pass
    return True
