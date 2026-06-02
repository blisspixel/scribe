"""
Main CLI interface for Scribe using Typer.

This module provides the command-line interface with commands for
transcription, recording, and system information.
"""

import time
import warnings
from pathlib import Path
from typing import Any, TypedDict

import typer
from rich.panel import Panel
from rich.table import Table

from scribe import __version__
from scribe.core.recorder import OBSRecorder
from scribe.core.transcriber import Transcriber
from scribe.exceptions import ProcessError, ScribeError, TranscriptionError
from scribe.models.config import ModelSize, ScribeConfig, TranscriptionMethod
from scribe.models.gpu import GPUConfig
from scribe.models.session import TranscriptionSession
from scribe.models.transcript import Transcript
from scribe.utils.branding import brand_header_markup
from scribe.utils.docx_converter import txt_to_docx
from scribe.utils.joke_generator import (
    ARCHETYPE_DISPLAY_NAMES,
    generate_transcript_joke,
)
from scribe.utils.logging import console, get_logger, setup_logging
from scribe.utils.theme import ScribeTheme
from scribe.utils.transcript_loader import is_supported_transcript_file, load_transcript_text
from scribe.utils.validation import sanitize_meeting_name, validate_file_path

# Suppress TorchAudio MP3 warnings
warnings.filterwarnings("ignore", message=".*MPEG_LAYER_III.*")

logger = get_logger(__name__)


class BatchResult(TypedDict, total=False):
    file: str
    status: str
    transcript: Path
    error: str


class MusicResult(TypedDict, total=False):
    file: str
    status: str
    lyrics: Path
    error: str


def _write_structured_outputs(
    transcriber: Transcriber,
    transcript_path: Path,
    config: ScribeConfig,
    format_override: str | None,
    session: TranscriptionSession | None = None,
) -> None:
    """Write the requested structured artifacts (json/vtt/srt/md) next to the .txt.

    Best-effort: a configured-but-empty format list, an absent structured transcript
    (some legacy API paths), or a writer error never fails the transcription.
    """
    try:
        transcript = transcriber.last_transcript
        if not isinstance(transcript, Transcript):
            return
        raw = format_override if format_override is not None else config.output_formats
        formats = [
            f.strip().lower()
            for f in str(raw).split(",")
            if f.strip() and f.strip().lower() != "txt"
        ]
        if not formats:
            return

        from scribe.utils.transcript_writers import write_formats

        for path in write_formats(transcript, transcript_path, formats):
            if session is not None:
                session.add_file(path, path.suffix.lstrip("."))
    except Exception as e:
        logger.warning(f"Could not write structured outputs: {e}")


# Create Typer app with custom help
# Using ScribeTheme colors for a modern, cohesive look


def _show_command_banner(console: Any) -> None:
    """Show animated banner + version before a command runs."""
    from scribe.utils.banner import show_banner

    if show_banner(console):
        console.print(f"  [{ScribeTheme.TEXT_MUTED}]{__version__}[/{ScribeTheme.TEXT_MUTED}]")
    else:
        console.print()
        console.print(
            f"{brand_header_markup('scribe', fallback_color=ScribeTheme.PRIMARY_BRIGHT)} "
            f"[{ScribeTheme.TEXT_MUTED}]{__version__}[/{ScribeTheme.TEXT_MUTED}]"
        )
    console.print()


