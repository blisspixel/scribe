"""
OBS Studio recording integration (migrated from working record.py).

This module provides OBS WebSocket integration for automated recording
with fallback to CLI control. The original implementation worked well,
so it's been preserved with minimal changes.
"""

import os
import sys
import time
import socket
import tempfile
import uuid
import shutil
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Tuple

from scribe.models.config import ScribeConfig
from scribe.exceptions import ProcessError
from scribe.utils.platform import get_ffmpeg_path, get_obs_executable_path
from scribe.utils.logging import get_logger

logger = get_logger(__name__)

# Try to import OBS WebSocket library
try:
    from obsws_python import reqs as obs_reqs
    from obsws_python import error as obs_error
    OBS_AVAILABLE = True
except ImportError:
    OBS_AVAILABLE = False
    logger.warning("obsws_python not installed. OBS integration will use CLI fallback only.")


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
    
    def __init__(self, config: ScribeConfig):
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
        except Exception as e:
            logger.warning(f"Cannot use configured output folder: {e}")
            fallback = Path(tempfile.gettempdir()) / "obs_recordings"
            logger.warning(f"Falling back to: {fallback}")
            self.output_folder = self._ensure_dir_writable(fallback)
        
        stop_event = self._start_stop_listener()
        
        try:
            # Try WebSocket control first
            if OBS_AVAILABLE:
                return self._record_with_websocket(meeting_name, stop_event)
            else:
                logger.info("Using CLI fallback (obsws_python not available)")
                return self._record_with_cli(meeting_name, stop_event)
                
        except Exception as e:
            logger.error(f"Recording failed: {e}")
            raise ProcessError(
                f"OBS recording failed: {e}",
                context={"meeting": meeting_name}
            )
    
    def _record_with_websocket(
        self,
        meeting_name: str,
        stop_event: threading.Event
    ) -> Path:
        """Record using OBS WebSocket."""
        try:
            with self._connect_obs() as client:
                self._set_record_dir_if_possible(client, str(self.output_folder))
                eff_dir = self._get_effective_record_dir(client, str(self.output_folder))
                
                self._start_recording_if_needed(client)
                # Set timestamp AFTER recording has started
                start_ts = time.time()
                self._wait_for_stop_with_input(client, stop_event)
                
                # Find recorded file
                mp4, mkv = self._newest_media_since(eff_dir, start_ts)
                media = mp4 or mkv
                
                if not media:
                    raise ProcessError("Could not locate recorded media")
                
                ext = ".mp4" if mp4 else ".mkv"
                return self._finalize_recording(media, ext, meeting_name, start_ts)
                
        except Exception as ws_err:
            logger.debug(f"WebSocket failed: {ws_err}")
            # Silently fall back to CLI mode
            return self._record_with_cli(meeting_name, stop_event)
    
    def _record_with_cli(
        self,
        meeting_name: str,
        stop_event: threading.Event
    ) -> Path:
        """
        Record using CLI fallback.
        
        This method handles the case where WebSocket connection fails.
        It tries to launch OBS with recording, but provides clear feedback
        if recording doesn't actually start.
        """
        from scribe.utils.logging import console
        from pathlib import Path as PathType
        
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
        
        found_path = None
        ext = ".mp4"
        deadline = time.time() + 30
        last_check_msg = 0
        
        while time.time() < deadline and not found_path:
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
        found_path = PathType(found_path)
        
        console.print(f"[green]Recording detected: {found_path.name}[/green]")
        console.print()
        
        # Now start the stop listener thread (after file is detected)
        threading.Thread(
            target=self._wait_for_stop_cli,
            args=(stop_event,),
            daemon=True
        ).start()
        
        # Wait for user to type 'stop'
        stop_event.wait()
        
        console.print()
        console.print("[cyan]Waiting for OBS to finalize file...[/cyan]")
        console.print("[dim]This may take a few seconds...[/dim]")
        
        # Give OBS time to stop and finalize the file
        # The --stoprecording command was sent by _wait_for_stop_cli
        time.sleep(3)
        
        # Wait for file to stabilize (stop growing)
        self._wait_until_file_finalized(str(found_path))
        
        return self._finalize_recording(found_path, ext, meeting_name, start_ts)
    
    @contextmanager
    def _connect_obs(self, max_wait_seconds: int = 15):
        """
        Connect to OBS WebSocket with retry.
        
        Attempts connection to OBS WebSocket server with multiple fallback strategies:
        1. Try configured host/port if OBS already running
        2. Launch OBS if not running
        3. Retry with exponential backoff during OBS startup
        
        The WebSocket library (obsws_python) can raise ValueError for invalid hostnames,
        particularly with IPv6 addresses. We catch and suppress these specific errors
        while preserving other connection failures for debugging.
        """
        from scribe.utils.logging import console
        
        # Prioritize IPv4 addresses - WebSocket libraries have better IPv4 support
        # IPv6 (::1) often triggers hostname validation errors in websocket-client
        hosts = [self.obs_host, "127.0.0.1"]
        if self.obs_host not in ["localhost", "127.0.0.1", "::1"]:
            # Only add IPv6 if user explicitly configured a different host
            hosts.append("::1")
        
        ports = [self.obs_port]
        if self.obs_port != 4455:
            ports.append(4455)  # Fallback to default port
        
        console.print(f"[cyan]Connecting to OBS (checking {hosts[0]}:{ports[0]})...[/cyan]")
        
        # Quick check if already running - only try connection if port is listening
        obs_already_running = False
        for h in hosts:
            for p in ports:
                is_listening = self._port_listening(h, p, timeout=0.3)
                logger.debug(f"Port check {h}:{p} = {is_listening}")
                if is_listening:
                    obs_already_running = True
                    try:
                        client = obs_reqs.ReqClient(
                            host=h,
                            port=p,
                            password=self.obs_password,
                            timeout=3.0
                        )
                        # Verify connection is actually working
                        client.get_record_status()
                        console.print(f"[green]Connected to OBS at ws://{h}:{p}[/green]")
                        logger.info(f"Connected to OBS at ws://{h}:{p}")
                        try:
                            yield client
                        finally:
                            try:
                                client.close()
                            except Exception:
                                pass
                        return
                    except ValueError as e:
                        # WebSocket library hostname validation failure
                        # Common with IPv6 addresses or non-standard hostnames
                        if "hostname is invalid" in str(e).lower() or "invalid" in str(e).lower():
                            logger.debug(f"Hostname validation failed for {h}:{p} - {e}")
                        else:
                            logger.debug(f"ValueError during connection to {h}:{p}: {e}")
                    except Exception as e:
                        logger.debug(f"Connection attempt to {h}:{p} failed: {e}")
        
        # Try launching OBS only if not already running
        if not obs_already_running:
            obs_exe = get_obs_executable_path()
        else:
            obs_exe = None
        
        if obs_exe:
            console.print("[cyan]Starting OBS Studio...[/cyan]")
            logger.info("Starting OBS...")
            try:
                obs_dir = obs_exe.parent
                subprocess.Popen(
                    [str(obs_exe), "--minimize-to-tray"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(obs_dir)
                )
            except Exception as e:
                logger.warning(f"Could not launch OBS: {e}")
            
            # Wait for OBS to start with retry logic
            console.print("[cyan]Waiting for OBS to start...[/cyan]")
            for attempt in range(int(max_wait_seconds * 2)):
                for h in hosts:
                    for p in ports:
                        if self._port_listening(h, p, timeout=0.2):
                            try:
                                client = obs_reqs.ReqClient(
                                    host=h,
                                    port=p,
                                    password=self.obs_password,
                                    timeout=3.0
                                )
                                # Give OBS a moment to fully initialize WebSocket server
                                # Early attempts may succeed at TCP level but fail at protocol level
                                if attempt < 4:
                                    time.sleep(0.5)
                                    continue
                                
                                try:
                                    client.get_record_status()
                                except obs_error.OBSSDKRequestError as e:
                                    if "not ready" in str(e).lower():
                                        time.sleep(0.5)
                                        continue
                                    raise
                                
                                console.print(f"[green]Connected to OBS at ws://{h}:{p}[/green]")
                                logger.info(f"Connected to OBS at ws://{h}:{p}")
                                try:
                                    yield client
                                finally:
                                    try:
                                        client.close()
                                    except Exception:
                                        pass
                                return
                            except ValueError as e:
                                # WebSocket library hostname validation failure
                                if "hostname is invalid" in str(e).lower() or "invalid" in str(e).lower():
                                    logger.debug(f"Hostname validation failed for {h}:{p} - {e}")
                                else:
                                    logger.debug(f"ValueError during connection to {h}:{p}: {e}")
                            except Exception as e:
                                # Log other connection failures for debugging
                                if "not ready" not in str(e).lower():
                                    logger.debug(f"Connection attempt to {h}:{p} failed: {e}")
                time.sleep(0.5)
        
        # Connection failed
        raise ConnectionError("Could not connect to OBS WebSocket")
    
    def _set_record_dir_if_possible(self, client, out_dir: str) -> bool:
        """Set OBS recording directory."""
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
            return False
        except Exception as e:
            logger.warning(f"Could not set record directory: {e}")
            return False
    
    def _start_recording_if_needed(self, client) -> None:
        """Start recording if not already active."""
        from scribe.utils.logging import console
        
        status = client.get_record_status()
        if getattr(status, "output_active", False):
            console.print("[yellow]Recording already active[/yellow]")
            logger.info("Recording already active")
            return
        
        console.print("[cyan]Starting recording...[/cyan]")
        logger.info("Starting recording...")
        client.start_record()
        
        # Verify recording started
        for _ in range(25):
            time.sleep(0.2)
            status = client.get_record_status()
            if getattr(status, "output_active", False):
                console.print("Recording started")
                logger.info("Recording started successfully")
                return
        
        raise ProcessError("Recording failed to start within 5 seconds")
    
    def _wait_for_stop_with_input(self, client, stop_event: threading.Event) -> None:
        """Wait for user to stop recording."""
        from scribe.utils.logging import console
        from rich.panel import Panel
        
        if sys.stdin and sys.stdin.isatty():
            console.print()
            console.print(Panel.fit(
                "[bold green]RECORDING IN PROGRESS[/bold green]\n\n"
                "[white]Type 'stop' and press Enter to stop[/white]\n"
                "[dim]Commands: stop, s, q, quit, exit[/dim]",
                border_style="green",
                padding=(1, 2)
            ))
            console.print()
        
        last_active = True
        recording_time = 0
        last_update = 0
        
        # Print initial status line using raw stdout for proper \r handling
        sys.stdout.write("Recording: 00:00")
        sys.stdout.flush()
        
        while True:
            try:
                status = client.get_record_status()
                active = getattr(status, "output_active", False)
            except Exception:
                active = last_active
            
            if stop_event.is_set() and active:
                # Clear the timer line and print stop message
                sys.stdout.write("\r" + " " * 50 + "\r")
                sys.stdout.flush()
                console.print("[cyan]Stopping recording...[/cyan]")
                logger.info("Stopping recording...")
                try:
                    client.stop_record()
                except Exception as e:
                    logger.warning(f"Stop command failed: {e}")
            
            if not active and last_active:
                # Clear the timer line and print stopped message
                sys.stdout.write("\r" + " " * 50 + "\r")
                sys.stdout.flush()
                console.print("[green]Recording stopped[/green]")
                logger.info("Recording stopped")
                return
            
            # Update recording time every second
            if active:
                recording_time += 0.5
                # Only update display every second to reduce flicker
                if int(recording_time) > last_update:
                    last_update = int(recording_time)
                    mins = int(recording_time // 60)
                    secs = int(recording_time % 60)
                    # Use raw stdout with \r for proper overwriting
                    sys.stdout.write(f"\rRecording: {mins:02d}:{secs:02d}")
                    sys.stdout.flush()
            
            last_active = active
            time.sleep(0.5)
    
    def _wait_for_stop_cli(self, stop_event: threading.Event) -> None:
        """CLI fallback stop listener with timer."""
        from scribe.utils.logging import console
        from rich.panel import Panel
        
        if sys.stdin and sys.stdin.isatty():
            console.print()
            console.print(Panel.fit(
                "[bold white on red]  RECORDING  [/bold white on red]\n\n"
                "[yellow]Type 'stop' and press Enter to stop[/yellow]\n"
                "[dim]Commands: stop, s, q, quit, exit[/dim]",
                border_style="red",
                padding=(1, 2)
            ))
            console.print()
        
        # Show elapsed time timer
        start_time = time.time()
        last_update = 0
        
        # Print initial timer using raw stdout for proper \r handling
        sys.stdout.write("Recording: 00:00")
        sys.stdout.flush()
        
        while not stop_event.is_set():
            elapsed = time.time() - start_time
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
                # Set working directory to OBS installation directory
                obs_dir = obs_exe.parent
                subprocess.Popen(
                    [str(obs_exe), "--stoprecording"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(obs_dir)
                )
            except Exception:
                logger.warning("Could not signal OBS to stop")
    
    def _start_stop_listener(self) -> threading.Event:
        """Start background thread listening for stop command."""
        from scribe.utils.logging import console
        ev = threading.Event()
        
        def _listen():
            if not sys.stdin or not sys.stdin.readable():
                logger.debug("stdin not available for stop listener")
                return
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
        
        t = threading.Thread(target=_listen, daemon=True)
        t.start()
        return ev
    
    def _get_effective_record_dir(self, client, fallback: str) -> str:
        """Get effective recording directory from OBS."""
        try:
            cur = client.get_record_directory()
            d = getattr(cur, "record_directory", None) or ""
            if d:
                return os.path.abspath(d)
        except Exception:
            pass
        return os.path.abspath(fallback)
    
    def _newest_media_since(
        self,
        dir_path: str,
        since_ts: float
    ) -> Tuple[Optional[str], Optional[str]]:
        """Find newest MP4/MKV file since timestamp."""
        best_mp4 = (None, -1.0)
        best_mkv = (None, -1.0)
        
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
                c = os.path.getctime(p)
            except Exception:
                continue
            
            if c >= since_ts - 120:
                if lower.endswith(".mp4") and c > best_mp4[1]:
                    best_mp4 = (p, c)
                if lower.endswith(".mkv") and c > best_mkv[1]:
                    best_mkv = (p, c)
        
        return best_mp4[0], best_mkv[0]
    
    def _wait_until_file_finalized(
        self,
        path: str,
        idle_seconds: float = 3.0,
        max_wait: float = 600.0
    ) -> None:
        """Wait for file to stop growing."""
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
    
    def _finalize_recording(
        self,
        media_path: str,
        ext: str,
        meeting_name: str,
        start_ts: float
    ) -> Path:
        """Finalize recording file."""
        from scribe.utils.logging import console
        
        src_path = media_path
        target_ext = ".mp4"
        
        # Remux MKV to MP4 if needed
        if ext == ".mkv":
            console.print("[cyan]Converting MKV to MP4...[/cyan]")
            ffmpeg_path = get_ffmpeg_path()
            if ffmpeg_path:
                tmp_mp4 = Path(media_path).parent / self._safe_filename(
                    meeting_name, start_ts, ".mp4"
                )
                if self._remux_mkv_to_mp4(media_path, str(tmp_mp4)):
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
                try:
                    os.remove(src_path)
                except Exception:
                    pass
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
            return False
        
        try:
            cmd = [str(ffmpeg_path), "-y", "-i", mkv_path, "-c", "copy", mp4_path]
            subprocess.check_call(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return os.path.isfile(mp4_path) and os.path.getsize(mp4_path) > 0
        except Exception:
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
        except Exception as e:
            raise ProcessError(f"Directory not writable: {path}. Reason: {e}")
        
        return path
