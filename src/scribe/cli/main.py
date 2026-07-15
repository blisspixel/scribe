"""
Main CLI interface for Scribe using Typer.

This module provides the command-line interface with commands for
transcription, recording, and system information.
"""

import os
import shutil
import sys
import time
import warnings
from contextlib import suppress
from pathlib import Path
from typing import Any, TypedDict

import typer
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from scribe import __version__
from scribe.cli.errors import exit_on_cli_error
from scribe.core.recorder import OBSRecorder
from scribe.core.transcriber import Transcriber
from scribe.exceptions import ProcessError, ScribeError, TranscriptionError
from scribe.models.config import ModelSize, ScribeConfig, TranscriptionMethod
from scribe.models.gpu import GPUConfig
from scribe.models.session import SessionOutcome, TranscriptionSession
from scribe.models.transcript import Transcript
from scribe.utils.branding import brand_header_markup
from scribe.utils.docx_converter import txt_to_docx
from scribe.utils.joke_generator import (
    ARCHETYPE_DISPLAY_NAMES,
    generate_transcript_joke,
)
from scribe.utils.logging import console, get_current_log_file, get_logger, setup_logging
from scribe.utils.safe_write import atomic_write
from scribe.utils.theme import ScribeTheme, file_uri
from scribe.utils.transcript_loader import is_supported_transcript_file, load_transcript_text
from scribe.utils.validation import sanitize_meeting_name, validate_file_path

# Suppress TorchAudio MP3 warnings
warnings.filterwarnings("ignore", message=".*MPEG_LAYER_III.*")

logger = get_logger(__name__)

_TRANSCRIPTION_METHOD_HELP = "Method: auto/local are $0 local (GPU or CPU); openai is paid cloud"


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
    summary: Path


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
    except (OSError, TypeError, ValueError, KeyError) as e:
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


def _resolve_feature(override: bool | None, config_default: bool) -> bool:
    """Resolve whether a paid AI feature should run for this invocation.

    Each of the notes/joke/meme features is a tri-state per-run flag
    (``--notes/--no-notes`` etc.): ``None`` means "no per-run flag was given,
    fall back to the config default"; ``True``/``False`` are an explicit
    per-run override that wins over the config. This is the single source of
    truth so the display panel and the generation step can never disagree.
    """
    return config_default if override is None else override


def _failure_message(error: BaseException) -> str:
    """Return the most useful nonempty message from a terminal command error."""
    if isinstance(error, typer.Exit):
        if error.__cause__ is None:
            return f"Command exited with status {error.exit_code}"
        candidate = error.__cause__
    else:
        candidate = error
    message = str(candidate).strip()
    if message:
        return message
    exit_code = getattr(error, "exit_code", None)
    return (
        f"Command exited with status {exit_code}" if exit_code is not None else type(error).__name__
    )


def _persist_failed_session(
    session: TranscriptionSession | None,
    output_dir: Path | None,
    error: BaseException,
) -> Path | None:
    """Persist a started failed session without masking the original command error."""
    if session is None or output_dir is None:
        return None
    try:
        session.complete(success=False, error_message=_failure_message(error))
        summary_path = session.save_summary(output_dir)
    except Exception as persistence_error:
        issue = f"Failure summary could not be saved: {_failure_message(persistence_error)}"
        with suppress(Exception):
            logger.warning(
                "Could not persist failed session summary: %s", persistence_error, exc_info=True
            )
        with suppress(Exception):
            console.print(f"[bold red]{escape(issue)}[/bold red]", soft_wrap=True)
        return None

    try:
        console.print(f"Failure summary: {escape(str(summary_path))}", soft_wrap=True)
    except Exception as notification_error:
        with suppress(Exception):
            logger.warning(
                "Failure summary was saved to %s but could not be shown: %s",
                summary_path,
                notification_error,
            )
    return summary_path


def _notify_saved_summary(summary_path: Path, label: str = "Session summary") -> None:
    """Show a saved evidence path without allowing terminal failure to change its outcome."""
    try:
        console.print(f"{label}: {escape(str(summary_path))}", soft_wrap=True)
    except Exception as notification_error:
        with suppress(Exception):
            logger.warning(
                "%s was saved to %s but could not be shown: %s",
                label,
                summary_path,
                notification_error,
            )


def _warn_saved_outcome_error(error: BaseException) -> None:
    """Log a post-save command error through the module logger without masking it."""
    with suppress(Exception):
        logger.warning("Session outcome was already saved before a later error: %s", error)


def _persist_terminal_session_error(
    session: TranscriptionSession | None,
    output_dir: Path | None,
    error: BaseException,
    *,
    summary_saved: bool,
) -> Path | None:
    """Persist a failure unless a durable terminal outcome already exists."""
    if summary_saved:
        _warn_saved_outcome_error(error)
        return None
    return _persist_failed_session(session, output_dir, error)


def _add_music_issue(result: MusicResult, message: str) -> None:
    """Make a track result incomplete while preserving its primary failure."""
    current_error = result.get("error", "").strip()
    if message not in current_error:
        result["error"] = f"{current_error}; {message}" if current_error else message
    if result.get("status") in {"success", "instrumental"}:
        result["status"] = "partial"


def _persist_music_session(
    session: TranscriptionSession,
    result: MusicResult,
    output_dir: Path,
) -> Path | None:
    """Persist one terminal track result without hiding summary-write failures."""
    lyrics_path = result.get("lyrics")
    if lyrics_path is not None and session.transcript_file != lyrics_path:
        session.add_file(lyrics_path, "transcript")

    status = result.get("status", "failed")
    outcome_by_status: dict[str, SessionOutcome] = {
        "success": "success",
        "instrumental": "instrumental",
        "partial": "partial",
        "failed": "failed",
    }
    outcome = outcome_by_status.get(status, "failed")
    error_message = result.get("error")
    session.complete(
        success=status in {"success", "instrumental"},
        error_message=error_message,
        outcome=outcome,
    )
    try:
        summary_path = session.save_summary(output_dir)
    except Exception as error:
        issue = f"Session summary could not be saved: {_failure_message(error)}"
        _add_music_issue(result, issue)
        failed_outcome = outcome_by_status.get(result.get("status", "failed"), "failed")
        session.complete(
            success=False,
            error_message=result.get("error"),
            outcome=failed_outcome,
        )
        with suppress(Exception):
            logger.error(issue, exc_info=True)
        with suppress(Exception):
            console.print(f"  [yellow]{escape(issue)}[/yellow]")
        return None

    result["summary"] = summary_path
    label = "Failure summary" if status == "failed" else "Evidence"
    try:
        console.print(f"  {label}: {escape(str(summary_path))}", soft_wrap=True)
    except Exception as notification_error:
        with suppress(Exception):
            logger.warning(
                "Music session summary was saved to %s but could not be shown: %s",
                summary_path,
                notification_error,
            )
    return summary_path


def _write_instrumental_marker(audio_path: Path, metadata: dict[str, Any]) -> Path:
    """Write the same truthful marker for every confirmed instrumental path."""
    return _write_music_lyrics(
        audio_path,
        metadata,
        "[Instrumental - No Speech Detected]",
    )


def _write_music_lyrics(audio_path: Path, metadata: dict[str, Any], lyrics: str) -> Path:
    """Atomically replace a lyrics output without following an existing symlink."""
    lines = [f"Track: {audio_path.stem}"]
    duration_formatted = metadata.get("duration_formatted")
    if duration_formatted:
        lines.append(f"Duration: {duration_formatted}")
    tempo = metadata.get("tempo")
    if isinstance(tempo, int | float) and tempo > 0:
        lines.append(f"Tempo: {tempo:.0f} BPM")
    key = metadata.get("key")
    if isinstance(key, str) and key and key != "Unknown":
        lines.append(f"Key: {key}")
    if lyrics == "[Instrumental - No Speech Detected]":
        genre_hints = metadata.get("genre_hints")
        if isinstance(genre_hints, list) and genre_hints:
            lines.append(f"Style: {', '.join(str(hint) for hint in genre_hints)}")
    lines.extend(["", lyrics])

    lyrics_path = audio_path.parent / f"{audio_path.stem}_lyrics.txt"
    lyrics_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(lyrics_path, "\n".join(lines) + "\n", encoding="utf-8")
    return lyrics_path