# Custom help formatter that's minimal and clean
class CleanGroup(typer.core.TyperGroup):
    """Custom group with minimal, elite-tier help formatting."""

    def format_help(self, _: Any, __: Any) -> None:
        """Override to provide clean, minimal help."""
        from rich.console import Console

        console = Console()

        _show_command_banner(console)

        console.print()

        # Commands - simple aligned list
        cmds = [
            ("transcribe FILE  ", "transcribe audio/video"),
            ("url LINK         ", "transcribe from URL"),
            ("batch FILES      ", "process multiple files"),
            ("rec NAME         ", "record via OBS"),
            ("music FILE       ", "extract lyrics"),
            ("notes TRANSCRIPT ", "meeting notes"),
            ("joke TRANSCRIPT ", "generate joke"),
            ("meme TRANSCRIPT ", "generate meme"),
            ("query TEXT       ", "search transcripts"),
            ("vocab            ", "domain glossaries"),
            ("listen           ", "dictate (speech to type)"),
            ("say FILE         ", "read a file aloud"),
            ("doctor           ", "diagnostics"),
            ("info             ", "configuration"),
            ("help             ", "show this help"),
        ]

        for cmd, desc in cmds:
            console.print(
                f"  [{ScribeTheme.PRIMARY}]{cmd}[/{ScribeTheme.PRIMARY}][{ScribeTheme.TEXT_MUTED}]{desc}[/{ScribeTheme.TEXT_MUTED}]"
            )

        console.print()
        console.print(
            f"[{ScribeTheme.TEXT_MUTED}]scribe <cmd> -h for options[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print()


app = typer.Typer(
    name="scribe",
    cls=CleanGroup,
    add_completion=False,  # Remove shell completion clutter
    rich_markup_mode="rich",
    no_args_is_help=True,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command(name="transcribe")
def transcribe_command(
    audio_file: Path = typer.Argument(
        ..., help="Path to audio/video file to transcribe", exists=True
    ),
    method: TranscriptionMethod = typer.Option(
        "auto",
        "--method",
        "-m",
        help="Transcription method: auto (intelligent choice), local (GPU), openai (API)",
    ),
    model: ModelSize | None = typer.Option(
        None, "--model", help="Whisper model size (overrides config default)"
    ),
    language: str | None = typer.Option(
        None,
        "--language",
        "-l",
        help="Language (english, spanish, french, german, japanese, chinese, or ISO code)",
    ),
    no_docx: bool = typer.Option(False, "--no-docx", help="Skip DOCX document generation"),
    no_notes: bool = typer.Option(False, "--no-notes", help="Skip meeting notes generation"),
    keep_all: bool = typer.Option(
        False, "--keep-all", help="Keep all intermediate files (don't cleanup)"
    ),
    no_joke: bool = typer.Option(False, "--no-joke", help="Skip joke generation"),
    no_meme: bool = typer.Option(False, "--no-meme", help="Skip meme generation"),
    vocabulary: str | None = typer.Option(
        None,
        "--vocabulary",
        "--vocab",
        help="Glossary name (e.g. finance, tech) or a .txt/.json file for domain terms",
    ),
    output_format: str | None = typer.Option(
        None,
        "--format",
        help="Structured outputs alongside the .txt: json,vtt,srt,md (default: json)",
    ),
    diarize: bool | None = typer.Option(
        None,
        "--diarize/--no-diarize",
        help="Label speakers locally (needs HF_TOKEN and the scribe[diarize] extra)",
    ),
) -> None:
    """
    Transcribe an audio or video file.

    Examples:

      scribe transcribe meeting.mp4

      scribe transcribe interview.wav --method local --model large-v3

      scribe transcribe podcast.mp3 --method openai --language spanish

      scribe transcribe meeting.mp4 --no-joke --no-meme

      scribe transcribe technical.mp4 --vocabulary terms.txt
    """
    unified_progress = None
    try:
        from scribe.utils.vocabulary import CustomVocabulary

        # Load configuration
        config = ScribeConfig()

        # Override config with CLI options
        if model:
            config.default_model = model
        if language:
            # Validate language code
            from scribe.exceptions import ValidationError
            from scribe.utils.validation import validate_language_code

            try:
                validated_lang = validate_language_code(language)
                config.default_language = validated_lang
            except ValidationError as e:
                console.print(f"[red]Invalid language code: {language}[/red]")
                console.print(
                    "[dim]Use 2-letter ISO 639-1 codes (e.g., 'en', 'es', 'fr', 'de', 'zh', 'ja')[/dim]"
                )
                raise typer.Exit(1) from e
        if keep_all:
            config.keep_intermediate_files = True
        if diarize is not None:
            config.enable_speaker_diarization = diarize

        # Load custom vocabulary if provided
        custom_vocab = None
        if vocabulary:
            try:
                custom_vocab = CustomVocabulary.load(vocabulary)
                console.print(f"[cyan]Loaded {len(custom_vocab)} custom vocabulary terms[/cyan]")
                console.print()
            except Exception as e:
                console.print(f"[red]Failed to load vocabulary: {e}[/red]")
                raise typer.Exit(1) from e

        # Validate audio file first
        audio_path = validate_file_path(str(audio_file))

        # Setup logging
        meeting_name = audio_file.stem
        setup_logging(meeting_name, config.log_folder)

        # Get audio duration for progress estimation
        from scribe.utils.audio import get_audio_duration

        audio_duration = get_audio_duration(audio_path)
        duration_mins = int(audio_duration / 60) if audio_duration else 0

        # Check what features are actually enabled
        has_api_key = bool(config.openai_api_key)
        will_generate_notes = not no_notes and config.enable_notes and has_api_key
        will_generate_joke = not no_joke and config.enable_joke and has_api_key
        will_generate_meme = not no_meme and config.enable_meme and has_api_key
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
        _show_command_banner(console)
        panel_lines = [
            f"[{ScribeTheme.TEXT_PRIMARY}]{audio_file.name}[/{ScribeTheme.TEXT_PRIMARY}]"
        ]

        details = []
        if duration_mins:
            details.append(f"{duration_mins} min")
        details.append(" · ".join(outputs))
        panel_lines.append(
            f"[{ScribeTheme.TEXT_MUTED}]{' · '.join(details)}[/{ScribeTheme.TEXT_MUTED}]"
        )

        console.print(
            Panel.fit("\n".join(panel_lines), border_style=ScribeTheme.PRIMARY_DIM, padding=(0, 1))
        )
        console.print()

        # Initialize unified progress with adaptive performance tracking
        import hashlib
        import platform

        from scribe.utils.unified_progress import UnifiedProgress

        # Generate stable machine ID from hardware info
        machine_info = f"{platform.node()}-{platform.processor()}"
        machine_id = hashlib.md5(machine_info.encode()).hexdigest()[:16]

        unified_progress = UnifiedProgress(
            audio_duration, machine_id=machine_id, include_api_features=include_api_features
        )
        unified_progress.start()

        # Create session
        session = TranscriptionSession.create(meeting_name)
        session.add_file(audio_path, "source")

        # Determine transcription method (local GPU vs OpenAI API)
        transcriber = Transcriber(config)
        # Honor a configured default (SCRIBE_DEFAULT_METHOD / config.toml) when the
        # caller did not pass --method. An explicit --method always wins.
        effective_method = config.default_method if method == "auto" else method
        chosen_method = transcriber.choose_method(effective_method)

        if effective_method == "auto" and chosen_method == "openai":
            gpu_reason = getattr(
                getattr(transcriber, "gpu_config", None), "reason", "local GPU not detected"
            )
            console.print(f"[yellow]Auto-selected OpenAI[/yellow] [dim]({gpu_reason})[/dim]")
            console.print(
                "[dim]Run `scribe info` if you expected local faster-whisper on your GPU.[/dim]"
            )
            console.print()

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
                    progress_callback=lambda p: unified_progress.update_phase("preparing", p),
                )
                unified_progress.update_phase("preparing", 1.0)
            except ProcessError as e:
                console.print(f"[bold red]Conversion failed:[/bold red] {e}")
                console.print(
                    "[yellow]Tip: Check that ffmpeg is installed and the audio file is valid[/yellow]"
                )
                raise typer.Exit(1) from e
            except Exception as e:
                console.print(f"[bold red]Unexpected conversion error:[/bold red] {e}")
                raise typer.Exit(1) from e
        else:
            # OpenAI API accepts multiple formats but has 25MB limit
            try:
                file_size_mb = audio_path.stat().st_size / (1024 * 1024)
            except (FileNotFoundError, OSError) as e:
                console.print(f"[bold red]Error:[/bold red] Cannot access file: {audio_path}")
                raise typer.Exit(1) from e

            if file_size_mb > 24:
                # File too large - compress to MP3 with normalized audio
                console.print(
                    f"[yellow]File is {file_size_mb:.0f}MB (OpenAI limit is 25MB)[/yellow]"
                )
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
                        console.print(
                            f"[bold red]Error:[/bold red] Compressed file still too large ({compressed_size_mb:.1f}MB)"
                        )
                        console.print(
                            "[yellow]Tip: Try using local GPU transcription for very long recordings[/yellow]"
                        )
                        raise typer.Exit(1)

                    console.print(f"Converted to MP3 ({compressed_size_mb:.1f}MB)")
                except ProcessError as e:
                    console.print(f"[bold red]Conversion failed:[/bold red] {e}")
                    console.print(
                        "[yellow]Tip: Check that ffmpeg is installed and the audio file is valid[/yellow]"
                    )
                    raise typer.Exit(1) from e
                except Exception as e:
                    console.print(f"[bold red]Unexpected conversion error:[/bold red] {e}")
                    raise typer.Exit(1) from e
            else:
                # File size OK - use original audio file
                audio_file = audio_path
            console.print()

        # Phase 2: Transcribing (18-68%)
        unified_progress.update_phase("transcribing", 0.0)

        # Start a thread to update progress during transcription
        import threading

        transcription_done = threading.Event()

        def update_transcription_progress() -> None:
            while not transcription_done.is_set():
                unified_progress.refresh()
                time.sleep(unified_progress.frame_delay)

        progress_thread = threading.Thread(target=update_transcription_progress, daemon=True)
        progress_thread.start()

        try:
            transcript_path = transcriber.transcribe(
                audio_file, method=chosen_method, session=session, custom_vocabulary=custom_vocab
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

        # Write structured outputs (JSON/VTT/SRT/Markdown) alongside the .txt.
        _write_structured_outputs(transcriber, transcript_path, config, output_format, session)

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
                    provider_name=None,  # Will use SCRIBE_NOTES_PROVIDER env var
                )
                notes_path = notes_generator.generate_notes(transcript_path)
                session.add_file(notes_path, "notes")
            except Exception as e:
                logger.error(f"Notes generation failed: {e}")

        # Generate joke if enabled
        if not no_joke and config.enable_joke and config.openai_api_key:
            unified_progress.update_phase("finishing", 0.6, "Generating joke")
            result = generate_transcript_joke(transcript_path, config.openai_api_key)
            if result:
                joke_text, comedy_style = result

                # Save joke to session for later display
                session.joke_data = {"text": joke_text, "style": comedy_style}

        # Generate meme from transcript (enabled by default)
        if not no_meme and config.enable_meme and config.openai_api_key:
            from scribe.utils.meme_generator import generate_meeting_meme

            def meme_progress(attempt: int, max_attempts: int, score: float | None) -> None:
                """Update progress during meme generation"""
                if score is None:
                    unified_progress.update_phase(
                        "finishing", 0.8, f"Generating meme (attempt {attempt}/{max_attempts})"
                    )
                else:
                    unified_progress.update_phase(
                        "finishing",
                        0.8,
                        f"Refining meme (score: {score:.1f}/10, attempt {attempt}/{max_attempts})",
                    )

            unified_progress.update_phase("finishing", 0.8, "Generating meme")
            meme_result = generate_meeting_meme(
                transcript_path,
                output_dir=config.output_folder,
                api_key=None,  # Let provider system choose the right key
                progress_callback=meme_progress,
            )

            if meme_result:
                meme_path = (
                    meme_result["final_path"] if isinstance(meme_result, dict) else meme_result
                )
                session.add_file(meme_path, "meme")

        # Cleanup
        if not keep_all:
            unified_progress.update_phase("finishing", 0.95, "Cleaning up")
            transcriber.cleanup_intermediate_files(audio_path.parent)

        # Complete unified progress
        unified_progress.update_phase("finishing", 1.0)
        unified_progress.complete()

        # Complete session
        session.complete(success=True)
        session.save_summary(config.output_folder)
        console.print()

        # Display joke if generated
        if hasattr(session, "joke_data") and session.joke_data:
            joke_text = session.joke_data["text"]
            console.print(f"[bold cyan]Joke:[/bold cyan] {joke_text}")
            console.print()

        # Display output files with enhanced formatting
        console.print()
        console.print("[bold green]Transcription Complete![/bold green]")
        console.print()
        console.print("[bold cyan]Output Files:[/bold cyan]")
        console.print()

        # Helper function to create clickable file links that work on Windows, macOS, and Linux
        def make_clickable_path(file_path: Path) -> str:
            """Create a clickable file:// URL that works across platforms"""
            import platform
            import urllib.parse

            # Get absolute path
            abs_path = file_path.resolve()

            # Convert to string and handle platform differences
            path_str = str(abs_path)

            if platform.system() == "Windows":
                # Windows: file:///C:/Users/... (forward slashes, three slashes)
                # Convert backslashes to forward slashes
                path_str = path_str.replace("\\", "/")
                # Ensure it starts with drive letter
                if len(path_str) > 1 and path_str[1] == ":":
                    url = f"file:///{path_str}"
                else:
                    url = f"file:///{path_str}"
            else:
                # macOS/Linux: file:///home/... (already has leading slash)
                url = f"file://{urllib.parse.quote(path_str)}"

            return url

        # Show files with clickable links (works in Windows Terminal, iTerm2, VS Code terminal, etc.)
        if transcript_path:
            url = make_clickable_path(transcript_path)
            console.print(
                f"  [green]-[/green] [white]Transcript:[/white] [link={url}]{transcript_path}[/link]"
            )

        if not no_docx and session.docx_file:
            url = make_clickable_path(session.docx_file)
            console.print(
                f"  [green]-[/green] [white]Document:[/white]   [link={url}]{session.docx_file}[/link]"
            )

        if notes_path:
            url = make_clickable_path(notes_path)
            console.print(
                f"  [green]-[/green] [white]Notes:[/white]      [link={url}]{notes_path}[/link]"
            )

        if session.meme_file:
            url = make_clickable_path(session.meme_file)
            console.print(
                f"  [green]-[/green] [white]Meme:[/white]       [link={url}]{session.meme_file}[/link]"
            )

        console.print()

    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if e.context:
            console.print(f"[dim]Context: {e.context}[/dim]")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        raise typer.Exit(1) from e
    finally:
        if unified_progress is not None:
            unified_progress.stop()


@app.command(name="url")
def url_command(
    source_url: str = typer.Argument(
        ..., help="URL to download and transcribe (YouTube, Vimeo, direct links, etc.)"
    ),
    method: TranscriptionMethod = typer.Option(
        "auto",
        "--method",
        "-m",
        help="Transcription method: auto (intelligent choice), local (GPU), openai (API)",
    ),
    model: ModelSize | None = typer.Option(
        None, "--model", help="Whisper model size (overrides config default)"
    ),
    language: str | None = typer.Option(
        None,
        "--language",
        "-l",
        help="Language (english, spanish, french, german, japanese, chinese, or ISO code)",
    ),
    no_docx: bool = typer.Option(False, "--no-docx", help="Skip DOCX document generation"),
    no_notes: bool = typer.Option(False, "--no-notes", help="Skip meeting notes generation"),
    keep_all: bool = typer.Option(
        False, "--keep-all", help="Keep all intermediate files (don't cleanup)"
    ),
    no_joke: bool = typer.Option(False, "--no-joke", help="Skip joke generation"),
    no_meme: bool = typer.Option(False, "--no-meme", help="Skip meme generation"),
    vocabulary: str | None = typer.Option(
        None,
        "--vocabulary",
        "--vocab",
        help="Glossary name (e.g. finance, tech) or a .txt/.json file for domain terms",
    ),
    keep_download: bool = typer.Option(
        False, "--keep-download", help="Keep the downloaded file after transcription"
    ),
    cookies: str | None = typer.Option(
        None,
        "--cookies",
        help="Browser to extract cookies from (chrome, firefox, edge) — fixes YouTube 403 errors",
    ),
    output_format: str | None = typer.Option(
        None,
        "--format",
        help="Structured outputs alongside the .txt: json,vtt,srt,md (default: json)",
    ),
    diarize: bool | None = typer.Option(
        None,
        "--diarize/--no-diarize",
        help="Label speakers locally (needs HF_TOKEN and the scribe[diarize] extra)",
    ),
) -> None:
    """
    Download and transcribe audio/video from a URL.

    Supports YouTube, Vimeo, Twitter/X, direct media links, and 1000+ sites via yt-dlp.

    Examples:

      scribe url https://www.youtube.com/watch?v=dQw4w9WgXcQ

      scribe url https://vimeo.com/123456789 --method local

      scribe url https://example.com/podcast.mp3 --language es

      scribe url https://youtu.be/abc123 --no-joke --no-meme

      scribe url https://youtube.com/watch?v=xyz --keep-download
    """
    unified_progress = None
    downloaded_file = None
    config = None
    try:
        from scribe.core.downloader import URLDownloader
        from scribe.utils.validation import validate_media_url
        from scribe.utils.vocabulary import CustomVocabulary

        # Validate URL
        validated_url = validate_media_url(source_url)

        # Load configuration
        config = ScribeConfig()

        # Override config with CLI options
        if model:
            config.default_model = model
        if diarize is not None:
            config.enable_speaker_diarization = diarize
        if language:
            from scribe.exceptions import ValidationError
            from scribe.utils.validation import validate_language_code

            try:
                validated_lang = validate_language_code(language)
                config.default_language = validated_lang
            except ValidationError as e:
                console.print(f"[red]Invalid language code: {language}[/red]")
                console.print(
                    "[dim]Use 2-letter ISO 639-1 codes (e.g., 'en', 'es', 'fr', 'de', 'zh', 'ja')[/dim]"
                )
                raise typer.Exit(1) from e
        if keep_all:
            config.keep_intermediate_files = True

        # Override keep_downloads from CLI flag
        if keep_download:
            config.keep_downloads = True

        # Load custom vocabulary if provided
        custom_vocab = None
        if vocabulary:
            try:
                custom_vocab = CustomVocabulary.load(vocabulary)
                console.print(f"[cyan]Loaded {len(custom_vocab)} custom vocabulary terms[/cyan]")
                console.print()
            except Exception as e:
                console.print(f"[red]Failed to load vocabulary: {e}[/red]")
                raise typer.Exit(1) from e

        # Setup logging
        setup_logging("url_download", config.log_folder)

        # Show download panel
        _show_command_banner(console)
        console.print(
            Panel.fit(
                "\n".join(
                    [
                        f"[{ScribeTheme.TEXT_PRIMARY}]downloading...[/{ScribeTheme.TEXT_PRIMARY}]",
                        f"[{ScribeTheme.TEXT_MUTED}]{validated_url}[/{ScribeTheme.TEXT_MUTED}]",
                    ]
                ),
                border_style=ScribeTheme.PRIMARY_DIM,
                padding=(0, 1),
            )
        )
        console.print()

        # Download the media
        output_dir = config.download_folder or config.output_folder
        cookies_browser = cookies or config.cookies_from_browser
        downloader = URLDownloader(
            output_dir=output_dir,
            audio_only=config.download_audio_only,
            timeout=config.download_timeout,
            max_file_size_gb=config.max_file_size_gb,
            cookies_from_browser=cookies_browser,
        )

        with console.status(f"[{ScribeTheme.PRIMARY}]Downloading...[/{ScribeTheme.PRIMARY}]"):
            result = downloader.download(validated_url)

        downloaded_file = result.file_path
        meeting_name = sanitize_meeting_name(result.title)

        duration_str = ""
        if result.duration:
            mins = int(result.duration / 60)
            duration_str = f" ({mins} min)"

        console.print(f"[green]Downloaded:[/green] {result.title}{duration_str}")
        console.print(f"[dim]File: {downloaded_file}[/dim]")
        console.print()

        # Now run the standard transcription pipeline on the downloaded file
        audio_path = downloaded_file

        # Re-setup logging with the actual meeting name
        setup_logging(meeting_name, config.log_folder)

        # Get audio duration for progress estimation
        from scribe.utils.audio import get_audio_duration

        audio_duration = result.duration or get_audio_duration(audio_path)
        duration_mins = int(audio_duration / 60) if audio_duration else 0

        # Check what features are enabled
        has_api_key = bool(config.openai_api_key)
        will_generate_notes = not no_notes and config.enable_notes and has_api_key
        will_generate_joke = not no_joke and config.enable_joke and has_api_key
        will_generate_meme = not no_meme and config.enable_meme and has_api_key
        include_api_features = will_generate_notes or will_generate_joke or will_generate_meme

        outputs = ["transcript"]
        if will_generate_notes:
            outputs.append("notes")
        if will_generate_joke:
            outputs.append("joke")
        if will_generate_meme:
            outputs.append("meme")

        # Display transcription info
        panel_lines = [f"[{ScribeTheme.TEXT_PRIMARY}]{result.title}[/{ScribeTheme.TEXT_PRIMARY}]"]
        details = []
        if duration_mins:
            details.append(f"{duration_mins} min")
        details.append(" · ".join(outputs))
        panel_lines.append(
            f"[{ScribeTheme.TEXT_MUTED}]{' · '.join(details)}[/{ScribeTheme.TEXT_MUTED}]"
        )

        console.print(
            Panel.fit("\n".join(panel_lines), border_style=ScribeTheme.PRIMARY_DIM, padding=(0, 1))
        )
        console.print()

        # Initialize unified progress
        import hashlib
        import platform

        from scribe.utils.unified_progress import UnifiedProgress

        machine_info = f"{platform.node()}-{platform.processor()}"
        machine_id = hashlib.md5(machine_info.encode()).hexdigest()[:16]

        unified_progress = UnifiedProgress(
            audio_duration, machine_id=machine_id, include_api_features=include_api_features
        )
        unified_progress.start()

        # Create session
        session = TranscriptionSession.create(meeting_name)
        session.add_file(audio_path, "source")

        # Determine transcription method
        transcriber = Transcriber(config)
        effective_method = config.default_method if method == "auto" else method
        chosen_method = transcriber.choose_method(effective_method)

        # Phase 1: Preparing audio (0-15%)
        if chosen_method == "local":
            unified_progress.update_phase("preparing", 0.0)
            try:
                from scribe.core.converter import Converter

                converter = Converter()
                audio_file = converter.convert_to_wav(
                    audio_path,
                    show_progress=False,
                    progress_callback=lambda p: unified_progress.update_phase("preparing", p),
                )
                unified_progress.update_phase("preparing", 1.0)
            except ProcessError as e:
                console.print(f"[bold red]Conversion failed:[/bold red] {e}")
                raise typer.Exit(1) from e
            except Exception as e:
                console.print(f"[bold red]Unexpected conversion error:[/bold red] {e}")
                raise typer.Exit(1) from e
        else:
            try:
                file_size_mb = audio_path.stat().st_size / (1024 * 1024)
            except (FileNotFoundError, OSError) as e:
                console.print(f"[bold red]Error:[/bold red] Cannot access file: {audio_path}")
                raise typer.Exit(1) from e

            if file_size_mb > 24:
                console.print(
                    f"[yellow]File is {file_size_mb:.0f}MB (OpenAI limit is 25MB)[/yellow]"
                )
                console.print("[cyan]Converting to compressed MP3...[/cyan]")
                try:
                    from scribe.core.converter import Converter

                    converter = Converter()
                    audio_file = converter.convert_to_mp3(audio_path, bitrate=48)
                    compressed_size_mb = audio_file.stat().st_size / (1024 * 1024)
                    if compressed_size_mb > 24:
                        console.print(
                            f"[bold red]Error:[/bold red] Compressed file still too large ({compressed_size_mb:.1f}MB)"
                        )
                        raise typer.Exit(1)
                    console.print(f"Converted to MP3 ({compressed_size_mb:.1f}MB)")
                except ProcessError as e:
                    console.print(f"[bold red]Conversion failed:[/bold red] {e}")
                    raise typer.Exit(1) from e
                except Exception as e:
                    console.print(f"[bold red]Unexpected conversion error:[/bold red] {e}")
                    raise typer.Exit(1) from e
            else:
                audio_file = audio_path
            console.print()

        # Phase 2: Transcribing (18-68%)
        unified_progress.update_phase("transcribing", 0.0)

        import threading

        transcription_done = threading.Event()

        def update_transcription_progress() -> None:
            while not transcription_done.is_set():
                unified_progress.refresh()
                time.sleep(unified_progress.frame_delay)

        progress_thread = threading.Thread(target=update_transcription_progress, daemon=True)
        progress_thread.start()

        try:
            transcript_path = transcriber.transcribe(
                audio_file, method=chosen_method, session=session, custom_vocabulary=custom_vocab
            )
        finally:
            transcription_done.set()
            progress_thread.join(timeout=1.0)

        unified_progress.update_phase("transcribing", 1.0)

        if not transcript_path or not transcript_path.exists():
            console.print("[red]Error: Transcription failed - no output file created[/red]")
            raise typer.Exit(1)

        if transcript_path.stat().st_size < 10:
            console.print("[red]Error: Transcription failed - output file is empty[/red]")
            raise typer.Exit(1)

        # Write structured outputs (JSON/VTT/SRT/Markdown) alongside the .txt.
        _write_structured_outputs(transcriber, transcript_path, config, output_format, session)

        # Phase 3: Finishing (85-100%)
        unified_progress.update_phase("finishing", 0.0, "Creating DOCX")

        if not no_docx:
            try:
                docx_path = txt_to_docx(transcript_path)
                session.add_file(docx_path, "docx")
            except Exception as e:
                logger.error(f"DOCX generation failed: {e}")

        notes_path = None
        if not no_notes and config.enable_notes and config.openai_api_key:
            unified_progress.update_phase("finishing", 0.2, "Generating notes")
            try:
                from scribe.utils.notes_generator import NotesGenerator

                notes_generator = NotesGenerator(
                    api_key=None, model=config.notes_model, provider_name=None
                )
                notes_path = notes_generator.generate_notes(transcript_path)
                session.add_file(notes_path, "notes")
            except Exception as e:
                logger.error(f"Notes generation failed: {e}")

        if not no_joke and config.enable_joke and config.openai_api_key:
            unified_progress.update_phase("finishing", 0.6, "Generating joke")
            result_joke = generate_transcript_joke(transcript_path, config.openai_api_key)
            if result_joke:
                joke_text, comedy_style = result_joke
                session.joke_data = {"text": joke_text, "style": comedy_style}

        if not no_meme and config.enable_meme and config.openai_api_key:
            from scribe.utils.meme_generator import generate_meeting_meme

            def meme_progress(attempt: int, max_attempts: int, score: float | None) -> None:
                if score is None:
                    unified_progress.update_phase(
                        "finishing", 0.8, f"Generating meme (attempt {attempt}/{max_attempts})"
                    )
                else:
                    unified_progress.update_phase(
                        "finishing",
                        0.8,
                        f"Refining meme (score: {score:.1f}/10, attempt {attempt}/{max_attempts})",
                    )

            unified_progress.update_phase("finishing", 0.8, "Generating meme")
            meme_result = generate_meeting_meme(
                transcript_path,
                output_dir=config.output_folder,
                api_key=None,
                progress_callback=meme_progress,
            )
            if meme_result:
                meme_path = (
                    meme_result["final_path"] if isinstance(meme_result, dict) else meme_result
                )
                session.add_file(meme_path, "meme")

        # Cleanup intermediate transcription files
        if not keep_all:
            unified_progress.update_phase("finishing", 0.95, "Cleaning up")
            transcriber.cleanup_intermediate_files(audio_path.parent)

        unified_progress.update_phase("finishing", 1.0)
        unified_progress.complete()

        session.complete(success=True)
        session.save_summary(config.output_folder)
        console.print()

        if hasattr(session, "joke_data") and session.joke_data:
            joke_text = session.joke_data["text"]
            console.print(f"[bold cyan]Joke:[/bold cyan] {joke_text}")
            console.print()

        # Display output files
        console.print()
        console.print("[bold green]Transcription Complete![/bold green]")
        console.print(f"[dim]Source: {validated_url}[/dim]")
        console.print()
        console.print("[bold cyan]Output Files:[/bold cyan]")
        console.print()

        def make_clickable_path(file_path: Path) -> str:
            import platform
            import urllib.parse

            abs_path = file_path.resolve()
            path_str = str(abs_path)
            if platform.system() == "Windows":
                path_str = path_str.replace("\\", "/")
                url = f"file:///{path_str}"
            else:
                url = f"file://{urllib.parse.quote(path_str)}"
            return url

        if transcript_path:
            file_url = make_clickable_path(transcript_path)
            console.print(
                f"  [green]-[/green] [white]Transcript:[/white] [link={file_url}]{transcript_path}[/link]"
            )

        if not no_docx and session.docx_file:
            file_url = make_clickable_path(session.docx_file)
            console.print(
                f"  [green]-[/green] [white]Document:[/white]   [link={file_url}]{session.docx_file}[/link]"
            )

        if notes_path:
            file_url = make_clickable_path(notes_path)
            console.print(
                f"  [green]-[/green] [white]Notes:[/white]      [link={file_url}]{notes_path}[/link]"
            )

        if session.meme_file:
            file_url = make_clickable_path(session.meme_file)
            console.print(
                f"  [green]-[/green] [white]Meme:[/white]       [link={file_url}]{session.meme_file}[/link]"
            )

        console.print()

    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if e.context:
            console.print(f"[dim]Context: {e.context}[/dim]")
        raise typer.Exit(1) from e
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        raise typer.Exit(1) from e
    finally:
        if unified_progress is not None:
            unified_progress.stop()
        # Cleanup downloaded file unless user wants to keep it
        if (
            config is not None
            and not config.keep_downloads
            and downloaded_file
            and downloaded_file.exists()
        ):
            try:
                downloaded_file.unlink()
                logger.info(f"Cleaned up downloaded file: {downloaded_file}")
                parent = downloaded_file.parent
                if parent.name.startswith("scribe_dl_") and parent.exists():
                    import shutil

                    shutil.rmtree(parent, ignore_errors=True)
            except Exception as cleanup_err:
                logger.warning(f"Could not clean up download: {cleanup_err}")


@app.command()
def record(
    name: str | None = typer.Option(None, "--name", "-n", help="Meeting name for the recording"),
    auto_transcribe: bool = typer.Option(
        True,
        "--auto-transcribe/--no-auto-transcribe",
        help="Automatically transcribe after recording (default: True)",
    ),
    method: TranscriptionMethod = typer.Option(
        "auto", "--method", "-m", help="Transcription method (if auto-transcribe enabled)"
    ),
    no_joke: bool = typer.Option(False, "--no-joke", help="Skip joke generation"),
    no_meme: bool = typer.Option(False, "--no-meme", help="Skip meme generation"),
) -> None:
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
        _show_command_banner(console)

        # Show configuration settings
        settings_table = Table(title="Recording Settings", show_header=False, box=None)
        settings_table.add_column("Setting", style=ScribeTheme.PRIMARY, no_wrap=True)
        settings_table.add_column("Value", style=ScribeTheme.TEXT_PRIMARY)

        settings_table.add_row("Output Folder", str(config.output_folder))
        settings_table.add_row("Transcription", "Enabled (auto)" if auto_transcribe else "Disabled")
        settings_table.add_row("Max Recording", f"{config.max_recording_hours:.1f}h")
        if auto_transcribe:
            settings_table.add_row("Method", method.upper())
            settings_table.add_row("Model", config.default_model)
            settings_table.add_row("Language", config.default_language or "auto")

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

        console.print("\n[bold green]Recording Complete![/bold green]")
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
            effective_method = config.default_method if method == "auto" else method
            chosen_method = transcriber.choose_method(effective_method)

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
                    console.print(
                        "[yellow]Tip: Check that ffmpeg is installed and the recording file is valid[/yellow]"
                    )
                    raise typer.Exit(1)
                except Exception as e:
                    console.print(f"[bold red]Unexpected conversion error:[/bold red] {e}")
                    raise typer.Exit(1)
            else:
                # OpenAI API accepts multiple formats but has 25MB limit
                try:
                    file_size_mb = recording_path.stat().st_size / (1024 * 1024)
                except (FileNotFoundError, OSError):
                    console.print(
                        f"[bold red]Error:[/bold red] Cannot access recording file: {recording_path}"
                    )
                    raise typer.Exit(1)

                if file_size_mb > 24:
                    # File too large - compress to MP3 with normalized audio
                    console.print(
                        f"[yellow]File is {file_size_mb:.0f}MB (OpenAI limit is 25MB)[/yellow]"
                    )
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
                            console.print(
                                f"[bold red]Error:[/bold red] Compressed file still too large ({compressed_size_mb:.1f}MB)"
                            )
                            console.print(
                                "[yellow]Tip: Try using local GPU transcription for very long recordings[/yellow]"
                            )
                            raise typer.Exit(1)

                        console.print(f"Converted to MP3 ({compressed_size_mb:.1f}MB)")
                    except ProcessError as e:
                        console.print(f"[bold red]Conversion failed:[/bold red] {e}")
                        console.print(
                            "[yellow]Tip: Check that ffmpeg is installed and the recording file is valid[/yellow]"
                        )
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
                audio_file, method=chosen_method, session=session
            )

            # Structured sidecars (json/vtt/srt/md) so `scribe query` can find these too
            _write_structured_outputs(transcriber, transcript_path, config, None, session)

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
                        provider_name=None,  # Will use SCRIBE_NOTES_PROVIDER env var
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
            logger.info(
                f"Humor flags: no_joke={no_joke}, no_meme={no_meme}, has_api_key={bool(config.openai_api_key)}"
            )

            # Generate joke (enabled by default)
            if not no_joke and config.enable_joke:
                if config.openai_api_key:
                    try:
                        # Quiet spinner for joke generation
                        from scribe.utils.spinner import show_spinner

                        with show_spinner("Generating joke"):
                            result = generate_transcript_joke(
                                transcript_path, config.openai_api_key
                            )
                        if result:
                            joke_text, comedy_style = result

                            # Get proper archetype display name
                            style_display = ARCHETYPE_DISPLAY_NAMES.get(
                                comedy_style, comedy_style.replace("_", " ").title()
                            )

                            # Display joke cleanly: archetype name in cyan, joke in white
                            console.print()
                            console.print(f"[bold cyan]{style_display}:[/bold cyan]")
                            console.print(f"[white]{joke_text}[/white]")
                            console.print()

                            # Add joke to session summary
                            if summary_path:
                                import json

                                try:
                                    with open(summary_path, encoding="utf-8") as f:
                                        summary_data = json.load(f)
                                    summary_data["joke"] = {
                                        "text": joke_text,
                                        "style": comedy_style,
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
            if not no_meme and config.enable_meme:
                if config.openai_api_key:
                    try:
                        # Quiet spinner for meme generation
                        from scribe.utils.meme_generator import generate_meeting_meme
                        from scribe.utils.spinner import show_spinner

                        with show_spinner("Generating meme") as spinner:
                            meme_result = generate_meeting_meme(
                                transcript_path,
                                output_dir=config.output_folder,
                                api_key=None,  # Let provider system choose the right key
                            )
                            if meme_result and meme_result.get("final_path"):
                                spinner.complete()
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


@app.command(name="batch")
def batch_transcribe(
    input_files: list[Path] = typer.Argument(..., help="Audio/video files to transcribe"),
    method: TranscriptionMethod = typer.Option(
        "auto", "--method", "-m", help="Transcription method: auto, local, openai"
    ),
    model: ModelSize | None = typer.Option(None, "--model", help="Whisper model size"),
    language: str | None = typer.Option(
        None, "--language", "-l", help="Language (english, spanish, etc. or ISO code)"
    ),
    no_docx: bool = typer.Option(False, "--no-docx", help="Skip DOCX generation"),
    no_notes: bool = typer.Option(False, "--no-notes", help="Skip meeting notes"),
    no_joke: bool = typer.Option(False, "--no-joke", help="Skip joke generation"),
    no_meme: bool = typer.Option(False, "--no-meme", help="Skip meme generation"),
    vocabulary: str | None = typer.Option(
        None,
        "--vocabulary",
        "--vocab",
        help="Glossary name (e.g. finance, tech) or a .txt/.json file for domain terms",
    ),
    continue_on_error: bool = typer.Option(
        True,
        "--continue-on-error/--stop-on-error",
        help="Continue processing remaining files if one fails",
    ),
) -> None:
    """
    Batch transcribe multiple audio/video files.

    Process multiple recordings in one command. Each file is transcribed
    independently with its own output files.

    Examples:

      scribe batch meeting1.mp4 meeting2.mp4 meeting3.mp4

      scribe batch *.mp4 --method local

      scribe batch file1.wav file2.wav --vocabulary terms.txt

      scribe batch *.mp3 --no-joke --no-meme
    """
    try:
        from scribe.utils.vocabulary import CustomVocabulary

        # Load configuration
        config = ScribeConfig()

        # Override config with CLI options
        if model:
            config.default_model = model
        if language:
            from scribe.utils.validation import validate_language_code

            try:
                validated_lang = validate_language_code(language)
                config.default_language = validated_lang
            except Exception:
                console.print(f"[red]Invalid language code: {language}[/red]")
                raise typer.Exit(1)

        # Load custom vocabulary if provided
        custom_vocab = None
        if vocabulary:
            try:
                custom_vocab = CustomVocabulary.load(vocabulary)
                console.print(f"[cyan]Loaded {len(custom_vocab)} custom vocabulary terms[/cyan]")
            except Exception as e:
                console.print(f"[red]Failed to load vocabulary: {e}[/red]")
                raise typer.Exit(1)

        # Validate all files exist
        valid_files = []
        for audio_file in input_files:
            if not audio_file.exists():
                console.print(f"[yellow]Warning: File not found: {audio_file}[/yellow]")
                if not continue_on_error:
                    raise typer.Exit(1)
            else:
                valid_files.append(audio_file)

        if not valid_files:
            console.print("[red]No valid files to process[/red]")
            raise typer.Exit(1)

        # Display batch header
        _show_command_banner(console)
        console.print(
            Panel.fit(
                f"[white]{len(valid_files)} file(s)[/white]", border_style="cyan", padding=(0, 1)
            )
        )
        console.print()

        # Process each file
        results: list[BatchResult] = []
        for idx, audio_file in enumerate(valid_files, 1):
            # Bound before the try so the except handler never hits an unbound
            # logger if validation fails before per-file setup_logging runs.
            logger = get_logger(__name__)
            console.print(
                f"[bold cyan]File {idx}/{len(valid_files)}:[/bold cyan] {audio_file.name}"
            )
            console.print()

            try:
                # Validate audio file
                audio_path = validate_file_path(str(audio_file))

                # Setup logging
                meeting_name = audio_file.stem
                logger = setup_logging(meeting_name, config.log_folder)

                # Create session
                session = TranscriptionSession.create(meeting_name)
                session.add_file(audio_path, "source")

                # Transcribe
                transcriber = Transcriber(config)
                effective_method = config.default_method if method == "auto" else method
                chosen_method = transcriber.choose_method(effective_method)

                # Convert audio if needed
                if chosen_method == "local":
                    from scribe.core.converter import Converter

                    converter = Converter()
                    audio_file_converted = converter.convert_to_wav(audio_path, show_progress=True)
                else:
                    # Check file size for OpenAI API
                    file_size_mb = audio_path.stat().st_size / (1024 * 1024)
                    if file_size_mb > 24:
                        console.print(
                            f"[yellow]File is {file_size_mb:.0f}MB, compressing...[/yellow]"
                        )
                        from scribe.core.converter import Converter

                        converter = Converter()
                        audio_file_converted = converter.convert_to_mp3(audio_path, bitrate=48)
                    else:
                        audio_file_converted = audio_path

                # Transcribe with custom vocabulary
                transcript_path = transcriber.transcribe(
                    audio_file_converted,
                    method=chosen_method,
                    session=session,
                    custom_vocabulary=custom_vocab,
                )

                # Structured sidecars (json/vtt/srt/md) so `scribe query` finds batch output
                _write_structured_outputs(transcriber, transcript_path, config, None, session)

                # Generate DOCX
                if not no_docx:
                    try:
                        docx_path = txt_to_docx(transcript_path)
                        session.add_file(docx_path, "docx")
                    except Exception as e:
                        logger.error(f"DOCX generation failed: {e}")

                # Generate notes
                if not no_notes and config.enable_notes and config.openai_api_key:
                    try:
                        from scribe.utils.notes_generator import NotesGenerator

                        notes_generator = NotesGenerator(api_key=None, model=config.notes_model)
                        notes_path = notes_generator.generate_notes(transcript_path)
                        session.add_file(notes_path, "notes")
                    except Exception as e:
                        logger.error(f"Notes generation failed: {e}")

                # Generate joke
                if not no_joke and config.enable_joke and config.openai_api_key:
                    try:
                        joke_result = generate_transcript_joke(
                            transcript_path, config.openai_api_key
                        )
                        if joke_result:
                            joke_text, comedy_style = joke_result
                            session.joke_data = {"text": joke_text, "style": comedy_style}
                    except Exception as e:
                        logger.error(f"Joke generation failed: {e}")

                # Generate meme
                if not no_meme and config.enable_meme and config.openai_api_key:
                    try:
                        from scribe.utils.meme_generator import generate_meeting_meme

                        meme_result = generate_meeting_meme(
                            transcript_path, output_dir=config.output_folder, api_key=None
                        )
                        if meme_result:
                            meme_path = (
                                meme_result["final_path"]
                                if isinstance(meme_result, dict)
                                else meme_result
                            )
                            session.add_file(meme_path, "meme")
                    except Exception as e:
                        logger.error(f"Meme generation failed: {e}")

                # Cleanup
                transcriber.cleanup_intermediate_files(audio_path.parent)

                # Complete session
                session.complete(success=True)
                session.save_summary(config.output_folder)

                results.append(
                    {"file": audio_file.name, "status": "success", "transcript": transcript_path}
                )

                console.print(f"[green]✓ Completed: {audio_file.name}[/green]")
                console.print()

            except Exception as e:
                logger.error(f"Failed to process {audio_file}: {e}")
                results.append({"file": audio_file.name, "status": "failed", "error": str(e)})
                console.print(f"[red]✗ Failed: {audio_file.name}[/red]")
                console.print(f"[dim]Error: {e}[/dim]")
                console.print()

                if not continue_on_error:
                    raise typer.Exit(1)

        # Summary
        console.print("─" * 60)
        console.print()
        console.print("[bold cyan]Batch Summary:[/bold cyan]")

        success_count = sum(1 for r in results if r["status"] == "success")
        failed_count = sum(1 for r in results if r["status"] == "failed")

        console.print(f"  [green]✓ Successful:[/green] {success_count}")
        console.print(f"  [red]✗ Failed:[/red] {failed_count}")
        console.print()

        if failed_count > 0:
            console.print("[yellow]Failed files:[/yellow]")
            for batch_result in results:
                if batch_result["status"] == "failed":
                    console.print(
                        f"  - {batch_result['file']}: {batch_result.get('error', 'Unknown error')}"
                    )
            console.print()

    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        raise typer.Exit(1)


@app.command(name="music")
def music_transcribe(
    audio_files: list[Path] = typer.Argument(
        ..., help="Path to music/audio file(s) or folder to transcribe"
    ),
    method: TranscriptionMethod = typer.Option(
        "auto", "--method", "-m", help="Transcription method: auto, local, openai"
    ),
    model: ModelSize | None = typer.Option(None, "--model", help="Whisper model size"),
    language: str | None = typer.Option(
        None, "--language", "-l", help="Language (english, spanish, etc. or ISO code)"
    ),
    continue_on_error: bool = typer.Option(
        True,
        "--continue-on-error/--stop-on-error",
        help="Continue processing remaining files if one fails",
    ),
) -> None:
    """
    Transcribe music/lyrics with clean formatting.

    Supports single files, multiple files, wildcards, or folders.

    Optimized for music transcription with:
    - Clean lyrics-only output (no timestamps)
    - Graceful handling of instrumental tracks
    - No jokes, memes, or meeting notes by default
    - Simple TXT output format
    - Lyrics files saved next to original MP3s

    Examples:

      scribe music song.mp3

      scribe music album/*.flac --method local

      scribe music folder/

      scribe music track1.mp3 track2.mp3 track3.mp3
    """
    # Bound up front so the outer except never hits an unbound logger if an error
    # occurs before the per-track setup_logging runs.
    logger = get_logger(__name__)
    try:
        # Load configuration
        config = ScribeConfig()

        # Override config with CLI options
        if model:
            config.default_model = model
        if language:
            from scribe.utils.validation import validate_language_code

            try:
                validated_lang = validate_language_code(language)
                config.default_language = validated_lang
            except Exception:
                console.print(f"[red]Invalid language code: {language}[/red]")
                raise typer.Exit(1)
        else:
            # For music mode, enable auto-detection by default
            # Language will be detected per-segment after vocal separation
            config.default_language = None

        # Collect all audio files to process
        files_to_process: list[Path] = []
        for path in audio_files:
            if not path.exists():
                console.print(f"[yellow]Warning: Path not found: {path}[/yellow]")
                if not continue_on_error:
                    raise typer.Exit(1)
                continue

            if path.is_dir():
                # Process all audio files in directory
                audio_extensions = {".mp3", ".flac", ".wav", ".m4a", ".ogg", ".opus"}
                dir_files = [
                    f
                    for f in path.iterdir()
                    if f.suffix.lower() in audio_extensions
                    and not f.stem.endswith("_vocals")  # Skip intermediate vocals files
                    and not f.stem.endswith("_16k_mono")  # Skip converted WAV files
                ]
                files_to_process.extend(dir_files)
            else:
                # Skip intermediate files
                if not path.stem.endswith("_vocals") and not path.stem.endswith("_16k_mono"):
                    files_to_process.append(path)

        if not files_to_process:
            console.print("[red]No audio files to process[/red]")
            raise typer.Exit(1)

        # Show summary
        console.print()
        console.print(f"[bold cyan]Processing {len(files_to_process)} audio file(s)[/bold cyan]")
        console.print()

        # Create transcriber once for all files
        transcriber = Transcriber(config)

        # Process each file
        results: list[MusicResult] = []
        for idx, audio_path in enumerate(files_to_process, 1):
            track_name = audio_path.stem
            vocals_path = None  # Initialize for cleanup in exception handler
            vocal_segments: list[dict[str, float]] | None = None

            try:
                # Setup logging for this track
                logger = setup_logging(track_name, config.log_folder)

                # Display header
                from scribe.utils.audio import format_duration, get_audio_duration

                duration = get_audio_duration(audio_path)
                if not duration:
                    raise ValueError(
                        "Could not read audio duration (invalid or unsupported audio file)"
                    )
                duration_str = format_duration(duration) if duration else "Unknown"

                console.print(
                    f"[bold]File {idx}/{len(files_to_process)}:[/bold] {audio_path.name} [dim]({duration_str})[/dim]"
                )

                # Step 1: Analyze music content and extract metadata
                console.print("  [dim]Analyzing music...[/dim]", end="")
                music_metadata: dict[str, Any] = {}
                try:
                    from scribe.utils.music_detection import MusicDetector

                    detector = MusicDetector()
                    music_analysis = detector.analyze_music(audio_path)
                    music_metadata = music_analysis.get("metadata", {})

                    if not music_analysis["is_music"]:
                        # Not music - skip processing
                        console.print(" [red]not music[/red]")
                        console.print(f"  [dim]{music_analysis['reason']}[/dim]")
                        console.print()
                        results.append(
                            {"file": audio_path.name, "status": "failed", "error": "Not music"}
                        )
                        continue

                    tempo = music_metadata.get("tempo")
                    key = music_metadata.get("key", "?")

                    # Only show measurable values
                    info_parts = []
                    if isinstance(tempo, (int, float)) and tempo > 0:
                        info_parts.append(f"[green]{tempo:.0f} BPM[/green]")
                    if key and key != "Unknown":
                        info_parts.append(f"[dim]{key}[/dim]")

                    if info_parts:
                        console.print(f" {' '.join(info_parts)}")
                    else:
                        console.print(" [green]ok[/green]")
                except Exception as e:
                    logger.debug(f"Music analysis failed: {e}")
                    console.print(" [yellow]skipped[/yellow]")

                # Step 2: Separate vocals from instruments
                console.print("  [dim]Separating vocals...[/dim]", end="")
                try:
                    from scribe.utils.source_separation import separate_vocals

                    vocals_path = separate_vocals(audio_path)
                    console.print(" [green]done[/green]")
                except Exception as e:
                    console.print(" [yellow]skipped[/yellow]")
                    logger.warning(f"Vocal separation failed, using original audio: {e}")
                    vocals_path = audio_path

                # Step 3: Detect vocal segments using VAD
                console.print("  [dim]Detecting vocals...[/dim]", end="")
                try:
                    from scribe.utils.vad import detect_vocal_segments

                    vocal_segments = detect_vocal_segments(vocals_path)

                    if not vocal_segments:
                        # No vocals detected - it's instrumental music
                        console.print(" [yellow]none found[/yellow]")
                        raise TranscriptionError("No speech detected in audio (instrumental track)")

                    console.print(f" [green]found {len(vocal_segments)}[/green]")
                except Exception as e:
                    if "No speech detected" in str(e) or not vocal_segments:
                        raise TranscriptionError("No speech detected in audio (instrumental track)")
                    logger.warning(f"VAD failed, will transcribe full audio: {e}")
                    vocal_segments = None

                # Step 4: Slice audio by vocal segments
                console.print("  [dim]Slicing audio...[/dim]", end="")
                try:
                    import tempfile

                    from scribe.utils.audio_slicer import slice_audio_by_segments

                    # Create temp directory for slices
                    slice_dir = Path(tempfile.mkdtemp(prefix="vocal_slices_"))
                    if vocal_segments is None:
                        raise ValueError("No vocal segments available for slicing")
                    sliced_paths = slice_audio_by_segments(vocals_path, vocal_segments, slice_dir)
                    console.print(f" [green]{len(sliced_paths)} slices[/green]")
                except Exception as e:
                    logger.warning(f"Audio slicing failed, will transcribe full audio: {e}")
                    sliced_paths = None
                    slice_dir = None

                # Step 5: Transcribe segments
                console.print("  [dim]Transcribing...[/dim]", end="")
                try:
                    all_lyrics = []

                    if sliced_paths:
                        # Transcribe each segment separately
                        for i, slice_path in enumerate(sliced_paths):
                            try:
                                segment_transcript = transcriber.transcribe(
                                    slice_path, method=method, music_mode=True
                                )

                                # Read segment transcript
                                with open(segment_transcript, encoding="utf-8") as f:
                                    segment_text = f.read()

                                # Extract just the text (remove metadata)
                                if "─" in segment_text:
                                    parts = segment_text.split("─" * 80, 1)
                                    if len(parts) > 1:
                                        segment_text = parts[1].strip()
                                    else:
                                        segment_text = segment_text.strip()
                                else:
                                    segment_text = segment_text.strip()

                                # Filter out hallucinations from segment
                                if segment_text:
                                    segment_lower = segment_text.lower().strip()

                                    # Known hallucination patterns
                                    hallucination_phrases = [
                                        "suscríbete",
                                        "gracias por ver",
                                        "thanks for watching",
                                        "please subscribe",
                                        "amara.org",
                                        "subtitle",
                                        "caption",
                                    ]

                                    # Skip if it's a known hallucination
                                    is_hallucination = any(
                                        phrase in segment_lower for phrase in hallucination_phrases
                                    )

                                    if not is_hallucination:
                                        all_lyrics.append(segment_text)

                                # Clean up segment transcript
                                segment_transcript.unlink()

                            except Exception as e:
                                logger.debug(f"Segment {i + 1} transcription failed: {e}")
                                continue

                        # Combine all segments
                        lyrics = "\n\n".join(all_lyrics)

                        # Clean up sliced audio files
                        if slice_dir and slice_dir.exists():
                            import shutil

                            shutil.rmtree(slice_dir, ignore_errors=True)
                    else:
                        # Fallback: transcribe full audio
                        transcript_path = transcriber.transcribe(
                            vocals_path, method=method, music_mode=True
                        )

                        with open(transcript_path, encoding="utf-8") as f:
                            transcript_content = f.read()

                        # Extract just the lyrics part
                        if "─" in transcript_content:
                            parts = transcript_content.split("─" * 80, 1)
                            if len(parts) > 1:
                                lyrics = parts[1].strip()
                            else:
                                lyrics = transcript_content.strip()
                        else:
                            lyrics = transcript_content.strip()

                        # Clean up transcript
                        if transcript_path.exists():
                            transcript_path.unlink()

                    console.print(" [green]done[/green]")

                    # Clean up intermediate files immediately after transcription
                    # 1. Converted WAV file (created by converter)
                    wav_file = audio_path.parent / f"{track_name}_16k_mono.wav"
                    if wav_file.exists() and wav_file != audio_path:
                        wav_file.unlink()
                        logger.debug(f"Cleaned up converted WAV: {wav_file.name}")

                    # 2. Separated vocals file (created by demucs)
                    vocals_file = audio_path.parent / f"{track_name}_vocals.wav"
                    if vocals_file.exists() and vocals_file != audio_path:
                        vocals_file.unlink()
                        logger.debug(f"Cleaned up separated vocals: {vocals_file.name}")

                    # Create clean lyrics file
                    lyrics_path = audio_path.parent / f"{track_name}_lyrics.txt"
                    lyrics_path.parent.mkdir(parents=True, exist_ok=True)

                    # Smart hallucination detection for instrumental music
                    # Whisper sometimes generates common phrases when there's no actual speech

                    # Known Whisper hallucination patterns
                    hallucination_patterns = {
                        # YouTube/video watermarks (English)
                        "thank you for watching",
                        "thanks for watching",
                        "please subscribe",
                        "like and subscribe",
                        "don't forget to subscribe",
                        # YouTube/video watermarks (Spanish)
                        "suscríbete al canal",
                        "suscríbete",
                        "dale like",
                        "gracias por ver",
                        "no olvides suscribirte",
                        # YouTube/video watermarks (Portuguese)
                        "inscreva-se no canal",
                        "inscreva-se",
                        "deixe seu like",
                        # Transcription service watermarks
                        "transcription by castingwords",
                        "high-quality transcription",
                        "transcribed by",
                        "subtítulos realizados por",
                        "subtitles by",
                        "amara.org",
                        # Generic filler
                        "we'll be right back",
                        "thank you",
                        "thanks",
                        # Music-specific hallucinations
                        "music playing",
                        "music",
                    }

                    lyrics_lower = lyrics.lower().strip()
                    word_count = len(lyrics.split())
                    line_count = len([line for line in lyrics.split("\n") if line.strip()])

                    # Check if entire transcript matches a hallucination pattern
                    is_exact_hallucination = lyrics_lower in hallucination_patterns

                    # Check if transcript contains hallucination phrases
                    has_hallucination_phrase = any(
                        phrase in lyrics_lower for phrase in hallucination_patterns
                    )

                    # Hallucination detection logic:
                    # 1. Exact match to known hallucination → instrumental
                    # 2. Very short (< 3 words) → likely hallucination
                    # 3. Short (< 10 words) + contains hallucination phrase → instrumental
                    # 4. Single line + hallucination phrase → instrumental
                    # 5. Otherwise → keep it (could be valid sparse lyrics)

                    is_hallucination = (
                        is_exact_hallucination
                        or word_count < 3
                        or (word_count < 10 and has_hallucination_phrase)
                        or (line_count == 1 and has_hallucination_phrase)
                    )

                    if is_hallucination:
                        logger.debug(
                            f"Detected hallucination: '{lyrics[:50]}...' ({word_count} words)"
                        )
                        lyrics = "[Instrumental - No Speech Detected]"

                    # Reuse metadata from initial analysis (no need to analyze again)
                    metadata = music_metadata

                    # Write clean lyrics file with metadata header
                    with open(lyrics_path, "w", encoding="utf-8") as f:
                        # Write metadata header (only measurable facts)
                        f.write(f"Track: {audio_path.stem}\n")
                        if metadata:
                            duration_formatted = metadata.get("duration_formatted")
                            if duration_formatted:
                                f.write(f"Duration: {duration_formatted}\n")
                            tempo_value = metadata.get("tempo")
                            if isinstance(tempo_value, (int, float)) and tempo_value > 0:
                                f.write(f"Tempo: {tempo_value:.0f} BPM\n")
                            key_value = metadata.get("key")
                            if isinstance(key_value, str) and key_value != "Unknown":
                                f.write(f"Key: {key_value}\n")
                        f.write("\n")

                        # Write lyrics
                        f.write(lyrics + "\n")

                    # Report status based on content
                    if lyrics == "[Instrumental - No Speech Detected]":
                        console.print(f"  [yellow]INST[/yellow] Instrumental: {lyrics_path.name}")
                        results.append(
                            {
                                "file": audio_path.name,
                                "status": "instrumental",
                                "lyrics": lyrics_path,
                            }
                        )
                    else:
                        console.print(f"  [green]OK[/green] Lyrics: {lyrics_path.name}")
                        results.append(
                            {"file": audio_path.name, "status": "success", "lyrics": lyrics_path}
                        )

                    console.print()

                except TranscriptionError as e:
                    # Check if it's instrumental (no speech detected)
                    if "No speech detected" in str(e) or "instrumental" in str(e).lower():
                        console.print("  [dim]Cleaning up...[/dim]", end="")

                        # Clean up intermediate files
                        # 1. Converted WAV file
                        wav_file = audio_path.parent / f"{track_name}_16k_mono.wav"
                        if wav_file.exists() and wav_file != audio_path:
                            wav_file.unlink()
                            logger.debug(f"Cleaned up converted WAV: {wav_file.name}")

                        # 2. Separated vocals file (use vocals_path directly)
                        if vocals_path and vocals_path.exists() and vocals_path != audio_path:
                            vocals_path.unlink()
                            logger.debug(f"Cleaned up separated vocals: {vocals_path.name}")

                        console.print(" [green]done[/green]")

                        # Reuse music metadata from initial analysis
                        metadata = music_metadata

                        # Create instrumental marker file with metadata
                        lyrics_path = audio_path.parent / f"{track_name}_lyrics.txt"
                        lyrics_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(lyrics_path, "w", encoding="utf-8") as f:
                            # Write metadata header
                            f.write(f"Track: {audio_path.stem}\n")
                            if metadata:
                                duration_formatted = metadata.get("duration_formatted")
                                if duration_formatted:
                                    f.write(f"Duration: {duration_formatted}\n")
                                tempo_value = metadata.get("tempo")
                                if isinstance(tempo_value, (int, float)):
                                    f.write(f"Tempo: {tempo_value:.0f} BPM\n")
                                key_value = metadata.get("key")
                                if key_value:
                                    f.write(f"Key: {key_value}\n")
                                genre_hints = metadata.get("genre_hints")
                                if isinstance(genre_hints, list):
                                    f.write(
                                        f"Style: {', '.join(str(hint) for hint in genre_hints)}\n"
                                    )
                            f.write("\n")
                            f.write("[Instrumental - No Speech Detected]\n")

                        console.print(f"  [yellow]INST[/yellow] Instrumental: {lyrics_path.name}")
                        console.print()

                        results.append(
                            {
                                "file": audio_path.name,
                                "status": "instrumental",
                                "lyrics": lyrics_path,
                            }
                        )
                    else:
                        raise

            except Exception as e:
                # Check if it's instrumental (expected, not an error)
                if "No speech detected" in str(e) or "instrumental" in str(e).lower():
                    # Clean up intermediate files
                    wav_file = audio_path.parent / f"{track_name}_16k_mono.wav"
                    if wav_file.exists() and wav_file != audio_path:
                        wav_file.unlink()

                    if vocals_path and vocals_path.exists() and vocals_path != audio_path:
                        vocals_path.unlink()

                    console.print("  [yellow]INST[/yellow] Instrumental (no vocals detected)")
                    console.print()
                    results.append({"file": audio_path.name, "status": "instrumental"})
                else:
                    # Actual failure
                    logger.error(f"Failed to process {audio_path.name}: {e}")
                    console.print(f"  [red]FAIL[/red] Failed: {e}")
                    console.print()
                    results.append({"file": audio_path.name, "status": "failed", "error": str(e)})

                if not continue_on_error:
                    raise typer.Exit(1)

        # Print summary
        console.print()
        console.print("[bold]Summary:[/bold]")
        success_count = sum(1 for r in results if r["status"] == "success")
        instrumental_count = sum(1 for r in results if r["status"] == "instrumental")
        failed_count = sum(1 for r in results if r["status"] == "failed")

        console.print(f"  [green]With Lyrics:[/green] {success_count}")
        console.print(f"  [yellow]Instrumental:[/yellow] {instrumental_count}")
        console.print(f"  [red]Failed:[/red] {failed_count}")
        console.print()

        if failed_count > 0:
            console.print("[yellow]Failed files:[/yellow]")
            for result in results:
                if result["status"] == "failed":
                    console.print(f"  - {result['file']}: {result.get('error', 'Unknown error')}")
            console.print()

    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        logger.exception("Unexpected error in music transcription")
        raise typer.Exit(1)


@app.command(name="rec")
def rec_shortcut(name: str | None = typer.Argument(None, help="Meeting name (optional)")) -> None:
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
        ..., help="Path to transcript file (.txt, .md, .docx)", exists=True
    ),
    spice: int | None = typer.Option(
        None, "--spice", help="Humor intensity 0-10 (0=off, 5=default, 10=spicy)"
    ),
    archetype: str | None = typer.Option(
        None,
        "--archetype",
        help="Force specific comedy archetype (translator, trickster, fool_scholar, etc.)",
    ),
    provider: str | None = typer.Option(
        None, "--provider", help="AI provider to use (openai, xai, gemini, anthropic)"
    ),
    bakeoff: bool = typer.Option(
        None,
        "--bakeoff/--no-bakeoff",
        help="Run joke bake-off across all providers (default: from env SCRIBE_ENABLE_JOKE_BAKEOFF)",
    ),
) -> None:
    """
    Generate an agentic AI joke about a transcript.

    Analyzes the transcript and generates context-aware humor using
    sophisticated comedy archetypes designed for post-meeting cognitive
    decompression.

    Example: scribe joke transcript.txt
    """
    try:
        # Validate file is a text file
        if not is_supported_transcript_file(transcript_file):
            console.print(
                "[bold red]Error:[/bold red] File must be a text file (.txt, .md, or .docx transcript)"
            )
            raise typer.Exit(1)

        config = ScribeConfig()

        if not config.openai_api_key:
            console.print("[bold red]Error:[/bold red] OpenAI API key not configured")
            console.print("[dim]Set SCRIBE_OPENAI_API_KEY in your .env file[/dim]")
            raise typer.Exit(1)

        # Display header
        _show_command_banner(console)
        panel_lines = [f"[white]{transcript_file.name}[/white]"]
        panel_lines.append("[dim]joke[/dim]")

        console.print(Panel.fit("\n".join(panel_lines), border_style="cyan", padding=(0, 1)))
        console.print()

        # Create humor config with spice level
        from scribe.utils.joke_generator import HumorConfig

        humor_config = HumorConfig.from_env()
        humor_config.api_key = config.openai_api_key

        if spice is not None:
            if 0 <= spice <= 10:
                humor_config.spice_level = spice
            else:
                console.print(
                    f"[bold yellow]Warning:[/bold yellow] Invalid spice level {spice} (must be 0-10), using default"
                )

        if archetype is not None:
            humor_config.archetype = archetype

        # Determine if bakeoff is enabled
        import os

        enable_bakeoff = (
            bakeoff
            if bakeoff is not None
            else os.getenv("SCRIBE_ENABLE_JOKE_BAKEOFF", "false").lower() == "true"
        )

        # Generate joke with progress
        from rich.progress import Progress, SpinnerColumn, TextColumn

        with Progress(
            SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console, transient=True
        ) as progress:
            progress.add_task("Generating joke...", total=None)

            if enable_bakeoff:
                # Run bake-off
                from scribe.utils.joke_bakeoff import run_joke_bakeoff

                # Read transcript
                transcript = load_transcript_text(transcript_file)

                try:
                    bakeoff_result = run_joke_bakeoff(transcript, humor_config)
                    joke_text = bakeoff_result["joke"]

                    console.print()
                    console.print(f"[bold cyan]Joke:[/bold cyan] {joke_text}")
                    console.print()
                    return

                except Exception as e:
                    console.print(
                        f"[yellow]Bake-off failed: {e}, falling back to single provider[/yellow]"
                    )
                    enable_bakeoff = False

            if not enable_bakeoff:
                # Standard single-provider approach
                result = generate_transcript_joke(
                    transcript_file, humor_config, provider_name=provider
                )

                console.print()

                if result:
                    joke_text, _comedy_style = result
                    console.print(f"[bold cyan]Joke:[/bold cyan] {joke_text}")
                    console.print()
                else:
                    console.print("[bold yellow]Warning:[/bold yellow] Failed to generate joke")
                    console.print("[dim]Check your API key and try again[/dim]")
                    raise typer.Exit(1)

    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if e.context:
            console.print(f"[dim]Context: {e.context}[/dim]")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        logger.exception("Unexpected error in joke command")
        raise typer.Exit(1)


