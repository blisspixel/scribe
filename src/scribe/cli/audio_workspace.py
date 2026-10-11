"""Own conversion files for one CLI input without touching neighboring media."""

from contextlib import suppress
from pathlib import Path
from tempfile import mkdtemp
from typing import TYPE_CHECKING

from rich.markup import escape

from scribe.utils.logging import TERMINAL_OUTPUT_ERRORS, console, get_logger

if TYPE_CHECKING:
    from scribe.core.transcriber import Transcriber
    from scribe.models.session import TranscriptionSession

logger = get_logger(__name__)


def preserve_download_outputs(
    session: "TranscriptionSession | None", downloaded_file: Path | None
) -> bool:
    """Keep a download directory when an output exists or inspection fails."""
    if session is None or downloaded_file is None:
        return False
    try:
        directory = downloaded_file.parent.resolve()
        return any(
            path != downloaded_file and path.is_file() and path.resolve().is_relative_to(directory)
            for path in session.files_created
        )
    except OSError as error:
        logger.warning("Could not inspect downloaded transcription outputs: %s", error)
        return True


class AudioWorkspace:
    """Keep disposable conversions separate from original recordings and outputs."""

    def __init__(self, *, keep: bool = False) -> None:
        self.keep = keep
        self.directory: Path | None = None
        self.conversions: set[Path] = set()

    def bind(self, transcriber: "Transcriber") -> None:
        """Route internal preparation and cloud-to-local fallback through this owner."""
        converter = getattr(transcriber, "converter", None)
        if converter is not None:
            converter.output_path_factory = self.output_for

    def output_for(self, source: Path, suffix: str) -> Path:
        """Allocate an owned conversion path; retain explicit keep-all beside input."""
        from uuid import uuid4

        if self.keep:
            target = source.with_name(f"{source.stem}{suffix}")
            if target.exists() or target.is_symlink():
                target = source.with_name(f"{source.stem}_{uuid4().hex[:8]}{suffix}")
        else:
            if self.directory is None:
                self.directory = Path(mkdtemp(prefix="scribe-audio-"))
            target = self.directory / f"{source.stem}{suffix}"
        self.conversions.add(target)
        return target

    def finish(self, session: "TranscriptionSession | None", output_dir: Path | None) -> None:
        """Remove only conversions we own, then refresh terminal session bookkeeping."""
        changed = False
        if session is not None:
            for path in self.conversions:
                try:
                    if path.exists():
                        session.add_file(path, "audio")
                        changed = True
                except OSError as error:
                    logger.warning("Could not inspect owned conversion %s: %s", path, error)
        if self.keep:
            if changed:
                self._refresh_summary(session, output_dir)
            return
        for path in list(self.conversions):
            try:
                if path.exists() or path.is_symlink():
                    path.unlink()
                    changed = True
                    if session is not None:
                        session.add_cleaned_file(path)
                self.conversions.discard(path)
            except OSError as error:
                logger.warning("Could not remove owned conversion %s: %s", path, error)
        if self.directory is not None:
            try:
                self.directory.rmdir()
                self.directory = None
            except OSError:
                # A partial transcript or another recoverable output is never deleted.
                with suppress(*TERMINAL_OUTPUT_ERRORS):
                    console.print(
                        "[yellow]Retained recoverable transcription files in "
                        f"{escape(str(self.directory))}[/yellow]"
                    )
        if changed:
            self._refresh_summary(session, output_dir)

    @staticmethod
    def _refresh_summary(session: "TranscriptionSession | None", output_dir: Path | None) -> None:
        """Persist changed bookkeeping without masking the original terminal result."""
        if session is not None and session.end_time is not None and output_dir is not None:
            try:
                session.save_summary(output_dir)
            except Exception as error:
                logger.warning("Could not refresh session after conversion cleanup: %s", error)
