"""
OBS Studio recording integration (migrated from working record.py).

This module provides OBS WebSocket integration for automated recording
with fallback to CLI control. The original implementation worked well,
so it's been preserved with minimal changes.
"""

import logging
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Generator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast

from scribe.core.recording_policy import (
    OBSActiveRecordingError,
    OBSAuthenticationError,
    RecordingEvent,
    RecordingPhase,
    RecordingSessionTracker,
    assess_recording_file_stability,
    format_recording_elapsed,
    media_discovery_poll_interval,
    recording_limit_seconds,
    recording_media_candidate_dirs,
    recording_warning_seconds,
    should_fallback_websocket_to_cli,
    step_recording_duration_limit,
)
from scribe.exceptions import ProcessError
from scribe.models.config import ScribeConfig
from scribe.utils.logging import get_logger
from scribe.utils.obs_config import read_obs_websocket_config
from scribe.utils.platform import get_ffmpeg_path, get_obs_executable_path

logger = get_logger(__name__)

# ADR-002: typed exception groups for intentional graceful-degradation sites.
_SUBPROCESS_PROBE_ERRORS = (OSError, subprocess.SubprocessError)
_OBS_SOCKET_ERRORS = (ConnectionError, OSError, TimeoutError)
_STOP_COMMANDS = frozenset({"stop", "s", "q", "quit", "exit"})
_RECORDING_STATUS_CLEAR_WIDTH = 80
_RECORDING_START_TIMEOUT_SECONDS = 15.0
_RECORDING_FILE_PROOF_TIMEOUT_SECONDS = 15.0
_RECORDING_STALL_WARNING_SECONDS = 15.0


class _WindowsConsoleInput(Protocol):
    """Typed boundary for the Windows-only console input API."""

    def kbhit(self) -> bool: ...

    def getwch(self) -> str: ...


# NOTE ON ERROR HANDLING IN THIS MODULE
# --------------------------------------
# This module intentionally uses broader exception handling (catching Exception
# in specific places) + explicit fallbacks for the following reasons:
#   - OBS Studio is external desktop software that may or may not be running,
#     may use WebSocket or CLI control, and can be in any state.
#   - Hardware variability (Windows primary target, multiple OBS versions,
#     permission differences, path differences) requires graceful degradation.
#   - The design prioritizes "recording still succeeds" over "fail fast on any
#     unexpected state".
# All such sites log at appropriate levels (debug/warning) and either:
#   - Fall back to a secondary strategy (WebSocket -> CLI), or
#   - Raise a typed ScribeError (ProcessError) with context for the caller.
# See ADR-002 for the exception taxonomy and recovery rationale.
# This is NOT a violation of defensive programming - it is a deliberate
# reliability choice for local-first desktop tools interacting with flaky
# external processes.

# Try to import OBS WebSocket library
try:
    from obsws_python import error as obs_error
    from obsws_python import reqs as obs_reqs

    OBS_AVAILABLE = True

    # obsws_python logs expected, scribe-handled failures via logger.exception(),
    # e.g. the code 207 "OBS not ready" retries during startup and the IPv6
    # "hostname is invalid" probe. Because scribe's handlers live on the "scribe"
    # logger tree, these records propagate to the root logger and get dumped raw
    # to stderr by logging's last-resort handler, scaring users about conditions
    # scribe already recovers from. Silence the library; genuine failures are
    # surfaced by scribe's own typed errors with actionable guidance.
    logging.getLogger("obsws_python").setLevel(logging.CRITICAL)
except ImportError:
    OBS_AVAILABLE = False
    logger.warning("obsws_python not installed. OBS integration will use CLI fallback only.")


@dataclass(frozen=True)
class OBSPreflightResult:
    """Read-only OBS WebSocket validation result."""

    status: str
    message: str
    details: tuple[str, ...] = ()
    fix_suggestion: str | None = None
    endpoint: str | None = None
    recording_active: bool | None = None

    @property
    def ok(self) -> bool:
        """Whether Quick Record can use OBS WebSocket."""
        return self.status == "pass"


@dataclass(frozen=True)
class RecordingStopResult:
    """Outcome reported by the live recording monitor."""

    output_path: str | None = None
    unexpected_stop: bool = False