@app.command()
def meme(
    transcript_file: Path = typer.Argument(
        ..., help="Path to transcript file (.txt, .md, .docx)", exists=True
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output path for meme (default: same directory as transcript)"
    ),
    spice: int | None = typer.Option(
        None, "--spice", help="Humor intensity 0-10 (0=off, 5=default, 10=spicy)"
    ),
    show_reasoning: bool = typer.Option(
        False,
        "--show-reasoning",
        "-r",
        help="Display GPT-5's reasoning process (Glass Box Transparency)",
    ),
    bakeoff: bool = typer.Option(
        None,
        "--bakeoff/--no-bakeoff",
        help="Run concept bake-off across all providers (default: from env SCRIBE_ENABLE_MEME_BAKEOFF)",
    ),
) -> None:
    """
    Generate a meme from a meeting transcript.

    Uses GPT-5 to analyze the transcript and create a clever meme concept,
    then generates the meme image using OpenAI's image generation API.

    Example: scribe meme transcript.txt
    Example: scribe meme transcript.txt --output ./memes/meeting.png
    Example: scribe meme transcript.txt --show-reasoning
    """
    try:
        # Validate file is a text file
        if not is_supported_transcript_file(transcript_file):
            console.print(
                "[bold red]Error:[/bold red] File must be a text file (.txt, .md, or .docx transcript)"
            )
            raise typer.Exit(1)

        config = ScribeConfig()

        if not config.openai_api_key:
            console.print("[bold red]Error:[/bold red] OpenAI API key not configured")
            console.print(
                "[dim]Set OPENAI_API_KEY or SCRIBE_OPENAI_API_KEY in your .env file[/dim]"
            )
            raise typer.Exit(1)

        # Display header
        _show_command_banner(console)
        panel_lines = [f"[white]{transcript_file.name}[/white]"]
        panel_lines.append("[dim]meme[/dim]")

        console.print(Panel.fit("\n".join(panel_lines), border_style="cyan", padding=(0, 1)))
        console.print()

        # Generate meme with progress
        from rich.progress import Progress, SpinnerColumn, TextColumn

        from scribe.utils.meme_generator import MemeConfig, generate_meeting_meme

        # Create meme config with spice level
        meme_config = MemeConfig.from_env()
        if spice is not None:
            if 0 <= spice <= 10:
                meme_config.spice_level = spice
            else:
                console.print(
                    f"[bold yellow]Warning:[/bold yellow] Invalid spice level {spice} (must be 0-10), using default"
                )

        with Progress(
            SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console, transient=True
        ) as progress:
            progress.add_task("Generating meme...", total=None)

            # Determine if bakeoff is enabled
            import os

            enable_bakeoff = (
                bakeoff
                if bakeoff is not None
                else os.getenv("SCRIBE_ENABLE_MEME_BAKEOFF", "false").lower() == "true"
            )

            if output:
                # Use specified output path
                meme_result = generate_meeting_meme(
                    transcript_file,
                    output_dir=output.parent if output.parent != Path(".") else None,
                    api_key=None,  # Let provider system choose the right key
                    config=meme_config,
                    show_reasoning=show_reasoning,
                    enable_bakeoff=enable_bakeoff,
                )
                if meme_result:
                    meme_path = (
                        meme_result["final_path"] if isinstance(meme_result, dict) else meme_result
                    )
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
                    show_reasoning=show_reasoning,
                    enable_bakeoff=enable_bakeoff,
                )
                meme_path = (
                    meme_result["final_path"]
                    if (meme_result and isinstance(meme_result, dict))
                    else meme_result
                )

        console.print()

        if not meme_path:
            console.print("[bold yellow]Warning:[/bold yellow] Failed to generate meme")
            console.print("[dim]Check your OpenAI API key and try again[/dim]")
            raise typer.Exit(1)

        # Extract attempts info
        attempts = meme_result.get("attempts", []) if isinstance(meme_result, dict) else []

        # Display results
        console.print()
        from scribe.utils.theme import file_link

        console.print(file_link("Meme:", str(meme_path)))

        # Show all attempts if multiple were generated
        if len(attempts) > 1:
            console.print(f"\n[{ScribeTheme.ACCENT}]All Attempts:[/{ScribeTheme.ACCENT}]")
            for attempt in attempts:
                score_str = f"{attempt['score']:.1f}/10" if attempt["score"] is not None else "N/A"
                attempt_path = attempt["path"]
                url_path = str(attempt_path).replace("\\", "/")
                console.print(
                    f"  Attempt {attempt['attempt']} (score: {score_str}): [link=file:///{url_path}]{attempt_path}[/link]"
                )
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
        ..., help="Path to transcript file (.txt, .md, .docx)", exists=True
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output path for notes (default: same directory as transcript)"
    ),
    model: str | None = typer.Option(
        None, "--model", help="Model to use (default: provider's notes default)"
    ),
    provider: str | None = typer.Option(
        None, "--provider", help="AI provider to use (openai, xai, anthropic, gemini, ollama)"
    ),
    compare: str | None = typer.Option(
        None,
        "--compare",
        help=(
            "Compare providers instead of generating. Use a preset ('smart', 'local', "
            "'all') or a list like 'openai,ollama:qwen2.5:14b'. Tip: `scribe compare` is "
            "the shorter way to do this."
        ),
    ),
    judge: str | None = typer.Option(
        None,
        "--judge",
        help="Judge for --compare: 'auto' (default), 'none', or e.g. 'openai'.",
    ),
) -> None:
    """
    Generate structured meeting notes from a transcript.

    Uses AI (OpenAI, XAI/Grok, Ollama, etc.) to analyze the transcript and create comprehensive notes with:
    - Detailed summary
    - Current state (business & technical)
    - Drivers and blockers
    - Future state and next steps

    Example: scribe notes transcript.txt
    Example: scribe notes transcript.txt --output ./notes/meeting.md
    Example: scribe notes transcript.txt --provider ollama          # free, local, offline
    Example: scribe notes transcript.txt --compare openai,ollama:qwen2.5:14b --judge openai
    """
    try:
        # Validate file is a text file
        if not is_supported_transcript_file(transcript_file):
            console.print(
                "[bold red]Error:[/bold red] File must be a text file (.txt, .md, or .docx transcript)"
            )
            raise typer.Exit(1)

        config = ScribeConfig()

        # Local-only (Ollama) and comparison runs do not need a cloud key; each
        # cloud provider validates its own key when it is actually used.
        single_provider = (provider or "openai").lower()
        needs_cloud_key = compare is None and single_provider not in ("ollama",)
        if needs_cloud_key and not config.openai_api_key:
            console.print("[bold red]Error:[/bold red] OpenAI API key not configured")
            console.print("[dim]Set OPENAI_API_KEY in your .env file[/dim]")
            raise typer.Exit(1)

        # Display header
        _show_command_banner(console)
        panel_lines = [f"[white]{transcript_file.name}[/white]"]
        panel_lines.append("[dim]notes · compare[/dim]" if compare else "[dim]notes[/dim]")

        console.print(Panel.fit("\n".join(panel_lines), border_style="cyan", padding=(0, 1)))
        console.print()

        # Comparison / eval mode: score providers side by side and return.
        if compare:
            _run_notes_comparison(transcript_file, compare, judge)
            return

        # Generate notes with progress
        from rich.progress import Progress, SpinnerColumn, TextColumn

        from scribe.utils.notes_generator import NotesGenerator

        notes_model = model or config.notes_model
        notes_generator = NotesGenerator(
            api_key=None,  # Let provider factory get the right key
            model=notes_model,
            provider_name=provider,
        )

        with Progress(
            SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console, transient=True
        ) as progress:
            progress.add_task("Generating notes...", total=None)
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


