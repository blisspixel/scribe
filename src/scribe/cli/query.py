"""
`scribe query`: keyword and structured search across stored transcripts.

Reads the JSON transcripts (schema scribe.transcript/v1) that the structured-output
writers leave next to each `.txt`, and prints matching segments by text and/or
speaker. This is the lean, no-index "ask across my meetings" capability: plain
keyword and field search over your output folder, not semantic retrieval.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scribe.utils.audio import format_timestamp
from scribe.utils.transcript_writers import JSON_SCHEMA

if TYPE_CHECKING:
    from rich.console import Console


# Skip absurdly large JSON files rather than reading them fully into memory; a real
# transcript is far smaller, and the output folder may be a synced/shared location.
_MAX_TRANSCRIPT_BYTES = 50 * 1024 * 1024


def _load_transcript(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > _MAX_TRANSCRIPT_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != JSON_SCHEMA:
        return None
    return data


def search_transcripts(
    folder: Path,
    text: str | None = None,
    speaker: str | None = None,
    limit: int = 50,
) -> list[tuple[Path, float, str | None, str]]:
    """Return (file, start, speaker, text) for segments matching the filters."""
    needle = text.lower() if text else None
    speaker_needle = speaker.lower() if speaker else None
    results: list[tuple[Path, float, str | None, str]] = []
    for path in sorted(folder.rglob("*.json")):
        data = _load_transcript(path)
        if data is None:
            continue
        for segment in data.get("segments", []):
            seg_text = str(segment.get("text", "")).strip()
            seg_speaker = segment.get("speaker")
            if needle and needle not in seg_text.lower():
                continue
            # Speaker match is case-insensitive substring, like the text filter,
            # so `--speaker nick` finds "Nick" and `--speaker 01` finds "SPEAKER_01".
            if speaker_needle and speaker_needle not in str(seg_speaker or "").lower():
                continue
            # Coerce defensively: a hand-edited or malformed start must not crash
            # the whole search across every file.
            try:
                start = float(segment.get("start", 0) or 0)
            except (TypeError, ValueError):
                start = 0.0
            results.append((path, start, seg_speaker, seg_text))
            # limit <= 0 means "no cap" (return everything matched).
            if limit > 0 and len(results) >= limit:
                return results
    return results


def run_query(
    console: Console,
    folder: Path,
    text: str | None = None,
    speaker: str | None = None,
    limit: int = 50,
) -> int:
    """Print matches; returns the number shown."""
    if not folder.exists():
        console.print(f"[yellow]Output folder not found: {folder}[/yellow]")
        return 0

    results = search_transcripts(folder, text=text, speaker=speaker, limit=limit)
    if not results:
        console.print("[yellow]No matching transcript segments.[/yellow]")
        return 0

    for path, start, seg_speaker, seg_text in results:
        prefix = f"[magenta]{seg_speaker}[/magenta] " if seg_speaker else ""
        console.print(
            f"[dim]{path.name}[/dim] [cyan]{format_timestamp(start)}[/cyan] {prefix}{seg_text}"
        )
    if limit > 0 and len(results) >= limit:
        console.print(f"[dim](showing the first {limit} matches)[/dim]")
    return len(results)
