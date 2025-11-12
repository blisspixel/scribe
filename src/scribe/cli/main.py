"""
Main CLI interface for Scribe using Typer.

This module provides the command-line interface with commands for
transcription, recording, and system information.
"""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from scribe import __version__
from scribe.models.config import ScribeConfig, TranscriptionMethod, ModelSize
from scribe.models.session import TranscriptionSession
from scribe.models.gpu import GPUConfig
from scribe.core.transcriber import Transcriber
from scribe.core.recorder import OBSRecorder
from scribe.utils.validation import validate_file_path, sanitize_meeting_name
from scribe.utils.files import extract_date_from_filename
from scribe.utils.docx_converter import txt_to_docx
from scribe.utils.logging import setup_logging, console, get_logger
from scribe.utils.joke_generator import generate_transcript_joke, ARCHETYPE_DISPLAY_NAMES

logger = get_logger(__name__)
from scribe.exceptions import ScribeError

# Create Typer app
app = typer.Typer(
    name="scribe",
    help="Professional GPU-accelerated speech-to-text transcription system",
    add_completion=True,
    rich_markup_mode="rich",
    no_args_is_help=True
)


@app.command(name="transcribe")
def transcribe_command(
    audio_file: Path = typer.Argument(
        ...,
        help="Path to audio/video file to transcribe",
        exists=True
    ),
    method: TranscriptionMethod = typer.Option(
        "auto",
        "--method", "-m",
        help="Transcription method: auto (intelligent choice), local (GPU), openai (API)"
    ),
    model: Optional[ModelSize] = typer.Option(
        None,
        "--model",
        help="Whisper model size (overrides config default)"
    ),
    language: Optional[str] = typer.Option(
        None,
        "--language", "-l",
        help="Language code (ISO 639-1, e.g., 'en', 'es', 'fr')"
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output file path (auto-generated if not specified)"
    ),
    no_docx: bool = typer.Option(
        False,
        "--no-docx",
        help="Skip DOCX document generation"
    ),
    no_notes: bool = typer.Option(
        False,
        "--no-notes",
        help="Skip meeting notes generation"
    ),
    keep_all: bool = typer.Option(
        False,
        "--keep-all",
        help="Keep all intermediate files (don't cleanup)"
    ),
    no_joke: bool = typer.Option(
        False,
        "--no-joke",
        help="Skip joke generation"
    ),
    no_meme: bool = typer.Option(
        False,
        "--no-meme",
        help="Skip meme generation"
    )
):
    """
    Transcribe an audio or video file.
    
    Examples:
    
      scribe transcribe meeting.mp4
      
      scribe transcribe interview.wav --method local --model large-v3
      
      scribe transcribe podcast.mp3 --method openai --language es
      
      scribe transcribe meeting.mp4 --no-joke --no-meme
    """
    try:
        # Load configuration
        config = ScribeConfig()
        
        # Override config with CLI options
        if model:
            config.default_model = model
        if language:
            # Validate language code
            from scribe.utils.validation import validate_language_code
            try:
                validated_lang = validate_language_code(language)
                config.default_language = validated_lang
            except ValidationError as e:
                console.print(f"[red]Invalid language code: {language}[/red]")
                console.print(f"[dim]Use 2-letter ISO 639-1 codes (e.g., 'en', 'es', 'fr', 'de', 'zh', 'ja')[/dim]")
                raise typer.Exit(1)
        if keep_all:
            config.keep_intermediate_files = True
        
        # Setup logging
        meeting_name = audio_file.stem
        logger = setup_logging(meeting_name, config.log_folder)
        
        console.print(Panel.fit(
            f"[bold cyan]Scribe Transcription System v{__version__}[/bold cyan]\n"
            f"File: {audio_file.name}",
            border_style="cyan"
        ))
        
        # Validate audio file
        audio_path = validate_file_path(str(audio_file))
        
        # Create session
        session = TranscriptionSession.create(meeting_name)
        session.add_file(audio_path, "source")
        
        # Determine transcription method (local GPU vs OpenAI API)
        transcriber = Transcriber(config)
        chosen_method = transcriber.choose_method(method)
        
        # Convert audio to optimal format based on transcription method
        if chosen_method == "local":
            # Local GPU transcription requires 16kHz mono WAV with normalized audio
            console.print("[cyan]Converting to WAV with normalized audio...[/cyan]")
            try:
                from scribe.core.converter import Converter
                converter = Converter()
                
                # Convert with timeout protection (won't hang indefinitely)
                # Uses dynaudnorm for proper audio normalization
                audio_file = converter.convert_to_wav(audio_path)
                
                console.print("[green]✓ Converted to WAV[/green]")
                console.print()
                console.print("[cyan]Transcribing with local NVIDIA GPU...[/cyan]")
            except ProcessError as e:
                console.print(f"[bold red]Conversion failed:[/bold red] {e}")
                console.print("[yellow]Tip: Check that ffmpeg is installed and the audio file is valid[/yellow]")
                raise typer.Exit(1)
            except Exception as e:
                console.print(f"[bold red]Unexpected conversion error:[/bold red] {e}")
                raise typer.Exit(1)
        else:
            # OpenAI API accepts multiple formats but has 25MB limit
            try:
                file_size_mb = audio_path.stat().st_size / (1024 * 1024)
            except (FileNotFoundError, OSError) as e:
                console.print(f"[bold red]Error:[/bold red] Cannot access file: {audio_path}")
                raise typer.Exit(1)
            
            if file_size_mb > 24:
                # File too large - compress to MP3 with normalized audio
                console.print(f"[yellow]File is {file_size_mb:.0f}MB (OpenAI limit is 25MB)[/yellow]")
                console.print("[cyan]Converting to compressed MP3...[/cyan]")
                try:
                    from scribe.core.converter import Converter
                    converter = Converter()
                    
                    # Convert with timeout protection
                    # Uses 48kbps bitrate for good quality at small size
                    audio_file = converter.convert_to_mp3(audio_path, bitrate=48)
                    
                    # Verify the compressed file is under the limit
                    compressed_size_mb = audio_file.stat().st_size / (1024 * 1024)
                    if compressed_size_mb > 24:
                        console.print(f"[bold red]Error:[/bold red] Compressed file still too large ({compressed_size_mb:.1f}MB)")
                        console.print("[yellow]Tip: Try using local GPU transcription for very long recordings[/yellow]")
                        raise typer.Exit(1)
                    
                    console.print(f"[green]✓ Converted to MP3 ({compressed_size_mb:.1f}MB)[/green]")
                except ProcessError as e:
                    console.print(f"[bold red]Conversion failed:[/bold red] {e}")
                    console.print("[yellow]Tip: Check that ffmpeg is installed and the audio file is valid[/yellow]")
                    raise typer.Exit(1)
                except Exception as e:
                    console.print(f"[bold red]Unexpected conversion error:[/bold red] {e}")
                    raise typer.Exit(1)
            else:
                # File size OK - use original audio file
                audio_file = audio_path
            
            console.print()
            console.print("[cyan]Transcribing with OpenAI API...[/cyan]")
        
        # Perform transcription (conversion already done above)
        transcript_path = transcriber.transcribe(
            audio_file,
            method=chosen_method,
            session=session
        )
        
        # Verify transcript was created and has content
        if not transcript_path or not transcript_path.exists():
            console.print("[red]Error: Transcription failed - no output file created[/red]")
            raise typer.Exit(1)
        
        if transcript_path.stat().st_size < 10:
            console.print("[red]Error: Transcription failed - output file is empty[/red]")
            raise typer.Exit(1)
        
        # Generate DOCX
        if not no_docx:
            console.print("[cyan]Generating DOCX document...[/cyan]")
            try:
                docx_path = txt_to_docx(transcript_path)
                session.add_file(docx_path, "docx")
                console.print(f"[green]DOCX created: {docx_path.name}[/green]")
            except Exception as e:
                console.print(f"[yellow]DOCX generation failed: {e}[/yellow]")
        
        # Generate meeting notes if enabled
        notes_path = None
        if not no_notes and config.enable_notes and config.openai_api_key:
            console.print("[cyan]Generating meeting notes...[/cyan]")
            try:
                from scribe.utils.notes_generator import NotesGenerator
                notes_generator = NotesGenerator(
                    api_key=config.openai_api_key,
                    model=config.notes_model
                )
                notes_path = notes_generator.generate_notes(transcript_path)
                session.add_file(notes_path, "notes")
                console.print(f"[green]✓ Notes generated: {notes_path.name}[/green]")
            except Exception as e:
                logger.error(f"Notes generation failed: {e}")
                console.print(f"[yellow]Notes generation failed: {e}[/yellow]")
        
        # Cleanup
        if not keep_all:
            console.print("[cyan]Cleaning up intermediate files...[/cyan]")
            deleted = transcriber.cleanup_intermediate_files(audio_path.parent)
            if deleted:
                console.print(f"[green]Cleaned up {len(deleted)} files[/green]")
        
        # Complete session
        session.complete(success=True)
        summary_path = session.save_summary(config.output_folder)
        
        console.print()
        console.print("[bold green]Transcription Complete[/bold green]")
        console.print()
        
        # Generate agentic AI joke (enabled by default)
        if not no_joke:
            if config.openai_api_key:
                console.print("[cyan]Generating joke...[/cyan]")
                result = generate_transcript_joke(transcript_path, config.openai_api_key)
                if result:
                    joke_text, comedy_style = result
                    
                    # Get human-readable archetype name for display
                    style_display = ARCHETYPE_DISPLAY_NAMES.get(
                        comedy_style, 
                        comedy_style.replace("_", " ").title()
                    )
                    
                    # Display joke cleanly: archetype name in cyan, joke in white
                    console.print()
                    console.print(f"[bold cyan]{style_display}:[/bold cyan]")
                    console.print(f"[white]{joke_text}[/white]")
                    console.print()
                    
                    # Save joke to session summary for future reference
                    if summary_path:
                        import json
                        try:
                            with open(summary_path, "r", encoding="utf-8") as f:
                                summary_data = json.load(f)
                            summary_data["joke"] = {
                                "text": joke_text,
                                "style": comedy_style
                            }
                            with open(summary_path, "w", encoding="utf-8") as f:
                                json.dump(summary_data, f, indent=2)
                        except Exception as e:
                            logger.warning(f"Failed to add joke to summary: {e}")
            else:
                logger.info("Skipping joke generation - OpenAI API key not configured")
        
        # Generate meme from transcript (enabled by default)
        if not no_meme:
            if config.openai_api_key:
                from scribe.utils.spinner import show_spinner
                from scribe.utils.meme_generator import generate_meeting_meme
                
                with show_spinner("Generating meme") as spinner:
                    meme_result = generate_meeting_meme(
                        transcript_path,
                        output_dir=config.output_folder,
                        api_key=config.openai_api_key
                    )
                    
                    if meme_result:
                        meme_path = meme_result["final_path"] if isinstance(meme_result, dict) else meme_result
                        attempts = meme_result.get("attempts", []) if isinstance(meme_result, dict) else []
                        best_score = meme_result.get("best_score") if isinstance(meme_result, dict) else None
                        
                        # Show success with score
                        if best_score is not None:
                            spinner.success("Meme generated", extra=f"score: {best_score:.1f}/10")
                        else:
                            spinner.success("Meme generated")
                        
                        # Store meme path and attempts for display later
                        session.add_file(meme_path, "meme")
                        session.meme_attempts = attempts  # Store all attempts
                    else:
                        spinner.error("Failed to generate meme")
                        logger.warning("Failed to generate meme")
            else:
                logger.info("Skipping meme generation - OpenAI API key not configured")
        
        # Display output files with clickable links
        # Order: Meme → Notes → DOCX → Transcript (TXT is what user usually clicks)
        console.print("[bold cyan]Output Files:[/bold cyan]")
        console.print()
        
        # Meme image (clickable link) - shown first after joke
        if session.meme_file:
            meme_path = session.meme_file
            url_path = str(meme_path).replace("\\", "/")
            console.print(f"  Meme:       [link=file:///{url_path}]{meme_path}[/link]")
            
            # Show all meme attempts if multiple were generated
            if hasattr(session, 'meme_attempts') and len(session.meme_attempts) > 1:
                console.print(f"\n  [dim]All meme attempts:[/dim]")
                for attempt in session.meme_attempts:
                    score_str = f"{attempt['score']:.1f}/10" if attempt['score'] is not None else "N/A"
                    attempt_path = attempt['path']
                    url_path = str(attempt_path).replace("\\", "/")
                    console.print(f"  [dim]  Attempt {attempt['attempt']} (score: {score_str}): [link=file:///{url_path}]{attempt_path}[/link][/dim]")
                console.print()
        
        # Notes file (clickable link)
        if notes_path:
            url_path = str(notes_path).replace("\\", "/")
            console.print(f"  Notes:      [link=file:///{url_path}]{notes_path}[/link]")
        
        # DOCX document (clickable link)
        if not no_docx and session.docx_file:
            docx_path = session.docx_file
            url_path = str(docx_path).replace("\\", "/")
            console.print(f"  Document:   [link=file:///{url_path}]{docx_path}[/link]")
        
        # Transcript file (clickable link) - shown last as it's most commonly clicked
        url_path = str(transcript_path).replace("\\", "/")
        console.print(f"  Transcript: [link=file:///{url_path}]{transcript_path}[/link]")
        
        console.print()
        
    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if e.context:
            console.print(f"[dim]Context: {e.context}[/dim]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def record(
    name: Optional[str] = typer.Option(
        None,
        "--name", "-n",
        help="Meeting name for the recording"
    ),
    auto_transcribe: bool = typer.Option(
        True,
        "--auto-transcribe/--no-auto-transcribe",
        help="Automatically transcribe after recording (default: True)"
    ),
    method: TranscriptionMethod = typer.Option(
        "auto",
        "--method", "-m",
        help="Transcription method (if auto-transcribe enabled)"
    ),
    no_joke: bool = typer.Option(
        False,
        "--no-joke",
        help="Skip joke generation"
    ),
    no_meme: bool = typer.Option(
        False,
        "--no-meme",
        help="Skip meme generation"
    )
):
    """
    Record audio/video using OBS Studio.
    
    Quick start: Just run 'scribe record' and enter the meeting name when prompted.
    Recording will start immediately and auto-transcribe when done.
    
    This command integrates with OBS Studio to record meetings and
    automatically transcribe them when recording stops.
    
    Examples:
    
      # Interactive mode (prompts for name)
      scribe record
      
      # With meeting name
      scribe record --name "Board Meeting"
      
      # Record without auto-transcription
      scribe record --name "Interview" --no-auto-transcribe
      
      # Record without humor
      scribe record --no-joke --no-meme
    """
    try:
        # Load configuration
        config = ScribeConfig()
        
        # Display header first
        console.print(Panel.fit(
            f"[bold cyan]Scribe Recording System v{__version__}[/bold cyan]",
            border_style="cyan"
        ))
        
        # Show configuration settings
        settings_table = Table(title="Recording Settings", show_header=False, box=None)
        settings_table.add_column("Setting", style="cyan", no_wrap=True)
        settings_table.add_column("Value", style="white")
        
        settings_table.add_row("Output Folder", str(config.output_folder))
        settings_table.add_row("Transcription", "Enabled (auto)" if auto_transcribe else "Disabled")
        if auto_transcribe:
            settings_table.add_row("Method", method.upper())
            settings_table.add_row("Model", config.default_model)
            settings_table.add_row("Language", config.default_language)
        
        console.print(settings_table)
        console.print()
        
        # Get meeting name interactively
        if not name:
            console.print("[dim]Press Ctrl+C to cancel[/dim]")
            name = typer.prompt("Meeting name", default="Meeting")
        
        # Sanitize meeting name
        name = sanitize_meeting_name(name)
        
        # Setup logging
        logger = setup_logging(name, config.log_folder)
        
        # Show meeting name
        console.print(f"\n[cyan]Meeting:[/cyan] [white]{name}[/white]\n")
        
        # Record
        recorder = OBSRecorder(config)
        recording_path = recorder.record(name)
        
        console.print(f"\n[bold green]Recording Complete![/bold green]")
        console.print(f"File: {recording_path}\n")
        
        # Auto-transcribe if requested
        if auto_transcribe:
            console.print("[cyan]Starting automatic transcription...[/cyan]\n")
            
            session = TranscriptionSession.create(name)
            session.add_file(recording_path, "source")
            
            # Determine method and convert
            transcriber = Transcriber(config)
            chosen_method = transcriber.choose_method(method)
            
            # Convert audio to optimal format based on transcription method
            if chosen_method == "local":
                # Local GPU transcription requires 16kHz mono WAV with normalized audio
                console.print("[cyan]Converting to WAV with normalized audio...[/cyan]")
                try:
                    from scribe.core.converter import Converter
                    converter = Converter()
                    
                    # Convert with timeout protection (won't hang indefinitely)
                    # Uses dynaudnorm for proper audio normalization
                    audio_file = converter.convert_to_wav(recording_path)
                    
                    console.print("[green]✓ Converted to WAV[/green]")
                    console.print()
                    console.print("[cyan]Transcribing with local NVIDIA GPU...[/cyan]")
                except ProcessError as e:
                    console.print(f"[bold red]Conversion failed:[/bold red] {e}")
                    console.print("[yellow]Tip: Check that ffmpeg is installed and the recording file is valid[/yellow]")
                    raise typer.Exit(1)
                except Exception as e:
                    console.print(f"[bold red]Unexpected conversion error:[/bold red] {e}")
                    raise typer.Exit(1)
            else:
                # OpenAI API accepts multiple formats but has 25MB limit
                try:
                    file_size_mb = recording_path.stat().st_size / (1024 * 1024)
                except (FileNotFoundError, OSError) as e:
                    console.print(f"[bold red]Error:[/bold red] Cannot access recording file: {recording_path}")
                    raise typer.Exit(1)
                
                if file_size_mb > 24:
                    # File too large - compress to MP3 with normalized audio
                    console.print(f"[yellow]File is {file_size_mb:.0f}MB (OpenAI limit is 25MB)[/yellow]")
                    console.print("[cyan]Converting to compressed MP3...[/cyan]")
                    try:
                        from scribe.core.converter import Converter
                        converter = Converter()
                        
                        # Convert with timeout protection
                        # Uses 48kbps bitrate for good quality at small size
                        audio_file = converter.convert_to_mp3(recording_path, bitrate=48)
                        
                        # Verify the compressed file is under the limit
                        compressed_size_mb = audio_file.stat().st_size / (1024 * 1024)
                        if compressed_size_mb > 24:
                            console.print(f"[bold red]Error:[/bold red] Compressed file still too large ({compressed_size_mb:.1f}MB)")
                            console.print("[yellow]Tip: Try using local GPU transcription for very long recordings[/yellow]")
                            raise typer.Exit(1)
                        
                        console.print(f"[green]✓ Converted to MP3 ({compressed_size_mb:.1f}MB)[/green]")
                    except ProcessError as e:
                        console.print(f"[bold red]Conversion failed:[/bold red] {e}")
                        console.print("[yellow]Tip: Check that ffmpeg is installed and the recording file is valid[/yellow]")
                        raise typer.Exit(1)
                    except Exception as e:
                        console.print(f"[bold red]Unexpected conversion error:[/bold red] {e}")
                        raise typer.Exit(1)
                else:
                    # File size OK - use original recording
                    audio_file = recording_path
                
                console.print()
                console.print("[cyan]Transcribing with OpenAI API...[/cyan]")
            
            # Transcribe
            transcript_path = transcriber.transcribe(
                audio_file,
                method=chosen_method,
                session=session
            )
            
            # Generate DOCX
            console.print("[cyan]Generating DOCX document...[/cyan]")
            try:
                docx_path = txt_to_docx(transcript_path)
                session.add_file(docx_path, "docx")
                console.print(f"[green]DOCX created: {docx_path.name}[/green]")
            except Exception as e:
                console.print(f"[yellow]DOCX generation failed: {e}[/yellow]")
            
            # Generate meeting notes if enabled
            notes_path = None
            if config.enable_notes and config.openai_api_key:
                console.print("[cyan]Generating meeting notes...[/cyan]")
                try:
                    from scribe.utils.notes_generator import NotesGenerator
                    notes_generator = NotesGenerator(
                        api_key=config.openai_api_key,
                        model=config.notes_model
                    )
                    notes_path = notes_generator.generate_notes(transcript_path)
                    session.add_file(notes_path, "notes")
                    console.print(f"[green]✓ Notes generated: {notes_path.name}[/green]")
                except Exception as e:
                    logger.error(f"Notes generation failed: {e}")
                    console.print(f"[yellow]Notes generation failed: {e}[/yellow]")
            
            # Cleanup
            console.print("[cyan]Cleaning up intermediate files...[/cyan]")
            deleted = transcriber.cleanup_intermediate_files(recording_path.parent)
            if deleted:
                console.print(f"[green]Cleaned up {len(deleted)} files[/green]")
            
            # Complete session
            session.complete(success=True)
            summary_path = session.save_summary(config.output_folder)
            
            console.print()
            console.print("[bold green]Recording & Transcription Complete[/bold green]")
            console.print()
            
            # Generate joke (enabled by default)
            if not no_joke:
                if config.openai_api_key:
                    try:
                        console.print("[cyan]Generating joke...[/cyan]")
                        result = generate_transcript_joke(transcript_path, config.openai_api_key)
                        if result:
                            joke_text, comedy_style = result
                            
                            # Get proper archetype display name
                            style_display = ARCHETYPE_DISPLAY_NAMES.get(comedy_style, comedy_style.replace("_", " ").title())
                            
                            # Display joke cleanly: archetype name in cyan, joke in white
                            console.print()
                            console.print(f"[bold cyan]{style_display}:[/bold cyan]")
                            console.print(f"[white]{joke_text}[/white]")
                            console.print()
                            
                            # Add joke to session summary
                            if summary_path:
                                import json
                                try:
                                    with open(summary_path, "r", encoding="utf-8") as f:
                                        summary_data = json.load(f)
                                    summary_data["joke"] = {
                                        "text": joke_text,
                                        "style": comedy_style
                                    }
                                    with open(summary_path, "w", encoding="utf-8") as f:
                                        json.dump(summary_data, f, indent=2)
                                except Exception as e:
                                    logger.warning(f"Failed to add joke to summary: {e}")
                        else:
                            logger.warning("Joke generation returned no result")
                    except Exception as e:
                        logger.error(f"Joke generation failed: {e}")
                        console.print(f"[yellow]Joke generation failed: {e}[/yellow]")
                else:
                    logger.info("Skipping joke generation - OpenAI API key not configured")
            
            # Generate meme from transcript (enabled by default)
            if not no_meme:
                if config.openai_api_key:
                    try:
                        console.print("[cyan]Generating meme...[/cyan]")
                        from scribe.utils.meme_generator import generate_meeting_meme
                        meme_result = generate_meeting_meme(
                            transcript_path,
                            output_dir=config.output_folder,
                            api_key=config.openai_api_key
                        )
                        if meme_result and meme_result.get("final_path"):
                            meme_path = meme_result["final_path"]
                            console.print(f"[green]✓ Meme generated[/green]")
                            console.print()
                            session.add_file(meme_path, "meme")
                        else:
                            logger.warning("Failed to generate meme")
                            console.print("[yellow]Meme generation returned no result[/yellow]")
                    except Exception as e:
                        logger.error(f"Meme generation failed: {e}")
                        console.print(f"[yellow]Meme generation failed: {e}[/yellow]")
                else:
                    logger.info("Skipping meme generation - OpenAI API key not configured")
            
            # Display output files with clickable links
            # Order: Meme → Notes → DOCX → Transcript → Recording
            console.print("[bold cyan]Output Files:[/bold cyan]")
            console.print()
            
            # Helper to format clickable file links
            def format_file_link(label: str, path: Path) -> str:
                # Convert Windows backslashes to forward slashes for file:// URLs
                url_path = str(path).replace("\\", "/")
                return f"  {label:<11} [link=file:///{url_path}]{path}[/link]"
            
            if session.meme_file:
                console.print(format_file_link("Meme:", session.meme_file))
            if notes_path:
                console.print(format_file_link("Notes:", notes_path))
            if session.docx_file:
                console.print(format_file_link("Document:", session.docx_file))
            console.print(format_file_link("Transcript:", transcript_path))
            console.print(format_file_link("Recording:", recording_path))
            console.print()
        
    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command(name="rec")