def _run_notes_comparison(
    transcript_file: Path, providers_arg: str | None, judge_arg: str | None
) -> None:
    """Shared comparison runner for `scribe compare` and `scribe notes --compare`."""
    from rich.progress import Progress, SpinnerColumn, TextColumn

    from scribe.utils.notes_eval import (
        detect_availability,
        format_scorecard,
        resolve_compare_plan,
        run_notes_eval,
        summarize_verdict,
    )
    from scribe.utils.transcript_loader import load_transcript_text

    avail = detect_availability()
    specs, judge = resolve_compare_plan(providers_arg, judge_arg, avail)
    if not specs:
        console.print(
            "[bold red]Error:[/bold red] nothing to compare — no cloud API keys and "
            "no local Ollama models found."
        )
        console.print(
            "[dim]Pull a local model (e.g. `ollama pull qwen2.5:14b`) or set an API key.[/dim]"
        )
        raise typer.Exit(1)

    transcript_text = load_transcript_text(transcript_file)
    plan = ", ".join(specs) + (f"   judge={judge}" if judge else "   (objective only)")
    console.print(f"[dim]comparing:[/dim] {plan}")
    console.print()

    with Progress(
        SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console, transient=True
    ) as progress:
        progress.add_task("Scoring providers...", total=None)
        results = run_notes_eval(transcript_text, specs, judge_spec=judge)

    console.print(format_scorecard(results))
    console.print()

    verdict = summarize_verdict(results)
    if verdict:
        console.print(f"[bold cyan]→[/bold cyan] {verdict}")
        console.print()

    for r in results:
        if not r.ok:
            console.print(f"[yellow]{r.spec} failed:[/yellow] {r.error}")


