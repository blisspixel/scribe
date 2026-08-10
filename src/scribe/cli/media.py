"""Implement focused media-maintenance commands for the Scribe CLI."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.markup import escape
from rich.panel import Panel

if TYPE_CHECKING:
    from rich.console import Console

DurationProbe = Callable[[Path], float | None]
TrimOperation = Callable[[Path, Path | None, str | None], Path]
AnalyzeOperation = Callable[[Path, str, float], dict[str, Any]]
RemoveOperation = Callable[[Path, Path | None, str, float], Path]


def clean_media(
    console: Console,
    input_file: Path,
    output: Path | None,
    threshold: str,
    duration: float,
    analyze_only: bool,
    trim_to: str | None,
) -> None:
    """Analyze, trim, or remove silence from one media file."""
    from scribe.utils.audio import get_audio_duration
    from scribe.utils.silence_remover import analyze_silence, remove_silence, trim_file

    panel_lines = [f"[white]{escape(input_file.name)}[/white]"]
    original_duration = get_audio_duration(input_file)
    original_minutes = int(original_duration / 60) if original_duration else None
    if original_minutes is not None:
        panel_lines.append(
            f"[dim]Original duration: {original_minutes} minutes ({original_duration:.1f}s)[/dim]"
        )

    if trim_to:
        panel_lines.append(f"[dim]Mode: Trim to {escape(trim_to)}[/dim]")
    elif analyze_only:
        panel_lines.append("[dim]Mode: Analyze only[/dim]")
    else:
        panel_lines.append("[dim]Mode: Remove silence[/dim]")
        panel_lines.append(f"[dim]Threshold: {escape(threshold)}, Min duration: {duration}s[/dim]")

    console.print(Panel.fit("\n".join(panel_lines), border_style="cyan", padding=(0, 1)))
    console.print()

    if trim_to:
        _trim_media(
            console,
            input_file,
            output,
            trim_to,
            original_minutes,
            get_audio_duration,
            trim_file,
        )
        return

    if analyze_only:
        _analyze_media(console, input_file, threshold, duration, analyze_silence)
        return

    _remove_silence(console, input_file, output, threshold, duration, remove_silence)


def _trim_media(
    console: Console,
    input_file: Path,
    output: Path | None,
    trim_to: str,
    original_minutes: int | None,
    get_audio_duration: DurationProbe,
    trim_file: TrimOperation,
) -> None:
    console.print(f"[cyan]Trimming to {escape(trim_to)}...[/cyan]")
    console.print("[dim]This is fast - just copying, no re-encoding...[/dim]")
    console.print()
    output_path = trim_file(input_file, output, trim_to)
    new_duration = get_audio_duration(output_path)

    console.print()
    console.print("[bold green]Success![/bold green]")
    if new_duration:
        new_minutes = int(new_duration / 60)
        if original_minutes is not None:
            console.print(
                f"  Original: {original_minutes} minutes ({original_minutes / 60:.1f} hours)"
            )
        console.print(f"  Trimmed:  {new_minutes} minutes ({new_minutes / 60:.1f} hours)")
        console.print()
    console.print(f"[bold]Output:[/bold] {escape(str(output_path))}", soft_wrap=True)


def _analyze_media(
    console: Console,
    input_file: Path,
    threshold: str,
    duration: float,
    analyze_silence: AnalyzeOperation,
) -> None:
    console.print("[cyan]Analyzing silence...[/cyan]")
    analysis = analyze_silence(input_file, threshold, duration)
    console.print()
    console.print("[bold]Silence Analysis:[/bold]")
    console.print(
        f"  Total silence: {analysis['total_silence_minutes']:.1f} minutes "
        f"({analysis['total_silence_seconds']:.1f}s)"
    )
    console.print(f"  Silent periods: {analysis['silence_periods']}")

    if analysis["silence_periods"] > 0:
        console.print()
        console.print("[dim]First few silent periods:[/dim]")
        for index, period in enumerate(analysis["periods"][:5], 1):
            start_minutes = int(period["start"] / 60)
            console.print(f"  {index}. At {start_minutes}m: {period['duration']:.1f}s of silence")
        if analysis["silence_periods"] > 5:
            console.print(f"  ... and {analysis['silence_periods'] - 5} more")

    console.print()
    console.print("[green]To remove silence, run without --analyze flag[/green]")


def _remove_silence(
    console: Console,
    input_file: Path,
    output: Path | None,
    threshold: str,
    duration: float,
    remove_silence: RemoveOperation,
) -> None:
    console.print("[cyan]Removing silence...[/cyan]")
    console.print("[dim]This may take a few minutes for large files...[/dim]")
    console.print()
    output_path = remove_silence(input_file, output, threshold, duration)

    original_size = input_file.stat().st_size / (1024 * 1024)
    new_size = output_path.stat().st_size / (1024 * 1024)
    reduction = None
    if original_size > 0:
        reduction = ((original_size - new_size) / original_size) * 100

    console.print()
    console.print("[bold green]Success![/bold green]")
    console.print(f"  Original size: {original_size:.1f} MB")
    console.print(f"  Cleaned size:  {new_size:.1f} MB")
    reduction_text = f"{reduction:.1f}%" if reduction is not None else "n/a (empty input)"
    console.print(f"  Reduction:     {reduction_text}")
    console.print()
    console.print("[dim]Note: Silent sections are reduced to near-silence.[/dim]")
    console.print("[dim]This makes transcription much faster as Whisper skips silent parts.[/dim]")
    console.print()
    console.print(f"[bold]Output:[/bold] {escape(str(output_path))}", soft_wrap=True)