def rec_shortcut(
    name: Optional[str] = typer.Argument(None, help="Meeting name (optional)")
):
    """
    Quick record shortcut - starts recording immediately.
    
    Ultra-fast recording: 'scribe rec' or 'scribe rec "Meeting Name"'
    
    This is a shortcut for 'scribe record' with auto-transcribe enabled.
    If no name is provided, you'll be prompted to enter one.
    
    Examples:
    
      # Fastest - prompts for name
      scribe rec
      
      # With name as argument
      scribe rec "Team Standup"
      scribe rec Board-Meeting
    """
    # Call the record command directly with auto-transcribe enabled
    record(name=name, auto_transcribe=True, method="auto")


@app.command()
def joke(
    transcript_file: Path = typer.Argument(
        ...,
        help="Path to transcript file (.txt)",
        exists=True
    ),
    spice: Optional[int] = typer.Option(
        None,
        "--spice",
        help="Humor intensity 0-10 (0=off, 5=default, 10=spicy)"
    )
):
    """
    Generate an agentic AI joke about a transcript.
    
    Analyzes the transcript and generates context-aware humor using
    sophisticated comedy archetypes designed for post-meeting cognitive
    decompression.
    
    Example: scribe joke transcript.txt
    """
    try:
        config = ScribeConfig()
        
        if not config.openai_api_key:
            console.print("[bold red]Error:[/bold red] OpenAI API key not configured")
            console.print("[dim]Set SCRIBE_OPENAI_API_KEY in your .env file[/dim]")
            raise typer.Exit(1)
        
        # Validate file is a text file
        if not transcript_file.suffix.lower() in ['.txt', '.md']:
            console.print(f"[bold red]Error:[/bold red] File must be a text file (.txt or .md)")
            raise typer.Exit(1)
        
        console.print(f"\n[cyan]Analyzing:[/cyan] {transcript_file.name}")
        console.print("[cyan]Generating joke...[/cyan]\n")
        
        # Create humor config with spice level
        from scribe.utils.joke_generator import HumorConfig
        humor_config = HumorConfig.from_env()
        humor_config.api_key = config.openai_api_key
        
        if spice is not None:
            if 0 <= spice <= 10:
                humor_config.spice_level = spice
            else:
                console.print(f"[bold yellow]Warning:[/bold yellow] Invalid spice level {spice} (must be 0-10), using default")
        
        # Generate joke
        result = generate_transcript_joke(transcript_file, humor_config)
        
        if result:
            joke_text, comedy_style = result
            
            # Get proper archetype display name
            style_display = ARCHETYPE_DISPLAY_NAMES.get(comedy_style, comedy_style.replace("_", " ").title())
            
            # Display joke cleanly: archetype name in cyan, joke in white
            console.print(f"[bold cyan]{style_display}:[/bold cyan]")
            console.print(f"[white]{joke_text}[/white]")
            console.print()
        else:
            console.print("[bold yellow]Warning:[/bold yellow] Failed to generate joke")
            console.print("[dim]Check your OpenAI API key and try again[/dim]")
            raise typer.Exit(1)
            
    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if e.context:
            console.print(f"[dim]Context: {e.context}[/dim]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        logger.exception("Unexpected error in joke command")
        raise typer.Exit(1)


@app.command()
def meme(
    transcript_file: Path = typer.Argument(
        ...,
        help="Path to transcript file (.txt)",
        exists=True
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output path for meme (default: same directory as transcript)"
    ),
    spice: Optional[int] = typer.Option(
        None,
        "--spice",
        help="Humor intensity 0-10 (0=off, 5=default, 10=spicy)"
    ),
    show_reasoning: bool = typer.Option(
        False,
        "--show-reasoning", "-r",
        help="Display GPT-5's reasoning process (Glass Box Transparency)"
    )
):
    """
    Generate a meme from a meeting transcript.
    
    Uses GPT-5 to analyze the transcript and create a clever meme concept,
    then generates the meme image using OpenAI's image generation API.
    
    Example: scribe meme transcript.txt
    Example: scribe meme transcript.txt --output ./memes/meeting.png
    Example: scribe meme transcript.txt --show-reasoning
    """
    try:
        config = ScribeConfig()
        
        if not config.openai_api_key:
            console.print("[bold red]Error:[/bold red] OpenAI API key not configured")
            console.print("[dim]Set OPENAI_API_KEY or SCRIBE_OPENAI_API_KEY in your .env file[/dim]")
            raise typer.Exit(1)
        
        # Validate file is a text file
        if not transcript_file.suffix.lower() in ['.txt', '.md']:
            console.print(f"[bold red]Error:[/bold red] File must be a text file (.txt or .md)")
            raise typer.Exit(1)
        
        console.print(f"\n[cyan]Analyzing:[/cyan] {transcript_file.name}\n")
        
        # Generate meme with spinner
        from scribe.utils.spinner import show_spinner
        from scribe.utils.meme_generator import generate_meeting_meme, MemeConfig
        
        # Create meme config with spice level
        meme_config = MemeConfig.from_env()
        if spice is not None:
            if 0 <= spice <= 10:
                meme_config.spice_level = spice
            else:
                console.print(f"[bold yellow]Warning:[/bold yellow] Invalid spice level {spice} (must be 0-10), using default")
        
        with show_spinner("Generating meme") as spinner:
            if output:
                # Use specified output path
                meme_result = generate_meeting_meme(
                    transcript_file,
                    output_dir=output.parent if output.parent != Path('.') else None,
                    api_key=config.openai_api_key,
                    config=meme_config,
                    show_reasoning=show_reasoning
                )
                if meme_result:
                    meme_path = meme_result["final_path"] if isinstance(meme_result, dict) else meme_result
                    if output != meme_path:
                        # Rename to desired output name
                        import shutil
                        shutil.move(str(meme_path), str(output))
                        meme_path = output
                else:
                    meme_path = None
            else:
                # Use default output location
                meme_result = generate_meeting_meme(
                    transcript_file,
                    api_key=config.openai_api_key,
                    config=meme_config,
                    show_reasoning=show_reasoning
                )
                meme_path = meme_result["final_path"] if (meme_result and isinstance(meme_result, dict)) else meme_result
            
            if meme_path:
                # Extract attempts info
                attempts = meme_result.get("attempts", []) if isinstance(meme_result, dict) else []
                best_score = meme_result.get("best_score") if isinstance(meme_result, dict) else None
                
                # Show success with score
                if best_score is not None:
                    spinner.success("Meme generated", extra=f"score: {best_score:.1f}/10")
                else:
                    spinner.success("Meme generated")
            else:
                spinner.error("Failed to generate meme")
                console.print("[dim]Check your OpenAI API key and try again[/dim]")
                raise typer.Exit(1)
        
        # Display results
        console.print()
        url_path = str(meme_path).replace("\\", "/")
        console.print(f"[bold cyan]Meme:[/bold cyan] [link=file:///{url_path}]{meme_path}[/link]")
        
        # Show all attempts if multiple were generated
        if len(attempts) > 1:
            console.print(f"\n[bold cyan]All Attempts:[/bold cyan]")
            for attempt in attempts:
                score_str = f"{attempt['score']:.1f}/10" if attempt['score'] is not None else "N/A"
                attempt_path = attempt['path']
                url_path = str(attempt_path).replace("\\", "/")
                console.print(f"  Attempt {attempt['attempt']} (score: {score_str}): [link=file:///{url_path}]{attempt_path}[/link]")
        console.print()
            
    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if e.context:
            console.print(f"[dim]Context: {e.context}[/dim]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        logger.exception("Unexpected error in meme command")
        raise typer.Exit(1)


@app.command()
def notes(
    transcript_file: Path = typer.Argument(
        ...,
        help="Path to transcript file (.txt)",
        exists=True
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output path for notes (default: same directory as transcript)"
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        help="GPT model to use (default: gpt-5)"
    )
):
    """
    Generate structured meeting notes from a transcript.
    
    Uses GPT-5 to analyze the transcript and create comprehensive notes with:
    - Detailed summary
    - Current state (business & technical)
    - Drivers and blockers
    - Future state and next steps
    
    Example: scribe notes transcript.txt
    Example: scribe notes transcript.txt --output ./notes/meeting.md
    Example: scribe notes transcript.txt --model gpt-5-mini
    """
    try:
        config = ScribeConfig()
        
        if not config.openai_api_key:
            console.print("[bold red]Error:[/bold red] OpenAI API key not configured")
            console.print("[dim]Set OPENAI_API_KEY in your .env file[/dim]")
            raise typer.Exit(1)
        
        # Validate file is a text file
        if not transcript_file.suffix.lower() in ['.txt', '.md']:
            console.print(f"[bold red]Error:[/bold red] File must be a text file (.txt or .md)")
            raise typer.Exit(1)
        
        console.print(f"\n[cyan]Analyzing:[/cyan] {transcript_file.name}")
        console.print("[cyan]Generating meeting notes...[/cyan]")
        console.print("[dim]This may take 30-60 seconds...[/dim]\n")
        
        # Generate notes
        from scribe.utils.notes_generator import NotesGenerator
        
        notes_model = model or config.notes_model
        notes_generator = NotesGenerator(
            api_key=config.openai_api_key,
            model=notes_model
        )
        
        notes_path = notes_generator.generate_notes(transcript_file, output)
        
        console.print(f"\n[bold green]✓[/bold green] Notes generated successfully!")
        console.print()
        
        # Convert to absolute path with forward slashes for clickable link
        abs_path = notes_path.absolute()
        link_path = str(abs_path).replace("\\", "/")
        console.print(f"[bold cyan]Notes:[/bold cyan] [link=file:///{link_path}]{abs_path}[/link]")
        console.print()
            
    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if e.context:
            console.print(f"[dim]Context: {e.context}[/dim]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        logger.exception("Unexpected error in notes command")
        raise typer.Exit(1)


@app.command()
def info():
    """
    Show system information and GPU capabilities.
    
    Displays GPU detection results, recommended transcription method,
    and system configuration.
    """
    try:
        config = ScribeConfig()
        gpu_config = GPUConfig.detect()
        
        console.print(Panel.fit(
            f"[bold cyan]Scribe System Information v{__version__}[/bold cyan]",
            border_style="cyan"
        ))
        
        # GPU Information
        gpu_table = Table(title="GPU Information", show_header=False)
        gpu_table.add_column("Property", style="cyan")
        gpu_table.add_column("Value", style="white")
        
        if gpu_config.has_gpu:
            gpu_table.add_row("GPU Detected", "[green]Yes[/green]")
            gpu_table.add_row("GPU Name", gpu_config.gpu_name or "Unknown")
            gpu_table.add_row("VRAM", f"{gpu_config.gpu_memory_gb:.1f} GB")
            gpu_table.add_row("CUDA Available", "[green]Yes[/green]" if gpu_config.cuda_available else "[red]No[/red]")
            if gpu_config.cuda_version:
                gpu_table.add_row("CUDA Version", gpu_config.cuda_version)
            gpu_table.add_row("Recommended Model", gpu_config.model_size)
            gpu_table.add_row("Beam Size", str(gpu_config.beam_size))
            gpu_table.add_row("FP16 Precision", "[green]Enabled[/green]" if gpu_config.use_fp16 else "[yellow]Disabled[/yellow]")
            gpu_table.add_row("Expected Speed", gpu_config.get_expected_speed())
        else:
            gpu_table.add_row("GPU Detected", "[red]No[/red]")
            gpu_table.add_row("Reason", gpu_config.reason)
        
        console.print(gpu_table)
        console.print()
        
        # Recommendation
        if gpu_config.recommendation == "local":
            console.print(f"[bold green]Recommendation:[/bold green] Use local GPU transcription")
            console.print(f"[dim]{gpu_config.reason}[/dim]")
        else:
            console.print(f"[bold yellow]Recommendation:[/bold yellow] Use OpenAI API transcription")
            console.print(f"[dim]{gpu_config.reason}[/dim]")
        
        console.print()
        
        # Configuration
        config_table = Table(title="Configuration", show_header=False)
        config_table.add_column("Setting", style="cyan")
        config_table.add_column("Value", style="white")
        
        config_table.add_row("Output Folder", str(config.output_folder))
        config_table.add_row("Default Model", config.default_model)
        config_table.add_row("Default Language", config.default_language)
        config_table.add_row("OpenAI API Key", "[green]Configured[/green]" if config.openai_api_key else "[yellow]Not Set[/yellow]")
        config_table.add_row("HF Token", "[green]Configured[/green]" if config.hf_token else "[yellow]Not Set[/yellow]")
        
        console.print(config_table)
        
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def doctor():
    """
    Run system diagnostics and health checks.
    
    Validates environment, dependencies, and configuration.
    Provides actionable suggestions for fixing issues.
    """
    from scribe.utils.diagnostics import SystemDiagnostics
    
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Scribe System Diagnostics[/bold cyan]",
        border_style="cyan"
    ))
    console.print()
    
    # Run diagnostics
    diagnostics = SystemDiagnostics()
    results = diagnostics.run_all_checks()
    
    # Display results
    for result in results:
        # Status icon and color
        if result.status == "pass":
            icon = "✓"
            color = "green"
        elif result.status == "warn":
            icon = "⚠"
            color = "yellow"
        else:
            icon = "✗"
            color = "red"
        
        # Print result
        console.print(f"[{color}]{icon}[/{color}] [bold]{result.name}:[/bold] {result.message}")
        
        if result.details:
            console.print(f"  [dim]{result.details}[/dim]")
        
        if result.fix_suggestion:
            console.print(f"  [cyan]→[/cyan] {result.fix_suggestion}")
        
        console.print()
    
    # Summary
    pass_count, warn_count, fail_count = diagnostics.get_summary()
    total = len(results)
    
    console.print("─" * 60)
    console.print()
    
    if fail_count == 0 and warn_count == 0:
        console.print("[bold green]✓ All checks passed![/bold green]")
        console.print("[dim]Your system is ready to use Scribe.[/dim]")
    elif fail_count == 0:
        console.print(f"[bold yellow]⚠ {warn_count} warning(s)[/bold yellow]")
        console.print("[dim]Scribe will work, but some features may be limited.[/dim]")
    else:
        console.print(f"[bold red]✗ {fail_count} critical issue(s)[/bold red]")
        console.print("[dim]Please fix the issues above before using Scribe.[/dim]")
    
    console.print()
    console.print(f"[dim]Summary: {pass_count} passed, {warn_count} warnings, {fail_count} failed[/dim]")
    console.print()
    
    # Exit with error code if there are failures
    if fail_count > 0:
        raise typer.Exit(1)


@app.command(name="support-bundle")
def support_bundle(
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output directory for support bundle (default: current directory)"
    )
):
    """
    Generate a support bundle for troubleshooting.
    
    Creates a comprehensive diagnostic package containing system information,
    environment configuration, recent run history, and diagnostic results.
    
    The bundle is saved as a JSON file that can be shared with support
    or used for debugging issues.
    
    Examples:
    
      # Generate in current directory
      scribe support-bundle
      
      # Generate in specific directory
      scribe support-bundle --output ~/Desktop
    """
    from scribe.utils.support_bundle import generate_support_bundle_cli
    
    console.print()
    console.print(Panel.fit(
        "[bold cyan]Generating Support Bundle[/bold cyan]",
        border_style="cyan"
    ))
    console.print()
    
    try:
        output_dir = output if output else Path.cwd()
        
        console.print("[cyan]Collecting system information...[/cyan]")
        console.print("[cyan]Running diagnostics...[/cyan]")
        console.print("[cyan]Gathering run history...[/cyan]")
        
        bundle_path = generate_support_bundle_cli(output_dir)
        
        console.print()
        console.print("[bold green]Support bundle created successfully[/bold green]")
        console.print()
        console.print(f"[cyan]Location:[/cyan] {bundle_path}")
        console.print()
        console.print("[dim]This bundle contains:[/dim]")
        console.print("[dim]  - System information (OS, Python, GPU)[/dim]")
        console.print("[dim]  - Environment configuration (sanitized)[/dim]")
        console.print("[dim]  - Diagnostic results[/dim]")
        console.print("[dim]  - Recent run history[/dim]")
        console.print()
        console.print("[dim]You can share this file for troubleshooting.[/dim]")
        console.print("[dim]API keys are automatically redacted.[/dim]")
        console.print()
        
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] Failed to create support bundle")
        console.print(f"[dim]{e}[/dim]")
        raise typer.Exit(1)


@app.command()
def version():
    """Show version information."""
    console.print(f"[bold cyan]Scribe[/bold cyan] version [bold]{__version__}[/bold]")


def main():
    """Main entry point with smart command detection."""
    import sys
    
    # If first argument looks like a file path, inject 'transcribe' command
    if len(sys.argv) > 1:
        first_arg = sys.argv[1]
        # Check if it's not a known command and looks like a file
        known_commands = ['transcribe', 'record', 'info', 'version', 'doctor', 'support-bundle', 'diagnose', '--help', '-h', '--version']
        if first_arg not in known_commands and not first_arg.startswith('-'):
            # Check if it looks like a file path
            if '.' in first_arg or '/' in first_arg or '\\' in first_arg or Path(first_arg).exists():
                # Insert 'transcribe' command
                sys.argv.insert(1, 'transcribe')
    
    app()


if __name__ == "__main__":
    main()