@app.command()
def compare(
    transcript_file: Path = typer.Argument(
        ..., help="Transcript to compare on (.txt, .md, .docx)", exists=True
    ),
    providers: str = typer.Argument(
        "smart",
        help=(
            "What to compare: 'smart' (your cloud default vs the best local model), "
            "'local' (every installed Ollama model, free/offline), 'all' (every "
            "provider you have), or an explicit list like 'openai,ollama:gemma4:26b'."
        ),
    ),
    judge: str = typer.Option(
        "auto",
        "--judge",
        help="Judge provider: 'auto' (a cloud model you have), 'none', or e.g. 'openai'.",
    ),
) -> None:
    """
    Compare note-generation providers and print a cost / latency / quality scorecard.

    Quality is scored objectively (free, offline) plus an optional LLM judge, and a
    one-line verdict tells you whether the free local model is worth it.

    Examples:
        scribe compare meeting.md                 # smart: cloud vs best local, auto-judged
        scribe compare meeting.md local           # every local model, free and offline
        scribe compare meeting.md all             # everything you have keys/models for
        scribe compare meeting.md openai,ollama:gemma4:26b --judge openai
    """
    try:
        if not is_supported_transcript_file(transcript_file):
            console.print(
                "[bold red]Error:[/bold red] File must be a text file (.txt, .md, or .docx)"
            )
            raise typer.Exit(1)

        _show_command_banner(console)
        console.print(
            Panel.fit(
                f"[white]{transcript_file.name}[/white]\n[dim]compare[/dim]",
                border_style="cyan",
                padding=(0, 1),
            )
        )
        console.print()

        _run_notes_comparison(transcript_file, providers, judge)

    except ScribeError as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Unexpected error:[/bold red] {e}")
        logger.exception("Unexpected error in compare command")
        raise typer.Exit(1)