def _require_music_transcript_output(
    transcript_path: Path | None,
    *,
    context: str,
) -> Path:
    """Reject missing transcriber output before it reaches readers or cleanup."""
    if transcript_path is None:
        raise TranscriptionError(f"{context} produced no transcript output")

    output_path = Path(transcript_path)
    if not output_path.is_file():
        raise TranscriptionError(f"{context} did not create transcript output: {output_path}")
    return output_path


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
            ("record NAME      ", "advanced OBS recording"),
            ("music FILE       ", "extract lyrics"),
            ("notes TRANSCRIPT ", "meeting notes"),
            ("joke TRANSCRIPT ", "generate joke"),
            ("meme TRANSCRIPT ", "generate meme"),
            ("query TEXT       ", "search transcripts"),
            ("vocab            ", "domain glossaries"),
            ("listen           ", "dictate (speech to type)"),
            ("tray             ", "resident voice hotkeys"),
            ("say FILE         ", "read a file aloud"),
            ("clean FILE       ", "remove silence / trim"),
            ("compare          ", "compare AI providers"),
            ("health           ", "provider health check"),
            ("doctor           ", "diagnostics"),
            ("info             ", "configuration"),
            ("init             ", "first-run setup"),
            ("shortcut         ", "install Quick Record launcher"),
            ("support-bundle   ", "create a diagnostic bundle"),
            ("version          ", "show version"),
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


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"scribe {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        None,
        "--version",
        "-V",
        is_eager=True,
        callback=_version_callback,
        help="Show the Scribe version and exit",
    ),
) -> None:
    """Scribe: local-first speech transcription, notes, and humor."""


