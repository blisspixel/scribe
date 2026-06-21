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
from pathlib import Path
from typing import Any

from scribe.exceptions import ProcessError
from scribe.models.config import ScribeConfig
from scribe.utils.logging import get_logger
from scribe.utils.obs_config import read_obs_websocket_config
from scribe.utils.platform import get_ffmpeg_path, get_obs_executable_path

logger = get_logger(__name__)

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
#   - Fall back to a secondary strategy (WebSocket → CLI), or
#   - Raise a typed ScribeError (ProcessError) with context for the caller.
# See ROADMAP.md Step 4 and future docs/adr/ for the exception taxonomy rationale.
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


class OBSActiveRecordingError(ConnectionError):
    """Raised when OBS appears to be recording and recovery must not attach."""


class OBSAuthenticationError(ConnectionError):
    """Raised when OBS WebSocket rejects the configured password."""


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
            # Already a ProcessError - don't double-wrap
            raise
        except Exception as e:
            logger.error(f"Recording failed: {e}")
            raise ProcessError(f"OBS recording failed: {e}", context={"meeting": meeting_name})
        finally:
            restore_sigint()

    def _record_with_websocket(self, meeting_name: str, stop_event: threading.Event) -> Path:
        """Record using OBS WebSocket.

        Falls back to CLI mode only when the WebSocket *connection* cannot be
        established.  Errors during an active recording (start/stop/file
        detection) are raised so the user gets clear feedback.
        """
        try:
            with self._connect_obs() as client:
                self._set_record_dir_if_possible(client, str(self.output_folder))
                eff_dir = self._get_effective_record_dir(client, str(self.output_folder))

                self._start_recording_if_needed(client)
                # Set timestamp AFTER recording has started
                start_ts = time.time()
                self._wait_for_stop_with_input(client, stop_event)

                # Find recorded file - OBS may still be flushing the
                # container, so retry for up to 15 seconds.
                media = None
                ext = ".mp4"
                for _wait in range(30):
                    mp4, mkv = self._newest_media_since(eff_dir, start_ts)
                    media = mp4 or mkv
                    if media:
                        ext = ".mp4" if mp4 else ".mkv"
                        break
                    time.sleep(0.5)

                if not media:
                    raise ProcessError(
                        f"Could not locate recorded media in {eff_dir}. "
                        "OBS may be saving to a different folder - check "
                        "OBS Settings → Output → Recording Path."
                    )

                self._wait_until_file_finalized(media)
                return self._finalize_recording(media, ext, meeting_name, start_ts)

        except OBSActiveRecordingError as e:
            logger.warning("OBS appears to be actively recording; not falling back to CLI")
            raise ProcessError(str(e)) from e
        except OBSAuthenticationError as e:
            logger.warning("OBS WebSocket authentication failed; not falling back to CLI")
            raise ProcessError(str(e)) from e
        except ConnectionError:
            # Only fall back to CLI mode for *connection* failures
            logger.warning("WebSocket connection failed, falling back to CLI mode")
            return self._record_with_cli(meeting_name, stop_event)

    def _record_with_cli(self, meeting_name: str, stop_event: threading.Event) -> Path:
        """
        Record using CLI fallback.

        This method handles the case where WebSocket connection fails.
        It tries to launch OBS with recording, but provides clear feedback
        if recording doesn't actually start.
        """
        from pathlib import Path as PathType

        from scribe.utils.logging import console

        console.print("[yellow]Using CLI fallback mode[/yellow]")
        console.print("[dim]Note: CLI mode has limited control over OBS[/dim]")
        console.print("[yellow]Please start recording manually in OBS[/yellow]")
        console.print()

        # CLI mode: Don't try to launch OBS automatically
        # User must start OBS and recording manually
        # This is intentional - CLI mode has limited control
        console.print("[dim]CLI mode does not auto-launch OBS[/dim]")
        console.print("[dim]Please ensure OBS is running and start recording manually[/dim]")

        # Set timestamp AFTER we've sent the start recording command
        # This ensures we only detect files created after this point
        start_ts = time.time()

        # Monitor for new file with better feedback
        console.print()
        console.print("[cyan]Waiting for recording to start...[/cyan]")
        console.print("[dim]Looking for new media files in:[/dim]")

        candidate_dirs = [
            self.output_folder,
            Path.home() / "Videos",
            Path.home() / "Videos" / "OBS",
        ]

        for d in candidate_dirs:
            if d.exists():
                console.print(f"[dim]  • {d}[/dim]")

        found_path: str | None = None
        ext = ".mp4"
        deadline = time.time() + 30
        last_check_msg = 0.0

        while time.time() < deadline and not found_path and not stop_event.is_set():
            for d in candidate_dirs:
                if not d.exists():
                    continue
                mp4, mkv = self._newest_media_since(str(d), start_ts)
                found_path = mp4 or mkv
                if found_path:
                    ext = ".mp4" if mp4 else ".mkv"
                    break

            # Show progress every 5 seconds
            elapsed = time.time() - start_ts
            if elapsed - last_check_msg >= 5:
                remaining = int(deadline - time.time())
                console.print(f"[dim]Still waiting... ({remaining}s remaining)[/dim]")
                last_check_msg = elapsed

            time.sleep(0.5)

        if stop_event.is_set() and not found_path:
            raise ProcessError("Recording cancelled before a file was detected")

        if not found_path:
            console.print()
            console.print("[bold red]ERROR: No recording file detected[/bold red]")
            console.print()
            console.print("[yellow]Possible causes:[/yellow]")
            console.print("  1. OBS is not actually recording (check OBS window)")
            console.print("  2. OBS is recording to a different folder")
            console.print("  3. Recording hasn't started yet (try waiting longer)")
            console.print()
            console.print("[yellow]To fix:[/yellow]")
            console.print("  1. Open OBS Studio manually")
            console.print("  2. Click 'Start Recording' button")
            console.print("  3. Run 'scribe rec' again")
            console.print()
            raise ProcessError(
                "No media file appeared after starting recording. "
                "OBS may not be recording. Please check OBS window and start recording manually."
            )

        # Convert string path to Path object for consistent handling
        recorded_path = PathType(found_path)

        console.print(f"[green]Recording detected: {recorded_path.name}[/green]")
        console.print()

        # Now start the stop listener thread (after file is detected)
        threading.Thread(target=self._wait_for_stop_cli, args=(stop_event,), daemon=True).start()

        # Wait for user to type 'stop' (with periodic timeout so we don't
        # block forever if the listener thread dies)
        while not stop_event.wait(timeout=1.0):
            pass

        console.print()
        console.print("[cyan]Waiting for OBS to finalize file...[/cyan]")
        console.print("[dim]This may take a few seconds...[/dim]")

        # Give OBS time to stop and finalize the file
        # The --stoprecording command was sent by _wait_for_stop_cli
        time.sleep(3)

        # Wait for file to stabilize (stop growing)
        self._wait_until_file_finalized(str(recorded_path))

        return self._finalize_recording(recorded_path, ext, meeting_name, start_ts)

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
                            client.close()

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
            f"`$env:SCRIBE_OBS_PORT='{obs_port}'`."
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

    def _kill_existing_obs(self) -> None:
        """Kill any running OBS processes and clean up crash sentinels.

        Without cleanup, OBS detects an "unclean shutdown" on next launch and
        presents the safe-mode dialog, blocking automated startup.
        """
        from scribe.utils.platform import is_windows

        try:
            if is_windows():
                for exe in ("obs64.exe", "obs32.exe"):
                    subprocess.run(
                        ["taskkill", "/F", "/IM", exe],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
            else:
                # Match the exact process name, never a substring: "pkill -f obs"
                # would also kill obsidian, an editor with "obs" in its path, or even
                # this process if "obs" appears in its argv. OBS is "obs" on Linux and
                # "OBS" on macOS.
                for name in ("obs", "OBS"):
                    subprocess.run(
                        ["pkill", "-x", name],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5,
                    )
        except Exception as e:
            logger.debug(f"Could not kill OBS processes: {e}")

        # Wait for process to fully exit, then verify
        time.sleep(1.0)

        # Verify OBS is actually gone
        if self._obs_process_running():
            logger.warning("OBS still running after kill attempt, retrying")
            try:
                if is_windows():
                    for exe in ("obs64.exe", "obs32.exe"):
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/IM", exe],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                else:
                    for name in ("obs", "OBS"):
                        subprocess.run(
                            ["pkill", "-9", "-x", name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=5,
                        )
            except Exception:
                # Best-effort cleanup only - OBS may already be dead or permissions
                # may prevent kill on this platform. Non-fatal; proceed to sentinel clean.
                logger.debug("Secondary kill attempt failed (non-fatal during OBS cleanup)")
            time.sleep(1.0)

        # Clean OBS crash sentinel so it won't ask about safe mode
        self._clean_obs_crash_sentinel()

        logger.debug("OBS process cleanup complete")

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
                # Exact name match only (see _kill_existing_obs); a substring match
                # would treat unrelated processes as OBS and trigger a SIGKILL escalation.
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
        except Exception:
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
        except Exception:
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
        except Exception as e:
            logger.debug(f"Could not clean OBS crash sentinel: {e}")

    def _launch_obs(self, obs_exe: Path) -> None:
        """Launch OBS for the current platform.

        On macOS, OBS is an app bundle that must be started via ``open`` so it
        finds its bundle resources (Popen-ing the inner binary is unreliable),
        and ``--minimize-to-tray`` has no meaning there. On Windows and Linux we
        run the executable directly with the appropriate flags.
        """
        from scribe.utils.platform import is_macos, is_windows

        if is_macos():
            bundle = next((p for p in obs_exe.parents if p.suffix == ".app"), None)
            app_ref = str(bundle) if bundle is not None else "OBS"
            subprocess.Popen(
                ["open", "-a", app_ref, "--args", "--disable-shutdown-check"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return

        flags = (
            ["--minimize-to-tray", "--disable-shutdown-check"]
            if is_windows()
            else ["--disable-shutdown-check"]
        )
        subprocess.Popen(
            [str(obs_exe), *flags],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(obs_exe.parent),
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
                                client.close()
                    except ValueError as e:
                        if "hostname is invalid" in str(e).lower() or "invalid" in str(e).lower():
                            logger.debug(f"Hostname validation failed for {h}:{p}")
                        else:
                            logger.debug(f"ValueError during connection to {h}:{p}")
                        if client:
                            with suppress(Exception):
                                client.close()
                    except obs_error.OBSSDKRequestError as e:
                        if self._is_obs_auth_error(e):
                            logger.warning(
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
                                client.close()
                    except Exception as e:
                        if self._is_obs_auth_error(e):
                            if client:
                                with suppress(Exception):
                                    client.close()
                            raise OBSAuthenticationError(
                                self._obs_password_fix_suggestion(wrong=True)
                            ) from e
                        # Connection failed - try next host/port
                        logger.debug(f"Connection to {h}:{p} failed: {e}")
                        if client:
                            with suppress(Exception):
                                client.close()
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
                                            client.close()
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
                                    client.close()
                        except obs_error.OBSSDKRequestError as e:
                            if self._is_obs_auth_error(e):
                                if client:
                                    with suppress(Exception):
                                        client.close()
                                raise OBSAuthenticationError(
                                    self._obs_password_fix_suggestion(wrong=True)
                                ) from e
                            logger.debug(f"OBS SDK error during startup at {h}:{p}: {e}")
                            if client:
                                with suppress(Exception):
                                    client.close()
                        except Exception as e:
                            if self._is_obs_auth_error(e):
                                if client:
                                    with suppress(Exception):
                                        client.close()
                                raise OBSAuthenticationError(
                                    self._obs_password_fix_suggestion(wrong=True)
                                ) from e
                            logger.debug(f"Connection to {h}:{p} failed: {e}")
                            if client:
                                with suppress(Exception):
                                    client.close()
            time.sleep(0.5)
        return None

    @contextmanager
    def _connect_obs(self, max_wait_seconds: int = 15) -> Generator[Any, None, None]:
        """
        Connect to OBS WebSocket with conservative recovery.

        Strategy:
        1. Try connecting to already-running OBS
        2. If OBS is already running or recording, refuse to restart it
        3. If no OBS process is present, clean crash sentinels and launch once more
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
                    client.close()
            return

        if self._obs_recording_process_running():
            raise OBSActiveRecordingError(
                "OBS appears to be actively recording, but WebSocket is unreachable. "
                "Refusing to restart OBS during an active recording. Finish the "
                "recording manually, then run `scribe rec --check` before the next one."
            )

        if self._obs_process_running():
            raise ConnectionError(
                "OBS is already running, but WebSocket is unreachable. Refusing to "
                "restart a running OBS instance. Enable Tools > WebSocket Server "
                "Settings or close OBS manually, then run `scribe rec --check`."
            )

        # Phase 2: no OBS process is present, so launch without terminating anything.
        obs_exe = get_obs_executable_path()
        max_launch_attempts = 2

        for attempt in range(1, max_launch_attempts + 1):
            console.print(
                f"[cyan]Preparing OBS (attempt {attempt}/{max_launch_attempts})...[/cyan]"
            )

            self._clean_obs_crash_sentinel()

            if not obs_exe:
                break  # nothing to launch

            console.print("[cyan]Starting OBS Studio...[/cyan]")
            logger.info("Starting OBS (attempt %d)...", attempt)
            try:
                self._launch_obs(obs_exe)
            except Exception as e:
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
                        client.close()
                return

            # Launch succeeded but WebSocket never became reachable - retry
            logger.warning("OBS launched but WebSocket unreachable (attempt %d)", attempt)

        raise ConnectionError(
            "Could not connect to OBS WebSocket. Ensure OBS is installed, "
            "WebSocket server is enabled (Tools → WebSocket Server Settings), "
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
        except Exception as e:
            logger.warning(f"Could not set record directory: {e}")
            console.print(
                "[yellow]Could not set recording folder - OBS may record elsewhere[/yellow]"
            )
            return False

    def _start_recording_if_needed(self, client: Any) -> None:
        """Ensure a fresh recording is running.

        If a stale recording from a previous session is active, stop it first
        so the new session gets its own clean file.
        """
        from scribe.utils.logging import console

        status = client.get_record_status()
        if getattr(status, "output_active", False):
            console.print("[yellow]Stale recording detected - stopping it first...[/yellow]")
            logger.info("Stopping stale recording before starting new one")
            stale_stopped = False
            try:
                client.stop_record()
                # Wait for OBS to finalize the old file
                for _ in range(20):
                    time.sleep(0.25)
                    status = client.get_record_status()
                    if not getattr(status, "output_active", False):
                        stale_stopped = True
                        break
            except Exception as e:
                logger.warning(f"Could not stop stale recording: {e}")

            if not stale_stopped:
                # Verify one more time
                try:
                    status = client.get_record_status()
                    stale_stopped = not getattr(status, "output_active", False)
                except Exception as e:
                    # ADR-002: OBS may drop the socket during stale-stop; treat as unknown.
                    logger.debug(f"Could not re-check OBS record status: {e}")

            if not stale_stopped:
                raise ProcessError(
                    "Cannot start new recording - OBS still has an active "
                    "recording that could not be stopped. Please stop it "
                    "manually in OBS and try again."
                )

            console.print("[green]Stale recording stopped[/green]")
            # Brief pause so OBS is ready to start a new recording
            time.sleep(0.5)

        console.print("[cyan]Starting recording...[/cyan]")
        logger.info("Starting recording...")
        try:
            client.start_record()
        except Exception as e:
            err_str = str(e).lower()
            if "already" in err_str:
                # Shouldn't reach here (stale-stop above), but handle
                console.print("[yellow]OBS reports recording already active[/yellow]")
                return
            raise ProcessError(
                f"OBS refused to start recording: {e}. "
                "Check OBS Settings → Output for valid recording path and codec."
            )

        # Verify recording started
        for _ in range(25):
            time.sleep(0.2)
            try:
                status = client.get_record_status()
            except Exception:
                continue
            if getattr(status, "output_active", False):
                console.print("Recording started")
                logger.info("Recording started successfully")
                return

        raise ProcessError("Recording failed to start within 5 seconds")

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
                    except Exception:
                        pass
        return None

    def _recording_limit_seconds(self) -> float:
        """Return the hard auto-stop limit in seconds."""
        return max(0.0, float(self.max_recording_hours) * 3600.0)

    def _recording_warning_seconds(self) -> float:
        """Return the warning threshold in seconds."""
        limit_seconds = self._recording_limit_seconds()
        warning_fraction = min(1.0, max(0.1, float(self.recording_warning_fraction)))
        return limit_seconds * warning_fraction

    def _format_elapsed(self, elapsed_seconds: float) -> str:
        """Format elapsed seconds for recorder warnings."""
        total_seconds = max(0, int(elapsed_seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, _ = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def _check_recording_duration_limit(
        self,
        elapsed_seconds: float,
        stop_event: threading.Event,
        warning_issued: bool,
        auto_stop_announced: bool,
    ) -> tuple[bool, bool]:
        """Warn near the cap and auto-stop when the recording limit is reached."""
        from scribe.utils.logging import console

        warning_seconds = self._recording_warning_seconds()
        limit_seconds = self._recording_limit_seconds()

        if (
            not warning_issued
            and warning_seconds > 0
            and elapsed_seconds >= warning_seconds
            and elapsed_seconds < limit_seconds
        ):
            console.print(
                "[yellow]Recording is nearing the configured limit "
                f"({self._format_elapsed(elapsed_seconds)} elapsed, "
                f"max {self.max_recording_hours:.1f}h)[/yellow]"
            )
            logger.warning(
                "Recording nearing configured limit: "
                f"elapsed={elapsed_seconds:.1f}s, max={limit_seconds:.1f}s"
            )
            warning_issued = True

        if not auto_stop_announced and limit_seconds > 0 and elapsed_seconds >= limit_seconds:
            stop_event.set()
            console.print(
                "[yellow]Maximum recording duration reached "
                f"({self.max_recording_hours:.1f}h) - stopping automatically[/yellow]"
            )
            logger.warning(
                "Auto-stopping recording at configured limit: "
                f"elapsed={elapsed_seconds:.1f}s, max={limit_seconds:.1f}s"
            )
            auto_stop_announced = True

        return warning_issued, auto_stop_announced

    def _wait_for_stop_with_input(self, client: Any, stop_event: threading.Event) -> None:
        """Wait for user to stop recording, with automatic reconnect.

        Includes a deadman timer: after the user sends stop, if OBS doesn't
        confirm within 30 seconds we return anyway (the file is probably fine).
        Also handles the no-TTY case (piped stdin / CI) by allowing Ctrl-C
        or the process_timeout to end the recording.
        """
        from rich.panel import Panel

        from scribe.utils.logging import console

        has_tty = sys.stdin and sys.stdin.isatty()

        if has_tty:
            console.print()
            console.print(
                Panel.fit(
                    "[bold green]RECORDING IN PROGRESS[/bold green]\n\n"
                    "[white]Type 'stop' and press Enter to stop[/white]\n"
                    "[dim]Commands: stop, s, q, quit, exit[/dim]",
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

        # Print initial status line using raw stdout for proper \r handling
        sys.stdout.write("Recording: 00:00")
        sys.stdout.flush()

        stop_requested = False

        while True:
            try:
                status = client.get_record_status()
                active = getattr(status, "output_active", False)
                consecutive_errors = 0  # reset on success
            except Exception:
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    # WebSocket likely dropped - try to reconnect
                    sys.stdout.write("\r" + " " * 50 + "\r")
                    sys.stdout.flush()
                    console.print("[yellow]Connection lost - reconnecting...[/yellow]")
                    new_client = self._reconnect_client()
                    if new_client:
                        with suppress(Exception):
                            client.close()
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
                            return
                active = last_active  # assume unchanged while disconnected

            if stop_event.is_set() and active and not stop_requested:
                # Clear the timer line and print stop message (only once)
                sys.stdout.write("\r" + " " * 50 + "\r")
                sys.stdout.flush()
                console.print("[cyan]Stopping recording...[/cyan]")
                logger.info("Stopping recording...")
                stop_requested = True
                stop_requested_at = time.time()
                try:
                    client.stop_record()
                except Exception as e:
                    logger.warning(f"Stop command failed: {e}")
                    # Try reconnect and stop again
                    new_client = self._reconnect_client()
                    if new_client:
                        with suppress(Exception):
                            client.close()
                        client = new_client
                        try:
                            client.stop_record()
                        except Exception:
                            logger.warning("Stop failed after reconnect too")

            # Deadman timer: if we sent stop but OBS still reports active,
            # bail out after 30s - the file is almost certainly written.
            if stop_requested and stop_requested_at:
                if time.time() - stop_requested_at > deadman_seconds:
                    sys.stdout.write("\r" + " " * 50 + "\r")
                    sys.stdout.flush()
                    console.print(
                        "[yellow]OBS did not confirm stop within "
                        f"{deadman_seconds}s - proceeding anyway[/yellow]"
                    )
                    logger.warning("Deadman timer expired waiting for OBS to confirm stop")
                    return

            if not active and last_active:
                # Clear the timer line and print stopped message
                sys.stdout.write("\r" + " " * 50 + "\r")
                sys.stdout.flush()
                console.print("[green]Recording stopped[/green]")
                logger.info("Recording stopped")
                return

            elapsed_seconds = max(0.0, time.time() - start_time)
            warning_issued, auto_stop_announced = self._check_recording_duration_limit(
                elapsed_seconds,
                stop_event,
                warning_issued,
                auto_stop_announced,
            )

            # Auto-stop can set stop_event after the earlier branch; honor it immediately.
            if stop_event.is_set() and active and not stop_requested:
                sys.stdout.write("\r" + " " * 50 + "\r")
                sys.stdout.flush()
                console.print("[cyan]Stopping recording...[/cyan]")
                logger.info("Stopping recording...")
                stop_requested = True
                stop_requested_at = time.time()
                try:
                    client.stop_record()
                except Exception as e:
                    logger.warning(f"Stop command failed: {e}")
                    new_client = self._reconnect_client()
                    if new_client:
                        with suppress(Exception):
                            client.close()
                        client = new_client
                        try:
                            client.stop_record()
                        except Exception:
                            logger.warning("Stop failed after reconnect too")

            # Update recording time every second
            if active:
                # Only update display every second to reduce flicker
                if int(elapsed_seconds) > last_update:
                    last_update = int(elapsed_seconds)
                    mins = int(elapsed_seconds // 60)
                    secs = int(elapsed_seconds % 60)
                    # Use raw stdout with \r for proper overwriting
                    sys.stdout.write(f"\rRecording: {mins:02d}:{secs:02d}")
                    sys.stdout.flush()

            last_active = active
            time.sleep(0.5)

    def _wait_for_stop_cli(self, stop_event: threading.Event) -> None:
        """CLI fallback stop listener with timer."""
        from rich.panel import Panel

        from scribe.utils.logging import console

        if sys.stdin and sys.stdin.isatty():
            console.print()
            console.print(
                Panel.fit(
                    "[bold white on red]  RECORDING  [/bold white on red]\n\n"
                    "[yellow]Type 'stop' and press Enter to stop[/yellow]\n"
                    "[dim]Commands: stop, s, q, quit, exit[/dim]",
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

        # Print initial timer using raw stdout for proper \r handling
        sys.stdout.write("Recording: 00:00")
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
            if int(elapsed) > last_update:
                last_update = int(elapsed)
                mins = int(elapsed // 60)
                secs = int(elapsed % 60)
                # Use raw stdout with \r for proper overwriting
                sys.stdout.write(f"\rRecording: {mins:02d}:{secs:02d}")
                sys.stdout.flush()
            time.sleep(0.2)

        # Clear the timer line
        sys.stdout.write("\r" + " " * 50 + "\r")
        sys.stdout.flush()

        console.print("[cyan]Sending stop signal...[/cyan]")
        logger.info("Sending stop signal...")
        obs_exe = get_obs_executable_path()
        if obs_exe:
            try:
                from scribe.utils.platform import is_macos

                obs_dir = obs_exe.parent
                if is_macos():
                    # macOS: forward the flag to the running instance via the bundle.
                    bundle = next((p for p in obs_exe.parents if p.suffix == ".app"), None)
                    app_ref = str(bundle) if bundle is not None else "OBS"
                    stop_cmd = ["open", "-a", app_ref, "--args", "--stoprecording"]
                else:
                    stop_cmd = [str(obs_exe), "--stoprecording"]
                proc = subprocess.run(
                    stop_cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(obs_dir),
                    timeout=10,
                )
                if proc.returncode != 0:
                    console.print("[yellow]Stop signal may not have reached OBS[/yellow]")
                    logger.warning(f"OBS --stoprecording exited with code {proc.returncode}")
            except subprocess.TimeoutExpired:
                console.print("[yellow]Stop signal timed out[/yellow]")
                logger.warning("OBS --stoprecording timed out after 10s")
            except Exception as e:
                console.print("[yellow]Could not signal OBS to stop - stop manually[/yellow]")
                logger.warning(f"Could not signal OBS to stop: {e}")
        else:
            console.print("[yellow]OBS executable not found - stop recording manually[/yellow]")
            logger.warning("Cannot send stop signal: OBS executable not found")

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
                    import msvcrt

                    buffer: list[str] = []
                    while not ev.is_set():
                        # Check if a key is available
                        if msvcrt.kbhit():
                            char = msvcrt.getwch()
                            if char == "\r" or char == "\n":
                                # Enter pressed - check command
                                cmd = "".join(buffer).strip().lower()
                                if cmd in {"stop", "s", "q", "quit", "exit"}:
                                    console.print(
                                        f"\n[yellow]Stop command received: '{cmd}'[/yellow]"
                                    )
                                    ev.set()
                                    break
                                buffer = []
                            elif char == "\x03":  # Ctrl+C
                                ev.set()
                                break
                            else:
                                buffer.append(char)
                                # Echo the character
                                sys.stdout.write(char)
                                sys.stdout.flush()
                        else:
                            time.sleep(0.1)
                except Exception as e:
                    logger.debug(f"Windows input error: {e}")
                    # Fall back to readline
                    self._listen_readline(ev, console)
            else:
                # Unix: use select for non-blocking
                self._listen_readline(ev, console)

        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        return ev, _restore

    def _listen_readline(self, ev: threading.Event, console: Any) -> None:
        """Fallback readline-based input listener."""
        try:
            while not ev.is_set():
                try:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    cmd = line.strip().lower()
                    if cmd in {"stop", "s", "q", "quit", "exit"}:
                        console.print(f"\n[yellow]Stop command received: '{cmd}'[/yellow]")
                        ev.set()
                        break
                except Exception as e:
                    logger.debug(f"Error reading input: {e}")
                    break
        except Exception as e:
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
            logger.warning(f"Could not query OBS recording directory: {e}")
        logger.warning(f"Using fallback recording directory: {fallback}")
        return os.path.abspath(fallback)

    def _newest_media_since(self, dir_path: str, since_ts: float) -> tuple[str | None, str | None]:
        """Find newest MP4/MKV file since timestamp."""
        best_mp4: tuple[str | None, float] = (None, -1.0)
        best_mkv: tuple[str | None, float] = (None, -1.0)

        try:
            entries = os.listdir(dir_path)
        except Exception:
            return None, None

        for name in entries:
            lower = name.lower()
            if not (lower.endswith(".mp4") or lower.endswith(".mkv")):
                continue

            p = os.path.join(dir_path, name)
            try:
                # Use mtime - getctime on Linux is inode change time, not creation
                c = os.path.getmtime(p)
            except Exception:
                continue

            if c >= since_ts - 5:
                if lower.endswith(".mp4") and c > best_mp4[1]:
                    best_mp4 = (p, c)
                if lower.endswith(".mkv") and c > best_mkv[1]:
                    best_mkv = (p, c)

        return best_mp4[0], best_mkv[0]

    def _wait_until_file_finalized(
        self, path: str, idle_seconds: float = 3.0, max_wait: float = 600.0
    ) -> None:
        """Wait for file to stop growing.

        Raises ProcessError if the file never stabilizes within max_wait.
        """
        last = -1
        stable = 0.0
        waited = 0.0

        while waited < max_wait:
            try:
                size = os.path.getsize(path)
            except FileNotFoundError:
                time.sleep(0.5)
                waited += 0.5
                continue

            if size == last:
                stable += 0.5
                if stable >= idle_seconds:
                    return
            else:
                stable = 0.0
                last = size

            time.sleep(0.5)
            waited += 0.5

        logger.warning(f"File finalization timed out after {max_wait}s: {path}")
        # Don't raise - the file likely exists and is usable, but warn loudly
        from scribe.utils.logging import console

        console.print(
            f"[yellow]Warning: recording file may still be writing "
            f"(waited {int(max_wait)}s)[/yellow]"
        )

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
            except Exception:
                shutil.copy2(src_path, str(final_path))
                with suppress(Exception):
                    os.remove(src_path)
        except Exception as e:
            raise ProcessError(f"Failed to place final file: {e}")

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
        except Exception as e:
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