@app.command()
def info() -> None:
    """
    Show system information and GPU capabilities.

    Displays GPU detection results, recommended transcription method,
    and system configuration.
    """
    from scribe.utils.terminal_ui import get_terminal_ui_config
    from scribe.utils.theme import ScribeTheme

    try:
        config = ScribeConfig()
        gpu_config = GPUConfig.detect()
        ui_config = get_terminal_ui_config()

        console.print()
        console.print(
            f"[bold {ScribeTheme.PRIMARY_BRIGHT}]scribe info[/bold {ScribeTheme.PRIMARY_BRIGHT}] [{ScribeTheme.TEXT_MUTED}]{__version__}[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print()

        # GPU section
        console.print(f"[bold {ScribeTheme.SECONDARY}]gpu[/bold {ScribeTheme.SECONDARY}]")
        if gpu_config.has_gpu:
            cuda_status = (
                f"CUDA {gpu_config.cuda_version}" if gpu_config.cuda_version else "CUDA detected"
            )
            console.print(
                f"  [{ScribeTheme.TEXT_PRIMARY}]{gpu_config.gpu_name}[/{ScribeTheme.TEXT_PRIMARY}] [{ScribeTheme.TEXT_MUTED}]{gpu_config.gpu_memory_gb:.0f}GB VRAM[/{ScribeTheme.TEXT_MUTED}]"
            )
            console.print(
                f"  [{ScribeTheme.TEXT_MUTED}]{cuda_status} · {gpu_config.model_size} · beam={gpu_config.beam_size} · {gpu_config.get_expected_speed()}[/{ScribeTheme.TEXT_MUTED}]"
            )
        else:
            console.print(
                f"  [{ScribeTheme.WARNING}]not detected[/{ScribeTheme.WARNING}] [{ScribeTheme.TEXT_MUTED}]{gpu_config.reason}[/{ScribeTheme.TEXT_MUTED}]"
            )
        console.print()

        # Local backend section: which engine the hardware-adaptive selector will
        # use for `--method local`, plus which optional engines are installed.
        from scribe.core.backends import (
            backend_availability,
            detect_hardware,
            select_backend,
        )

        hardware = detect_hardware()
        availability = backend_availability()
        chosen_backend = select_backend(
            hardware, override=config.local_backend, available=availability
        )
        installed = ", ".join(sorted(name for name, ok in availability.items() if ok)) or "none"

        console.print(f"[bold {ScribeTheme.SECONDARY}]local backend[/bold {ScribeTheme.SECONDARY}]")
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]selected[/{ScribeTheme.TEXT_PRIMARY}]  "
            f"[{ScribeTheme.SUCCESS}]{chosen_backend}[/{ScribeTheme.SUCCESS}] "
            f"[{ScribeTheme.TEXT_MUTED}]· vendor {hardware.vendor}[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]installed[/{ScribeTheme.TEXT_PRIMARY}] "
            f"[{ScribeTheme.TEXT_MUTED}]{installed}[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print()

        # Config section
        console.print(f"[bold {ScribeTheme.SECONDARY}]config[/bold {ScribeTheme.SECONDARY}]")
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]output[/{ScribeTheme.TEXT_PRIMARY}]    [{ScribeTheme.TEXT_MUTED}]{config.output_folder}[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]model[/{ScribeTheme.TEXT_PRIMARY}]     [{ScribeTheme.TEXT_MUTED}]{config.default_model}[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]language[/{ScribeTheme.TEXT_PRIMARY}]  [{ScribeTheme.TEXT_MUTED}]{config.default_language or 'auto'}[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print()

        # UI section
        console.print(f"[bold {ScribeTheme.SECONDARY}]ui[/bold {ScribeTheme.SECONDARY}]")
        mode = ui_config.animation_mode
        color_mode = ui_config.color_mode
        fps = ui_config.fps
        cap = ui_config.capabilities
        color_state = "enabled" if ui_config.use_color else "disabled"
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]animations[/{ScribeTheme.TEXT_PRIMARY}] "
            f"[{ScribeTheme.TEXT_MUTED}]{mode}[/{ScribeTheme.TEXT_MUTED}] "
            f"[{ScribeTheme.TEXT_MUTED}]({fps} fps)[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]color[/{ScribeTheme.TEXT_PRIMARY}]      "
            f"[{ScribeTheme.TEXT_MUTED}]{color_mode} ({color_state})[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]terminal[/{ScribeTheme.TEXT_PRIMARY}]   "
            f"[{ScribeTheme.TEXT_MUTED}]tty={cap.is_tty} dumb={cap.is_dumb_terminal} "
            f"ci={cap.is_ci} windows={cap.is_windows}[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print()

        # API keys section
        console.print(f"[bold {ScribeTheme.SECONDARY}]api keys[/bold {ScribeTheme.SECONDARY}]")
        openai_status = (
            f"[{ScribeTheme.SUCCESS}]set[/{ScribeTheme.SUCCESS}]"
            if config.openai_api_key
            else f"[{ScribeTheme.TEXT_MUTED}]not set[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]openai[/{ScribeTheme.TEXT_PRIMARY}]    {openai_status}"
        )

        # Check for other API keys
        import os

        xai_key = os.getenv("XAI_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY")

        xai_status = (
            f"[{ScribeTheme.SUCCESS}]set[/{ScribeTheme.SUCCESS}]"
            if xai_key
            else f"[{ScribeTheme.TEXT_MUTED}]not set[/{ScribeTheme.TEXT_MUTED}]"
        )
        gemini_status = (
            f"[{ScribeTheme.SUCCESS}]set[/{ScribeTheme.SUCCESS}]"
            if gemini_key
            else f"[{ScribeTheme.TEXT_MUTED}]not set[/{ScribeTheme.TEXT_MUTED}]"
        )
        anthropic_status = (
            f"[{ScribeTheme.SUCCESS}]set[/{ScribeTheme.SUCCESS}]"
            if anthropic_key
            else f"[{ScribeTheme.TEXT_MUTED}]not set[/{ScribeTheme.TEXT_MUTED}]"
        )

        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]xai[/{ScribeTheme.TEXT_PRIMARY}]       {xai_status}"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]gemini[/{ScribeTheme.TEXT_PRIMARY}]    {gemini_status}"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]anthropic[/{ScribeTheme.TEXT_PRIMARY}] {anthropic_status}"
        )
        console.print()

        # Local LLM (Ollama) section — free, offline notes. Surfaces the smart
        # default model auto-selected for this machine's memory budget.
        from scribe.utils.ollama_models import (
            available_model_memory_gb,
            list_installed_models,
            select_default_ollama_model,
        )

        console.print(f"[bold {ScribeTheme.SECONDARY}]local llm[/bold {ScribeTheme.SECONDARY}]")
        ollama_models = list_installed_models(os.getenv("SCRIBE_OLLAMA_BASE_URL"))
        if ollama_models:
            budget = available_model_memory_gb()
            chosen = select_default_ollama_model(os.getenv("SCRIBE_OLLAMA_BASE_URL"))
            budget_label = f"{budget:.0f}GB budget" if budget > 0 else "conservative (cpu)"
            console.print(
                f"  [{ScribeTheme.TEXT_PRIMARY}]ollama[/{ScribeTheme.TEXT_PRIMARY}]    "
                f"[{ScribeTheme.SUCCESS}]{len(ollama_models)} models[/{ScribeTheme.SUCCESS}] "
                f"[{ScribeTheme.TEXT_MUTED}]· {budget_label}[/{ScribeTheme.TEXT_MUTED}]"
            )
            console.print(
                f"  [{ScribeTheme.TEXT_PRIMARY}]auto[/{ScribeTheme.TEXT_PRIMARY}]      "
                f"[{ScribeTheme.TEXT_MUTED}]{chosen} (notes --provider ollama)[/{ScribeTheme.TEXT_MUTED}]"
            )
        else:
            console.print(
                f"  [{ScribeTheme.TEXT_PRIMARY}]ollama[/{ScribeTheme.TEXT_PRIMARY}]    "
                f"[{ScribeTheme.TEXT_MUTED}]not running (optional, for free local notes)[/{ScribeTheme.TEXT_MUTED}]"
            )
        console.print()

        # Recommendation
        if gpu_config.recommendation == "local":
            console.print(f"[{ScribeTheme.SUCCESS}]recommended: local GPU[/{ScribeTheme.SUCCESS}]")
        else:
            console.print(f"[{ScribeTheme.PRIMARY}]recommended: OpenAI API[/{ScribeTheme.PRIMARY}]")
        console.print()

    except Exception as e:
        console.print(f"\n[bold {ScribeTheme.ERROR}]error:[/bold {ScribeTheme.ERROR}] {e}")
        raise typer.Exit(1)