class OBSRecorder:
    """
    OBS Studio recording integration with WebSocket and CLI fallback.

    This class handles:
    - OBS WebSocket connection with retry
    - Automatic OBS launch if not running
    - Interactive stop listener
    - MKV to MP4 remuxing
    - File detection and finalization
    """

    def __init__(self, config: ScribeConfig) -> None:
        """
        Initialize OBS recorder.

        Args:
            config: System configuration
        """
        self.config = config
        self.obs_host = config.obs_host
        self.obs_port = config.obs_port
        self.obs_password = config.obs_password
        self.output_folder = config.output_folder
        self.max_recording_hours = config.max_recording_hours
        self.recording_warning_fraction = config.recording_warning_fraction
        self._session = RecordingSessionTracker()
        self._terminal_input_lock = threading.Lock()
        self._stop_input_buffer: list[str] = []

    def record(self, meeting_name: str) -> Path:
        """
        Start OBS recording and wait for completion.

        Args:
            meeting_name: Name of the meeting/recording

        Returns:
            Path to recorded file

        Raises:
            ProcessError: If recording fails
        """
        logger.info(f"Starting OBS recording: {meeting_name}")
        self._session = RecordingSessionTracker()
        self._session.advance(RecordingEvent.BEGIN)

        # Ensure output directory is writable
        try:
            self._ensure_dir_writable(self.output_folder)
        except (ProcessError, OSError) as e:
            logger.warning(f"Cannot use configured output folder: {e}")
            fallback = Path(tempfile.gettempdir()) / "obs_recordings"
            logger.warning(f"Falling back to: {fallback}")
            self.output_folder = self._ensure_dir_writable(fallback)

        stop_event, restore_sigint = self._start_stop_listener()

        try:
            # Try WebSocket control first
            if OBS_AVAILABLE:
                return self._record_with_websocket(meeting_name, stop_event)
            else:
                logger.info("Using CLI fallback (obsws_python not available)")
                return self._record_with_cli(meeting_name, stop_event)

        except ProcessError:
            # Already a ProcessError - don't double-wrap, but retain truthful
            # lifecycle evidence for session summaries.
            with suppress(ValueError):
                self._session.advance(RecordingEvent.CANCEL)
            raise
        except OSError as e:
            logger.error("Recording failed (OS error): %s", e)
            with suppress(ValueError):
                self._session.advance(RecordingEvent.CANCEL)
            raise ProcessError(
                f"OBS recording failed: {e}",
                context={"meeting": meeting_name, "phase": self._session.phase.value},
            ) from e
        except Exception as e:
            logger.error(f"Recording failed: {e}")
            with suppress(ValueError):
                self._session.advance(RecordingEvent.CANCEL)
            raise ProcessError(
                f"OBS recording failed: {e}",
                context={"meeting": meeting_name, "phase": self._session.phase.value},
            )
        finally:
            restore_sigint()

    def _ensure_recording_session_started(self) -> None:
        """Begin the lifecycle when callers invoke websocket helpers directly."""
        if self._session.phase == RecordingPhase.IDLE:
            self._session.advance(RecordingEvent.BEGIN)

    def _record_with_websocket(self, meeting_name: str, stop_event: threading.Event) -> Path:
        """Record using OBS WebSocket.

        Falls back to CLI mode only when the WebSocket *connection* cannot be
        established.  Errors during an active recording (start/stop/file
        detection) are raised so the user gets clear feedback.
        """
        self._ensure_recording_session_started()
        try:
            with self._connect_obs() as client:
                self._set_record_dir_if_possible(client, str(self.output_folder))
                eff_dir = self._get_effective_record_dir(client, str(self.output_folder))

                # Timestamp before StartRecord so a file created immediately by OBS
                # cannot fall just outside the discovery window.
                media_baseline = self._recording_media_snapshot(eff_dir)
                start_ts = time.time()
                self._start_recording_if_needed(client)
                self._session.advance(RecordingEvent.CONNECT_OK)

                confirmed_media = self._confirm_recording_file_progress(
                    eff_dir,
                    start_ts,
                    exclude=media_baseline,
                )
                if confirmed_media is None:
                    from scribe.utils.logging import console

                    console.print(
                        "[yellow]OBS output is advancing, but the recording file path "
                        "is not visible yet. Recording will continue while Scribe keeps "
                        "tracking it.[/yellow]"
                    )

                stop_result = self._wait_for_stop_with_input(client, stop_event)
                self._session.advance(RecordingEvent.STOP_REQUESTED)

                media_result = self._usable_reported_media(stop_result.output_path, start_ts)
                if media_result is None and confirmed_media is not None:
                    media_result = confirmed_media
                if media_result is None:
                    try:
                        media_result = self._discover_recorded_media(
                            eff_dir,
                            start_ts,
                            exclude=media_baseline,
                        )
                    except ProcessError:
                        with suppress(ValueError):
                            self._session.advance(RecordingEvent.MEDIA_MISSING)
                        raise
                media, ext = media_result
                self._session.advance(RecordingEvent.MEDIA_FOUND)

                if not self._wait_until_file_finalized(media):
                    raise ProcessError(
                        "OBS did not finish the recording file, so Scribe left the "
                        f"live file untouched: {media}. Check OBS before processing it."
                    )
                final_path = self._finalize_recording(media, ext, meeting_name, start_ts)
                if stop_result.unexpected_stop:
                    raise ProcessError(
                        "OBS stopped recording unexpectedly before Scribe received a stop "
                        f"request. The partial recording was preserved at: {final_path}"
                    )
                self._session.advance(RecordingEvent.FINALIZED)
                return final_path

        except (OBSActiveRecordingError, OBSAuthenticationError) as e:
            # Don't spam console with "blocked fallback" for auth errors; the
            # raised ProcessError already gives the user clear guidance.
            logger.debug(
                "OBS WebSocket %s: %s",
                "auth failed" if isinstance(e, OBSAuthenticationError) else "busy",
                e,
            )
            with suppress(ValueError):
                self._session.advance(
                    RecordingEvent.CONNECT_BUSY
                    if isinstance(e, OBSActiveRecordingError)
                    else RecordingEvent.CONNECT_AUTH_FAIL
                )
            raise ProcessError(str(e), context={"phase": self._session.phase.value}) from e
        except ConnectionError as e:
            if should_fallback_websocket_to_cli(e):
                logger.warning("WebSocket connection failed, falling back to CLI mode")
                return self._record_with_cli(meeting_name, stop_event)
            with suppress(ValueError):
                self._session.advance(RecordingEvent.CANCEL)
            raise ProcessError(
                f"OBS WebSocket connection failed: {e}",
                context={"phase": self._session.phase.value},
            ) from e

    @staticmethod
    def _usable_reported_media(path: str | None, start_ts: float) -> tuple[str, str] | None:
        """Return an OBS-reported output path when it is a fresh real file."""
        if not path:
            return None
        candidate = Path(path)
        try:
            if not candidate.is_file() or candidate.stat().st_mtime < start_ts - 5:
                return None
        except OSError:
            return None
        suffix = candidate.suffix.lower()
        if suffix not in {".mp4", ".mkv"}:
            return None
        return str(candidate), suffix

    def _confirm_recording_file_progress(
        self,
        primary_dir: str,
        start_ts: float,
        *,
        timeout: float = _RECORDING_FILE_PROOF_TIMEOUT_SECONDS,
        stop_event: threading.Event | None = None,
        exclude: set[str] | None = None,
    ) -> tuple[str, str] | None:
        """Confirm that a fresh OBS media file exists and is growing.

        OBS can buffer the filesystem write or report a path different from the
        configured one. Failure to see the file is therefore a warning, not a
        reason to stop an encoder that has already proven byte progress.
        """
        candidate_dirs = recording_media_candidate_dirs(
            primary_dir,
            temp_obs_dir=Path(tempfile.gettempdir()) / "obs_recordings",
        )
        sizes: dict[str, int] = {}
        deadline = time.monotonic() + max(0.0, timeout)
        attempt = 0

        while time.monotonic() < deadline:
            if stop_event is not None and stop_event.is_set():
                return None
            for directory in candidate_dirs:
                if not directory.exists():
                    continue
                mp4, mkv = self._newest_media_since(str(directory), start_ts)
                for path, ext in ((mp4, ".mp4"), (mkv, ".mkv")):
                    if path is None:
                        continue
                    if self._normalized_media_path(path) in (exclude or set()):
                        continue
                    try:
                        size = os.path.getsize(path)
                    except OSError:
                        continue
                    previous = sizes.get(path)
                    sizes[path] = size
                    if previous is not None and size > previous:
                        logger.info("Confirmed growing OBS media file: %s", path)
                        return path, ext
            time.sleep(media_discovery_poll_interval(attempt, base=0.2, max_interval=1.0))
            attempt += 1
        return None

    @staticmethod
    def _normalized_media_path(path: str | Path) -> str:
        """Normalize a media path for stable cross-platform identity checks."""
        return os.path.normcase(os.path.abspath(os.fspath(path)))

    def _recording_media_snapshot(self, primary_dir: str | Path) -> set[str]:
        """Snapshot existing MP4/MKV files so they cannot prove a new recording."""
        snapshot: set[str] = set()
        for directory in recording_media_candidate_dirs(
            primary_dir,
            temp_obs_dir=Path(tempfile.gettempdir()) / "obs_recordings",
        ):
            try:
                entries = tuple(directory.iterdir())
            except OSError:
                continue
            for entry in entries:
                if entry.suffix.lower() in {".mp4", ".mkv"}:
                    snapshot.add(self._normalized_media_path(entry))
        return snapshot

    def _discover_recorded_media(
        self,
        primary_dir: str,
        start_ts: float,
        *,
        max_attempts: int = 30,
        exclude: set[str] | None = None,
    ) -> tuple[str, str]:
        """Search adaptive candidate folders for media written after ``start_ts``."""
        temp_obs = Path(tempfile.gettempdir()) / "obs_recordings"
        candidate_dirs = recording_media_candidate_dirs(
            primary_dir,
            temp_obs_dir=temp_obs,
        )
        searched = ", ".join(str(path) for path in candidate_dirs)
        for attempt in range(max_attempts):
            for directory in candidate_dirs:
                if not directory.exists():
                    continue
                mp4, mkv = self._newest_media_since(str(directory), start_ts)
                media = next(
                    (
                        path
                        for path in (mp4, mkv)
                        if path is not None
                        and self._normalized_media_path(path) not in (exclude or set())
                    ),
                    None,
                )
                if media:
                    ext = Path(media).suffix.lower()
                    logger.info(
                        "Located recorded media in %s after %d discovery attempt(s)",
                        directory,
                        attempt + 1,
                    )
                    return media, ext
            time.sleep(media_discovery_poll_interval(attempt))

        raise ProcessError(
            "Could not locate recorded media after stopping OBS. "
            f"Searched: {searched}. OBS may be saving to a different folder - check "
            "OBS Settings -> Output -> Recording Path.",
            context={
                "primary_dir": primary_dir,
                "phase": self._session.phase.value,
                "attempts": max_attempts,
            },
        )

    def _record_with_cli(self, meeting_name: str, stop_event: threading.Event) -> Path:
        """Start emergency capture through OBS's supported command-line option.

        CLI mode cannot safely stop OBS by command line. Scribe reconnects through
        WebSocket when possible; otherwise it preserves the active file and asks
        the user to stop OBS manually before finalization.
        """
        from scribe.utils.logging import console

        self._ensure_recording_session_started()
        console.print("[yellow]Using CLI fallback mode[/yellow]")
        obs_exe = get_obs_executable_path()
        obs_running = self._obs_process_running()

        if self._obs_recording_process_running():
            raise ProcessError(
                "OBS appears to be recording already. Scribe left that recording "
                "untouched. Finish it manually before starting another session."
            )

        media_baseline = self._recording_media_snapshot(self.output_folder)
        start_ts = time.time()
        if obs_exe is not None:
            if obs_running:
                console.print(
                    "[yellow]The existing OBS process is unreachable. Starting a "
                    "separate recovery instance without interrupting it.[/yellow]"
                )
            else:
                console.print("[cyan]Starting OBS emergency capture...[/cyan]")
            try:
                self._launch_obs(
                    obs_exe,
                    start_recording=True,
                    allow_multi=obs_running,
                )
            except OSError as e:
                raise ProcessError(f"Could not launch OBS emergency capture: {e}") from e
        else:
            console.print(
                "[yellow]OBS executable was not found. Open OBS and click Start "
                "Recording now; Scribe will verify the media file.[/yellow]"
            )

        console.print()
        console.print("[cyan]Waiting for proof that recording data is being written...[/cyan]")
        console.print("[dim]Looking for new media files in:[/dim]")

        candidate_dirs = recording_media_candidate_dirs(self.output_folder)
        for d in candidate_dirs:
            if d.exists():
                console.print(f"[dim]  - {d}[/dim]")

        confirmed_media = self._confirm_recording_file_progress(
            str(self.output_folder),
            start_ts,
            timeout=30.0,
            stop_event=stop_event,
            exclude=media_baseline,
        )
        if stop_event.is_set() and confirmed_media is None:
            raise ProcessError("Recording cancelled before a file was detected")

        if confirmed_media is None:
            console.print()
            console.print("[bold red]ERROR: No recording file detected[/bold red]")
            console.print()
            console.print("[yellow]Possible causes:[/yellow]")
            console.print("  1. OBS is not actually recording (check OBS window)")
            console.print("  2. OBS is recording to a different folder")
            console.print("  3. OBS could not initialize its encoder or output file")
            console.print()
            console.print("[yellow]To fix:[/yellow]")
            console.print("  1. Open OBS Studio manually")
            console.print("  2. Click 'Start Recording' button")
            console.print("  3. Run 'scribe rec' again")
            console.print()
            raise ProcessError(
                "No media file appeared after starting recording. "
                "OBS may not be recording. Please check OBS window and start recording manually.",
                context={"phase": self._session.phase.value},
            )

        found_path, ext = confirmed_media
        recorded_path = Path(found_path)
        self._session.advance(RecordingEvent.USE_CLI_FALLBACK)

        console.print(f"[green]Recording confirmed: {recorded_path.name} is growing[/green]")
        console.print()

        control_client = None
        if OBS_AVAILABLE:
            try:
                candidate = self._try_connect_to_running_obs(
                    self._candidate_obs_hosts(), self._candidate_obs_ports()
                )
                if candidate is not None:
                    status = candidate.get_record_status()
                    if getattr(status, "output_active", False):
                        control_client = candidate
                    else:
                        with suppress(Exception):
                            candidate.disconnect()
            except OBSAuthenticationError:
                logger.warning("Emergency capture is active, but WebSocket authentication failed")

        try:
            stopped_path = self._wait_for_stop_cli(stop_event, control_client)
        finally:
            if control_client is not None:
                with suppress(Exception):
                    control_client.disconnect()
        self._session.advance(RecordingEvent.STOP_REQUESTED)

        console.print()
        console.print("[cyan]Waiting for OBS to finalize file...[/cyan]")
        console.print("[dim]This may take a few seconds...[/dim]")

        reported_media = self._usable_reported_media(stopped_path, start_ts)
        if reported_media is not None:
            found_path, ext = reported_media
            recorded_path = Path(found_path)

        if not self._wait_until_file_finalized(str(recorded_path)):
            raise ProcessError(
                "The recording file is still growing, so Scribe left it in place "
                f"instead of moving a live file: {recorded_path}. Stop recording in "
                "OBS, then process that file directly."
            )

        self._session.advance(RecordingEvent.MEDIA_FOUND)
        final_path = self._finalize_recording(recorded_path, ext, meeting_name, start_ts)
        self._session.advance(RecordingEvent.FINALIZED)
        return final_path

    def check_obs_preflight(self, timeout: float = 0.75) -> OBSPreflightResult:
        """Fast, read-only OBS WebSocket preflight.

        This intentionally does not launch OBS, kill OBS, start recording, stop
        recording, set folders, or transcribe. It is safe to run before a meeting
        and useful during debugging because it tests the same lightweight status
        request Quick Record needs before it can control OBS.
        """
        hosts = self._candidate_obs_hosts()
        ports = self._candidate_obs_ports()
        details: list[str] = [
            f"configured host={self.obs_host}",
            f"configured port={self.obs_port}",
            f"password={'set' if self.obs_password else 'not set'}",
        ]

        obs_running = self._obs_process_running()
        details.append(f"obs process={'running' if obs_running else 'not detected'}")
        recording_mux_running = self._obs_recording_process_running()
        details.append(f"recording mux={'running' if recording_mux_running else 'not detected'}")
        obs_config = read_obs_websocket_config()
        if obs_config.path is not None:
            details.append(f"obs config={obs_config.path}")
        if obs_config.error:
            details.append(f"obs config status={obs_config.error}")
        if obs_config.server_enabled is not None:
            details.append(f"obs websocket enabled={obs_config.server_enabled}")
        if obs_config.server_port is not None:
            details.append(f"obs websocket port={obs_config.server_port}")
        if obs_config.auth_required is not None:
            details.append(f"obs websocket auth required={obs_config.auth_required}")

        if obs_config.exists and not obs_config.error and obs_config.server_enabled is False:
            return OBSPreflightResult(
                status="fail",
                message="OBS WebSocket server is disabled",
                details=tuple(details),
                fix_suggestion=(
                    "Open OBS, enable Tools > WebSocket Server Settings, then rerun "
                    "`scribe rec --check`."
                ),
            )

        if (
            obs_config.exists
            and not obs_config.error
            and obs_config.server_port is not None
            and obs_config.server_port != self.obs_port
        ):
            return OBSPreflightResult(
                status="fail",
                message="OBS WebSocket port mismatch",
                details=tuple(details),
                fix_suggestion=self._obs_port_fix_suggestion(obs_config.server_port),
            )

        if (
            obs_config.exists
            and not obs_config.error
            and obs_config.auth_required
            and not self.obs_password
        ):
            return OBSPreflightResult(
                status="fail",
                message="OBS WebSocket requires a password",
                details=tuple(details),
                fix_suggestion=self._obs_password_fix_suggestion(),
            )

        if not OBS_AVAILABLE:
            return OBSPreflightResult(
                status="fail",
                message="obsws_python is not installed",
                details=tuple(details),
                fix_suggestion="Install Scribe with OBS WebSocket support and rerun this check.",
            )

        any_listening = False
        request_failures: list[str] = []
        for host in hosts:
            for port in ports:
                endpoint = f"{host}:{port}"
                if not self._port_listening(host, port, timeout=timeout):
                    details.append(f"{endpoint}: tcp closed")
                    continue

                any_listening = True
                details.append(f"{endpoint}: tcp open")
                client = None
                try:
                    client = obs_reqs.ReqClient(
                        host=host,
                        port=port,
                        password=self.obs_password,
                        timeout=max(1.0, timeout),
                    )
                    status = client.get_record_status()
                    active = bool(getattr(status, "output_active", False))
                    details.append(f"{endpoint}: get_record_status ok")
                    return OBSPreflightResult(
                        status="pass",
                        message=(
                            "OBS WebSocket is ready; recording is active"
                            if active
                            else "OBS WebSocket is ready; recording is inactive"
                        ),
                        details=tuple(details),
                        endpoint=endpoint,
                        recording_active=active,
                    )
                except ValueError as e:
                    failure = f"{endpoint}: invalid host for WebSocket client ({e})"
                    details.append(failure)
                    request_failures.append(failure)
                except obs_error.OBSSDKRequestError as e:
                    failure = f"{endpoint}: OBS request failed ({e})"
                    details.append(failure)
                    request_failures.append(failure)
                    if self._is_obs_auth_error(e):
                        return OBSPreflightResult(
                            status="fail",
                            message="OBS WebSocket authentication failed",
                            details=tuple(details),
                            fix_suggestion=self._obs_password_fix_suggestion(wrong=True),
                            endpoint=endpoint,
                        )
                except Exception as e:
                    failure = f"{endpoint}: WebSocket status request failed ({e})"
                    details.append(failure)
                    request_failures.append(failure)
                    if self._is_obs_auth_error(e):
                        return OBSPreflightResult(
                            status="fail",
                            message="OBS WebSocket authentication failed",
                            details=tuple(details),
                            fix_suggestion=self._obs_password_fix_suggestion(wrong=True),
                            endpoint=endpoint,
                        )
                finally:
                    if client is not None:
                        with suppress(Exception):
                            client.disconnect()

        if not any_listening:
            if recording_mux_running:
                return OBSPreflightResult(
                    status="fail",
                    message="OBS appears to be recording, but WebSocket is not reachable",
                    details=tuple(details),
                    fix_suggestion=(
                        "Do not restart OBS during this recording. Finish the recording "
                        "manually, then run `scribe rec --check` before the next one."
                    ),
                )
            return OBSPreflightResult(
                status="fail",
                message="OBS WebSocket port is not listening",
                details=tuple(details),
                fix_suggestion=(
                    "Open OBS, enable Tools > WebSocket Server Settings, then rerun "
                    "`scribe rec --check`. If OBS uses a different port, run "
                    "`scribe init --force` and set that port."
                ),
            )

        return OBSPreflightResult(
            status="fail",
            message="OBS WebSocket port is open, but the status request failed",
            details=tuple(details),
            fix_suggestion=(
                "Check OBS WebSocket authentication and wait until OBS startup is complete, "
                "then rerun `scribe rec --check`."
            ),
            endpoint=None,
        )

    def _obs_port_fix_suggestion(self, obs_port: int) -> str:
        return (
            f"Run `scribe init --force` and set OBS port {obs_port}, or set CMD "
            f"`set SCRIBE_OBS_PORT={obs_port}` or PowerShell "
            f"`$env:SCRIBE_OBS_PORT='{obs_port}'`. On a Linux shell, "
            f"`export SCRIBE_OBS_PORT={obs_port}`."
        )

    @staticmethod
    def _obs_password_fix_suggestion(*, wrong: bool = False) -> str:
        prefix = (
            "OBS rejected the configured password. "
            if wrong
            else "OBS requires a WebSocket password. "
        )
        return (
            f"{prefix}In OBS, open Tools > WebSocket Server Settings > Show Connect Info, "
            "copy the Server Password, then run `scribe init --force` or update "
            "[obs].password in ~/.scribe/config.toml."
        )

    @staticmethod
    def _is_obs_auth_error(error: Exception | str) -> bool:
        """Return True when OBS WebSocket rejected authentication."""
        text = str(error).lower()
        return any(
            marker in text
            for marker in (
                "auth",
                "password",
                "failed to identify",
                "identify client",
            )
        )

    def _obs_process_running(self) -> bool:
        """Check whether an OBS process is currently running."""
        from scribe.utils.platform import is_windows

        try:
            if is_windows():
                for exe in ("obs64.exe", "obs32.exe"):
                    result = subprocess.run(
                        ["tasklist", "/FI", f"IMAGENAME eq {exe}", "/NH"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if exe in result.stdout.lower():
                        return True
                return False
            else:
                # Exact name match only. A substring match would treat unrelated
                # processes as OBS and trigger unsafe recovery decisions.
                for name in ("obs", "OBS"):
                    result = subprocess.run(
                        ["pgrep", "-x", name],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        return True
                return False
        except _SUBPROCESS_PROBE_ERRORS:
            return False

    def _obs_recording_process_running(self) -> bool:
        """Check whether OBS has an active recording mux process."""
        from scribe.utils.platform import is_windows

        mux_process = "obs-ffmpeg-mux.exe"
        try:
            if is_windows():
                result = subprocess.run(
                    ["tasklist", "/FI", f"IMAGENAME eq {mux_process}", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return mux_process in result.stdout.lower()

            result = subprocess.run(
                ["pgrep", "-x", "obs-ffmpeg-mux"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except _SUBPROCESS_PROBE_ERRORS:
            return False

    def _obs_config_dir(self) -> Path | None:
        """Return OBS Studio's per-user config directory for this platform.

        Windows: %APPDATA%/obs-studio
        macOS:   ~/Library/Application Support/obs-studio
        Linux:   ~/.config/obs-studio   (or $XDG_CONFIG_HOME)
        """
        from scribe.utils.platform import is_macos, is_windows

        if is_windows():
            appdata = os.environ.get("APPDATA", "")
            return Path(appdata) / "obs-studio" if appdata else None
        if is_macos():
            return Path.home() / "Library" / "Application Support" / "obs-studio"
        xdg = os.environ.get("XDG_CONFIG_HOME", "")
        config_home = Path(xdg) if xdg else Path.home() / ".config"
        return config_home / "obs-studio"

    def _clean_obs_crash_sentinel(self) -> None:
        """Remove OBS crash/unclean-shutdown markers.

        OBS writes a CrashRecovery flag in global.ini on startup and clears
        it on clean shutdown.  If the process was killed, the flag remains and
        triggers the safe-mode dialog on next launch.  We clear it here.
        """
        try:
            config_dir = self._obs_config_dir()
            if config_dir is None:
                return
            sentinel = config_dir / "global.ini"

            if not sentinel.exists():
                return

            lines = sentinel.read_text(encoding="utf-8", errors="replace").splitlines()
            cleaned = []
            for line in lines:
                stripped = line.strip().lower()
                # Remove the flags that trigger safe-mode / crash recovery
                if stripped.startswith("lastcrash") or stripped.startswith("safemode"):
                    logger.debug(f"Removing OBS crash sentinel line: {line.strip()}")
                    continue
                cleaned.append(line)
            sentinel.write_text("\n".join(cleaned) + "\n", encoding="utf-8")
            logger.debug("Cleaned OBS crash sentinel")
        except OSError as e:
            logger.debug(f"Could not clean OBS crash sentinel: {e}")

    def _launch_obs(
        self,
        obs_exe: Path,
        *,
        start_recording: bool = False,
        allow_multi: bool = False,
    ) -> None:
        """Launch OBS for the current platform.

        On macOS, OBS is an app bundle that must be started via ``open`` so it
        finds its bundle resources (Popen-ing the inner binary is unreliable),
        and ``--minimize-to-tray`` has no meaning there. On Windows and Linux we
        run the executable directly with the appropriate flags. ``--multi`` is
        required for non-blocking recovery when an unreachable OBS process is
        already present, and ``--startrecording`` is OBS's supported emergency
        capture path when WebSocket control is unavailable.
        """
        from scribe.utils.platform import is_macos, is_windows

        flags = ["--disable-shutdown-check"]
        if allow_multi:
            flags.append("--multi")
        if start_recording:
            flags.append("--startrecording")

        if is_macos():
            bundle = next((p for p in obs_exe.parents if p.suffix == ".app"), None)
            app_ref = str(bundle) if bundle is not None else "OBS"
            open_args = ["open"]
            if allow_multi:
                open_args.append("-n")
            subprocess.Popen(
                [*open_args, "-a", app_ref, "--args", *flags],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return

        if is_windows():
            flags.insert(0, "--minimize-to-tray")
            # Windows OBS finds its DLLs beside the executable.
            subprocess.Popen(
                [str(obs_exe), *flags],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(obs_exe.parent),
            )
            return

        # On Linux, `/usr/bin` is the wrong working directory for OBS.
        subprocess.Popen(
            [str(obs_exe), *flags],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def _try_connect_to_running_obs(self, hosts: list[str], ports: list[int]) -> Any | None:
        """
        Attempt to connect to already-running OBS instance.

        Returns client if successful, None otherwise.
        Handles the case where OBS is starting up and not yet ready.
        """
        for h in hosts:
            for p in ports:
                is_listening = self._port_listening(h, p, timeout=0.3)
                logger.debug(f"Port check {h}:{p} = {is_listening}")
                if is_listening:
                    client = None
                    try:
                        client = obs_reqs.ReqClient(
                            host=h, port=p, password=self.obs_password, timeout=3.0
                        )
                        # Try to verify OBS is ready with retries
                        for retry in range(5):
                            try:
                                client.get_record_status()
                                logger.info(f"Connected to OBS at ws://{h}:{p}")
                                return client
                            except obs_error.OBSSDKRequestError as e:
                                # OBS is connected but not ready yet (code 207)
                                if "not ready" in str(e).lower():
                                    logger.debug(f"OBS not ready yet, retry {retry + 1}/5")
                                    time.sleep(0.5)
                                    continue
                                # Other OBS errors - connection works but request failed
                                raise
                        # Exhausted retries - OBS still not ready
                        logger.debug(f"OBS at {h}:{p} not ready after retries")
                        if client:
                            with suppress(Exception):
                                client.disconnect()
                    except ValueError as e:
                        if "hostname is invalid" in str(e).lower() or "invalid" in str(e).lower():
                            logger.debug(f"Hostname validation failed for {h}:{p}")
                        else:
                            logger.debug(f"ValueError during connection to {h}:{p}")
                        if client:
                            with suppress(Exception):
                                client.disconnect()
                    except obs_error.OBSSDKRequestError as e:
                        if self._is_obs_auth_error(e):
                            logger.debug(
                                f"OBS authentication failed at {h}:{p} - "
                                "check SCRIBE_OBS_PASSWORD or [obs].password"
                            )
                            raise OBSAuthenticationError(
                                self._obs_password_fix_suggestion(wrong=True)
                            ) from e
                        else:
                            logger.debug(f"OBS SDK error at {h}:{p}: {e}")
                        if client:
                            with suppress(Exception):
                                client.disconnect()
                    except Exception as e:
                        if self._is_obs_auth_error(e):
                            if client:
                                with suppress(Exception):
                                    client.disconnect()
                            raise OBSAuthenticationError(
                                self._obs_password_fix_suggestion(wrong=True)
                            ) from e
                        # Connection failed - try next host/port
                        logger.debug(f"Connection to {h}:{p} failed: {e}")
                        if client:
                            with suppress(Exception):
                                client.disconnect()
        return None

    def _wait_for_obs_startup(
        self, hosts: list[str], ports: list[int], max_wait_seconds: int
    ) -> Any | None:
        """
        Wait for OBS to start and attempt connection with retry.

        Returns client if successful, None otherwise.
        """
        # Wait a bit before first connection attempt to let OBS initialize
        time.sleep(1.0)

        for attempt in range(int(max_wait_seconds * 2)):
            for h in hosts:
                for p in ports:
                    if self._port_listening(h, p, timeout=0.2):
                        client = None
                        try:
                            client = obs_reqs.ReqClient(
                                host=h, port=p, password=self.obs_password, timeout=3.0
                            )
                            # Try to verify OBS is ready
                            try:
                                client.get_record_status()
                                logger.info(f"Connected to OBS at ws://{h}:{p}")
                                return client
                            except obs_error.OBSSDKRequestError as e:
                                # OBS connected but not ready yet (code 207)
                                if "not ready" in str(e).lower():
                                    logger.debug(f"OBS not ready yet (attempt {attempt + 1})")
                                    if client:
                                        with suppress(Exception):
                                            client.disconnect()
                                    # Don't continue inner loops, wait and retry
                                    break
                                raise

                        except ValueError as e:
                            if (
                                "hostname is invalid" in str(e).lower()
                                or "invalid" in str(e).lower()
                            ):
                                logger.debug(f"Hostname validation failed for {h}:{p}")
                            if client:
                                with suppress(Exception):
                                    client.disconnect()
                        except obs_error.OBSSDKRequestError as e:
                            if self._is_obs_auth_error(e):
                                if client:
                                    with suppress(Exception):
                                        client.disconnect()
                                raise OBSAuthenticationError(
                                    self._obs_password_fix_suggestion(wrong=True)
                                ) from e
                            logger.debug(f"OBS SDK error during startup at {h}:{p}: {e}")
                            if client:
                                with suppress(Exception):
                                    client.disconnect()
                        except Exception as e:
                            if self._is_obs_auth_error(e):
                                if client:
                                    with suppress(Exception):
                                        client.disconnect()
                                raise OBSAuthenticationError(
                                    self._obs_password_fix_suggestion(wrong=True)
                                ) from e
                            logger.debug(f"Connection to {h}:{p} failed: {e}")
                            if client:
                                with suppress(Exception):
                                    client.disconnect()
            time.sleep(0.5)
        return None

    @contextmanager
    def _connect_obs(self, max_wait_seconds: int = 15) -> Generator[Any, None, None]:
        """
        Connect to OBS WebSocket with conservative recovery.

        Strategy:
        1. Try connecting to already-running OBS
        2. If OBS is recording, refuse recovery
        3. Launch OBS without terminating an unreachable existing process
        """
        from scribe.utils.logging import console

        # Prioritize IPv4 - WebSocket libraries have better IPv4 support
        # Deduplicate while preserving order
        hosts = self._candidate_obs_hosts()
        ports = self._candidate_obs_ports()

        console.print(f"[cyan]Connecting to OBS (checking {hosts[0]}:{ports[0]})...[/cyan]")

        # Phase 1: try connecting to a healthy running OBS.
        client = self._try_connect_to_running_obs(hosts, ports)
        if client:
            console.print("[green]Connected to OBS[/green]")
            try:
                yield client
            finally:
                with suppress(Exception):
                    client.disconnect()
            return

        if self._obs_recording_process_running():
            raise OBSActiveRecordingError(
                "OBS appears to be actively recording, but WebSocket is unreachable. "
                "Refusing to restart OBS during an active recording. Finish the "
                "recording manually, then run `scribe rec --check` before the next one."
            )

        obs_was_running = self._obs_process_running()
        if obs_was_running:
            console.print(
                "[yellow]OBS is running without WebSocket; attempting a "
                "non-destructive relaunch...[/yellow]"
            )
            logger.warning(
                "OBS process detected without a reachable WebSocket; launching "
                "another instance without terminating the existing process"
            )

        # Phase 2: launch without terminating anything. This also recovers from an
        # OBS process that completed shutdown but remained in the process table.
        obs_exe = get_obs_executable_path()
        max_launch_attempts = 1 if obs_was_running else 2

        for attempt in range(1, max_launch_attempts + 1):
            console.print(
                f"[cyan]Preparing OBS (attempt {attempt}/{max_launch_attempts})...[/cyan]"
            )

            if not obs_was_running:
                self._clean_obs_crash_sentinel()

            if not obs_exe:
                break  # nothing to launch

            action = "Relaunching" if obs_was_running else "Starting"
            console.print(f"[cyan]{action} OBS Studio...[/cyan]")
            logger.info("%s OBS (attempt %d)...", action, attempt)
            try:
                self._launch_obs(obs_exe, allow_multi=obs_was_running)
            except OSError as e:
                logger.warning(f"Could not launch OBS: {e}")
                continue

            console.print("[cyan]Waiting for OBS to start...[/cyan]")
            client = self._wait_for_obs_startup(hosts, ports, max_wait_seconds)
            if client:
                console.print("[green]Connected to OBS[/green]")
                try:
                    yield client
                finally:
                    with suppress(Exception):
                        client.disconnect()
                return

            # Launch succeeded but WebSocket never became reachable - retry
            logger.warning("OBS launched but WebSocket unreachable (attempt %d)", attempt)

        if obs_was_running:
            raise ConnectionError(
                "OBS was running without a reachable WebSocket, and relaunching it did "
                "not restore the connection. Close all OBS instances, reopen OBS, and "
                "run `scribe rec --check`."
            )
        raise ConnectionError(
            "Could not connect to OBS WebSocket. Ensure OBS is installed, "
            "WebSocket server is enabled (Tools -> WebSocket Server Settings), "
            "and SCRIBE_OBS_PASSWORD matches if authentication is on."
        )

    def _candidate_obs_hosts(self) -> list[str]:
        """Return deduplicated OBS hosts to try, preserving preferred order."""
        seen: set[str] = set()
        hosts: list[str] = []
        for host in [self.obs_host, "127.0.0.1", "::1"]:
            if host not in seen:
                seen.add(host)
                hosts.append(host)
        return hosts

    def _candidate_obs_ports(self) -> list[int]:
        """Return deduplicated OBS ports to try."""
        ports = [self.obs_port]
        if self.obs_port != 4455:
            ports.append(4455)
        return ports

    def _set_record_dir_if_possible(self, client: Any, out_dir: str) -> bool:
        """Set OBS recording directory.

        Returns True if the directory was set (or already matched).
        Logs a visible warning when the directory could not be set so the
        user knows OBS may record somewhere unexpected.
        """
        from scribe.utils.logging import console

        out_dir = out_dir.replace("\\", "/")
        try:
            status = client.get_record_status()
            if getattr(status, "output_active", False):
                logger.warning("Recording already active, skipping directory set")
                return False

            try:
                cur = client.get_record_directory()
                cur_dir = getattr(cur, "record_directory", None) or ""
            except Exception:
                # ADR-002: obsws_python query failures are assorted types; proceed to set.
                cur_dir = ""

            if cur_dir and os.path.normcase(cur_dir) == os.path.normcase(out_dir):
                logger.debug("Record directory already set")
                return True

            client.set_record_directory(out_dir)
            logger.info(f"Recording directory set to: {out_dir}")
            return True

        except obs_error.OBSSDKRequestError as e:
            logger.warning(f"SetRecordDirectory rejected: {e}")
            console.print(
                "[yellow]Could not set recording folder - OBS may record elsewhere[/yellow]"
            )
            return False
        except _OBS_SOCKET_ERRORS as e:
            logger.warning(f"Could not set record directory: {e}")
            console.print(
                "[yellow]Could not set recording folder - OBS may record elsewhere[/yellow]"
            )
            return False

    def _start_recording_if_needed(
        self,
        client: Any,
        *,
        timeout: float = _RECORDING_START_TIMEOUT_SECONDS,
    ) -> None:
        """Start a fresh recording and prove that OBS output is advancing.

        An active recording is never classified as stale and never stopped. It
        may contain the only copy of an in-progress meeting, so attaching to or
        replacing it requires an explicit future recovery workflow.
        """
        from scribe.utils.logging import console

        status = client.get_record_status()
        if getattr(status, "output_active", False):
            raise OBSActiveRecordingError(
                "OBS is already recording. Scribe left that recording untouched "
                "to protect the captured media. Stop it manually only when the "
                "meeting is finished, then start a new Scribe session."
            )

        console.print("[cyan]Starting recording...[/cyan]")
        logger.info("Starting recording...")
        try:
            client.start_record()
        except Exception as e:
            err_str = str(e).lower()
            if "already" in err_str:
                raise OBSActiveRecordingError(
                    "OBS became active before Scribe could start its recording. "
                    "Scribe left that recording untouched."
                ) from e
            raise ProcessError(
                f"OBS refused to start recording: {e}. "
                "Check OBS Settings -> Output for valid recording path and codec."
            )

        # StartRecord is asynchronous. Do not claim success from output_active
        # alone. GetRecordStatus exposes outputBytes and outputDuration, and at
        # least one must advance between samples before Scribe reports capture.
        deadline = time.monotonic() + max(0.0, timeout)
        previous_bytes: int | float | None = None
        previous_duration: int | float | None = None
        active_seen = False
        while time.monotonic() < deadline:
            time.sleep(0.2)
            try:
                status = client.get_record_status()
            except _OBS_SOCKET_ERRORS:
                continue
            if not getattr(status, "output_active", False):
                continue

            active_seen = True
            output_bytes = self._numeric_status_value(status, "output_bytes")
            output_duration = self._numeric_status_value(status, "output_duration")
            bytes_advanced = (
                output_bytes is not None
                and previous_bytes is not None
                and output_bytes > previous_bytes
            )
            duration_advanced = (
                output_duration is not None
                and previous_duration is not None
                and output_duration > previous_duration
            )
            if bytes_advanced or duration_advanced:
                console.print("[green]Recording confirmed: OBS output is advancing[/green]")
                logger.info(
                    "Recording output confirmed (bytes=%s, duration=%s)",
                    output_bytes,
                    output_duration,
                )
                return
            if output_bytes is not None:
                previous_bytes = output_bytes
            if output_duration is not None:
                previous_duration = output_duration

        if active_seen:
            raise ProcessError(
                "OBS entered recording mode, but its byte and duration counters did not "
                "advance. Scribe did not stop OBS because media may still be writing. "
                "Check the OBS status bar and recording folder immediately."
            )
        raise ProcessError(f"Recording failed to start within {timeout:.0f} seconds")

    @staticmethod
    def _numeric_status_value(status: Any, name: str) -> int | float | None:
        """Read a real numeric OBS status counter without accepting mock-like values."""
        value = getattr(status, name, None)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return value

    def _reconnect_client(self) -> Any | None:
        """Try to re-establish a WebSocket connection to OBS.

        Used when the connection drops mid-recording.  Returns a new client
        or ``None`` if reconnection fails.
        """
        hosts = [self.obs_host, "127.0.0.1"]
        ports = [self.obs_port]
        for h in hosts:
            for p in ports:
                if self._port_listening(h, p, timeout=0.5):
                    new_client = None
                    try:
                        new_client = obs_reqs.ReqClient(
                            host=h,
                            port=p,
                            password=self.obs_password,
                            timeout=3.0,
                        )
                        new_client.get_record_status()
                        logger.info(f"Reconnected to OBS at ws://{h}:{p}")
                        return new_client
                    except _OBS_SOCKET_ERRORS:
                        if new_client is not None:
                            with suppress(Exception):
                                new_client.disconnect()
        return None

    def _recording_limit_seconds(self) -> float:
        """Return the hard auto-stop limit in seconds."""
        return recording_limit_seconds(self.max_recording_hours)

    def _recording_warning_seconds(self) -> float:
        """Return the warning threshold in seconds."""
        warning_fraction = min(1.0, max(0.1, float(self.recording_warning_fraction)))
        return recording_warning_seconds(self.max_recording_hours, warning_fraction)

    def _format_elapsed(self, elapsed_seconds: float) -> str:
        """Format elapsed seconds for recorder warnings."""
        return format_recording_elapsed(elapsed_seconds)

    def _check_recording_duration_limit(
        self,
        elapsed_seconds: float,
        stop_event: threading.Event,
        warning_issued: bool,
        auto_stop_announced: bool,
    ) -> tuple[bool, bool]:
        """Warn near the cap and auto-stop when the recording limit is reached."""
        from scribe.utils.logging import console

        warning_fraction = min(1.0, max(0.1, float(self.recording_warning_fraction)))
        step = step_recording_duration_limit(
            elapsed_seconds,
            max_hours=self.max_recording_hours,
            warning_fraction=warning_fraction,
            warning_issued=warning_issued,
            auto_stop_announced=auto_stop_announced,
        )
        limit_seconds = self._recording_limit_seconds()

        if step.emit_warning:
            console.print(
                "[yellow]Recording is nearing the configured limit "
                f"({self._format_elapsed(elapsed_seconds)} elapsed, "
                f"max {self.max_recording_hours:.1f}h)[/yellow]"
            )
            logger.warning(
                "Recording nearing configured limit: "
                f"elapsed={elapsed_seconds:.1f}s, max={limit_seconds:.1f}s"
            )

        if step.emit_auto_stop:
            stop_event.set()
            console.print(
                "[yellow]Maximum recording duration reached "
                f"({self.max_recording_hours:.1f}h) - stopping automatically[/yellow]"
            )
            logger.warning(
                "Auto-stopping recording at configured limit: "
                f"elapsed={elapsed_seconds:.1f}s, max={limit_seconds:.1f}s"
            )

        return step.warning_issued, step.auto_stop_announced

    @staticmethod
    def _format_recording_status(
        elapsed_seconds: float,
        command: str = "",
        *,
        include_prompt: bool,
    ) -> str:
        """Build one complete status line so timer redraws preserve typed input."""
        minutes = int(max(0.0, elapsed_seconds) // 60)
        seconds = int(max(0.0, elapsed_seconds) % 60)
        status = f"Recording: {minutes:02d}:{seconds:02d}"
        if include_prompt:
            return f"{status}  |  Stop [s/stop, Enter]: {command}"
        return status

    def _write_recording_status(self, elapsed_seconds: float, *, include_prompt: bool) -> None:
        """Redraw the complete recording status without splitting timer and input."""
        with self._terminal_input_lock:
            command = "".join(self._stop_input_buffer)
            line = self._format_recording_status(
                elapsed_seconds,
                command,
                include_prompt=include_prompt,
            )
            sys.stdout.write(f"\r{line}")
            sys.stdout.flush()

    def _clear_recording_status(self) -> None:
        """Clear the complete timer and command line before normal output."""
        with self._terminal_input_lock:
            sys.stdout.write("\r" + " " * _RECORDING_STATUS_CLEAR_WIDTH + "\r")
            sys.stdout.flush()

    def _wait_for_stop_with_input(
        self, client: Any, stop_event: threading.Event
    ) -> RecordingStopResult:
        """Wait for user to stop recording, with automatic reconnect.

        Includes a deadman timer: after the user sends stop, if OBS doesn't
        confirm within 30 seconds we return anyway (the file is probably fine).
        Also handles the no-TTY case (piped stdin / CI) by allowing Ctrl-C
        or the process_timeout to end the recording.
        """
        from rich.panel import Panel

        from scribe.utils.logging import console

        initial_client = client

        def disconnect_replacement() -> None:
            if client is not initial_client:
                with suppress(Exception):
                    client.disconnect()

        has_tty = sys.stdin and sys.stdin.isatty()
        inline_command = bool(has_tty and sys.platform == "win32")
        live_status = bool(not has_tty or inline_command)

        if has_tty:
            console.print()
            console.print(
                Panel.fit(
                    "[bold green]RECORDING IN PROGRESS[/bold green]\n\n"
                    "[white]Type s or stop, then press Enter[/white]\n"
                    "[dim]Ctrl+C also stops safely[/dim]",
                    border_style="green",
                    padding=(1, 2),
                )
            )
            console.print()
        else:
            console.print(
                "[yellow]No interactive terminal - press Ctrl-C to stop recording[/yellow]"
            )

        start_time = time.time()
        last_active = True
        last_update = -1
        consecutive_errors = 0
        max_consecutive_errors = 10  # ~5 seconds of failures before reconnect
        stop_requested_at = None  # timestamp when stop was sent
        deadman_seconds = 30  # max time to wait for OBS to confirm stop
        warning_issued = False
        auto_stop_announced = False
        stopped_output_path: str | None = None
        last_output_bytes: int | float | None = None
        last_output_progress_at = time.monotonic()
        stall_warning_issued = False

        def remember_output_path(response: Any) -> None:
            nonlocal stopped_output_path
            value = getattr(response, "output_path", None)
            if isinstance(value, str) and value:
                stopped_output_path = value

        self._write_recording_status(0.0, include_prompt=inline_command)
        if has_tty and not inline_command:
            sys.stdout.write("\nStop [s/stop, Enter]: ")
            sys.stdout.flush()

        stop_requested = False

        while True:
            status = None
            try:
                status = client.get_record_status()
                active = getattr(status, "output_active", False)
                consecutive_errors = 0  # reset on success
            except _OBS_SOCKET_ERRORS:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    # WebSocket likely dropped - try to reconnect
                    self._clear_recording_status()
                    console.print("[yellow]Connection lost - reconnecting...[/yellow]")
                    new_client = self._reconnect_client()
                    if new_client:
                        with suppress(Exception):
                            client.disconnect()
                        client = new_client
                        console.print("[green]Reconnected to OBS[/green]")
                        consecutive_errors = 0
                    else:
                        console.print("[red]Could not reconnect to OBS[/red]")
                        consecutive_errors = 0
                        # If we already sent stop and can't reconnect,
                        # bail out - the file is probably being finalized
                        if stop_requested:
                            console.print(
                                "[yellow]Assuming recording stopped (connection lost)[/yellow]"
                            )
                            disconnect_replacement()
                            return RecordingStopResult(stopped_output_path)
                active = last_active  # assume unchanged while disconnected

            output_bytes = (
                self._numeric_status_value(status, "output_bytes")
                if active and status is not None
                else None
            )
            if output_bytes is not None:
                if last_output_bytes is None or output_bytes > last_output_bytes:
                    last_output_progress_at = time.monotonic()
                    stall_warning_issued = False
                elif (
                    not stop_requested
                    and not stall_warning_issued
                    and time.monotonic() - last_output_progress_at
                    >= _RECORDING_STALL_WARNING_SECONDS
                ):
                    self._clear_recording_status()
                    console.print(
                        "[bold red]Recording warning: OBS is active, but its output byte "
                        "counter has stopped advancing. Check OBS and available disk "
                        "space immediately.[/bold red]"
                    )
                    logger.error("OBS recording output byte counter stalled")
                    stall_warning_issued = True
                last_output_bytes = output_bytes

            if stop_event.is_set() and active and not stop_requested:
                # Clear the timer line and print stop message (only once)
                self._clear_recording_status()
                console.print("[cyan]Stopping recording...[/cyan]")
                logger.info("Stopping recording...")
                stop_requested = True
                stop_requested_at = time.time()
                try:
                    remember_output_path(client.stop_record())
                except Exception as e:
                    logger.warning(f"Stop command failed: {e}")
                    # Try reconnect and stop again
                    new_client = self._reconnect_client()
                    if new_client:
                        with suppress(Exception):
                            client.disconnect()
                        client = new_client
                        try:
                            remember_output_path(client.stop_record())
                        except _OBS_SOCKET_ERRORS:
                            logger.warning("Stop failed after reconnect too")

            # Deadman timer: if we sent stop but OBS still reports active,
            # bail out after 30s - the file is almost certainly written.
            if stop_requested and stop_requested_at:
                if time.time() - stop_requested_at > deadman_seconds:
                    self._clear_recording_status()
                    console.print(
                        "[yellow]OBS did not confirm stop within "
                        f"{deadman_seconds}s - proceeding anyway[/yellow]"
                    )
                    logger.warning("Deadman timer expired waiting for OBS to confirm stop")
                    disconnect_replacement()
                    return RecordingStopResult(stopped_output_path)

            if not active and last_active:
                # Clear the timer line and print stopped message
                self._clear_recording_status()
                unexpected_stop = not stop_requested and not stop_event.is_set()
                if unexpected_stop:
                    console.print(
                        "[bold red]OBS stopped recording unexpectedly. Scribe will "
                        "preserve the partial file and report this session as "
                        "incomplete.[/bold red]"
                    )
                    logger.error("OBS stopped recording before a Scribe stop request")
                else:
                    console.print("[green]Recording stopped[/green]")
                    logger.info("Recording stopped")
                disconnect_replacement()
                return RecordingStopResult(stopped_output_path, unexpected_stop)

            elapsed_seconds = max(0.0, time.time() - start_time)
            warning_issued, auto_stop_announced = self._check_recording_duration_limit(
                elapsed_seconds,
                stop_event,
                warning_issued,
                auto_stop_announced,
            )

            # Auto-stop can set stop_event after the earlier branch; honor it immediately.
            if stop_event.is_set() and active and not stop_requested:
                self._clear_recording_status()
                console.print("[cyan]Stopping recording...[/cyan]")
                logger.info("Stopping recording...")
                stop_requested = True
                stop_requested_at = time.time()
                try:
                    remember_output_path(client.stop_record())
                except Exception as e:
                    logger.warning(f"Stop command failed: {e}")
                    new_client = self._reconnect_client()
                    if new_client:
                        with suppress(Exception):
                            client.disconnect()
                        client = new_client
                        try:
                            remember_output_path(client.stop_record())
                        except _OBS_SOCKET_ERRORS:
                            logger.warning("Stop failed after reconnect too")

            # Update recording time every second
            if active and live_status:
                # Only update display every second to reduce flicker
                if int(elapsed_seconds) > last_update:
                    last_update = int(elapsed_seconds)
                    self._write_recording_status(
                        elapsed_seconds,
                        include_prompt=inline_command,
                    )

            last_active = active
            time.sleep(0.5)

    def _wait_for_stop_cli(
        self, stop_event: threading.Event, client: Any | None = None
    ) -> str | None:
        """Wait for stop in fallback mode and use WebSocket only when available.

        OBS does not provide a supported ``--stoprecording`` command-line option.
        When WebSocket is unavailable, asking for a manual stop is safer than
        terminating OBS or moving a file that is still being written.
        """
        from rich.panel import Panel

        from scribe.utils.logging import console

        has_tty = bool(sys.stdin and sys.stdin.isatty())
        inline_command = bool(has_tty and sys.platform == "win32")
        live_status = bool(not has_tty or inline_command)

        if has_tty:
            console.print()
            console.print(
                Panel.fit(
                    "[bold white on red]  RECORDING  [/bold white on red]\n\n"
                    "[yellow]Type s or stop, then press Enter[/yellow]\n"
                    "[dim]Ctrl+C also stops safely[/dim]",
                    border_style="red",
                    padding=(1, 2),
                )
            )
            console.print()

        # Show elapsed time timer
        start_time = time.time()
        last_update = -1
        warning_issued = False
        auto_stop_announced = False

        self._write_recording_status(0.0, include_prompt=inline_command)
        if has_tty and not inline_command:
            sys.stdout.write("\nStop [s/stop, Enter]: ")
            sys.stdout.flush()

        while not stop_event.is_set():
            elapsed = max(0.0, time.time() - start_time)
            warning_issued, auto_stop_announced = self._check_recording_duration_limit(
                elapsed,
                stop_event,
                warning_issued,
                auto_stop_announced,
            )
            # Update display every second
            if live_status and int(elapsed) > last_update:
                last_update = int(elapsed)
                self._write_recording_status(elapsed, include_prompt=inline_command)
            time.sleep(0.2)

        # Clear the timer line
        self._clear_recording_status()

        if client is not None:
            console.print("[cyan]Stopping recording through OBS WebSocket...[/cyan]")
            logger.info("Stopping CLI-started recording through OBS WebSocket")
            try:
                response = client.stop_record()
            except Exception as e:
                console.print(
                    "[yellow]OBS did not accept the safe stop request. Stop recording "
                    "manually; Scribe will not terminate OBS.[/yellow]"
                )
                logger.warning("Could not stop emergency capture through WebSocket: %s", e)
                return None
            value = getattr(response, "output_path", None)
            return value if isinstance(value, str) and value else None

        console.print(
            "[yellow]Stop recording in OBS now. Scribe will wait for the file to "
            "finish and will not terminate OBS or touch a live file.[/yellow]"
        )
        logger.warning("Manual OBS stop required because WebSocket control is unavailable")
        return None

    def _start_stop_listener(self) -> tuple[threading.Event, Callable[[], None]]:
        """Start background thread listening for stop command.

        Also installs a SIGINT (Ctrl-C) handler so recording can be stopped
        even when stdin is not a TTY (piped, CI, etc.).

        Returns (stop_event, restore_sigint) - caller MUST call
        restore_sigint() when recording is done (use finally).
        """
        import signal

        from scribe.utils.logging import console

        ev = threading.Event()
        with self._terminal_input_lock:
            self._stop_input_buffer.clear()

        # Always wire up Ctrl-C as a stop mechanism
        _original_sigint = signal.getsignal(signal.SIGINT)
        _restored = False

        def _restore() -> None:
            nonlocal _restored
            if not _restored:
                with suppress(ValueError, OSError):
                    signal.signal(signal.SIGINT, _original_sigint)
                _restored = True

        def _sigint_handler(signum: int, frame: Any) -> None:
            console.print("\n[yellow]Ctrl-C received - stopping recording...[/yellow]")
            ev.set()
            # Restore original handler so a second Ctrl-C hard-kills
            _restore()

        try:
            signal.signal(signal.SIGINT, _sigint_handler)
        except ValueError:
            # Not in main thread - Ctrl-C can't be wired, but typed
            # stop commands and process_timeout still work
            logger.debug("Cannot install SIGINT handler (not main thread)")

        def _listen() -> None:
            if not sys.stdin or not sys.stdin.isatty():
                logger.debug("stdin not available for stop listener (Ctrl-C still works)")
                return

            # Windows-specific: use msvcrt for non-blocking input
            if sys.platform == "win32":
                try:
                    self._listen_windows(ev)
                except OSError as e:
                    logger.debug(f"Windows input error: {e}")
                    # Fall back to readline
                    self._listen_readline(ev)
            else:
                # The daemon listener thread may block safely on readline.
                self._listen_readline(ev)

        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        return ev, _restore

    def _listen_windows(self, ev: threading.Event) -> None:
        """Echo stop input through the coordinated status-line renderer."""
        msvcrt = cast(_WindowsConsoleInput, import_module("msvcrt"))

        while not ev.is_set():
            if msvcrt.kbhit():
                char = msvcrt.getwch()
                if char == "\x03":
                    ev.set()
                    break
                should_stop = False
                with self._terminal_input_lock:
                    if char in {"\r", "\n"}:
                        command = "".join(self._stop_input_buffer).strip().lower()
                        if command in _STOP_COMMANDS:
                            sys.stdout.write("\n")
                            should_stop = True
                        else:
                            visible_length = len(self._stop_input_buffer)
                            self._stop_input_buffer.clear()
                            sys.stdout.write("\b \b" * visible_length)
                    elif char in {"\b", "\x7f"}:
                        if self._stop_input_buffer:
                            self._stop_input_buffer.pop()
                            sys.stdout.write("\b \b")
                    elif char.isprintable() and len(self._stop_input_buffer) < 8:
                        self._stop_input_buffer.append(char)
                        sys.stdout.write(char)
                    sys.stdout.flush()
                if should_stop:
                    ev.set()
                    break
            else:
                time.sleep(0.1)

    def _listen_readline(self, ev: threading.Event) -> None:
        """Fallback listener for explicit typed stop commands."""
        try:
            while not ev.is_set():
                try:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    if line.strip().lower() in _STOP_COMMANDS:
                        ev.set()
                        break
                except (OSError, EOFError) as e:
                    logger.debug(f"Error reading input: {e}")
                    break
        except OSError as e:
            logger.debug(f"Stop listener error: {e}")

    def _get_effective_record_dir(self, client: Any, fallback: str) -> str:
        """Get effective recording directory from OBS.

        Returns the directory OBS is actually recording to.  If the query
        fails, logs a warning and falls back to the configured folder.
        """
        try:
            cur = client.get_record_directory()
            d = getattr(cur, "record_directory", None) or ""
            if d:
                return os.path.abspath(d)
        except Exception as e:
            # ADR-002: obsws_python query failures are assorted types; use fallback.
            logger.warning(f"Could not query OBS recording directory: {e}")
        logger.warning(f"Using fallback recording directory: {fallback}")
        return os.path.abspath(fallback)

    def _newest_media_since(self, dir_path: str, since_ts: float) -> tuple[str | None, str | None]:
        """Find newest MP4/MKV file since timestamp."""
        best_mp4: tuple[str | None, float] = (None, -1.0)
        best_mkv: tuple[str | None, float] = (None, -1.0)

        try:
            entries = os.listdir(dir_path)
        except OSError:
            return None, None

        for name in entries:
            lower = name.lower()
            if not (lower.endswith(".mp4") or lower.endswith(".mkv")):
                continue

            p = os.path.join(dir_path, name)
            try:
                # Use mtime - getctime on Linux is inode change time, not creation
                c = os.path.getmtime(p)
            except OSError:
                continue

            if c >= since_ts - 5:
                if lower.endswith(".mp4") and c > best_mp4[1]:
                    best_mp4 = (p, c)
                if lower.endswith(".mkv") and c > best_mkv[1]:
                    best_mkv = (p, c)

        return best_mp4[0], best_mkv[0]

    def _wait_until_file_finalized(
        self, path: str, idle_seconds: float = 3.0, max_wait: float = 600.0
    ) -> bool:
        """Wait for file to stop growing.

        Returns False if the file never stabilizes within max_wait. Callers must
        leave an unstable file in place because moving it can corrupt capture.
        """
        previous_size: int | None = None
        stable = 0.0
        waited = 0.0

        while waited < max_wait:
            try:
                size = os.path.getsize(path)
            except FileNotFoundError:
                time.sleep(0.5)
                waited += 0.5
                continue

            assessment = assess_recording_file_stability(size, previous_size, min_bytes=1)
            if assessment.ready:
                stable += 0.5
                if stable >= idle_seconds:
                    return True
            else:
                stable = 0.0
            previous_size = size

            time.sleep(0.5)
            waited += 0.5

        logger.warning(f"File finalization timed out after {max_wait}s: {path}")
        # Don't raise - the file likely exists and is usable, but warn loudly
        from scribe.utils.logging import console

        console.print(
            f"[yellow]Warning: recording file may still be writing "
            f"(waited {int(max_wait)}s)[/yellow]"
        )
        return False

    def _finalize_recording(
        self, media_path: str | Path, ext: str, meeting_name: str, start_ts: float
    ) -> Path:
        """Finalize recording file."""
        from scribe.utils.logging import console

        src_path = str(media_path)
        target_ext = ".mp4"

        # Remux MKV to MP4 if needed
        if ext == ".mkv":
            console.print("[cyan]Converting MKV to MP4...[/cyan]")
            ffmpeg_path = get_ffmpeg_path()
            if ffmpeg_path:
                tmp_mp4 = Path(src_path).parent / self._safe_filename(
                    meeting_name, start_ts, ".mp4"
                )
                if self._remux_mkv_to_mp4(src_path, str(tmp_mp4)):
                    # Drop the now-redundant source MKV; the MP4 is what we keep.
                    with suppress(Exception):
                        os.remove(str(media_path))
                    src_path = str(tmp_mp4)
                    logger.info("MKV to MP4 conversion complete")
                else:
                    target_ext = ".mkv"
                    console.print("[yellow]Conversion failed, keeping MKV format[/yellow]")
            else:
                target_ext = ".mkv"
                console.print("[yellow]FFmpeg not found, keeping MKV format[/yellow]")

        # Move to final location
        final_name = self._safe_filename(meeting_name, start_ts, target_ext)
        final_path = self.output_folder / final_name

        try:
            if Path(src_path).parent != self.output_folder:
                self._ensure_dir_writable(self.output_folder)

            try:
                os.replace(src_path, str(final_path))
            except OSError:
                shutil.copy2(src_path, str(final_path))
                with suppress(OSError):
                    os.remove(src_path)
        except OSError as e:
            raise ProcessError(f"Failed to place final file: {e}") from e

        logger.info(f"Recording saved: {final_path}")
        return final_path

    def _safe_filename(self, label: str, ts: float, ext: str = ".mp4") -> str:
        """Generate safe filename with timestamp."""
        base = "".join(c for c in label if c not in r'<>:"/\\|?*').strip() or "Recording"
        dt = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(ts))
        return f"{base}_{dt}{ext}"

    def _remux_mkv_to_mp4(self, mkv_path: str, mp4_path: str) -> bool:
        """Remux MKV to MP4 using ffmpeg."""
        ffmpeg_path = get_ffmpeg_path()
        if not ffmpeg_path:
            logger.warning("FFmpeg not found - cannot remux MKV to MP4")
            return False

        try:
            cmd = [str(ffmpeg_path), "-y", "-i", mkv_path, "-c", "copy", mp4_path]
            # Bounded so a corrupt or still-locked MKV cannot hang the whole CLI;
            # on timeout we keep the original MKV rather than blocking forever.
            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=600,
            )
            if result.returncode != 0:
                stderr_tail = (result.stderr or b"")[-500:].decode("utf-8", errors="replace")
                logger.warning(f"FFmpeg remux failed (exit {result.returncode}): {stderr_tail}")
                return False
            return os.path.isfile(mp4_path) and os.path.getsize(mp4_path) > 0
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg remux timed out; keeping the original MKV")
            return False
        except _SUBPROCESS_PROBE_ERRORS as e:
            logger.warning(f"FFmpeg remux exception: {e}")
            return False

    def _port_listening(self, host: str, port: int, timeout: float = 0.75) -> bool:
        """Check if port is listening."""
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _ensure_dir_writable(self, path: Path) -> Path:
        """Ensure directory exists and is writable."""
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)

        # Test write permissions
        probe = path / f".write_test_{uuid.uuid4().hex}.tmp"
        try:
            probe.write_bytes(b".")
            probe.unlink()
        except OSError as e:
            raise ProcessError(f"Directory not writable: {path}. Reason: {e}")

        return path
