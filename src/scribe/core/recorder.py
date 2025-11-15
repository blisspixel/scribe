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
        
        start_ts = time.time()
        stop_event = self._start_stop_listener()
        
        try:
            # Try WebSocket control first
            if OBS_AVAILABLE:
                return self._record_with_websocket(meeting_name, start_ts, stop_event)
            else:
                logger.info("Using CLI fallback (obsws_python not available)")
                return self._record_with_cli(meeting_name, start_ts, stop_event)
                
        except Exception as e:
            logger.error(f"Recording failed: {e}")
            raise ProcessError(
                f"OBS recording failed: {e}",
                context={"meeting": meeting_name}
            )
    
    def _record_with_websocket(
        self,
        meeting_name: str,
        start_ts: float,
        stop_event: threading.Event
    ) -> Path:
        """Record using OBS WebSocket."""
        try:
            with self._connect_obs() as client:
                self._set_record_dir_if_possible(client, str(self.output_folder))
                eff_dir = self._get_effective_record_dir(client, str(self.output_folder))
                
                self._start_recording_if_needed(client)
                self._wait_for_stop_with_input(client, stop_event)
                
                # Find recorded file
                mp4, mkv = self._newest_media_since(eff_dir, start_ts)
                media = mp4 or mkv
                
                if not media:
                    raise ProcessError("Could not locate recorded media")
                
                ext = ".mp4" if mp4 else ".mkv"
                return self._finalize_recording(media, ext, meeting_name, start_ts)
                
        except Exception as ws_err:
            logger.warning(f"WebSocket failed: {ws_err}")
            logger.info("Falling back to CLI control...")
            return self._record_with_cli(meeting_name, start_ts, stop_event)
    
    def _record_with_cli(
        self,
        meeting_name: str,
        start_ts: float,
        stop_event: threading.Event
    ) -> Path:
        """Record using CLI fallback."""
        from scribe.utils.logging import console
        
        console.print("[yellow]Using CLI fallback mode[/yellow]")
        
        # Try to launch OBS with recording
        obs_exe = get_obs_executable_path()
        if obs_exe:
            try:
                console.print("[cyan]Launching OBS with recording...[/cyan]")
                # Set working directory to OBS installation directory
                obs_dir = obs_exe.parent
                args = [str(obs_exe), "--minimize-to-tray", "--startrecording"]
                subprocess.Popen(
                    args,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(obs_dir)
                )
                logger.info("Launched OBS with recording")
            except Exception as e:
                logger.warning(f"Could not launch OBS: {e}")
        
        # Start background listener for stop
        threading.Thread(
            target=self._wait_for_stop_cli,
            args=(stop_event,),
            daemon=True
        ).start()
        
        # Monitor for new file
        found_path = None
        ext = ".mp4"
        deadline = time.time() + 30
        
        candidate_dirs = [
            self.output_folder,
            Path.home() / "Videos",
            Path.home() / "Videos" / "OBS",
        ]
        
        while time.time() < deadline and not found_path:
            for d in candidate_dirs:
                if not d.exists():
                    continue
                mp4, mkv = self._newest_media_since(str(d), start_ts)
                found_path = mp4 or mkv
                if found_path:
                    ext = ".mp4" if mp4 else ".mkv"
                    break
            time.sleep(0.5)
        
        if not found_path:
            raise ProcessError("No media file appeared after starting recording")
        
        # Wait for file to stabilize
        self._wait_until_file_finalized(found_path)
        
        return self._finalize_recording(found_path, ext, meeting_name, start_ts)
    
    @contextmanager
    def _connect_obs(self, max_wait_seconds: int = 15):
        """Connect to OBS WebSocket with retry."""
        from scribe.utils.logging import console
        
        hosts = [self.obs_host, "127.0.0.1"]
        ports = [self.obs_port, 4455]
        
        console.print("[cyan]Connecting to OBS Studio...[/cyan]")
        
        # Quick check if already running
        obs_already_running = False
        for h in hosts:
            for p in ports:
                if self._port_listening(h, p, timeout=0.3):
                    obs_already_running = True
                    try:
                        client = obs_reqs.ReqClient(
                            host=h,
                            port=p,
                            password=self.obs_password,
                            timeout=3.0
                        )
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
                    except Exception:
                        pass
        
        # Try launching OBS only if not already running
        if not obs_already_running:
            obs_exe = get_obs_executable_path()
        else:
            obs_exe = None
            
        if obs_exe:
            console.print("[cyan]Starting OBS Studio...[/cyan]")
            logger.info("Starting OBS...")
            try:
                # Set working directory to OBS installation directory
                obs_dir = obs_exe.parent
                subprocess.Popen(
                    [str(obs_exe), "--minimize-to-tray"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    cwd=str(obs_dir)
                )
            except Exception as e:
                logger.warning(f"Could not launch OBS: {e}")
            
            # Wait for OBS to start
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
                                # Give OBS a moment to fully initialize before checking status
                                if attempt < 4:  # First 2 seconds
                                    time.sleep(0.5)
                                    continue
                                    
                                try:
                                    client.get_record_status()
                                except obs_error.OBSSDKRequestError as e:
                                    if "not ready" in str(e).lower():
                                        # OBS is starting up, wait a bit more
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
                            except Exception as e:
                                # Suppress "not ready" errors during startup
                                if "not ready" not in str(e).lower():
                                    logger.debug(f"Connection attempt failed: {e}")
                time.sleep(0.5)
        
        console.print("\n[bold red]Failed to connect to OBS WebSocket[/bold red]")
        console.print("\n[yellow]Troubleshooting steps:[/yellow]")
        console.print("  1. Ensure OBS Studio is installed")
        console.print("  2. Open OBS Studio manually")
        console.print("  3. Go to Tools > WebSocket Server Settings")
        console.print("  4. Enable WebSocket server on port 4455")
        console.print("  5. Disable authentication or set password in config")
        console.print()
        
        raise ConnectionError(
            "Could not connect to OBS WebSocket. "
            "Ensure OBS is running with WebSocket enabled (port 4455, no SSL)."
        )
    
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
                "[bold white on red]  RECORDING  [/bold white on red]\n\n"
                "[yellow]Type 'stop' and press Enter to stop[/yellow]\n"
                "[dim]Commands: stop, s, q, quit, exit[/dim]",
                border_style="red",
                padding=(1, 2)
            ))
            console.print()
        
        last_active = True
        recording_time = 0
        last_update = 0
        
        # Print initial status line using sys.stdout for proper \r handling
        sys.stdout.write("● Recording: 00:00")
        sys.stdout.flush()
        
        while True:
            try:
                status = client.get_record_status()
                active = getattr(status, "output_active", False)
            except Exception:
                active = last_active
            
            if stop_event.is_set() and active:
                # Clear the status line before printing stop message
                sys.stdout.write("\r" + " " * 40 + "\r")
                sys.stdout.flush()
                console.print("[cyan]Stopping recording...[/cyan]")
                logger.info("Stopping recording...")
                try:
                    client.stop_record()
                except Exception as e:
                    logger.warning(f"Stop command failed: {e}")
            
            if not active and last_active:
                # Clear the status line before printing stopped message
                sys.stdout.write("\r" + " " * 40 + "\r")
                sys.stdout.flush()
                console.print("Recording stopped")
                logger.info("Recording stopped")
                return
            
            # Update recording time every second (not every 0.5s to reduce flicker)
            if active:
                recording_time += 0.5
                # Only update display every second
                if int(recording_time) > last_update:
                    last_update = int(recording_time)
                    mins = int(recording_time // 60)
                    secs = int(recording_time % 60)
                    # Use \r to return to start of line and overwrite
                    sys.stdout.write(f"\r● Recording: {mins:02d}:{secs:02d}")
                    sys.stdout.flush()
            
            last_active = active
            time.sleep(0.5)
    
    def _wait_for_stop_cli(self, stop_event: threading.Event) -> None:
        """CLI fallback stop listener."""
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
        
        while not stop_event.is_set():
            time.sleep(0.2)
        
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