@app.command()
def doctor() -> None:
    """
    Run system diagnostics and health checks.

    Validates environment, dependencies, and configuration.
    Provides actionable suggestions for fixing issues.
    """
    from rich.table import Table

    from scribe.utils.diagnostics import SystemDiagnostics
    from scribe.utils.theme import ScribeTheme

    console.print()
    doctor_header = (
        f"{brand_header_markup('scribe doctor', fallback_color=ScribeTheme.PRIMARY_BRIGHT)} "
        f"[{ScribeTheme.TEXT_MUTED}]{__version__}[/{ScribeTheme.TEXT_MUTED}]"
    )
    console.print(doctor_header)
    console.print()

    # Run diagnostics with progress spinner
    diagnostics = SystemDiagnostics()
    with console.status(
        f"[{ScribeTheme.PRIMARY}]Running diagnostics...[/{ScribeTheme.PRIMARY}]",
        spinner="dots",
    ):
        results = diagnostics.run_all_checks()

    # Group results by status for cleaner display
    passed = [r for r in results if r.status == "pass"]
    warnings = [r for r in results if r.status == "warn"]
    failures = [r for r in results if r.status == "fail"]

    # Display failures first (if any)
    if failures:
        console.print(f"[bold {ScribeTheme.ERROR}]FAILED[/bold {ScribeTheme.ERROR}]")
        for result in failures:
            console.print(
                f"  [{ScribeTheme.ERROR}]×[/{ScribeTheme.ERROR}] [{ScribeTheme.TEXT_PRIMARY}]{result.name}[/{ScribeTheme.TEXT_PRIMARY}]"
            )
            console.print(
                f"    [{ScribeTheme.TEXT_MUTED}]{result.message}[/{ScribeTheme.TEXT_MUTED}]"
            )
            if result.fix_suggestion:
                console.print(
                    f"    [{ScribeTheme.PRIMARY}]→ {result.fix_suggestion}[/{ScribeTheme.PRIMARY}]"
                )
        console.print()

    # Display warnings (if any)
    if warnings:
        console.print(f"[bold {ScribeTheme.WARNING}]WARNINGS[/bold {ScribeTheme.WARNING}]")
        for result in warnings:
            console.print(
                f"  [{ScribeTheme.WARNING}]![/{ScribeTheme.WARNING}] [{ScribeTheme.TEXT_PRIMARY}]{result.name}[/{ScribeTheme.TEXT_PRIMARY}]"
            )
            console.print(
                f"    [{ScribeTheme.TEXT_MUTED}]{result.message}[/{ScribeTheme.TEXT_MUTED}]"
            )
            if result.fix_suggestion:
                console.print(
                    f"    [{ScribeTheme.PRIMARY}]→ {result.fix_suggestion}[/{ScribeTheme.PRIMARY}]"
                )
        console.print()

    # Compact passed checks - just a summary table
    if passed:
        table = Table(
            show_header=False,
            box=None,
            padding=(0, 1, 0, 0),
            collapse_padding=True,
        )
        table.add_column(style=ScribeTheme.SUCCESS, width=2)
        table.add_column(style=ScribeTheme.TEXT_PRIMARY, width=20)
        table.add_column(style=ScribeTheme.TEXT_MUTED)

        for result in passed:
            # Extract key info from message (first line or short version)
            short_msg = result.message.split("\n")[0][:40]
            table.add_row("+", result.name, short_msg)

        console.print(table)
        console.print()

    # Summary line
    pass_count, warn_count, fail_count = diagnostics.get_summary()

    if fail_count == 0 and warn_count == 0:
        console.print(
            f"[{ScribeTheme.SUCCESS}]ready[/{ScribeTheme.SUCCESS}] [{ScribeTheme.TEXT_MUTED}]{pass_count} checks passed[/{ScribeTheme.TEXT_MUTED}]"
        )
    elif fail_count == 0:
        console.print(
            f"[{ScribeTheme.WARNING}]ready with warnings[/{ScribeTheme.WARNING}] [{ScribeTheme.TEXT_MUTED}]{pass_count} passed, {warn_count} warnings[/{ScribeTheme.TEXT_MUTED}]"
        )
    else:
        console.print(
            f"[{ScribeTheme.ERROR}]not ready[/{ScribeTheme.ERROR}] [{ScribeTheme.TEXT_MUTED}]{fail_count} failed, {warn_count} warnings[/{ScribeTheme.TEXT_MUTED}]"
        )

    console.print()

    # Exit with error code if there are failures
    if fail_count > 0:
        raise typer.Exit(1)


@app.command(name="health")
def health_check(
    provider: str | None = typer.Option(
        None, "--provider", "-p", help="Check specific provider (openai, xai, anthropic, gemini)"
    ),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force fresh health check (ignore cache)"
    ),
) -> None:
    """
    Check health status of AI providers.

    Validates API connectivity and response times for configured providers.
    Useful for troubleshooting provider issues.
    """
    import os

    from scribe.providers.health import get_health_monitor
    from scribe.utils.theme import ScribeTheme

    console.print()
    console.print(brand_header_markup("scribe health", fallback_color=ScribeTheme.PRIMARY_BRIGHT))
    console.print()

    # Get health monitor
    monitor = get_health_monitor()

    # Collect API keys
    api_keys: dict[str, str] = {}
    openai_key = os.getenv("OPENAI_API_KEY")
    xai_key = os.getenv("XAI_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    if openai_key is not None:
        api_keys["openai"] = openai_key
    if xai_key is not None:
        api_keys["xai"] = xai_key
    if anthropic_key is not None:
        api_keys["anthropic"] = anthropic_key
    if gemini_key is not None:
        api_keys["gemini"] = gemini_key

    if not api_keys:
        console.print(f"[{ScribeTheme.WARNING}]no api keys configured[/{ScribeTheme.WARNING}]")
        console.print(
            f"[{ScribeTheme.TEXT_MUTED}]set OPENAI_API_KEY, XAI_API_KEY, etc.[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print()
        raise typer.Exit(1)

    # Check specific provider or all
    providers_to_check = [provider] if provider else list(api_keys.keys())

    all_healthy = True
    results: list[tuple[str, bool, str]] = []

    for provider_name in providers_to_check:
        if provider_name not in api_keys:
            continue

        try:
            status = monitor.check_provider_health(
                provider_name, api_keys[provider_name], force=force
            )

            if status.is_healthy:
                response_time = (
                    f"{status.response_time_ms:.0f}ms" if status.response_time_ms else ""
                )
                results.append((provider_name, True, response_time))
            else:
                results.append((provider_name, False, status.error_message or "error"))
                all_healthy = False

        except Exception as e:
            results.append((provider_name, False, str(e)[:30]))
            all_healthy = False

    # Display results
    for name, healthy, detail in results:
        if healthy:
            console.print(
                f"  [{ScribeTheme.SUCCESS}]+[/{ScribeTheme.SUCCESS}] [{ScribeTheme.TEXT_PRIMARY}]{name:<12}[/{ScribeTheme.TEXT_PRIMARY}][{ScribeTheme.TEXT_MUTED}]{detail}[/{ScribeTheme.TEXT_MUTED}]"
            )
        else:
            console.print(
                f"  [{ScribeTheme.ERROR}]x[/{ScribeTheme.ERROR}] [{ScribeTheme.TEXT_PRIMARY}]{name:<12}[/{ScribeTheme.TEXT_PRIMARY}][{ScribeTheme.TEXT_MUTED}]{detail}[/{ScribeTheme.TEXT_MUTED}]"
            )

    console.print()

    # Summary
    if all_healthy:
        console.print(f"[{ScribeTheme.SUCCESS}]all providers healthy[/{ScribeTheme.SUCCESS}]")
    else:
        console.print(f"[{ScribeTheme.WARNING}]some providers have issues[/{ScribeTheme.WARNING}]")

    console.print()

    if not all_healthy:
        raise typer.Exit(1)


@app.command(name="support-bundle")
def support_bundle(
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Output directory for support bundle (default: current directory)",
    ),
) -> None:
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
    console.print(Panel.fit(brand_header_markup("Generating Support Bundle"), border_style="cyan"))
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
        console.print("[bold red]Error:[/bold red] Failed to create support bundle")
        console.print(f"[dim]{e}[/dim]")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"Scribe {__version__}")