@app.command(name="transcribe")
def transcribe_command(
    audio_file: Path = typer.Argument(
        ..., help="Path to audio/video file to transcribe", exists=True
    ),
    output_dir: Path | None = typer.Option(
        None, "--output-dir", "-o", help="Write output here instead of the configured folder"
    ),
    method: TranscriptionMethod = typer.Option(
        "auto",
        "--method",
        "-m",
        help=_TRANSCRIPTION_METHOD_HELP,
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
    notes: bool | None = typer.Option(
        None,
        "--notes/--no-notes",
        show_default=False,
        help="Generate meeting notes this run (paid text API); overrides the config default",
    ),
    keep_all: bool = typer.Option(
        False, "--keep-all", help="Keep all intermediate files (don't cleanup)"
    ),
    joke: bool | None = typer.Option(
        None,
        "--joke/--no-joke",
        show_default=False,
        help="Generate a joke this run (paid text API); overrides the config default",
    ),
    meme: bool | None = typer.Option(
        None,
        "--meme/--no-meme",
        show_default=False,
        help="Generate a meme this run (paid image API); overrides the config default",
    ),
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

      scribe transcribe meeting.mp4 --notes        # add notes this run (off by default)

      scribe transcribe technical.mp4 --vocabulary terms.txt
    """
    unified_progress = None
    config: ScribeConfig | None = None
    session: TranscriptionSession | None = None
    summary_saved = False
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
        if output_dir is not None:
            config.output_folder = output_dir

        # Fail fast on an explicit OpenAI request with no key, before the banner,
        # conversion, and progress all start and the error surfaces deep in the run.
        if method == "openai" and not config.openai_api_key:
            console.print(
                "[red]--method openai needs an OpenAI API key.[/red] "
                "Set OPENAI_API_KEY in your environment or .env, or run `scribe init`. "
                "For local transcription use --method local."
            )
            raise typer.Exit(1)

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
        will_generate_notes = _resolve_feature(notes, config.enable_notes) and has_api_key
        will_generate_joke = _resolve_feature(joke, config.enable_joke) and has_api_key
        will_generate_meme = _resolve_feature(meme, config.enable_meme) and has_api_key
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
        session.log_file = get_current_log_file()
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
                        raise TranscriptionError(
                            f"Compressed file is still too large ({compressed_size_mb:.1f}MB). "
                            "Use --method local for this recording."
                        )

                    console.print(f"Converted to MP3 ({compressed_size_mb:.1f}MB)")
                except ProcessError as e:
                    console.print(f"[bold red]Conversion failed:[/bold red] {e}")
                    console.print(
                        "[yellow]Tip: Check that ffmpeg is installed and the audio file is valid[/yellow]"
                    )
                    raise typer.Exit(1) from e
                except ScribeError:
                    raise
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
            raise TranscriptionError("Transcription produced no output file")

        if transcript_path.stat().st_size < 10:
            raise TranscriptionError("Transcription output file is empty")

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
        if will_generate_notes:
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
        if will_generate_joke:
            unified_progress.update_phase("finishing", 0.6, "Generating joke")
            result = generate_transcript_joke(transcript_path, config.openai_api_key)
            if result:
                joke_text, comedy_style = result

                # Save joke to session for later display
                session.joke_data = {"text": joke_text, "style": comedy_style}

        # Generate meme from transcript (enabled by default)
        if will_generate_meme:
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
        summary_saved = True
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

        # Show files with clickable links (works in Windows Terminal, iTerm2, VS Code terminal, etc.)
        if transcript_path:
            console.print(
                f"  [green]-[/green] [white]Transcript:[/white] [link={file_uri(transcript_path)}]{transcript_path}[/link]"
            )

        if not no_docx and session.docx_file:
            console.print(
                f"  [green]-[/green] [white]Document:[/white]   [link={file_uri(session.docx_file)}]{session.docx_file}[/link]"
            )

        if notes_path:
            console.print(
                f"  [green]-[/green] [white]Notes:[/white]      [link={file_uri(notes_path)}]{notes_path}[/link]"
            )

        if session.meme_file:
            console.print(
                f"  [green]-[/green] [white]Meme:[/white]       [link={file_uri(session.meme_file)}]{session.meme_file}[/link]"
            )

        console.print()

    except ScribeError as e:
        _persist_terminal_session_error(
            session, config.output_folder if config else None, e, summary_saved=summary_saved
        )
        exit_on_cli_error(e, log_unexpected=False)
    except typer.Exit as e:
        _persist_terminal_session_error(
            session, config.output_folder if config else None, e, summary_saved=summary_saved
        )
        if e.__cause__ is not None:
            exit_on_cli_error(e.__cause__, log_unexpected=not isinstance(e.__cause__, ScribeError))
        raise
    except Exception as e:
        _persist_terminal_session_error(
            session, config.output_folder if config else None, e, summary_saved=summary_saved
        )
        exit_on_cli_error(e)
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
        help=_TRANSCRIPTION_METHOD_HELP,
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
    notes: bool | None = typer.Option(
        None,
        "--notes/--no-notes",
        show_default=False,
        help="Generate meeting notes this run (paid text API); overrides the config default",
    ),
    keep_all: bool = typer.Option(
        False, "--keep-all", help="Keep all intermediate files (don't cleanup)"
    ),
    joke: bool | None = typer.Option(
        None,
        "--joke/--no-joke",
        show_default=False,
        help="Generate a joke this run (paid text API); overrides the config default",
    ),
    meme: bool | None = typer.Option(
        None,
        "--meme/--no-meme",
        show_default=False,
        help="Generate a meme this run (paid image API); overrides the config default",
    ),
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
        help="Browser to extract cookies from (chrome, firefox, edge) - fixes YouTube 403 errors",
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

      scribe url https://youtu.be/abc123 --notes        # add notes this run (off by default)

      scribe url https://youtube.com/watch?v=xyz --keep-download
    """
    unified_progress = None
    downloaded_file = None
    config = None
    session: TranscriptionSession | None = None
    summary_saved = False
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
        # Cookie extraction reads the browser's full cookie jar, so only accept a known
        # browser keyword and tell the user what it does.
        if cookies_browser:
            supported_browsers = {
                "brave",
                "chrome",
                "chromium",
                "edge",
                "firefox",
                "opera",
                "safari",
                "vivaldi",
            }
            if cookies_browser.lower() not in supported_browsers:
                console.print(
                    f"[red]Unsupported --cookies value '{cookies_browser}'. "
                    f"Choose one of: {', '.join(sorted(supported_browsers))}.[/red]"
                )
                raise typer.Exit(1)
            cookies_browser = cookies_browser.lower()
            console.print(
                f"[{ScribeTheme.TEXT_MUTED}]Reading {cookies_browser} cookies for the download "
                f"(grants the site access to that browser's session).[/{ScribeTheme.TEXT_MUTED}]"
            )
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
        will_generate_notes = _resolve_feature(notes, config.enable_notes) and has_api_key
        will_generate_joke = _resolve_feature(joke, config.enable_joke) and has_api_key
        will_generate_meme = _resolve_feature(meme, config.enable_meme) and has_api_key
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
        session.log_file = get_current_log_file()
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
                        raise TranscriptionError(
                            f"Compressed file is still too large ({compressed_size_mb:.1f}MB). "
                            "Use --method local for this recording."
                        )
                    console.print(f"Converted to MP3 ({compressed_size_mb:.1f}MB)")
                except ProcessError as e:
                    console.print(f"[bold red]Conversion failed:[/bold red] {e}")
                    raise typer.Exit(1) from e
                except ScribeError:
                    raise
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
            raise TranscriptionError("Transcription produced no output file")

        if transcript_path.stat().st_size < 10:
            raise TranscriptionError("Transcription output file is empty")

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
        if will_generate_notes:
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

        if will_generate_joke:
            unified_progress.update_phase("finishing", 0.6, "Generating joke")
            result_joke = generate_transcript_joke(transcript_path, config.openai_api_key)
            if result_joke:
                joke_text, comedy_style = result_joke
                session.joke_data = {"text": joke_text, "style": comedy_style}

        if will_generate_meme:
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
        summary_saved = True
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

        if transcript_path:
            console.print(
                f"  [green]-[/green] [white]Transcript:[/white] [link={file_uri(transcript_path)}]{transcript_path}[/link]"
            )

        if not no_docx and session.docx_file:
            console.print(
                f"  [green]-[/green] [white]Document:[/white]   [link={file_uri(session.docx_file)}]{session.docx_file}[/link]"
            )

        if notes_path:
            console.print(
                f"  [green]-[/green] [white]Notes:[/white]      [link={file_uri(notes_path)}]{notes_path}[/link]"
            )

        if session.meme_file:
            console.print(
                f"  [green]-[/green] [white]Meme:[/white]       [link={file_uri(session.meme_file)}]{session.meme_file}[/link]"
            )

        console.print()

    except ScribeError as e:
        _persist_terminal_session_error(
            session, config.output_folder if config else None, e, summary_saved=summary_saved
        )
        exit_on_cli_error(e, log_unexpected=False)
    except typer.Exit as e:
        _persist_terminal_session_error(
            session, config.output_folder if config else None, e, summary_saved=summary_saved
        )
        if e.__cause__ is not None:
            exit_on_cli_error(e.__cause__, log_unexpected=not isinstance(e.__cause__, ScribeError))
        raise
    except Exception as e:
        _persist_terminal_session_error(
            session, config.output_folder if config else None, e, summary_saved=summary_saved
        )
        exit_on_cli_error(e)
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
                if session is not None:
                    session.add_cleaned_file(downloaded_file)
                logger.info(f"Cleaned up downloaded file: {downloaded_file}")
                parent = downloaded_file.parent
                if parent.name.startswith("scribe_dl_") and parent.exists():
                    import shutil

                    shutil.rmtree(parent, ignore_errors=True)
            except Exception as cleanup_err:
                logger.warning(f"Could not clean up download: {cleanup_err}")
            else:
                if session is not None and session.end_time is not None:
                    try:
                        session.save_summary(config.output_folder)
                    except Exception as summary_err:
                        logger.warning(
                            "Could not refresh session summary after URL cleanup: %s",
                            summary_err,
                        )


def _run_obs_preflight() -> int:
    """Run a read-only OBS WebSocket preflight for Quick Record."""
    config = ScribeConfig()
    recorder = OBSRecorder(config)
    result = recorder.check_obs_preflight()

    status_style = {"pass": "green", "warn": "yellow", "fail": "red"}.get(result.status, "white")
    console.print("[bold cyan]OBS preflight[/bold cyan]")
    console.print(f"[{status_style}]{result.status.upper()}[/{status_style}] {result.message}")
    if result.endpoint:
        console.print(f"[dim]endpoint: {result.endpoint}[/dim]")
    if result.recording_active is not None:
        console.print(f"[dim]recording active: {result.recording_active}[/dim]")
    if result.details:
        console.print()
        for detail in result.details:
            console.print(f"[dim]- {escape(detail)}[/dim]")
    if result.fix_suggestion:
        console.print()
        console.print(f"[yellow]{escape(result.fix_suggestion)}[/yellow]")
    return 0 if result.ok else 1


@app.command()
def record(
    name: str | None = typer.Option(None, "--name", "-n", help="Meeting name for the recording"),
    check: bool = typer.Option(
        False,
        "--check",
        help="Run a read-only OBS preflight for Quick Record, then exit",
    ),
    auto_transcribe: bool = typer.Option(
        True,
        "--auto-transcribe/--no-auto-transcribe",
        help="Automatically transcribe after recording (default: True)",
    ),
    method: TranscriptionMethod = typer.Option(
        "auto", "--method", "-m", help=_TRANSCRIPTION_METHOD_HELP
    ),
    notes: bool | None = typer.Option(
        None,
        "--notes/--no-notes",
        show_default=False,
        help="Generate meeting notes after recording (paid text API); overrides the config default",
    ),
    joke: bool | None = typer.Option(
        None,
        "--joke/--no-joke",
        show_default=False,
        help="Generate a joke after recording (paid text API); overrides the config default",
    ),
    meme: bool | None = typer.Option(
        None,
        "--meme/--no-meme",
        show_default=False,
        help="Generate a meme after recording (paid image API); overrides the config default",
    ),
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

      # Record and also generate notes this run (extras are off by default)
      scribe record --name "Interview" --notes
    """
    if check:
        raise typer.Exit(_run_obs_preflight())

    session: TranscriptionSession | None = None
    session_output_dir: Path | None = None
    summary_saved = False
    incomplete_run = False
    try:
        # Load configuration
        config = ScribeConfig()
        session_output_dir = config.output_folder

        # Display header first
        _show_command_banner(console)

        # One-time recording-consent acknowledgement (responsible use, not legal advice)
        from scribe.cli.consent import ensure_recording_consent

        if not ensure_recording_consent(console):
            raise typer.Exit(0)

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

        # Start durable evidence before OBS or post-processing can fail.
        session = TranscriptionSession.create(name)
        session.log_file = get_current_log_file()

        # Show meeting name
        console.print(f"\n[cyan]Meeting:[/cyan] [white]{name}[/white]\n")

        # Record
        recorder = OBSRecorder(config)
        recording_path = recorder.record(name)
        session.add_file(recording_path, "source")

        console.print("\n[bold green]Media capture complete[/bold green]")
        console.print(f"File: {recording_path}\n")

        if not auto_transcribe:
            session.complete(success=True)
            summary_path = session.save_summary(config.output_folder)
            summary_saved = True
            _notify_saved_summary(summary_path)

            # For non-auto case on shortcut launch, pause here.
            if sys.platform == "win32" and os.environ.get("SCRIBE_FROM_SHORTCUT"):
                # Cosmetic "keep the window open" pause; the only ways input() can
                # fail here are a closed/redirected stdin (EOFError) or the user
                # pressing Ctrl-C, and in both cases we just let the window close.
                with suppress(EOFError, KeyboardInterrupt):
                    input("\n[Shortcut launcher] Press Enter to close this window...")

        # Auto-transcribe if requested
        # Note: Could use unified progress here, but record command shows individual
        # progress bars for each step which provides more detail during the workflow
        if auto_transcribe:
            console.print("[cyan]Starting automatic transcription...[/cyan]\n")
            artifact_errors: list[str] = []

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
                    console.print(
                        "[yellow]Tip: Check that ffmpeg is installed and the recording file is valid[/yellow]"
                    )
                    raise TranscriptionError(f"Recording conversion failed: {e}") from e
                except Exception as e:
                    raise TranscriptionError(f"Recording conversion failed: {e}") from e
            else:
                # OpenAI API accepts multiple formats but has 25MB limit
                try:
                    file_size_mb = recording_path.stat().st_size / (1024 * 1024)
                except (FileNotFoundError, OSError):
                    raise TranscriptionError(f"Cannot access recording file: {recording_path}")

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
                                "[yellow]Tip: Try using local GPU transcription for very long recordings[/yellow]"
                            )
                            raise TranscriptionError(
                                "Compressed recording is still too large "
                                f"({compressed_size_mb:.1f}MB)"
                            )

                        console.print(f"Converted to MP3 ({compressed_size_mb:.1f}MB)")
                    except ProcessError as e:
                        console.print(
                            "[yellow]Tip: Check that ffmpeg is installed and the recording file is valid[/yellow]"
                        )
                        raise TranscriptionError(f"Recording conversion failed: {e}") from e
                    except Exception as e:
                        if isinstance(e, TranscriptionError):
                            raise
                        raise TranscriptionError(f"Recording conversion failed: {e}") from e
                else:
                    # File size OK - use original recording
                    audio_file = recording_path

                console.print()
                console.print("[cyan]Transcribing with OpenAI API...[/cyan]")

            # Transcribe
            transcript_path = transcriber.transcribe(
                audio_file, method=chosen_method, session=session
            )
            if not transcript_path:
                raise TranscriptionError("Recording transcription produced no output file")
            if session.transcript_file != transcript_path:
                session.add_file(transcript_path, "transcript")

            # Structured sidecars (json/vtt/srt/md) so `scribe query` can find these too
            _write_structured_outputs(transcriber, transcript_path, config, None, session)

            # Generate DOCX
            try:
                docx_path = txt_to_docx(transcript_path)
                if not docx_path:
                    raise RuntimeError("no output file was returned")
                session.add_file(docx_path, "docx")
            except Exception as e:
                reason = f"DOCX generation failed: {e}"
                artifact_errors.append(reason)
                console.print(f"[yellow]{escape(reason)}[/yellow]")

            # Generate meeting notes if enabled
            notes_path = None
            notes_requested = _resolve_feature(notes, config.enable_notes)
            if notes_requested:
                if config.openai_api_key:
                    console.print("[cyan]Generating meeting notes...[/cyan]")
                    try:
                        from scribe.utils.notes_generator import NotesGenerator

                        notes_generator = NotesGenerator(
                            api_key=None,  # Let provider factory get the right key
                            model=config.notes_model,
                            provider_name=None,  # Will use SCRIBE_NOTES_PROVIDER env var
                        )
                        notes_path = notes_generator.generate_notes(transcript_path)
                        if not notes_path:
                            raise RuntimeError("no output file was returned")
                        session.add_file(notes_path, "notes")
                    except Exception as e:
                        reason = f"Notes generation failed: {e}"
                        artifact_errors.append(reason)
                        logger.error(reason)
                        console.print(f"[yellow]{escape(reason)}[/yellow]")
                else:
                    reason = "Notes requested but OPENAI_API_KEY is not configured"
                    artifact_errors.append(reason)
                    logger.warning(reason)
                    console.print(f"[yellow]{reason}[/yellow]")

            # Cleanup
            try:
                deleted = transcriber.cleanup_intermediate_files(recording_path.parent)
                if deleted:
                    logger.debug(f"Cleaned up {len(deleted)} intermediate files")
                    for deleted_file in deleted:
                        session.add_cleaned_file(Path(deleted_file))
            except Exception as e:
                reason = f"Intermediate cleanup failed: {e}"
                artifact_errors.append(reason)
                logger.warning(reason)
                console.print(f"[yellow]{escape(reason)}[/yellow]")

            # Debug: Log the resolved feature decisions
            logger.info(
                "Humor flags: joke=%s meme=%s has_api_key=%s",
                _resolve_feature(joke, config.enable_joke),
                _resolve_feature(meme, config.enable_meme),
                bool(config.openai_api_key),
            )

            # Generate joke if enabled
            if _resolve_feature(joke, config.enable_joke):
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

                            session.joke_data = {
                                "text": joke_text,
                                "style": comedy_style,
                            }
                        else:
                            reason = "Joke generation returned no result"
                            artifact_errors.append(reason)
                            logger.warning(reason)
                            console.print(f"[yellow]{reason}[/yellow]")
                    except Exception as e:
                        reason = f"Joke generation failed: {e}"
                        artifact_errors.append(reason)
                        logger.error(reason)
                        console.print(f"[yellow]{escape(reason)}[/yellow]")
                else:
                    reason = "Joke requested but OPENAI_API_KEY is not configured"
                    artifact_errors.append(reason)
                    logger.warning(reason)
                    console.print(f"[yellow]{reason}[/yellow]")

            # Generate meme from transcript if enabled
            if _resolve_feature(meme, config.enable_meme):
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
                            reason = "Meme generation returned no result"
                            artifact_errors.append(reason)
                            logger.warning(reason)
                            console.print(f"[yellow]{reason}[/yellow]")
                    except Exception as e:
                        reason = f"Meme generation failed: {e}"
                        artifact_errors.append(reason)
                        logger.error(reason)
                        console.print(f"[yellow]{escape(reason)}[/yellow]")
                else:
                    reason = "Meme requested but OPENAI_API_KEY is not configured"
                    artifact_errors.append(reason)
                    logger.warning(reason)
                    console.print(f"[yellow]{reason}[/yellow]")

            error_message = "; ".join(artifact_errors) if artifact_errors else None
            session.complete(
                success=not artifact_errors,
                error_message=error_message,
                outcome="partial" if artifact_errors else "success",
            )
            summary_path = session.save_summary(config.output_folder)
            summary_saved = True
            incomplete_run = bool(artifact_errors)

            console.print()
            if incomplete_run:
                console.print("[bold yellow]Recording & Transcription Partial[/bold yellow]")
                console.print("[yellow]Incomplete requested outputs:[/yellow]")
                for reason in artifact_errors:
                    console.print(f"  - {escape(reason)}")
            else:
                console.print("[bold green]Recording & Transcription Complete[/bold green]")
            _notify_saved_summary(summary_path)
            console.print()

            # Display output files with clickable links
            # Order: Transcript (txt) -> Document (docx) -> Notes -> Recording -> Meme
            console.print("[bold cyan]Output:[/bold cyan]")
            console.print()

            # Helper to format clickable file links
            def format_file_link(label: str, path: Path) -> str:
                return f"  {label:<11} [link={file_uri(path)}]{path}[/link]"

            console.print(format_file_link("Transcript:", transcript_path))
            if session.docx_file:
                console.print(format_file_link("Document:", session.docx_file))
            if notes_path:
                console.print(format_file_link("Notes:", notes_path))
            console.print(format_file_link("Recording:", recording_path))
            if session.meme_file:
                console.print(format_file_link("Meme:", session.meme_file))
            console.print()

            # For dedicated shortcut launches, pause at the end so all output is seen.
            if sys.platform == "win32" and os.environ.get("SCRIBE_FROM_SHORTCUT"):
                # Cosmetic "keep the window open" pause; the only ways input() can
                # fail here are a closed/redirected stdin (EOFError) or the user
                # pressing Ctrl-C, and in both cases we just let the window close.
                with suppress(EOFError, KeyboardInterrupt):
                    input("\n[Shortcut launcher] Press Enter to close this window...")

    except typer.Exit:
        raise
    except ScribeError as e:
        _persist_terminal_session_error(session, session_output_dir, e, summary_saved=summary_saved)
        exit_on_cli_error(e, log_unexpected=False)
    except Exception as e:
        _persist_terminal_session_error(session, session_output_dir, e, summary_saved=summary_saved)
        exit_on_cli_error(e)
    if incomplete_run:
        raise typer.Exit(1)


@app.command(name="batch")
def batch_transcribe(
    input_files: list[Path] = typer.Argument(..., help="Audio/video files to transcribe"),
    method: TranscriptionMethod = typer.Option(
        "auto",
        "--method",
        "-m",
        help=_TRANSCRIPTION_METHOD_HELP,
    ),
    model: ModelSize | None = typer.Option(None, "--model", help="Whisper model size"),
    language: str | None = typer.Option(
        None, "--language", "-l", help="Language (english, spanish, etc. or ISO code)"
    ),
    no_docx: bool = typer.Option(False, "--no-docx", help="Skip DOCX generation"),
    notes: bool | None = typer.Option(
        None,
        "--notes/--no-notes",
        show_default=False,
        help="Generate meeting notes for each file (paid text API); overrides the config default",
    ),
    joke: bool | None = typer.Option(
        None,
        "--joke/--no-joke",
        show_default=False,
        help="Generate a joke for each file (paid text API); overrides the config default",
    ),
    meme: bool | None = typer.Option(
        None,
        "--meme/--no-meme",
        show_default=False,
        help="Generate a meme for each file (paid image API); overrides the config default",
    ),
    vocabulary: str | None = typer.Option(
        None,
        "--vocabulary",
        "--vocab",
        help="Glossary name (e.g. finance, tech) or a .txt/.json file for domain terms",
    ),
    continue_on_error: bool = typer.Option(
        True,
        "--continue-on-error/--stop-on-error",
        help="Continue after failures; incomplete runs exit nonzero",
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

      scribe batch *.mp3 --notes        # add notes to every file (off by default)
    """
    incomplete_run = False
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
                console.print(f"[red]Invalid language code: {escape(language)}[/red]")
                raise typer.Exit(1)

        # Load custom vocabulary if provided
        custom_vocab = None
        if vocabulary:
            try:
                custom_vocab = CustomVocabulary.load(vocabulary)
                console.print(f"[cyan]Loaded {len(custom_vocab)} custom vocabulary terms[/cyan]")
            except Exception as e:
                console.print(f"[red]Failed to load vocabulary: {escape(str(e))}[/red]")
                raise typer.Exit(1)

        # Validate all files exist and retain missing inputs in final accounting.
        results: list[BatchResult] = []
        valid_files: list[Path] = []
        for audio_file in input_files:
            if not audio_file.exists():
                console.print(
                    f"[yellow]Warning: File not found: {escape(str(audio_file))}[/yellow]",
                    soft_wrap=True,
                )
                results.append(
                    {"file": audio_file.name, "status": "failed", "error": "File not found"}
                )
                if not continue_on_error:
                    raise typer.Exit(1)
            else:
                valid_files.append(audio_file)

        # Display batch header
        if valid_files:
            _show_command_banner(console)
            console.print(
                Panel.fit(
                    f"[white]{len(valid_files)} file(s)[/white]",
                    border_style="cyan",
                    padding=(0, 1),
                )
            )
            console.print()

        # Resolve paid AI features once for the whole batch. Missing credentials
        # must remain visible as an incomplete requested outcome.
        has_api_key = bool(config.openai_api_key)
        notes_requested = _resolve_feature(notes, config.enable_notes)
        joke_requested = _resolve_feature(joke, config.enable_joke)
        meme_requested = _resolve_feature(meme, config.enable_meme)
        feature_preflight_errors: list[str] = []
        if not has_api_key:
            if notes_requested:
                feature_preflight_errors.append(
                    "Notes not generated: OPENAI_API_KEY is not configured"
                )
            if joke_requested:
                feature_preflight_errors.append(
                    "Joke not generated: OPENAI_API_KEY is not configured"
                )
            if meme_requested:
                feature_preflight_errors.append(
                    "Meme not generated: OPENAI_API_KEY is not configured"
                )
        will_generate_notes = notes_requested and has_api_key
        will_generate_joke = joke_requested and has_api_key
        will_generate_meme = meme_requested and has_api_key

        # Process each file
        for idx, audio_file in enumerate(valid_files, 1):
            # Bound before the try so the except handler never hits an unbound
            # logger if validation fails before per-file setup_logging runs.
            logger = get_logger(__name__)
            session: TranscriptionSession | None = None
            console.print(
                f"[bold cyan]File {idx}/{len(valid_files)}:[/bold cyan] {escape(audio_file.name)}"
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
                session.log_file = get_current_log_file()
                session.add_file(audio_path, "source")
                artifact_errors = feature_preflight_errors.copy()

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
                        artifact_errors.append(f"DOCX generation failed: {e}")

                # Generate notes
                if will_generate_notes:
                    try:
                        from scribe.utils.notes_generator import NotesGenerator

                        notes_generator = NotesGenerator(api_key=None, model=config.notes_model)
                        notes_path = notes_generator.generate_notes(transcript_path)
                        session.add_file(notes_path, "notes")
                    except Exception as e:
                        logger.error(f"Notes generation failed: {e}")
                        artifact_errors.append(f"Notes generation failed: {e}")

                # Generate joke
                if will_generate_joke:
                    try:
                        joke_result = generate_transcript_joke(
                            transcript_path, config.openai_api_key
                        )
                        if joke_result:
                            joke_text, comedy_style = joke_result
                            session.joke_data = {"text": joke_text, "style": comedy_style}
                        else:
                            artifact_errors.append("Joke generation returned no result")
                    except Exception as e:
                        logger.error(f"Joke generation failed: {e}")
                        artifact_errors.append(f"Joke generation failed: {e}")

                # Generate meme
                if will_generate_meme:
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
                        else:
                            artifact_errors.append("Meme generation returned no result")
                    except Exception as e:
                        logger.error(f"Meme generation failed: {e}")
                        artifact_errors.append(f"Meme generation failed: {e}")

                # Cleanup
                transcriber.cleanup_intermediate_files(audio_path.parent)

                # A usable transcript with a missing requested artifact is partial,
                # not successful. Persist the reason with the session summary.
                error_message = "; ".join(artifact_errors) or None
                session.complete(
                    success=not artifact_errors,
                    error_message=error_message,
                    outcome="partial" if artifact_errors else "success",
                )
                session.save_summary(config.output_folder)

                if artifact_errors:
                    results.append(
                        {
                            "file": audio_file.name,
                            "status": "partial",
                            "transcript": transcript_path,
                            "error": error_message or "Requested artifact was not generated",
                        }
                    )
                    console.print(f"[yellow]! Partial: {escape(audio_file.name)}[/yellow]")
                    for artifact_error in artifact_errors:
                        console.print(f"[dim]  {escape(artifact_error)}[/dim]")
                else:
                    results.append(
                        {
                            "file": audio_file.name,
                            "status": "success",
                            "transcript": transcript_path,
                        }
                    )
                    console.print(f"[green]+ Completed: {escape(audio_file.name)}[/green]")
                console.print()

            except Exception as e:
                logger.error(f"Failed to process {audio_file}: {e}")
                _persist_failed_session(session, config.output_folder, e)
                results.append({"file": audio_file.name, "status": "failed", "error": str(e)})
                console.print(f"[red]x Failed: {escape(audio_file.name)}[/red]")
                console.print(f"[dim]Error: {escape(str(e))}[/dim]")
                console.print()

                if not continue_on_error:
                    break

        # Summary
        console.print("-" * 60)
        console.print()
        console.print("[bold cyan]Batch Summary:[/bold cyan]")

        success_count = sum(1 for r in results if r["status"] == "success")
        partial_count = sum(1 for r in results if r["status"] == "partial")
        failed_count = sum(1 for r in results if r["status"] == "failed")

        console.print(f"  [green]+ Successful:[/green] {success_count}")
        console.print(f"  [yellow]! Partial:[/yellow] {partial_count}")
        console.print(f"  [red]x Failed:[/red] {failed_count}")
        console.print()

        if partial_count > 0 or failed_count > 0:
            console.print("[yellow]Incomplete files:[/yellow]")
            for batch_result in results:
                if batch_result["status"] in {"partial", "failed"}:
                    console.print(
                        f"  - {escape(str(batch_result['file']))} "
                        f"({escape(str(batch_result['status']))}): "
                        f"{escape(str(batch_result.get('error', 'Unknown error')))}"
                    )
            console.print()
        incomplete_run = partial_count > 0 or failed_count > 0

    except typer.Exit:
        raise
    except ScribeError as e:
        exit_on_cli_error(e, log_unexpected=False)
    except Exception as e:
        exit_on_cli_error(e)
    if incomplete_run:
        raise typer.Exit(1)


@app.command(name="music")
def music_transcribe(
    audio_files: list[Path] = typer.Argument(
        ..., help="Path to music/audio file(s) or folder to transcribe"
    ),
    method: TranscriptionMethod = typer.Option(
        "auto",
        "--method",
        "-m",
        help=_TRANSCRIPTION_METHOD_HELP,
    ),
    model: ModelSize | None = typer.Option(None, "--model", help="Whisper model size"),
    language: str | None = typer.Option(
        None, "--language", "-l", help="Language (english, spanish, etc. or ISO code)"
    ),
    continue_on_error: bool = typer.Option(
        True,
        "--continue-on-error/--stop-on-error",
        help="Continue after failures; incomplete runs exit nonzero",
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
    incomplete_run = False
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
        results: list[MusicResult] = []
        files_to_process: list[Path] = []
        for path in audio_files:
            if not path.exists():
                console.print(f"[yellow]Warning: Path not found: {path}[/yellow]")
                results.append({"file": path.name, "status": "failed", "error": "Path not found"})
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
                if not dir_files:
                    console.print(f"[yellow]Warning: No supported audio files in: {path}[/yellow]")
                    results.append(
                        {
                            "file": path.name,
                            "status": "failed",
                            "error": "No supported audio files found",
                        }
                    )
                    if not continue_on_error:
                        raise typer.Exit(1)
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
        for idx, audio_path in enumerate(files_to_process, 1):
            track_name = audio_path.stem
            vocals_path = None  # Initialize for cleanup in exception handler
            vocal_segments: list[dict[str, float]] | None = None
            slice_dir: Path | None = None  # cleaned in the finally regardless of outcome
            sliced_paths: list[Path] | None = None
            transient_outputs: list[Path] = []
            segment_failure_count = 0
            session: TranscriptionSession | None = None
            result_start = len(results)

            try:
                # Setup logging for this track
                logger = setup_logging(track_name, config.log_folder)
                session = TranscriptionSession.create(track_name)
                session.log_file = get_current_log_file()
                session.add_file(audio_path, "source")

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
                        not_music_reason = str(music_analysis.get("reason") or "Not music")
                        console.print(" [red]not music[/red]")
                        console.print(f"  [dim]{escape(not_music_reason)}[/dim]")
                        console.print()
                        results.append(
                            {
                                "file": audio_path.name,
                                "status": "failed",
                                "error": f"Not music: {not_music_reason}",
                            }
                        )
                        if not continue_on_error:
                            break
                        continue

                    tempo = music_metadata.get("tempo")
                    key = music_metadata.get("key", "?")

                    # Only show measurable values
                    info_parts = []
                    if isinstance(tempo, int | float) and tempo > 0:
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
                except Exception as e:
                    console.print(" [yellow]unavailable, using full audio[/yellow]")
                    logger.warning(f"VAD failed, will transcribe full audio: {e}")
                    vocal_segments = None
                else:
                    if not vocal_segments:
                        # No vocals detected - it's instrumental music
                        console.print(" [yellow]none found[/yellow]")
                        raise TranscriptionError("No speech detected in audio (instrumental track)")

                    console.print(f" [green]found {len(vocal_segments)}[/green]")

                # Step 4: Slice audio by vocal segments
                console.print("  [dim]Slicing audio...[/dim]", end="")
                if vocal_segments is None:
                    console.print(" [yellow]full audio fallback[/yellow]")
                    sliced_paths = None
                else:
                    try:
                        import tempfile

                        from scribe.utils.audio_slicer import slice_audio_by_segments

                        # Create temp directory for slices
                        slice_dir = Path(tempfile.mkdtemp(prefix="vocal_slices_"))
                        sliced_paths = slice_audio_by_segments(
                            vocals_path, vocal_segments, slice_dir
                        )
                        console.print(f" [green]{len(sliced_paths)} slices[/green]")
                    except Exception as e:
                        logger.warning(f"Audio slicing failed, will transcribe full audio: {e}")
                        console.print(" [yellow]full audio fallback[/yellow]")
                        sliced_paths = None

                # Step 5: Transcribe segments
                console.print("  [dim]Transcribing...[/dim]", end="")
                try:
                    all_lyrics: list[str] = []

                    if sliced_paths:
                        # Transcribe each segment separately
                        for i, slice_path in enumerate(sliced_paths):
                            try:
                                segment_transcript = transcriber.transcribe(
                                    slice_path,
                                    method=method,
                                    music_mode=True,
                                    session=session,
                                )
                                segment_transcript = _require_music_transcript_output(
                                    segment_transcript,
                                    context=f"Segment {i + 1} transcription",
                                )
                                transient_outputs.append(segment_transcript)

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

                            except Exception as e:
                                segment_failure_count += 1
                                logger.warning(
                                    f"Segment {i + 1}/{len(sliced_paths)} transcription failed: {e}"
                                )
                                continue

                        # Combine all segments
                        lyrics = "\n\n".join(all_lyrics)
                        if segment_failure_count == len(sliced_paths):
                            raise TranscriptionError(
                                f"Transcription failed for all {len(sliced_paths)} vocal segments"
                            )
                        if segment_failure_count and not lyrics.strip():
                            raise TranscriptionError(
                                "No usable lyrics remained after "
                                f"{segment_failure_count} vocal segment failures"
                            )
                        # (sliced audio is cleaned in the per-file finally below)
                    else:
                        # Fallback: transcribe full audio
                        transcript_path = transcriber.transcribe(
                            vocals_path,
                            method=method,
                            music_mode=True,
                            session=session,
                        )
                        transcript_path = _require_music_transcript_output(
                            transcript_path,
                            context="Full-track transcription",
                        )
                        transient_outputs.append(transcript_path)

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

                    if segment_failure_count:
                        console.print(
                            f" [yellow]partial ({segment_failure_count} segment failures)[/yellow]"
                        )
                    else:
                        console.print(" [green]done[/green]")

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
                    # 1. Exact match to known hallucination -> instrumental
                    # 2. Very short (< 3 words) -> likely hallucination
                    # 3. Short (< 10 words) + contains hallucination phrase -> instrumental
                    # 4. Single line + hallucination phrase -> instrumental
                    # 5. Otherwise -> keep it (could be valid sparse lyrics)

                    is_hallucination = (
                        is_exact_hallucination
                        or word_count < 3
                        or (word_count < 10 and has_hallucination_phrase)
                        or (line_count == 1 and has_hallucination_phrase)
                    )

                    if is_hallucination and segment_failure_count:
                        raise TranscriptionError(
                            "No usable lyrics remained after "
                            f"{segment_failure_count} vocal segment failures"
                        )

                    if is_hallucination:
                        logger.debug(
                            f"Detected hallucination: '{lyrics[:50]}...' ({word_count} words)"
                        )
                        lyrics = "[Instrumental - No Speech Detected]"

                    lyrics_path = _write_music_lyrics(audio_path, music_metadata, lyrics)

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
                    elif segment_failure_count:
                        partial_reason = (
                            f"{segment_failure_count} of {len(sliced_paths or [])} "
                            "vocal segments failed"
                        )
                        console.print(f"  [yellow]PARTIAL[/yellow] Lyrics: {lyrics_path.name}")
                        console.print(f"  [dim]{partial_reason}[/dim]")
                        results.append(
                            {
                                "file": audio_path.name,
                                "status": "partial",
                                "lyrics": lyrics_path,
                                "error": partial_reason,
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
                        console.print(" [green]done[/green]")
                        lyrics_path = _write_instrumental_marker(audio_path, music_metadata)
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
                    lyrics_path = _write_instrumental_marker(audio_path, music_metadata)
                    console.print("  [yellow]INST[/yellow] Instrumental (no vocals detected)")
                    console.print()
                    results.append(
                        {
                            "file": audio_path.name,
                            "status": "instrumental",
                            "lyrics": lyrics_path,
                        }
                    )
                else:
                    # Actual failure
                    logger.error(f"Failed to process {audio_path.name}: {e}")
                    console.print(f"  [red]FAIL[/red] Failed: {e}")
                    console.print()
                    results.append({"file": audio_path.name, "status": "failed", "error": str(e)})

            finally:
                if len(results) == result_start:
                    results.append(
                        {
                            "file": audio_path.name,
                            "status": "failed",
                            "error": "Track ended without a terminal result",
                        }
                    )

                terminal_result = results[-1]
                cleanup_errors: list[str] = []
                final_paths = {audio_path}
                terminal_lyrics = terminal_result.get("lyrics")
                if terminal_lyrics is not None:
                    final_paths.add(terminal_lyrics)

                cleanup_candidates = list(transient_outputs)
                if session is not None and session.audio_file is not None:
                    cleanup_candidates.append(session.audio_file)
                if vocals_path is not None:
                    cleanup_candidates.append(vocals_path)

                seen_cleanup_paths: set[Path] = set()
                for cleanup_path in cleanup_candidates:
                    if cleanup_path in final_paths or cleanup_path in seen_cleanup_paths:
                        continue
                    seen_cleanup_paths.add(cleanup_path)
                    try:
                        if cleanup_path.exists() or cleanup_path.is_symlink():
                            cleanup_path.unlink()
                            logger.debug("Cleaned up intermediate file: %s", cleanup_path.name)
                            if session is not None:
                                session.add_cleaned_file(cleanup_path)
                    except OSError as cleanup_error:
                        cleanup_errors.append(f"Cleanup failed: {cleanup_error}")

                if slice_dir is not None:
                    try:
                        if slice_dir.exists():
                            shutil.rmtree(slice_dir)
                            if session is not None:
                                for created_path in session.files_created:
                                    if created_path.is_relative_to(slice_dir):
                                        session.add_cleaned_file(created_path)
                    except OSError as cleanup_error:
                        cleanup_errors.append(f"Cleanup failed: {cleanup_error}")

                for cleanup_issue in cleanup_errors:
                    _add_music_issue(terminal_result, cleanup_issue)
                    logger.warning(cleanup_issue)
                    console.print(f"  [yellow]{escape(cleanup_issue)}[/yellow]")

                if session is not None:
                    _persist_music_session(session, terminal_result, config.output_folder)

            if not continue_on_error and terminal_result["status"] in {"partial", "failed"}:
                break

        # Print summary
        console.print()
        console.print("[bold]Summary:[/bold]")
        success_count = sum(1 for r in results if r["status"] == "success")
        instrumental_count = sum(1 for r in results if r["status"] == "instrumental")
        partial_count = sum(1 for r in results if r["status"] == "partial")
        failed_count = sum(1 for r in results if r["status"] == "failed")

        console.print(f"  [green]With Lyrics:[/green] {success_count}")
        console.print(f"  [yellow]Instrumental:[/yellow] {instrumental_count}")
        console.print(f"  [yellow]Partial:[/yellow] {partial_count}")
        console.print(f"  [red]Failed:[/red] {failed_count}")
        console.print()

        if partial_count > 0 or failed_count > 0:
            console.print("[yellow]Incomplete files:[/yellow]")
            for result in results:
                if result["status"] in {"partial", "failed"}:
                    console.print(
                        f"  - {result['file']} ({result['status']}): "
                        f"{result.get('error', 'Unknown error')}"
                    )
            console.print()
        incomplete_run = partial_count > 0 or failed_count > 0

    except typer.Exit:
        raise
    except ScribeError as e:
        exit_on_cli_error(e, log_unexpected=False)
    except Exception as e:
        exit_on_cli_error(e)
    if incomplete_run:
        raise typer.Exit(1)


@app.command(name="rec")
def rec_shortcut(
    name: str | None = typer.Argument(None, help="Meeting name (optional)"),
    check: bool = typer.Option(
        False,
        "--check",
        help="Run a read-only OBS preflight for Quick Record, then exit",
    ),
) -> None:
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
    record(
        name=name,
        check=check,
        auto_transcribe=True,
        method="auto",
        # None = respect the user's config defaults for the paid AI extras
        # (off unless they opted in), rather than forcing them on.
        notes=None,
        joke=None,
        meme=None,
    )


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
        exit_on_cli_error(e, log_unexpected=False)
    except typer.Exit:
        raise
    except Exception as e:
        exit_on_cli_error(e)


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
                console.print(
                    f"  Attempt {attempt['attempt']} (score: {score_str}): [link={file_uri(attempt_path)}]{attempt_path}[/link]"
                )
        console.print()

    except ScribeError as e:
        exit_on_cli_error(e, log_unexpected=False)
    except Exception as e:
        exit_on_cli_error(e)


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

        abs_path = notes_path.absolute()
        console.print(f"[bold cyan]Notes:[/bold cyan] [link={file_uri(abs_path)}]{abs_path}[/link]")
        console.print()

    except ScribeError as e:
        exit_on_cli_error(e, log_unexpected=False)
    except Exception as e:
        exit_on_cli_error(e)


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
            "[bold red]Error:[/bold red] nothing to compare - no cloud API keys and "
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
        console.print(f"[bold cyan]->[/bold cyan] {verdict}")
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
        exit_on_cli_error(e, log_unexpected=False)
    except Exception as e:
        exit_on_cli_error(e)


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
        # Where the config lives and which AI features are on, so the effective
        # state is visible in one place (env vars can override the wizard's choices).
        from scribe.config_file import CONFIG_PATH

        cfg_state = "present" if CONFIG_PATH.exists() else "defaults"
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]file[/{ScribeTheme.TEXT_PRIMARY}]      "
            f"[{ScribeTheme.TEXT_MUTED}]{CONFIG_PATH} ({cfg_state})[/{ScribeTheme.TEXT_MUTED}]"
        )
        features = (
            f"notes:{'on' if config.enable_notes else 'off'} "
            f"joke:{'on' if config.enable_joke else 'off'} "
            f"meme:{'on' if config.enable_meme else 'off'}"
        )
        console.print(
            f"  [{ScribeTheme.TEXT_PRIMARY}]features[/{ScribeTheme.TEXT_PRIMARY}]  "
            f"[{ScribeTheme.TEXT_MUTED}]{features}[/{ScribeTheme.TEXT_MUTED}]"
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

        # Local LLM (Ollama) section - free, offline notes. Surfaces the smart
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

        # Recommendation - $0-first: local transcription runs on any machine, so
        # it is always the free default. The paid API is an explicit opt-in.
        tx_kind = "GPU" if gpu_config.recommendation == "local" else "CPU"
        notes_bit = " + Ollama notes" if ollama_models else ""
        console.print(
            f"[{ScribeTheme.SUCCESS}]$0 local ready: {tx_kind} transcription{notes_bit}"
            f"[/{ScribeTheme.SUCCESS}]"
        )
        if tx_kind == "CPU":
            console.print(
                f"  [{ScribeTheme.TEXT_MUTED}]CPU is slower; pass --method openai to use "
                f"the paid OpenAI API instead.[/{ScribeTheme.TEXT_MUTED}]"
            )
        console.print()

    except ScribeError as e:
        exit_on_cli_error(e, log_unexpected=False)
    except Exception as e:
        exit_on_cli_error(e)


@app.command()
def doctor(
    live: bool = typer.Option(
        False,
        "--live",
        help="Opt in to live provider API checks for configured keys.",
    ),
) -> None:
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
    if live:
        console.print("[dim]Live provider checks enabled for configured API keys.[/dim]")
    else:
        console.print(
            "[dim]Live provider checks skipped. Use `scribe doctor --live` to validate API keys.[/dim]"
        )
    console.print()

    # Run diagnostics with progress spinner
    diagnostics = SystemDiagnostics()
    with console.status(
        f"[{ScribeTheme.PRIMARY}]Running diagnostics...[/{ScribeTheme.PRIMARY}]",
        spinner="dots",
    ):
        results = diagnostics.run_all_checks(live=live)

    # Group results by status for cleaner display
    passed = [r for r in results if r.status == "pass"]
    warnings = [r for r in results if r.status == "warn"]
    failures = [r for r in results if r.status == "fail"]

    # Headline $0-local verdict, derived from the readiness checks already run
    # (no extra probe). This is the "can I run this for free?" answer up front.
    tx = next((r for r in results if r.name == "Local Transcription ($0)"), None)
    notes = next((r for r in results if r.name == "Local Notes ($0)"), None)
    if tx is not None:
        can_notes = notes is not None and notes.status == "pass"
        if tx.status == "pass":
            what = "transcribe and take notes" if can_notes else "transcribe"
            console.print(
                f"[bold {ScribeTheme.SUCCESS}]$0 LOCAL[/bold {ScribeTheme.SUCCESS}]  "
                f"[{ScribeTheme.SUCCESS}]You can {what} on this machine with no API key.[/{ScribeTheme.SUCCESS}]"
            )
            console.print(
                f"  [{ScribeTheme.TEXT_MUTED}]transcription: {escape(tx.message)}[/{ScribeTheme.TEXT_MUTED}]"
            )
            if notes is not None:
                console.print(
                    f"  [{ScribeTheme.TEXT_MUTED}]notes: {escape(notes.message)}[/{ScribeTheme.TEXT_MUTED}]"
                )
        else:
            console.print(
                f"[bold {ScribeTheme.WARNING}]$0 LOCAL[/bold {ScribeTheme.WARNING}]  "
                f"[{ScribeTheme.WARNING}]Local transcription needs setup: {escape(tx.message)}[/{ScribeTheme.WARNING}]"
            )
        console.print()

    # Display failures first (if any)
    if failures:
        console.print(f"[bold {ScribeTheme.ERROR}]FAILED[/bold {ScribeTheme.ERROR}]")
        for result in failures:
            console.print(
                f"  [{ScribeTheme.ERROR}]×[/{ScribeTheme.ERROR}] "
                f"[{ScribeTheme.TEXT_PRIMARY}]{escape(result.name)}[/{ScribeTheme.TEXT_PRIMARY}]"
            )
            console.print(
                f"    [{ScribeTheme.TEXT_MUTED}]{escape(result.message)}[/{ScribeTheme.TEXT_MUTED}]"
            )
            if result.fix_suggestion:
                console.print(
                    f"    [{ScribeTheme.PRIMARY}]-> {escape(result.fix_suggestion)}[/{ScribeTheme.PRIMARY}]"
                )
        console.print()

    # Display warnings (if any)
    if warnings:
        console.print(f"[bold {ScribeTheme.WARNING}]WARNINGS[/bold {ScribeTheme.WARNING}]")
        for result in warnings:
            console.print(
                f"  [{ScribeTheme.WARNING}]![/{ScribeTheme.WARNING}] "
                f"[{ScribeTheme.TEXT_PRIMARY}]{escape(result.name)}[/{ScribeTheme.TEXT_PRIMARY}]"
            )
            console.print(
                f"    [{ScribeTheme.TEXT_MUTED}]{escape(result.message)}[/{ScribeTheme.TEXT_MUTED}]"
            )
            if result.fix_suggestion:
                console.print(
                    f"    [{ScribeTheme.PRIMARY}]-> {escape(result.fix_suggestion)}[/{ScribeTheme.PRIMARY}]"
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
            first_line = result.message.splitlines()[0] if result.message else ""
            table.add_row("+", escape(result.name), escape(first_line))

        console.print(table)
        console.print()

    # Summary line - extremely polished QOL
    pass_count, warn_count, fail_count = diagnostics.get_summary()

    if fail_count == 0 and warn_count == 0:
        check_label = "check" if pass_count == 1 else "checks"
        console.print(f"[{ScribeTheme.SUCCESS}]+ All systems ready[/] ({pass_count} {check_label})")
        console.print(
            '[dim]Try: [cyan]scribe rec "Team sync"[/cyan] or create a launcher with [cyan]scribe shortcut[/cyan][/dim]'
        )
    elif fail_count == 0:
        warning_label = "warning" if warn_count == 1 else "warnings"
        console.print(
            f"[{ScribeTheme.WARNING}]Ready with warnings[/] "
            f"({pass_count} passed, {warn_count} {warning_label})"
        )
    else:
        failed_label = "failure" if fail_count == 1 else "failures"
        warning_label = "warning" if warn_count == 1 else "warnings"
        console.print(
            f"[{ScribeTheme.ERROR}]Needs attention[/] "
            f"({fail_count} {failed_label}, {warn_count} {warning_label})"
        )

    console.print()

    if fail_count > 0:
        try:
            from rich.prompt import Confirm

            if Confirm.ask("Run the setup wizard to fix issues?", default=False, console=console):
                from scribe.cli.init import run_wizard

                run_wizard(console=console, force=True)
        except Exception as e:
            # The wizard offer is a best-effort self-heal; never let it mask the
            # underlying doctor failure (we still exit non-zero below).
            logger.debug("Setup-wizard self-heal prompt failed: %s", e)
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
    if openai_key:
        api_keys["openai"] = openai_key
    if xai_key:
        api_keys["xai"] = xai_key
    if anthropic_key:
        api_keys["anthropic"] = anthropic_key
    if gemini_key:
        api_keys["gemini"] = gemini_key

    provider_key_names = {
        "openai": "OPENAI_API_KEY",
        "xai": "XAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "gemini": "GEMINI_API_KEY",
    }
    if provider is not None and provider not in provider_key_names:
        console.print(
            f"[{ScribeTheme.ERROR}]Unknown provider: {escape(provider)}[/{ScribeTheme.ERROR}]"
        )
        console.print(
            f"[{ScribeTheme.TEXT_MUTED}]Choose one of: openai, xai, anthropic, gemini.[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print()
        raise typer.Exit(1)

    if not api_keys:
        console.print(f"[{ScribeTheme.WARNING}]no api keys configured[/{ScribeTheme.WARNING}]")
        console.print(
            f"[{ScribeTheme.TEXT_MUTED}]set OPENAI_API_KEY, XAI_API_KEY, etc.[/{ScribeTheme.TEXT_MUTED}]"
        )
        console.print()
        raise typer.Exit(1)

    if provider is not None and provider not in api_keys:
        key_name = provider_key_names[provider]
        console.print(
            f"[{ScribeTheme.WARNING}]{key_name} is not configured[/{ScribeTheme.WARNING}]"
        )
        console.print(
            f"[{ScribeTheme.TEXT_MUTED}]Set {key_name}, then retry `scribe health --provider {provider}`.[/{ScribeTheme.TEXT_MUTED}]"
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

        except ScribeError as e:
            results.append((provider_name, False, str(e)[:30]))
            all_healthy = False
        except Exception as e:
            logger.debug("Provider health check failed for %s: %s", provider_name, e)
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

    Creates a diagnostic package containing system information, recursively
    redacted environment and diagnostic values, bounded durable session outcomes,
    and opaque recent-log metadata. Log filenames and contents are excluded.

    The bundle is saved as JSON for local debugging or support. Review it before
    sharing because diagnostic text can still be sensitive.

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
        console.print("[cyan]Gathering durable session and log metadata...[/cyan]")

        bundle_path = generate_support_bundle_cli(output_dir)

        console.print()
        console.print("[bold green]Support bundle created successfully[/bold green]")
        console.print()
        console.print(f"[cyan]Location:[/cyan] {escape(str(bundle_path))}", soft_wrap=True)
        console.print()
        console.print("[dim]This bundle contains:[/dim]")
        console.print("[dim]  - System information (OS, Python, GPU)[/dim]")
        console.print("[dim]  - Redacted environment configuration[/dim]")
        console.print("[dim]  - Diagnostic results[/dim]")
        console.print("[dim]  - Redacted recent session summaries[/dim]")
        console.print("[dim]  - Recent log metadata[/dim]")
        console.print()
        console.print("Log contents are not included.")
        console.print("Automated redaction covers known home-identifier and credential patterns.")
        console.print("[bold]Review the file before sharing it for troubleshooting.[/bold]")
        console.print()

    except ScribeError as e:
        exit_on_cli_error(e, log_unexpected=False)
    except Exception as e:
        exit_on_cli_error(
            e,
            recovery_hint=(
                "Check the error above and output-directory permissions. "
                "If a log path is shown, inspect it, then retry."
            ),
        )


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

    except ScribeError as e:
        exit_on_cli_error(e, log_unexpected=False)
    except FileNotFoundError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)
    except RuntimeError as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        exit_on_cli_error(e)


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
    mode: str = typer.Option(
        "toggle",
        "--mode",
        help="toggle (tap F9 on/off, default), hold (push-to-talk), or continuous",
    ),
    inject: str = typer.Option(
        "paste", "--inject", help="How to insert text: paste (clipboard) or type (keystrokes)"
    ),
    model: str | None = typer.Option(
        None, "--model", help="Whisper model for dictation (default: small on GPU, base on CPU)"
    ),
    language: str | None = typer.Option(
        None, "--language", "-l", help="Spoken language (ISO 639-1); auto-detect if omitted"
    ),
) -> None:
    """
    Dictate: speak and have your words inserted into the focused window.

    A real-time mode separate from the batch pipeline. Default is tap-to-toggle:
    tap F9 to start, tap again to insert; Esc quits. Use --mode hold for
    push-to-talk or --mode continuous for always-listening. Needs a microphone and
    the voice extra (pip install "scribe[voice]").
    """
    from scribe.cli.voice import run_listen

    raise typer.Exit(run_listen(console, model=model, language=language, mode=mode, inject=inject))


@app.command(name="say")
def say_command(
    file: Path | None = typer.Argument(
        None, help="Transcript or notes file to read aloud", exists=True
    ),
    selection: bool = typer.Option(
        False, "--selection", "-s", help="Read the currently selected text aloud"
    ),
    clipboard: bool = typer.Option(False, "--clipboard", help="Read the clipboard contents aloud"),
    rate: int | None = typer.Option(None, "--rate", help="Speech rate in words per minute"),
    voice: str | None = typer.Option(None, "--voice", help="Voice name or id substring to use"),
    speed: float | None = typer.Option(
        None, "--speed", help="Playback speed multiplier, e.g. 1.2 (0.5-2.0)"
    ),
) -> None:
    """
    Read a file, the current selection, or the clipboard aloud with a local voice.

    Examples: `scribe say notes.md`, `scribe say --selection`, `scribe say --speed 1.2`.
    Esc stops playback. Needs the voice extra (pip install "scribe[voice]").
    """
    from scribe.cli.voice import run_say

    raise typer.Exit(
        run_say(
            console,
            file,
            rate=rate,
            voice=voice,
            speed=speed,
            use_selection=selection,
            use_clipboard=clipboard,
        )
    )


@app.command(name="tray")
def tray_command(
    check: bool = typer.Option(
        False,
        "--check",
        help="Validate voice/tray dependencies and settings, then exit",
    ),
    setup: bool = typer.Option(
        False,
        "--setup",
        help="Download the dictation model and set up a read-aloud voice, then exit",
    ),
    startup: str | None = typer.Option(
        None,
        "--startup",
        help="Run the tray at login: install | remove | status",
    ),
    no_tray: bool = typer.Option(
        False,
        "--no-tray",
        help="Run resident hotkeys in the terminal without a tray icon",
    ),
    profile: str | None = typer.Option(
        None,
        "--profile",
        help="Voice STT profile: fast, balanced, or accurate",
    ),
    activation: str | None = typer.Option(
        None,
        "--activation",
        help="Hotkey style: toggle (tap on/off, default) or hold (push-to-talk)",
    ),
    dictate_hotkey: str | None = typer.Option(
        None,
        "--dictate-hotkey",
        help="Dictation hotkey or chord (default: f9)",
    ),
    read_hotkey: str | None = typer.Option(
        None,
        "--read-hotkey",
        help="Read selected text hotkey or chord (default: f8)",
    ),
    inject: str | None = typer.Option(
        None,
        "--inject",
        help="How to insert dictated text: paste or type",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Whisper model override for tray dictation",
    ),
    language: str | None = typer.Option(
        None,
        "--language",
        "-l",
        help="Spoken language (ISO 639-1); auto-detect if omitted",
    ),
    preload: bool | None = typer.Option(
        None,
        "--preload/--no-preload",
        help="Warm the STT model at startup so the first dictation is instant (default: on)",
    ),
    speed: float | None = typer.Option(
        None,
        "--speed",
        help="Read-aloud speed multiplier, e.g. 1.2 (0.5-2.0)",
    ),
) -> None:
    """
    Run the resident voice tray utility.

    Hold the dictation hotkey to speak into the focused field. Press the read
    hotkey to read the selected text aloud. This is a separate opt-in voice
    surface behind the tray optional extra.
    """
    from scribe.voice.settings import resolve_tray_settings
    from scribe.voice.tray import run_tray, run_tray_check

    if startup is not None:
        from scribe.voice.startup import run_tray_startup

        raise typer.Exit(run_tray_startup(console, startup))

    if setup:
        from scribe.voice.setup import run_voice_setup

        raise typer.Exit(run_voice_setup(console, interactive=True, profile=profile))

    try:
        settings = resolve_tray_settings(
            profile=profile,
            activation=activation,
            dictate_hotkey=dictate_hotkey,
            read_hotkey=read_hotkey,
            inject=inject,
            model=model,
            language=language,
            preload=preload,
            speed=speed,
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1) from e

    if check:
        raise typer.Exit(run_tray_check(console, settings, include_tray=not no_tray))
    raise typer.Exit(run_tray(console, settings, no_tray=no_tray))


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
    skip_for = {"init", "shortcut", "version", "--help", "-h", "--version", "--banner", "help"}
    if len(sys.argv) <= 1 or sys.argv[1] not in skip_for:
        try:
            from scribe.cli.init import maybe_prompt_first_run

            maybe_prompt_first_run(console=console)
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Setup skipped.[/dim]")

    try:
        app()
    except (KeyboardInterrupt, EOFError):
        import sys

        console.print("\n[dim]Cancelled by user.[/dim]")
        sys.exit(130)


if __name__ == "__main__":
    main()
