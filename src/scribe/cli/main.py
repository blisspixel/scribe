"""
Main CLI interface for Scribe using Typer.

This module provides the command-line interface with commands for
transcription, recording, and system information.
"""

from pathlib import Path
from typing import Optional
import time

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
from scribe.exceptions import ScribeError, ProcessError

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
        
        # Validate audio file first
        audio_path = validate_file_path(str(audio_file))
        
        # Setup logging
        meeting_name = audio_file.stem
        logger = setup_logging(meeting_name, config.log_folder)
        workflow_start_time = time.time()
        
        # Get audio duration for progress estimation
        from scribe.utils.audio import get_audio_duration
        audio_duration = get_audio_duration(audio_path)
        duration_mins = int(audio_duration / 60) if audio_duration else 0
        
        # Check what features are actually enabled
        has_api_key = bool(config.openai_api_key)
        will_generate_notes = not no_notes and config.enable_notes and has_api_key
        will_generate_joke = not no_joke and has_api_key
        will_generate_meme = not no_meme and has_api_key
        include_api_features = will_generate_notes or will_generate_joke or will_generate_meme
        
        # Build feature list for display
        outputs = ["transcript"]
        if will_generate_notes:
            outputs.append("notes")
        if will_generate_joke:
            outputs.append("joke")
        if will_generate_meme:
            outputs.append("meme")
        
        # Build panel content
        panel_lines = [f"[bold cyan]Scribe v{__version__}[/bold cyan]"]
        panel_lines.append(f"[white]{audio_file.name}[/white]")
        
        if duration_mins:
            panel_lines.append(f"[dim]Duration: {duration_mins} minutes[/dim]")
        
        panel_lines.append(f"[dim]Generating: {', '.join(outputs)}[/dim]")
        
        console.print(Panel.fit(
            "\n".join(panel_lines),
            border_style="cyan",
            padding=(0, 1)
        ))
        console.print()
        
        # Initialize unified progress with adaptive performance tracking
        from scribe.utils.unified_progress import UnifiedProgress
        import platform
        import hashlib
        
        # Generate stable machine ID from hardware info
        machine_info = f"{platform.node()}-{platform.processor()}"
        machine_id = hashlib.md5(machine_info.encode()).hexdigest()[:16]
        
        unified_progress = UnifiedProgress(audio_duration, machine_id=machine_id, include_api_features=include_api_features)
        unified_progress.start()
        
        # Create session
        session = TranscriptionSession.create(meeting_name)
        session.add_file(audio_path, "source")
        
        # Determine transcription method (local GPU vs OpenAI API)
        transcriber = Transcriber(config)
        chosen_method = transcriber.choose_method(method)
        
        # Phase 1: Preparing audio (0-15%)
        if chosen_method == "local":
            unified_progress.update_phase("preparing", 0.0)
            try:
                from scribe.core.converter import Converter
                converter = Converter()
                # Suppress converter's own progress (unified progress handles it)
                # Pass callback to update unified progress during conversion
                audio_file = converter.convert_to_wav(
                    audio_path, 
                    show_progress=False,
                    progress_callback=lambda p: unified_progress.update_phase("preparing", p)
                )
                unified_progress.update_phase("preparing", 1.0)
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
                    
                    console.print(f"Converted to MP3 ({compressed_size_mb:.1f}MB)")
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
        
        # Phase 2: Transcribing (18-68%)
        unified_progress.update_phase("transcribing", 0.0)
        
        # Start a thread to update progress during transcription
        import threading
        transcription_done = threading.Event()
        
        def update_transcription_progress():
            while not transcription_done.is_set():
                unified_progress.refresh()
                time.sleep(1.0)
        
        progress_thread = threading.Thread(target=update_transcription_progress, daemon=True)
        progress_thread.start()
        
        try:
            transcript_path = transcriber.transcribe(
                audio_file,
                method=chosen_method,
                session=session
            )
        finally:
            transcription_done.set()
            progress_thread.join(timeout=1.0)
        
        unified_progress.update_phase("transcribing", 1.0)
        
        # Verify transcript was created and has content
        if not transcript_path or not transcript_path.exists():
            console.print("[red]Error: Transcription failed - no output file created[/red]")
            raise typer.Exit(1)
        
        if transcript_path.stat().st_size < 10:
            console.print("[red]Error: Transcription failed - output file is empty[/red]")
            raise typer.Exit(1)
        
        # Phase 3: Finishing (85-100%)
        unified_progress.update_phase("finishing", 0.0, "Creating DOCX")
        
        # Generate DOCX
        if not no_docx:
            try:
                docx_path = txt_to_docx(transcript_path)
                session.add_file(docx_path, "docx")
            except Exception as e:
                logger.error(f"DOCX generation failed: {e}")
        
        # Generate meeting notes if enabled
        notes_path = None
        if not no_notes and config.enable_notes and config.openai_api_key:
            unified_progress.update_phase("finishing", 0.2, "Generating notes")
            try:
                from scribe.utils.notes_generator import NotesGenerator
                notes_generator = NotesGenerator(
                    api_key=None,  # Let provider factory get the right key
                    model=config.notes_model,
                    provider_name=None  # Will use SCRIBE_NOTES_PROVIDER env var
                )
                notes_path = notes_generator.generate_notes(transcript_path)
                session.add_file(notes_path, "notes")
            except Exception as e:
                logger.error(f"Notes generation failed: {e}")
        
        # Generate joke if enabled
        if not no_joke and config.openai_api_key:
            unified_progress.update_phase("finishing", 0.6, "Generating joke")
            result = generate_transcript_joke(transcript_path, config.openai_api_key)
            if result:
                joke_text, comedy_style = result
                
                # Save joke to session for later display
                if not hasattr(session, 'joke_data'):
                    session.joke_data = {"text": joke_text, "style": comedy_style}
        
        # Generate meme from transcript (enabled by default)
        if not no_meme and config.openai_api_key:
            from scribe.utils.meme_generator import generate_meeting_meme
            
            def meme_progress(attempt, max_attempts, score):
                """Update progress during meme generation"""
                if score is None:
                    unified_progress.update_phase("finishing", 0.8, f"Generating meme (attempt {attempt}/{max_attempts})")
                else:
                    unified_progress.update_phase("finishing", 0.8, f"Refining meme (score: {score:.1f}/10, attempt {attempt}/{max_attempts})")
            
            unified_progress.update_phase("finishing", 0.8, "Generating meme")
            meme_result = generate_meeting_meme(
                transcript_path,
                output_dir=config.output_folder,
                api_key=None,  # Let provider system choose the right key
                progress_callback=meme_progress
            )
            
            if meme_result:
                meme_path = meme_result["final_path"] if isinstance(meme_result, dict) else meme_result
                session.add_file(meme_path, "meme")
        
        # Cleanup
        if not keep_all:
            unified_progress.update_phase("finishing", 0.95, "Cleaning up")
            deleted = transcriber.cleanup_intermediate_files(audio_path.parent)
        
        # Complete unified progress
        unified_progress.update_phase("finishing", 1.0)
        unified_progress.complete()
        
        # Complete session
        session.complete(success=True)
        summary_path = session.save_summary(config.output_folder)
        console.print()
        
        # Display joke if generated
        if hasattr(session, 'joke_data') and session.joke_data:
            joke_text = session.joke_data["text"]
            console.print(f"[bold cyan]Joke:[/bold cyan] {joke_text}")
            console.print()
        
        # Display output files - simple names with clickable links
        console.print("[bold cyan]Output:[/bold cyan]")
        console.print()
        
        # Show just filenames, but make them clickable
        if transcript_path:
            url_path = str(transcript_path).replace("\\", "/")
            console.print(f"  [link=file:///{url_path}]{transcript_path.name}[/link]")
        
        if not no_docx and session.docx_file:
            url_path = str(session.docx_file).replace("\\", "/")
            console.print(f"  [link=file:///{url_path}]{session.docx_file.name}[/link]")
        
        if notes_path:
            url_path = str(notes_path).replace("\\", "/")
            console.print(f"  [link=file:///{url_path}]{notes_path.name}[/link]")
        
        if session.meme_file:
            url_path = str(session.meme_file).replace("\\", "/")
            console.print(f"  [link=file:///{url_path}]{session.meme_file.name}[/link]")
        
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
        # Note: Could use unified progress here, but record command shows individual
        # progress bars for each step which provides more detail during the workflow
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
                try:
                    from scribe.core.converter import Converter
                    converter = Converter()
                    
                    # Convert with timeout protection (won't hang indefinitely)
                    # Uses dynaudnorm for proper audio normalization
                    audio_file = converter.convert_to_wav(recording_path)
                    
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
                        
                        console.print(f"Converted to MP3 ({compressed_size_mb:.1f}MB)")
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
            try:
                docx_path = txt_to_docx(transcript_path)
                session.add_file(docx_path, "docx")
            except Exception as e:
                console.print(f"[yellow]DOCX generation failed: {e}[/yellow]")
            
            # Generate meeting notes if enabled
            notes_path = None
            if config.enable_notes and config.openai_api_key:
                console.print("[cyan]Generating meeting notes...[/cyan]")
                try:
                    from scribe.utils.notes_generator import NotesGenerator
                    notes_generator = NotesGenerator(
                        api_key=None,  # Let provider factory get the right key
                        model=config.notes_model,
                        provider_name=None  # Will use SCRIBE_NOTES_PROVIDER env var
                    )
                    notes_path = notes_generator.generate_notes(transcript_path)
                    session.add_file(notes_path, "notes")
                except Exception as e:
                    logger.error(f"Notes generation failed: {e}")
                    console.print(f"[yellow]Notes generation failed: {e}[/yellow]")
            
            # Cleanup
            deleted = transcriber.cleanup_intermediate_files(recording_path.parent)
            if deleted:
                logger.debug(f"Cleaned up {len(deleted)} intermediate files")
            
            # Complete session
            session.complete(success=True)
            summary_path = session.save_summary(config.output_folder)
            
            console.print()
            console.print("[bold green]Recording & Transcription Complete[/bold green]")
            console.print()
            
            # Debug: Log the flags
            logger.info(f"Humor flags: no_joke={no_joke}, no_meme={no_meme}, has_api_key={bool(config.openai_api_key)}")
            
            # Generate joke (enabled by default)
            if not no_joke:
                if config.openai_api_key:
                    try:
                        # Quiet spinner for joke generation
                        from scribe.utils.spinner import show_spinner
                        with show_spinner("Generating joke"):
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
                        # Quiet spinner for meme generation
                        from scribe.utils.spinner import show_spinner
                        from scribe.utils.meme_generator import generate_meeting_meme
                        
                        with show_spinner("Generating meme") as spinner:
                            meme_result = generate_meeting_meme(
                                transcript_path,
                                output_dir=config.output_folder,
                                api_key=None  # Let provider system choose the right key
                            )
                            if meme_result and meme_result.get("final_path"):
                                spinner.success("Meme generated")
                            else:
                                spinner.error("Meme generation failed")
                        if meme_result and meme_result.get("final_path"):
                            meme_path = meme_result["final_path"]
                            logger.info("Meme generated")
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
            # Order: Transcript (txt) → Document (docx) → Notes → Recording → Meme
            console.print("[bold cyan]Output:[/bold cyan]")
            console.print()
            
            # Helper to format clickable file links
            def format_file_link(label: str, path: Path) -> str:
                # Convert Windows backslashes to forward slashes for file:// URLs
                url_path = str(path).replace("\\", "/")
                return f"  {label:<11} [link=file:///{url_path}]{path}[/link]"
            
            console.print(format_file_link("Transcript:", transcript_path))
            if session.docx_file:
                console.print(format_file_link("Document:", session.docx_file))
            if notes_path:
                console.print(format_file_link("Notes:", notes_path))
            console.print(format_file_link("Recording:", recording_path))
            if session.meme_file:
                console.print(format_file_link("Meme:", session.meme_file))
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
    record(name=name, auto_transcribe=True, method="auto", no_joke=False, no_meme=False)


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
    ),
    archetype: Optional[str] = typer.Option(
        None,
        "--archetype",
        help="Force specific comedy archetype (translator, trickster, fool_scholar, etc.)"
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="AI provider to use (openai, xai)"
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
        
        # Display header
        panel_lines = [f"[bold cyan]Scribe v{__version__}[/bold cyan]"]
        panel_lines.append(f"[white]{transcript_file.name}[/white]")
        panel_lines.append(f"[dim]Generating: joke[/dim]")
        
        console.print(Panel.fit(
            "\n".join(panel_lines),
            border_style="cyan",
            padding=(0, 1)
        ))
        console.print()
        
        # Create humor config with spice level
        from scribe.utils.joke_generator import HumorConfig
        humor_config = HumorConfig.from_env()
        humor_config.api_key = config.openai_api_key
        
        if spice is not None:
            if 0 <= spice <= 10:
                humor_config.spice_level = spice
            else:
                console.print(f"[bold yellow]Warning:[/bold yellow] Invalid spice level {spice} (must be 0-10), using default")
        
        if archetype is not None:
            humor_config.archetype = archetype
        
        # Generate joke with progress
        from rich.progress import Progress, SpinnerColumn, TextColumn
        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("Generating joke...", total=None)
            result = generate_transcript_joke(transcript_file, humor_config, provider_name=provider)
        
        console.print()
        
        if result:
            joke_text, comedy_style = result
            console.print(f"[bold cyan]Joke:[/bold cyan] {joke_text}")
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
        
        # Display header
        panel_lines = [f"[bold cyan]Scribe v{__version__}[/bold cyan]"]
        panel_lines.append(f"[white]{transcript_file.name}[/white]")
        panel_lines.append(f"[dim]Generating: meme[/dim]")
        
        console.print(Panel.fit(
            "\n".join(panel_lines),
            border_style="cyan",
            padding=(0, 1)
        ))
        console.print()
        
        # Generate meme with progress
        from scribe.utils.meme_generator import generate_meeting_meme, MemeConfig
        from rich.progress import Progress, SpinnerColumn, TextColumn
        
        # Create meme config with spice level
        meme_config = MemeConfig.from_env()
        if spice is not None:
            if 0 <= spice <= 10:
                meme_config.spice_level = spice
            else:
                console.print(f"[bold yellow]Warning:[/bold yellow] Invalid spice level {spice} (must be 0-10), using default")
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("Generating meme...", total=None)
            if output:
                # Use specified output path
                meme_result = generate_meeting_meme(
                    transcript_file,
                    output_dir=output.parent if output.parent != Path('.') else None,
                    api_key=None,  # Let provider system choose the right key
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
                    api_key=None,  # Let provider system choose the right key
                    config=meme_config,
                    show_reasoning=show_reasoning
                )
                meme_path = meme_result["final_path"] if (meme_result and isinstance(meme_result, dict)) else meme_result
            
        
        console.print()
        
        if not meme_path:
            console.print("[bold yellow]Warning:[/bold yellow] Failed to generate meme")
            console.print("[dim]Check your OpenAI API key and try again[/dim]")
            raise typer.Exit(1)
        
        # Extract attempts info
        attempts = meme_result.get("attempts", []) if isinstance(meme_result, dict) else []
        best_score = meme_result.get("best_score") if isinstance(meme_result, dict) else None
        
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
    ),
    provider: Optional[str] = typer.Option(
        None,
        "--provider",
        help="AI provider to use (openai, xai)"
    )
):
    """
    Generate structured meeting notes from a transcript.
    
    Uses AI (OpenAI, XAI/Grok, etc.) to analyze the transcript and create comprehensive notes with:
    - Detailed summary
    - Current state (business & technical)
    - Drivers and blockers
    - Future state and next steps
    
    Example: scribe notes transcript.txt
    Example: scribe notes transcript.txt --output ./notes/meeting.md
    Example: scribe notes transcript.txt --provider xai
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
        
        # Display header
        panel_lines = [f"[bold cyan]Scribe v{__version__}[/bold cyan]"]
        panel_lines.append(f"[white]{transcript_file.name}[/white]")
        panel_lines.append(f"[dim]Generating: notes[/dim]")
        
        console.print(Panel.fit(
            "\n".join(panel_lines),
            border_style="cyan",
            padding=(0, 1)
        ))
        console.print()
        
        # Generate notes with progress
        from scribe.utils.notes_generator import NotesGenerator
        from rich.progress import Progress, SpinnerColumn, TextColumn
        
        notes_model = model or config.notes_model
        notes_generator = NotesGenerator(
            api_key=None,  # Let provider factory get the right key
            model=notes_model,
            provider_name=provider
        )
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[cyan]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            task = progress.add_task("Generating notes...", total=None)
            notes_path = notes_generator.generate_notes(transcript_file, output)
        
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


@app.command()
def clean(
    input_file: Path = typer.Argument(
        ...,
        help="Path to audio/video file to clean",
        exists=True
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output", "-o",
        help="Output path (default: input_cleaned.ext)"
    ),
    threshold: str = typer.Option(
        "-50dB",
        "--threshold", "-t",
        help="Silence threshold (e.g., -50dB, -40dB)"
    ),
    duration: float = typer.Option(
        2.0,
        "--duration", "-d",
        help="Minimum silence duration to remove (seconds)"
    ),
    analyze_only: bool = typer.Option(
        False,
        "--analyze", "-a",
        help="Only analyze silence, don't remove it"
    ),
    trim_to: Optional[str] = typer.Option(
        None,
        "--trim",
        help="Trim to specific time (e.g., '01:42:00' for 1h 42m, or '6120' for seconds)"
    )
):
    """
    Remove silence from audio/video files or trim to specific duration.
    
    Useful for cleaning up recordings left running overnight or with long pauses.
    Uses FFmpeg to detect and remove silent sections while preserving audio quality.
    
    Example: scribe clean long_recording.mp4
    Example: scribe clean recording.mp4 --threshold -40dB --duration 3.0
    Example: scribe clean recording.mp4 --analyze (just show how much silence)
    Example: scribe clean recording.mp4 --trim 01:42:00 (trim to 1h 42m)
    """
    try:
        from scribe.utils.silence_remover import remove_silence, analyze_silence, trim_file
        from scribe.utils.audio import get_audio_duration
        
        # Display header
        panel_lines = [f"[bold cyan]Scribe v{__version__}[/bold cyan]"]
        panel_lines.append(f"[white]{input_file.name}[/white]")
        
        # Get original duration
        original_duration = get_audio_duration(input_file)
        if original_duration:
            original_mins = int(original_duration / 60)
            panel_lines.append(f"[dim]Original duration: {original_mins} minutes ({original_duration:.1f}s)[/dim]")
        
        if trim_to:
            panel_lines.append(f"[dim]Mode: Trim to {trim_to}[/dim]")
        elif analyze_only:
            panel_lines.append(f"[dim]Mode: Analyze only[/dim]")
        else:
            panel_lines.append(f"[dim]Mode: Remove silence[/dim]")
            panel_lines.append(f"[dim]Threshold: {threshold}, Min duration: {duration}s[/dim]")
        
        console.print(Panel.fit(
            "\n".join(panel_lines),
            border_style="cyan",
            padding=(0, 1)
        ))
        console.print()
        
        # Handle trim mode
        if trim_to:
            console.print(f"[cyan]Trimming to {trim_to}...[/cyan]")
            console.print("[dim]This is fast - just copying, no re-encoding...[/dim]")
            console.print()
            
            output_path = trim_file(input_file, output, trim_to)
            
            # Get new duration
            new_duration = get_audio_duration(output_path)
            if new_duration:
                new_mins = int(new_duration / 60)
                new_hours = new_mins / 60
                
                console.print()
                console.print(f"[bold green]Success![/bold green]")
                console.print(f"  Original: {original_mins} minutes ({original_mins/60:.1f} hours)")
                console.print(f"  Trimmed:  {new_mins} minutes ({new_hours:.1f} hours)")
                console.print()
                console.print(f"[bold]Output:[/bold] {output_path}")
            else:
                console.print()
                console.print(f"[bold green]Success![/bold green]")
                console.print(f"[bold]Output:[/bold] {output_path}")
            
            return
        
        if analyze_only:
            # Just analyze
            console.print("[cyan]Analyzing silence...[/cyan]")
            analysis = analyze_silence(input_file, threshold, duration)
            
            console.print()
            console.print(f"[bold]Silence Analysis:[/bold]")
            console.print(f"  Total silence: {analysis['total_silence_minutes']:.1f} minutes ({analysis['total_silence_seconds']:.1f}s)")
            console.print(f"  Silent periods: {analysis['silence_periods']}")
            
            if analysis['silence_periods'] > 0:
                console.print()
                console.print(f"[dim]First few silent periods:[/dim]")
                for i, period in enumerate(analysis['periods'][:5], 1):
                    start_min = int(period['start'] / 60)
                    duration_sec = period['duration']
                    console.print(f"  {i}. At {start_min}m: {duration_sec:.1f}s of silence")
                
                if analysis['silence_periods'] > 5:
                    console.print(f"  ... and {analysis['silence_periods'] - 5} more")
            
            console.print()
            console.print(f"[green]To remove silence, run without --analyze flag[/green]")
            
        else:
            # Remove silence
            console.print("[cyan]Removing silence...[/cyan]")
            console.print("[dim]This may take a few minutes for large files...[/dim]")
            console.print()
            
            output_path = remove_silence(
                input_file,
                output,
                threshold,
                duration
            )
            
            # Get file sizes for comparison
            original_size = input_file.stat().st_size / (1024 * 1024)  # MB
            new_size = output_path.stat().st_size / (1024 * 1024)  # MB
            size_reduction = ((original_size - new_size) / original_size) * 100
            
            console.print()
            console.print(f"[bold green]Success![/bold green]")
            console.print(f"  Original size: {original_size:.1f} MB")
            console.print(f"  Cleaned size:  {new_size:.1f} MB")
            console.print(f"  Reduction:     {size_reduction:.1f}%")
            console.print()
            console.print(f"[dim]Note: Silent sections are reduced to near-silence.[/dim]")
            console.print(f"[dim]This makes transcription much faster as Whisper skips silent parts.[/dim]")
            console.print()
            console.print(f"[bold]Output:[/bold] {output_path}")
        
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[bold red]Unexpected error:[/bold red] {e}")
        logger.exception("Unexpected error in clean command")
        raise typer.Exit(1)


def main():
    """Main entry point with smart command detection."""
    import sys
    
    # If first argument looks like a file path, inject 'transcribe' command
    if len(sys.argv) > 1:
        first_arg = sys.argv[1]
        # Check if it's not a known command and looks like a file
        known_commands = ['transcribe', 'record', 'joke', 'meme', 'notes', 'clean', 'info', 'version', 'doctor', 'support-bundle', 'diagnose', '--help', '-h', '--version']
        if first_arg not in known_commands and not first_arg.startswith('-'):
            # Check if it looks like a file path
            if '.' in first_arg or '/' in first_arg or '\\' in first_arg or Path(first_arg).exists():
                # Insert 'transcribe' command
                sys.argv.insert(1, 'transcribe')
    
    app()


if __name__ == "__main__":
    main()