@app.command(name="help")
def help_command() -> None:
    """Show help information."""
    # Trigger the main help by invoking the app's format_help
    import click

    ctx = click.get_current_context()
    # Go up to parent context (the main app)
    if ctx.parent:
        click.echo(ctx.parent.get_help())
    else:
        click.echo(ctx.get_help())


@app.command()
def clean(
    input_file: Path = typer.Argument(..., help="Path to audio/video file to clean", exists=True),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Output path (default: input_cleaned.ext)"
    ),
    threshold: str = typer.Option(
        "-50dB", "--threshold", "-t", help="Silence threshold (e.g., -50dB, -40dB)"
    ),
    duration: float = typer.Option(
        2.0, "--duration", "-d", help="Minimum silence duration to remove (seconds)"
    ),
    analyze_only: bool = typer.Option(
        False, "--analyze", "-a", help="Only analyze silence, don't remove it"
    ),
    trim_to: str | None = typer.Option(
        None,
        "--trim",
        help="Trim to specific time (e.g., '01:42:00' for 1h 42m, or '6120' for seconds)",
    ),
) -> None:
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
        from scribe.utils.audio import get_audio_duration
        from scribe.utils.silence_remover import analyze_silence, remove_silence, trim_file

        # Display header
        _show_command_banner(console)
        panel_lines = [f"[white]{input_file.name}[/white]"]

        # Get original duration
        original_duration = get_audio_duration(input_file)
        if original_duration:
            original_mins = int(original_duration / 60)
            panel_lines.append(
                f"[dim]Original duration: {original_mins} minutes ({original_duration:.1f}s)[/dim]"
            )

        if trim_to:
            panel_lines.append(f"[dim]Mode: Trim to {trim_to}[/dim]")
        elif analyze_only:
            panel_lines.append("[dim]Mode: Analyze only[/dim]")
        else:
            panel_lines.append("[dim]Mode: Remove silence[/dim]")
            panel_lines.append(f"[dim]Threshold: {threshold}, Min duration: {duration}s[/dim]")

        console.print(Panel.fit("\n".join(panel_lines), border_style="cyan", padding=(0, 1)))
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
                console.print("[bold green]Success![/bold green]")
                console.print(
                    f"  Original: {original_mins} minutes ({original_mins / 60:.1f} hours)"
                )
                console.print(f"  Trimmed:  {new_mins} minutes ({new_hours:.1f} hours)")
                console.print()
                console.print(f"[bold]Output:[/bold] {output_path}")
            else:
                console.print()
                console.print("[bold green]Success![/bold green]")
                console.print(f"[bold]Output:[/bold] {output_path}")

            return

        if analyze_only:
            # Just analyze
            console.print("[cyan]Analyzing silence...[/cyan]")
            analysis = analyze_silence(input_file, threshold, duration)

            console.print()
            console.print("[bold]Silence Analysis:[/bold]")
            console.print(
                f"  Total silence: {analysis['total_silence_minutes']:.1f} minutes ({analysis['total_silence_seconds']:.1f}s)"
            )
            console.print(f"  Silent periods: {analysis['silence_periods']}")

            if analysis["silence_periods"] > 0:
                console.print()
                console.print("[dim]First few silent periods:[/dim]")
                for i, period in enumerate(analysis["periods"][:5], 1):
                    start_min = int(period["start"] / 60)
                    duration_sec = period["duration"]
                    console.print(f"  {i}. At {start_min}m: {duration_sec:.1f}s of silence")

                if analysis["silence_periods"] > 5:
                    console.print(f"  ... and {analysis['silence_periods'] - 5} more")

            console.print()
            console.print("[green]To remove silence, run without --analyze flag[/green]")

        else:
            # Remove silence
            console.print("[cyan]Removing silence...[/cyan]")
            console.print("[dim]This may take a few minutes for large files...[/dim]")
            console.print()

            output_path = remove_silence(input_file, output, threshold, duration)

            # Get file sizes for comparison
            original_size = input_file.stat().st_size / (1024 * 1024)  # MB
            new_size = output_path.stat().st_size / (1024 * 1024)  # MB
            size_reduction = ((original_size - new_size) / original_size) * 100

            console.print()
            console.print("[bold green]Success![/bold green]")
            console.print(f"  Original size: {original_size:.1f} MB")
            console.print(f"  Cleaned size:  {new_size:.1f} MB")
            console.print(f"  Reduction:     {size_reduction:.1f}%")
            console.print()
            console.print("[dim]Note: Silent sections are reduced to near-silence.[/dim]")
            console.print(
                "[dim]This makes transcription much faster as Whisper skips silent parts.[/dim]"
            )
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


@app.command(name="init")
def init_command(
    force: bool = typer.Option(
        False, "--force", "-f", help="Overwrite existing config without prompting"
    ),
) -> None:
    """
    Run the first-run setup wizard.

    Writes ~/.scribe/config.toml with your output folder, transcription method,
    default features (notes/joke/meme), and AI vendor preference. Env vars and
    CLI flags continue to override these values.
    """
    from scribe.cli.init import run_wizard

    run_wizard(console=console, force=force)


@app.command(name="shortcut")
def shortcut_command(
    desktop: bool | None = typer.Option(
        None,
        "--desktop/--no-desktop",
        help="Also place a launcher on the Desktop (otherwise you're asked)",
    ),
    remove: bool = typer.Option(False, "--remove", help="Remove installed launchers"),
) -> None:
    """
    Install a 'Quick Record' launcher in your OS app menu (Windows/macOS/Linux).

    Creates a native, double-clickable shortcut that runs `scribe rec`, the
    cross-platform replacement for a hand-made batch file. Use --remove to undo.

    Examples:

      scribe shortcut             # install to the app menu (offers a Desktop copy)
      scribe shortcut --desktop   # also drop one on the Desktop
      scribe shortcut --remove    # remove installed launchers
    """
    from scribe.cli.shortcut import run_shortcut

    run_shortcut(console=console, desktop=desktop, remove=remove)


@app.command(name="query")
def query_command(
    text: str | None = typer.Argument(None, help="Text to search for in transcript segments"),
    speaker: str | None = typer.Option(None, "--speaker", help="Filter by speaker label"),
    folder: Path | None = typer.Option(
        None, "--folder", help="Folder to search (default: your configured output folder)"
    ),
    limit: int = typer.Option(50, "--limit", help="Maximum matches to show"),
) -> None:
    """
    Search across your structured (.json) transcripts.

    Keyword and speaker search over the JSON transcripts written next to each
    transcript, so you can find a moment across past meetings.

    Examples:

      scribe query "budget"
      scribe query "action item" --speaker SPEAKER_01
    """
    from scribe.cli.query import run_query

    config = ScribeConfig()
    search_folder = folder or config.output_folder
    run_query(console=console, folder=search_folder, text=text, speaker=speaker, limit=limit)


@app.command(name="vocab")
def vocab_command(
    name: str | None = typer.Argument(
        None, help="Glossary to show (name or .txt/.json path); omit to list all"
    ),
) -> None:
    """
    List available domain glossaries, or show one glossary's terms.

    Glossaries bias transcription toward your domain terms and rewrite known
    misrecognitions to the canonical form. Use one with `--vocab <name>` on
    transcribe/url/batch. Add your own under ~/.scribe/vocab/.
    """
    from scribe.utils.theme import ScribeTheme
    from scribe.utils.vocabulary import CustomVocabulary, _bundled_glossary_dir

    if name:
        try:
            vocab = CustomVocabulary.load(name)
        except FileNotFoundError as e:
            console.print(f"[{ScribeTheme.ERROR}]{e}[/{ScribeTheme.ERROR}]")
            raise typer.Exit(1)
        console.print(
            f"[bold {ScribeTheme.PRIMARY_BRIGHT}]{name}[/bold {ScribeTheme.PRIMARY_BRIGHT}] "
            f"[{ScribeTheme.TEXT_MUTED}]{len(vocab)} terms, "
            f"{len(vocab.aliases)} with aliases[/{ScribeTheme.TEXT_MUTED}]"
        )
        for term in vocab.words:
            variants = vocab.aliases.get(term)
            if variants:
                console.print(
                    f"  [{ScribeTheme.TEXT_PRIMARY}]{term}[/{ScribeTheme.TEXT_PRIMARY}] "
                    f"[{ScribeTheme.TEXT_MUTED}]<- {', '.join(variants)}[/{ScribeTheme.TEXT_MUTED}]"
                )
            else:
                console.print(f"  [{ScribeTheme.TEXT_PRIMARY}]{term}[/{ScribeTheme.TEXT_PRIMARY}]")
        return

    console.print(f"[bold {ScribeTheme.SECONDARY}]glossaries[/bold {ScribeTheme.SECONDARY}]")
    found = False
    sources = [
        ("user", Path.home() / ".scribe" / "vocab"),
        ("bundled", _bundled_glossary_dir()),
    ]
    for label, root in sources:
        if not root.exists():
            continue
        for path in sorted(root.glob("*.txt")) + sorted(root.glob("*.json")):
            found = True
            console.print(
                f"  [{ScribeTheme.PRIMARY}]{path.stem}[/{ScribeTheme.PRIMARY}] "
                f"[{ScribeTheme.TEXT_MUTED}]({label})[/{ScribeTheme.TEXT_MUTED}]"
            )
    if not found:
        console.print(
            f"  [{ScribeTheme.TEXT_MUTED}]none; add .txt/.json files under "
            f"~/.scribe/vocab/[/{ScribeTheme.TEXT_MUTED}]"
        )


@app.command(name="listen")
def listen_command(
    model: str | None = typer.Option(
        None, "--model", help="Whisper model for dictation (default: small on GPU, base on CPU)"
    ),
    language: str | None = typer.Option(
        None, "--language", "-l", help="Spoken language (ISO 639-1); auto-detect if omitted"
    ),
) -> None:
    """
    Dictate: speak and have your words typed into the focused window.

    A real-time mode separate from the batch pipeline. F9 toggles listening,
    Esc quits. Needs a microphone and the voice extra (pip install "scribe[voice]").
    """
    from scribe.cli.voice import run_listen

    raise typer.Exit(run_listen(console, model=model, language=language))


@app.command(name="say")
def say_command(
    file: Path = typer.Argument(..., help="Transcript or notes file to read aloud", exists=True),
    rate: int | None = typer.Option(None, "--rate", help="Speech rate in words per minute"),
    voice: str | None = typer.Option(None, "--voice", help="Voice name or id substring to use"),
) -> None:
    """
    Read a transcript or notes file aloud with a local, offline TTS engine.

    Needs the voice extra (pip install "scribe[voice]").
    """
    from scribe.cli.voice import run_say

    raise typer.Exit(run_say(console, file, rate=rate, voice=voice))


def main() -> None:
    """Main entry point with smart command detection."""
    import sys

    # Handle --banner flag (show animated banner and exit)
    if "--banner" in sys.argv:
        from rich.console import Console as BannerConsole

        c = BannerConsole()
        _show_command_banner(c)
        return

    # If first argument looks like a file path, inject 'transcribe' command
    if len(sys.argv) > 1:
        first_arg = sys.argv[1]
        # Derive the command set from what is actually registered so this never
        # drifts as commands are added or renamed. Commands declared with a bare
        # @app.command() have name=None and take their name from the function, so
        # include the callback name (and its hyphenated form) too.
        known_commands: set[str] = {"--help", "-h", "--version", "--banner"}
        for cmd in app.registered_commands:
            if cmd.name:
                known_commands.add(cmd.name)
            if cmd.callback is not None:
                known_commands.add(cmd.callback.__name__)
                known_commands.add(cmd.callback.__name__.replace("_", "-"))
        if first_arg not in known_commands and not first_arg.startswith("-"):
            # Check if it looks like a file path
            if (
                "." in first_arg
                or "/" in first_arg
                or "\\" in first_arg
                or Path(first_arg).exists()
            ):
                # Insert 'transcribe' command
                sys.argv.insert(1, "transcribe")

    # First-run setup: prompt to create ~/.scribe/config.toml if missing.
    # Skipped for init/version/help/banner and when stdin is not a TTY.
    skip_for = {"init", "version", "--help", "-h", "--version", "--banner", "help"}
    if len(sys.argv) <= 1 or sys.argv[1] not in skip_for:
        try:
            from scribe.cli.init import maybe_prompt_first_run

            maybe_prompt_first_run(console=console)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Setup skipped.[/dim]")

    app()


if __name__ == "__main__":
    main()
