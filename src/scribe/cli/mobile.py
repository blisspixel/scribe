"""
Simplified mobile workflow for non-GPU transcription.

This module provides a streamlined pipeline for systems without GPU,
using OpenAI API for transcription. Fixes the missing find_wav_file bug.
"""

import sys
from pathlib import Path

from rich.console import Console

from scribe.core.converter import Converter
from scribe.core.openai_api import OpenAITranscriber
from scribe.exceptions import ScribeError, ValidationError
from scribe.models.config import ScribeConfig
from scribe.utils.logging import setup_logging
from scribe.utils.platform import open_file_with_default_app
from scribe.utils.validation import validate_file_path

console = Console()


def find_wav_file(input_file: Path) -> Path:
    """
    Locate the converted WAV file for a given input.

    This function fixes the missing find_wav_file bug in scribemobile.py.

    Args:
        input_file: Original input file path

    Returns:
        Path to converted WAV file

    Raises:
        FileNotFoundError: If WAV file doesn't exist
    """
    # Try common WAV naming patterns
    candidates = [
        input_file.with_name(f"{input_file.stem}_converted.wav"),
        input_file.with_name(f"{input_file.stem}_16k_mono.wav"),
        input_file.with_suffix(".wav"),
    ]

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"Could not find converted WAV file for {input_file.name}. "
        f"Tried: {[c.name for c in candidates]}"
    )


def mobile_transcribe(input_file: str) -> None:
    """
    Run simplified mobile transcription workflow.

    Pipeline:
    1. Validate input file
    2. Convert to MP3 (optimized for OpenAI)
    3. Transcribe with OpenAI API
    4. Open transcript

    Args:
        input_file: Path to input file
    """
    try:
        # Load configuration
        config = ScribeConfig()

        if not config.openai_api_key:
            raise ValidationError(
                "OpenAI API key not configured. "
                "Set SCRIBE_OPENAI_API_KEY environment variable or add to .env file."
            )

        # Validate input
        console.print("[cyan]Validating input file...[/cyan]")
        input_path = validate_file_path(input_file)

        # Setup logging
        meeting_name = input_path.stem
        setup_logging(meeting_name, config.log_folder)  # Side effect: creates log file

        console.print(f"[green]Input: {input_path.name}[/green]\n")

        # Step 1: Convert to MP3
        console.print("[bold cyan]Step 1: Converting to MP3...[/bold cyan]")
        converter = Converter()
        mp3_path = converter.convert_to_mp3(input_path)
        console.print(f"[green]MP3 created: {mp3_path.name}[/green]\n")

        # Step 2: Transcribe with OpenAI
        console.print("[bold cyan]Step 2: Transcribing with OpenAI API...[/bold cyan]")
        transcriber = OpenAITranscriber(api_key=config.openai_api_key, model=config.openai_model)
        transcript_path = transcriber.transcribe(
            mp3_path, cleanup_temp=not config.keep_intermediate_files
        )
        console.print(f"[green]Transcript created: {transcript_path.name}[/green]\n")

        # Step 3: Open transcript
        console.print("[bold cyan]Step 3: Opening transcript...[/bold cyan]")
        if open_file_with_default_app(transcript_path):
            console.print("[green]Transcript opened successfully[/green]")
        else:
            console.print("[yellow]Could not open transcript automatically[/yellow]")
            console.print(f"[yellow]Please open manually: {transcript_path}[/yellow]")

        # Cleanup
        if not config.keep_intermediate_files:
            console.print("\n[cyan]Cleaning up temporary files...[/cyan]")
            try:
                if mp3_path.exists() and mp3_path != input_path:
                    mp3_path.unlink()
                    console.print(f"[dim]Deleted: {mp3_path.name}[/dim]")
            except Exception as e:
                console.print(f"[yellow]Could not delete {mp3_path.name}: {e}[/yellow]")

        console.print("\n[bold green]Done! Transcription saved and opened.[/bold green]")

    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if e.context:
            console.print(f"[dim]Context: {e.context}[/dim]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        sys.exit(1)


def main() -> None:
    """Main entry point for mobile workflow."""
    if len(sys.argv) < 2:
        console.print("[yellow]Usage: python -m scribe.cli.mobile <input_file>[/yellow]")
        console.print("\nExample:")
        console.print("  python -m scribe.cli.mobile recording.mp4")
        sys.exit(1)

    input_file = sys.argv[1]
    mobile_transcribe(input_file)


if __name__ == "__main__":
    main()
