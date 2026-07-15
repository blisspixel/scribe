"""Local-first diagnostics used by `scribe doctor` and support bundles.

Default diagnostics are local-only and safe to run without spending money or
calling provider APIs. They inspect Python 3.12 readiness, critical packages,
dependency-audit status, FFmpeg/FFprobe/yt-dlp, OBS settings, CUDA/GPU state,
local transcription and notes readiness, writable output folders, disk and temp
space, environment files, configuration conflicts, system resources, and voice
readiness.

Live provider API-key validation is intentionally opt-in through
`run_all_checks(live=True)` or `scribe doctor --live`. Individual checks append
`DiagnosticResult` objects to `self.results`; `run_all_checks` isolates each
check so one unexpected failure becomes a diagnostic result rather than aborting
the whole run.
"""

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from openai import AuthenticationError, OpenAI

from scribe.models.gpu import GPUConfig
from scribe.utils.obs_config import read_obs_websocket_config
from scribe.utils.platform import get_platform, is_windows

# Accepted torch advisories per ADR-004 (mirrors .github/workflows/ci.yml).
_ACCEPTED_TORCH_VULN_IGNORES: tuple[str, ...] = (
    "PYSEC-2025-203",
    "PYSEC-2025-204",
    "PYSEC-2025-206",
    "PYSEC-2026-139",
    "PYSEC-2026-2286",
    "CVE-2025-2999",
    "CVE-2025-3000",
    "CVE-2025-3001",
)


@dataclass
class DiagnosticResult:
    """Result of a diagnostic check."""

    name: str
    status: str  # "pass", "warn", "fail"
    message: str
    details: str | None = None
    fix_suggestion: str | None = None


@dataclass
class LocalReadiness:
    """Whether Scribe can process at $0 (no paid API) on this machine right now.

    Transcription is the core feature and runs on any machine (GPU when present,
    CPU int8 as the universal floor), so ``can_transcribe`` is the headline.
    Notes need a local Ollama server with a model, which is a heavier opt-in.
    """

    can_transcribe: bool
    transcribe_detail: str
    transcribe_fix: str | None
    can_take_notes: bool
    notes_detail: str
    notes_fix: str | None
    backend: str
    vendor: str
    ffmpeg: bool

    @property
    def fully_local(self) -> bool:
        """True when both transcription and notes can run with no paid API."""
        return self.can_transcribe and self.can_take_notes


def assess_local_readiness() -> LocalReadiness:
    """Assess whether transcription and notes can run locally at $0 right now.

    Pure inspection: never makes a paid API call. Reused by ``scribe doctor``,
    ``scribe info``, and the ``check_local_readiness`` diagnostic so they can
    never disagree about what runs for free on this machine.
    """
    # --- Transcription: a local Whisper backend + ffmpeg for format conversion ---
    backend = "cpu"
    vendor = "cpu"
    backend_ok = False
    try:
        from scribe.core.backends import (
            backend_availability,
            detect_hardware,
            select_backend,
        )

        hardware = detect_hardware()
        vendor = hardware.vendor
        availability = backend_availability()
        backend = select_backend(hardware, available=availability)
        backend_ok = any(availability.values())
    except Exception:
        backend_ok = False

    ffmpeg = shutil.which("ffmpeg") is not None
    can_transcribe = backend_ok and ffmpeg
    transcribe_fix: str | None = None
    if not backend_ok:
        transcribe_detail = "no local Whisper backend importable"
        transcribe_fix = (
            'Reinstall the base package (it bundles faster-whisper): pip install "scribe".'
        )
    elif not ffmpeg:
        transcribe_detail = f"{backend} ({vendor}) ready, but ffmpeg is missing"
        transcribe_fix = (
            "Install ffmpeg: winget install FFmpeg.FFmpeg / brew install ffmpeg / "
            "apt install ffmpeg."
        )
    else:
        accelerated = backend != "cpu"
        speed = "GPU-accelerated" if accelerated else "CPU int8 (slower, still $0)"
        transcribe_detail = f"{backend} on {vendor} - {speed}"
        # Nudge Apple/AMD/Intel users off the CPU floor toward their fast backend.
        if backend == "cpu" and vendor == "apple":
            transcribe_fix = 'Faster on Apple Silicon: pip install "scribe[mlx]" (Metal GPU).'
        elif backend == "cpu" and vendor in ("amd", "intel"):
            transcribe_fix = 'Faster on this GPU: pip install "scribe[whispercpp]" (Vulkan/ROCm).'

    # --- Notes: a local Ollama server with at least one installed model ---
    notes_fix: str | None = None
    try:
        from scribe.utils.ollama_models import (
            list_installed_models,
            select_default_ollama_model,
        )

        base_url = os.getenv("SCRIBE_OLLAMA_BASE_URL")
        models = list_installed_models(base_url)
        if models:
            chosen = select_default_ollama_model(base_url)
            can_take_notes = True
            notes_detail = f"Ollama - {len(models)} model(s), auto-selects {chosen}"
        else:
            can_take_notes = False
            notes_detail = "Ollama has no models installed (or isn't running)"
            notes_fix = "Install/start Ollama (https://ollama.com), then `ollama pull llama3.2`."
    except Exception:
        can_take_notes = False
        notes_detail = "Ollama not reachable (optional, for free local notes)"
        notes_fix = "Install and start Ollama (https://ollama.com), then `ollama pull llama3.2`."

    return LocalReadiness(
        can_transcribe=can_transcribe,
        transcribe_detail=transcribe_detail,
        transcribe_fix=transcribe_fix,
        can_take_notes=can_take_notes,
        notes_detail=notes_detail,
        notes_fix=notes_fix,
        backend=backend,
        vendor=vendor,
        ffmpeg=ffmpeg,
    )


class SystemDiagnostics:
    """System diagnostics and health checks."""

    def __init__(self) -> None:
        self.results: list[DiagnosticResult] = []

    def run_all_checks(self, live: bool = False) -> list[DiagnosticResult]:
        """Run all diagnostic checks.

        Each check is isolated so one raising an unexpected error cannot abort the
        whole run. When ``live`` is False the API-key checks (which make real network
        calls and can cost money or hang) are skipped, which the support bundle uses.
        """
        self.results = []

        # The checks self-append to self.results; the return type varies (some return
        # a single result, check_additional_providers returns a list), so type loosely.
        checks: list[Callable[[], Any]] = [
            self.check_python_version,
            self.check_python_packages,
            self.check_dependency_security,
            self.check_api_resilience,
            self.check_ffmpeg,
            self.check_ffprobe,
            self.check_ytdlp,
            self.check_obs_websocket,
            self.check_cuda,
            self.check_cuda_driver,
            self.check_gpu,
            self.check_gpu_memory,
            self.check_local_readiness,
        ]
        if live:
            checks += [self.check_openai_api_key, self.check_additional_providers]
        checks += [
            self.check_output_folder,
            self.check_disk_space,
            self.check_temp_space,
            self.check_env_file,
            self.check_configuration_conflicts,
            self.check_system_resources,
            self.check_voice_readiness,
        ]

        for check in checks:
            try:
                check()
            except Exception as e:
                self.results.append(
                    DiagnosticResult(
                        name=getattr(check, "__name__", "check").replace("check_", ""),
                        status="fail",
                        message=f"Check raised an unexpected error: {e}",
                    )
                )

        return self.results

    def check_local_readiness(self) -> DiagnosticResult:
        """Report whether Scribe can process at $0 (no paid API) on this machine.

        Emits a headline result for local transcription (the core feature, which
        runs on any machine) plus a secondary result for local notes via Ollama.
        """
        readiness = assess_local_readiness()

        # Secondary: local notes via Ollama (optional heavier opt-in).
        self.results.append(
            DiagnosticResult(
                name="Local Notes ($0)",
                status="pass" if readiness.can_take_notes else "warn",
                message=readiness.notes_detail,
                fix_suggestion=readiness.notes_fix,
            )
        )

        # Headline: local transcription. Fail only if it genuinely can't run.
        result = DiagnosticResult(
            name="Local Transcription ($0)",
            status="pass" if readiness.can_transcribe else "fail",
            message=readiness.transcribe_detail,
            details=(
                "You can transcribe with no API key or cost. "
                + ("Notes also run locally via Ollama." if readiness.can_take_notes else "")
            )
            if readiness.can_transcribe
            else None,
            fix_suggestion=readiness.transcribe_fix,
        )
        self.results.append(result)
        return result

    def check_python_version(self) -> DiagnosticResult:
        """Check Python version."""
        version = sys.version_info
        version_str = f"{version.major}.{version.minor}.{version.micro}"

        if version.major == 3 and version.minor >= 12:
            result = DiagnosticResult(
                name="Python Version",
                status="pass",
                message=f"Python {version_str}",
                details="Python 3.12+ detected",
            )
        elif version.major == 3 and version.minor >= 10:
            result = DiagnosticResult(
                name="Python Version",
                status="warn",
                message=f"Python {version_str}",
                details="Python 3.12+ recommended",
                fix_suggestion="Upgrade to Python 3.12 or newer for full feature support",
            )
        else:
            result = DiagnosticResult(
                name="Python Version",
                status="fail",
                message=f"Python {version_str}",
                details="Python 3.12+ required",
                fix_suggestion="Install Python 3.12 or newer from python.org",
            )

        self.results.append(result)
        return result

    def check_ffmpeg(self) -> DiagnosticResult:
        """Check FFmpeg availability."""
        ffmpeg_path = shutil.which("ffmpeg")

        if ffmpeg_path:
            try:
                # Invoke the resolved absolute path, not the bare name, so the check
                # cannot be answered by a stray ffmpeg earlier on PATH.
                output = subprocess.check_output(
                    [ffmpeg_path, "-version"], stderr=subprocess.STDOUT, text=True, timeout=5
                )
                version_line = output.split("\n")[0]

                result = DiagnosticResult(
                    name="FFmpeg",
                    status="pass",
                    message="Installed",
                    details=f"Found at: {ffmpeg_path}\n{version_line}",
                )
            except Exception as e:
                result = DiagnosticResult(
                    name="FFmpeg",
                    status="warn",
                    message="Found but not working",
                    details=f"Path: {ffmpeg_path}\nError: {e}",
                    fix_suggestion="Reinstall FFmpeg",
                )
        else:
            platform = get_platform()
            if is_windows():
                fix = "Install: winget install FFmpeg.FFmpeg"
            elif platform == "macos":
                fix = "Install: brew install ffmpeg"
            else:
                fix = "Install: sudo apt install ffmpeg"

            result = DiagnosticResult(
                name="FFmpeg",
                status="fail",
                message="Not found",
                details="FFmpeg is required for audio/video conversion",
                fix_suggestion=fix,
            )

        self.results.append(result)
        return result

    def check_ffprobe(self) -> DiagnosticResult:
        """Check FFprobe availability."""
        ffprobe_path = shutil.which("ffprobe")

        if ffprobe_path:
            result = DiagnosticResult(
                name="FFprobe",
                status="pass",
                message="Installed",
                details=f"Found at: {ffprobe_path}",
            )
        else:
            result = DiagnosticResult(
                name="FFprobe",
                status="warn",
                message="Not found",
                details="FFprobe is useful for media file inspection",
                fix_suggestion="Usually installed with FFmpeg",
            )

        self.results.append(result)
        return result

    def check_ytdlp(self) -> DiagnosticResult:
        """Check yt-dlp availability for URL downloads."""
        try:
            import yt_dlp  # type: ignore[import-untyped]

            version = getattr(yt_dlp, "version", None)
            ver_str = getattr(version, "__version__", "installed") if version else "installed"
            result = DiagnosticResult(
                name="yt-dlp",
                status="pass",
                message=ver_str,
                details="Required for scribe url command",
            )
        except ImportError:
            result = DiagnosticResult(
                name="yt-dlp",
                status="warn",
                message="Not installed",
                details="Required for scribe url (YouTube, Vimeo, etc.)",
                fix_suggestion="Run: pip install yt-dlp",
            )

        self.results.append(result)
        return result

    def check_obs_websocket(self) -> DiagnosticResult:
        """Check OBS WebSocket settings against Scribe's recorder config."""
        obs_config = read_obs_websocket_config()
        if obs_config.path is None:
            result = DiagnosticResult(
                name="OBS WebSocket",
                status="warn",
                message="Could not locate OBS config directory",
                details="Recording requires OBS WebSocket when using scribe rec.",
                fix_suggestion=(
                    "Open OBS once, enable Tools > WebSocket Server Settings, then run "
                    "`scribe rec --check`."
                ),
            )
            self.results.append(result)
            return result

        if not obs_config.exists:
            result = DiagnosticResult(
                name="OBS WebSocket",
                status="warn",
                message="Config not found",
                details=f"Expected: {obs_config.path}",
                fix_suggestion=(
                    "Open OBS, enable Tools > WebSocket Server Settings, then run "
                    "`scribe rec --check`."
                ),
            )
            self.results.append(result)
            return result

        if obs_config.error:
            result = DiagnosticResult(
                name="OBS WebSocket",
                status="warn",
                message="Could not read config",
                details=f"Path: {obs_config.path}\nError: {obs_config.error}",
                fix_suggestion=(
                    "Open OBS, re-save Tools > WebSocket Server Settings, then run "
                    "`scribe rec --check`."
                ),
            )
            self.results.append(result)
            return result

        server_enabled = bool(obs_config.server_enabled)
        auth_required = bool(obs_config.auth_required)
        server_port = obs_config.server_port or 4455

        from scribe.models.config import ScribeConfig

        config = ScribeConfig()
        details = (
            f"OBS config: {obs_config.path}\n"
            f"OBS server enabled: {server_enabled}\n"
            f"OBS port: {server_port}\n"
            f"OBS auth required: {auth_required}\n"
            f"Scribe port: {config.obs_port}\n"
            f"Scribe password configured: {bool(config.obs_password)}"
        )

        if not server_enabled:
            result = DiagnosticResult(
                name="OBS WebSocket",
                status="warn",
                message="Server disabled",
                details=details,
                fix_suggestion="Enable OBS Tools > WebSocket Server Settings.",
            )
        elif config.obs_port != server_port:
            result = DiagnosticResult(
                name="OBS WebSocket",
                status="warn",
                message="Port mismatch",
                details=details,
                fix_suggestion=(
                    f"Run `scribe init --force` and set OBS port {server_port}, "
                    f"or set CMD `set SCRIBE_OBS_PORT={server_port}` "
                    f"or PowerShell `$env:SCRIBE_OBS_PORT='{server_port}'`."
                ),
            )
        elif auth_required and not config.obs_password:
            result = DiagnosticResult(
                name="OBS WebSocket",
                status="warn",
                message="Password required but not configured",
                details=details,
                fix_suggestion=(
                    "Run `scribe init --force` and configure OBS, or set CMD "
                    "`set SCRIBE_OBS_PASSWORD=<password>` or PowerShell "
                    "`$env:SCRIBE_OBS_PASSWORD='<password>'`. Persistent config: "
                    "add [obs].password to ~/.scribe/config.toml."
                ),
            )
        else:
            result = DiagnosticResult(
                name="OBS WebSocket",
                status="pass",
                message="Configured",
                details=details,
            )

        self.results.append(result)
        return result

    def check_cuda(self) -> DiagnosticResult:
        """Check CUDA availability."""
        gpu_config = GPUConfig.detect()

        if gpu_config.has_gpu:
            result = DiagnosticResult(
                name="CUDA",
                status="pass",
                message=(
                    f"CUDA {gpu_config.cuda_version}"
                    if gpu_config.cuda_version
                    else "CUDA available"
                ),
                details=gpu_config.reason,
            )
        else:
            result = DiagnosticResult(
                name="CUDA",
                status="warn",
                message="Not available",
                details=gpu_config.reason,
                fix_suggestion="Install CUDA-enabled PyTorch for PyTorch-backed features: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124",
            )

        self.results.append(result)
        return result

    def check_cuda_driver(self) -> DiagnosticResult:
        """Check CUDA driver version and age."""
        import subprocess

        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                driver_version = result.stdout.strip().splitlines()[0]

                # Check if it's very old (e.g. < 525)
                try:
                    major_ver = int(float(driver_version.split(".")[0]))
                    if major_ver < 525:
                        diag_result = DiagnosticResult(
                            name="CUDA Driver",
                            status="warn",
                            message=f"Driver v{driver_version} (Very old)",
                            details="Driver is older than v525. CUDA support may be degraded.",
                            fix_suggestion="Update NVIDIA drivers for better compatibility with modern PyTorch.",
                        )
                    else:
                        diag_result = DiagnosticResult(
                            name="CUDA Driver",
                            status="pass",
                            message=f"Driver v{driver_version}",
                            details="Driver version is recent enough for modern PyTorch.",
                        )
                except ValueError:
                    diag_result = DiagnosticResult(
                        name="CUDA Driver",
                        status="pass",
                        message=f"Driver v{driver_version}",
                        details="Could not parse driver version for age check.",
                    )
            else:
                diag_result = DiagnosticResult(
                    name="CUDA Driver",
                    status="warn",
                    message="Not detected",
                    details="nvidia-smi did not return a valid driver version.",
                )
        except Exception as e:
            diag_result = DiagnosticResult(
                name="CUDA Driver",
                status="warn",
                message="Check failed",
                details=f"Could not execute nvidia-smi: {e}",
            )

        self.results.append(diag_result)
        return diag_result

    def check_gpu(self) -> DiagnosticResult:
        """Check GPU availability and details."""
        gpu_config = GPUConfig.detect()

        if gpu_config.has_gpu:
            result = DiagnosticResult(
                name="GPU",
                status="pass",
                message=gpu_config.gpu_name or "CUDA GPU detected",
                details=f"VRAM: {gpu_config.gpu_memory_gb:.1f} GB\n{gpu_config.reason}",
            )
        else:
            result = DiagnosticResult(
                name="GPU",
                status="warn",
                message="No GPU detected",
                details=gpu_config.reason,
                fix_suggestion="GPU is optional - API mode works great",
            )

        self.results.append(result)
        return result

    def check_openai_api_key(self) -> DiagnosticResult:
        """Check OpenAI API key existence and validity."""
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("SCRIBE_OPENAI_API_KEY")

        if not api_key:
            result = DiagnosticResult(
                name="OpenAI API Key",
                status="fail",
                message="Not configured",
                details="Required for API transcription, notes, jokes, and memes",
                fix_suggestion="Set OPENAI_API_KEY in your .env file",
            )
            self.results.append(result)
            return result

        # Basic format check
        if not (api_key.startswith("sk-") and len(api_key) > 20):
            result = DiagnosticResult(
                name="OpenAI API Key",
                status="warn",
                message="Invalid format",
                details="API key doesn't match expected format",
                fix_suggestion="Get a valid API key from https://platform.openai.com/api-keys",
            )
            self.results.append(result)
            return result

        # Live validation - actually call the API to verify the key works
        try:
            client = OpenAI(api_key=api_key, timeout=10)
            client.models.list()
            result = DiagnosticResult(
                name="OpenAI API Key",
                status="pass",
                message="Valid",
                details=f"Key: {api_key[:10]}...{api_key[-4:]}",
            )
        except AuthenticationError:
            result = DiagnosticResult(
                name="OpenAI API Key",
                status="fail",
                message="Invalid key (401 Unauthorized)",
                details=f"Key: {api_key[:10]}...{api_key[-4:]}",
                fix_suggestion=(
                    "Your API key is rejected by OpenAI. "
                    "Get a new key at https://platform.openai.com/api-keys"
                ),
            )
        except Exception as e:
            # Network error, timeout, etc. - key format is fine, can't verify
            result = DiagnosticResult(
                name="OpenAI API Key",
                status="warn",
                message="Could not verify",
                details=f"Key: {api_key[:10]}...{api_key[-4:]} | Error: {e}",
                fix_suggestion="Check your internet connection",
            )

        self.results.append(result)
        return result

    def check_output_folder(self) -> DiagnosticResult:
        """Check output folder configuration and permissions."""
        output_folder = os.getenv("SCRIBE_OUTPUT_FOLDER")

        if not output_folder:
            result = DiagnosticResult(
                name="Output Folder",
                status="warn",
                message="Not configured",
                details="Will use default: ./output",
                fix_suggestion="Set SCRIBE_OUTPUT_FOLDER in your .env file",
            )
        else:
            output_path = Path(output_folder).expanduser()

            if output_path.exists():
                if output_path.is_dir():
                    # Check write permissions
                    test_file = output_path / ".scribe_test"
                    try:
                        test_file.touch()
                        test_file.unlink()

                        result = DiagnosticResult(
                            name="Output Folder",
                            status="pass",
                            message="Configured and writable",
                            details=f"Path: {output_path}",
                        )
                    except Exception as e:
                        result = DiagnosticResult(
                            name="Output Folder",
                            status="fail",
                            message="Not writable",
                            details=f"Path: {output_path}\nError: {e}",
                            fix_suggestion="Check folder permissions",
                        )
                else:
                    result = DiagnosticResult(
                        name="Output Folder",
                        status="fail",
                        message="Not a directory",
                        details=f"Path: {output_path}",
                        fix_suggestion="Remove the file or choose a different path",
                    )
            else:
                result = DiagnosticResult(
                    name="Output Folder",
                    status="warn",
                    message="Does not exist",
                    details=f"Path: {output_path}",
                    fix_suggestion="Folder will be created automatically on first use",
                )

        self.results.append(result)
        return result

    def check_disk_space(self) -> DiagnosticResult:
        """Check available disk space."""
        output_folder = os.getenv("SCRIBE_OUTPUT_FOLDER", "./output")
        output_path = Path(output_folder).expanduser()

        try:
            # Get disk usage for the output folder's drive
            check_path = output_path if output_path.exists() else output_path.parent

            stat = shutil.disk_usage(check_path)
            free_gb = stat.free / (1024**3)
            total_gb = stat.total / (1024**3)
            percent_free = (stat.free / stat.total) * 100

            if free_gb > 10:
                result = DiagnosticResult(
                    name="Disk Space",
                    status="pass",
                    message=f"{free_gb:.1f} GB free",
                    details=f"Total: {total_gb:.1f} GB ({percent_free:.1f}% free)",
                )
            elif free_gb > 5:
                result = DiagnosticResult(
                    name="Disk Space",
                    status="warn",
                    message=f"{free_gb:.1f} GB free",
                    details=f"Total: {total_gb:.1f} GB ({percent_free:.1f}% free)",
                    fix_suggestion="Consider freeing up disk space",
                )
            else:
                result = DiagnosticResult(
                    name="Disk Space",
                    status="fail",
                    message=f"{free_gb:.1f} GB free",
                    details=f"Total: {total_gb:.1f} GB ({percent_free:.1f}% free)",
                    fix_suggestion="Free up disk space - less than 5 GB available",
                )
        except Exception as e:
            result = DiagnosticResult(
                name="Disk Space",
                status="warn",
                message="Could not check",
                details=f"Error: {e}",
                fix_suggestion=None,
            )

        self.results.append(result)
        return result

    def check_env_file(self) -> DiagnosticResult:
        """Check .env file existence."""
        env_file = Path(".env")

        if env_file.exists():
            result = DiagnosticResult(
                name=".env File",
                status="pass",
                message="Found",
                details=f"Path: {env_file.absolute()}",
            )
        else:
            result = DiagnosticResult(
                name=".env File",
                status="pass",
                message="Not found",
                details="Running without .env file (using environment variables or defaults)",
            )

        self.results.append(result)
        return result

    def check_python_packages(self) -> DiagnosticResult:
        """Check critical Python packages."""
        missing = []

        critical_packages = {
            "torch": "2.0.0",
            "faster_whisper": "0.10.0",
            "openai": "1.0.0",
            "typer": "0.9.0",
            "rich": "13.0.0",
        }

        for package, _min_version in critical_packages.items():
            try:
                __import__(package)
            except ImportError:
                missing.append(package)

        if missing:
            result = DiagnosticResult(
                name="Python Packages",
                status="fail",
                message=f"{len(missing)} critical package(s) missing",
                details=f"Missing: {', '.join(missing)}",
                fix_suggestion="Run: pip install -r requirements.txt",
            )
        else:
            result = DiagnosticResult(
                name="Python Packages",
                status="pass",
                message="All critical packages installed",
                details=f"Checked: {', '.join(critical_packages.keys())}",
            )

        self.results.append(result)
        return result

    def check_dependency_security(self) -> DiagnosticResult:
        """Scan installed packages for known vulnerabilities (pip-audit)."""
        import importlib.util

        if importlib.util.find_spec("pip_audit") is None:
            result = DiagnosticResult(
                name="Dependency Security",
                status="warn",
                message="pip-audit not installed",
                details="Dependency vulnerability scan is only available in the dev environment.",
                fix_suggestion="Developers: run `uv sync --group dev` then re-run `scribe doctor`.",
            )
            self.results.append(result)
            return result

        cmd = [
            sys.executable,
            "-m",
            "pip_audit",
            "--local",
            "--progress-spinner",
            "off",
            "--desc",
            "on",
        ]
        for vuln_id in _ACCEPTED_TORCH_VULN_IGNORES:
            cmd.extend(["--ignore-vuln", vuln_id])

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            result = DiagnosticResult(
                name="Dependency Security",
                status="warn",
                message="Dependency scan could not run",
                details=str(exc),
                fix_suggestion="Re-run `scribe doctor` or check your Python environment.",
            )
            self.results.append(result)
            return result

        if completed.returncode == 0:
            summary_lines = (completed.stdout or completed.stderr or "").strip().splitlines()
            summary = summary_lines[0] if summary_lines else "No known vulnerabilities found"
            result = DiagnosticResult(
                name="Dependency Security",
                status="pass",
                message="No unignored vulnerabilities found",
                details=(
                    "Scanned local packages with pip-audit "
                    f"(ADR-004 torch exceptions applied). {summary}"
                ),
            )
        else:
            output = (completed.stdout or completed.stderr or "").strip()
            result = DiagnosticResult(
                name="Dependency Security",
                status="fail",
                message="Known vulnerabilities detected",
                details=output[:2000] if output else "pip-audit exited with errors",
                fix_suggestion="Run `uv run pip-audit --local` and upgrade affected packages.",
            )

        self.results.append(result)
        return result

    def check_gpu_memory(self) -> DiagnosticResult:
        """Check GPU memory and recommend optimal settings."""
        gpu_config = GPUConfig.detect()

        if gpu_config.has_gpu and gpu_config.gpu_memory_gb > 0:
            vram_gb = gpu_config.gpu_memory_gb

            if vram_gb >= 24:
                recommendation = "large-v3 with beam_size=10 (optimal)"
                status = "pass"
            elif vram_gb >= 16:
                recommendation = "large-v3 with beam_size=8 (good)"
                status = "pass"
            elif vram_gb >= 12:
                recommendation = "large-v3 with beam_size=5 (adequate)"
                status = "warn"
            elif vram_gb >= 8:
                recommendation = "large-v2 or medium (recommended)"
                status = "warn"
            else:
                recommendation = "Use OpenAI API (insufficient VRAM)"
                status = "warn"

            result = DiagnosticResult(
                name="GPU Memory",
                status=status,
                message=f"{vram_gb:.1f} GB VRAM",
                details=f"Recommendation: {recommendation}",
                fix_suggestion=(
                    None if status == "pass" else "Consider using OpenAI API for better performance"
                ),
            )
        elif gpu_config.has_gpu:
            result = DiagnosticResult(
                name="GPU Memory",
                status="warn",
                message="GPU detected",
                details="Could not determine VRAM amount automatically",
                fix_suggestion="Run nvidia-smi to confirm available VRAM",
            )
        else:
            result = DiagnosticResult(
                name="GPU Memory",
                status="warn",
                message="No GPU detected",
                details="GPU memory check skipped",
                fix_suggestion=None,
            )

        self.results.append(result)
        return result

    def check_additional_providers(self) -> list[DiagnosticResult]:
        """Check additional AI provider configurations with live validation."""
        results: list[DiagnosticResult] = []

        # XAI/Grok - OpenAI-compatible API
        xai_key = os.getenv("XAI_API_KEY") or os.getenv("SCRIBE_XAI_API_KEY")
        if xai_key:
            try:
                client = OpenAI(
                    api_key=xai_key,
                    base_url="https://api.x.ai/v1",
                    timeout=10,
                )
                client.models.list()
                results.append(
                    DiagnosticResult(
                        name="XAI/Grok API Key",
                        status="pass",
                        message="Valid",
                        details=f"Key: {xai_key[:8]}...{xai_key[-4:]}",
                    )
                )
            except AuthenticationError:
                results.append(
                    DiagnosticResult(
                        name="XAI/Grok API Key",
                        status="fail",
                        message="Invalid key (401 Unauthorized)",
                        details=f"Key: {xai_key[:8]}...{xai_key[-4:]}",
                        fix_suggestion="Update XAI_API_KEY in your .env file",
                    )
                )
            except Exception as e:
                results.append(
                    DiagnosticResult(
                        name="XAI/Grok API Key",
                        status="warn",
                        message="Could not verify",
                        details=f"Key: {xai_key[:8]}...{xai_key[-4:]} | Error: {e}",
                        fix_suggestion="Check your internet connection",
                    )
                )

        # Gemini - Google genai SDK
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("SCRIBE_GEMINI_API_KEY")
        if gemini_key:
            try:
                import google.genai as genai

                # Bound the call so a network stall cannot hang `scribe doctor`
                # (the OpenAI/XAI checks already pass a 10s timeout).
                gemini_client = genai.Client(api_key=gemini_key, http_options={"timeout": 10_000})
                list_models = cast(Any, gemini_client.models).list
                list(list_models(config={"page_size": 1}))
                results.append(
                    DiagnosticResult(
                        name="Gemini API Key",
                        status="pass",
                        message="Valid",
                        details=f"Key: {gemini_key[:8]}...{gemini_key[-4:]}",
                    )
                )
            except Exception as e:
                err = str(e).lower()
                if "401" in err or "invalid" in err or "api key" in err:
                    results.append(
                        DiagnosticResult(
                            name="Gemini API Key",
                            status="fail",
                            message="Invalid key",
                            details=f"Key: {gemini_key[:8]}...{gemini_key[-4:]}",
                            fix_suggestion="Update GEMINI_API_KEY in your .env file",
                        )
                    )
                else:
                    results.append(
                        DiagnosticResult(
                            name="Gemini API Key",
                            status="warn",
                            message="Could not verify",
                            details=f"Error: {e}",
                            fix_suggestion="Check your internet connection",
                        )
                    )

        # Anthropic - just check presence (no lightweight endpoint)
        anthropic_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("SCRIBE_ANTHROPIC_API_KEY")
        if anthropic_key:
            results.append(
                DiagnosticResult(
                    name="Anthropic API Key",
                    status="pass",
                    message="Configured",
                    details=f"Key: {anthropic_key[:8]}...{anthropic_key[-4:]}",
                )
            )

        if not results:
            results.append(
                DiagnosticResult(
                    name="Additional Providers",
                    status="warn",
                    message="No additional providers",
                    details="Only OpenAI configured",
                    fix_suggestion="Consider adding XAI or other providers for cost savings",
                )
            )

        self.results.extend(results)
        return results

    def check_temp_space(self) -> DiagnosticResult:
        """Check temporary directory space."""
        import tempfile

        try:
            temp_dir = Path(tempfile.gettempdir())
            stat = shutil.disk_usage(temp_dir)
            free_gb = stat.free / (1024**3)

            if free_gb > 5:
                result = DiagnosticResult(
                    name="Temp Space",
                    status="pass",
                    message=f"{free_gb:.1f} GB free",
                    details=f"Temp dir: {temp_dir}",
                )
            elif free_gb > 2:
                result = DiagnosticResult(
                    name="Temp Space",
                    status="warn",
                    message=f"{free_gb:.1f} GB free",
                    details=f"Temp dir: {temp_dir}",
                    fix_suggestion="Consider cleaning temp directory",
                )
            else:
                result = DiagnosticResult(
                    name="Temp Space",
                    status="fail",
                    message=f"{free_gb:.1f} GB free",
                    details=f"Temp dir: {temp_dir}",
                    fix_suggestion="Clean temp directory - audio processing requires temporary space",
                )
        except Exception as e:
            result = DiagnosticResult(
                name="Temp Space",
                status="warn",
                message="Could not check",
                details=f"Error: {e}",
                fix_suggestion=None,
            )

        self.results.append(result)
        return result

    def check_configuration_conflicts(self) -> DiagnosticResult:
        """Check for configuration conflicts or issues."""
        issues = []

        # Check for conflicting API keys
        openai_key = os.getenv("OPENAI_API_KEY")
        scribe_openai_key = os.getenv("SCRIBE_OPENAI_API_KEY")

        if openai_key and scribe_openai_key and openai_key != scribe_openai_key:
            issues.append("Conflicting OPENAI_API_KEY and SCRIBE_OPENAI_API_KEY")

        # Check for reasonable timeout values
        timeout = os.getenv("SCRIBE_PROCESS_TIMEOUT")
        if timeout:
            try:
                timeout_val = int(timeout)
                if timeout_val < 300:
                    issues.append(f"SCRIBE_PROCESS_TIMEOUT too low ({timeout_val}s)")
            except ValueError:
                issues.append(f"Invalid SCRIBE_PROCESS_TIMEOUT: {timeout}")

        # Check meme QA threshold
        qa_threshold = os.getenv("SCRIBE_MEME_QA_THRESHOLD")
        if qa_threshold:
            try:
                threshold_val = float(qa_threshold)
                if threshold_val < 0 or threshold_val > 10:
                    issues.append(f"SCRIBE_MEME_QA_THRESHOLD out of range: {threshold_val}")
            except ValueError:
                issues.append(f"Invalid SCRIBE_MEME_QA_THRESHOLD: {qa_threshold}")

        if issues:
            result = DiagnosticResult(
                name="Configuration",
                status="warn",
                message=f"{len(issues)} issue(s) found",
                details="\n".join(f"- {issue}" for issue in issues),
                fix_suggestion="Review and fix configuration in .env file",
            )
        else:
            result = DiagnosticResult(
                name="Configuration",
                status="pass",
                message="No conflicts detected",
                details="Configuration appears valid",
            )

        self.results.append(result)
        return result

    def check_system_resources(self) -> DiagnosticResult:
        """Check system resources (CPU, RAM)."""
        try:
            import psutil  # type: ignore[import-untyped]

            # Check RAM
            ram = psutil.virtual_memory()
            ram_gb = ram.total / (1024**3)
            ram_available_gb = ram.available / (1024**3)
            ram_percent = ram.percent

            # Check CPU
            cpu_count = psutil.cpu_count()

            details_lines = [
                f"RAM: {ram_gb:.1f} GB total, {ram_available_gb:.1f} GB available ({100 - ram_percent:.1f}% free)",
                f"CPU: {cpu_count} cores",
            ]

            if ram_gb < 8:
                status = "warn"
                message = "Low RAM"
                fix = "8+ GB RAM recommended for local transcription"
            elif ram_available_gb < 2:
                status = "warn"
                message = "Low available RAM"
                fix = "Close other applications to free memory"
            else:
                status = "pass"
                message = "Adequate resources"
                fix = None

            result = DiagnosticResult(
                name="System Resources",
                status=status,
                message=message,
                details="\n".join(details_lines),
                fix_suggestion=fix,
            )
        except ImportError:
            result = DiagnosticResult(
                name="System Resources",
                status="warn",
                message="Resource monitor unavailable (psutil not installed)",
                details="Cannot check system memory",
                fix_suggestion="Reinstall Scribe; psutil is a required dependency",
            )
        except Exception as e:
            result = DiagnosticResult(
                name="System Resources",
                status="warn",
                message="Could not check",
                details=f"Error: {e}",
                fix_suggestion=None,
            )

        self.results.append(result)
        return result

    def check_api_resilience(self) -> DiagnosticResult:
        """Report OpenAI API circuit breaker state (defensive cloud transcription)."""
        from scribe.utils.api_resilience import api_circuit_breaker_status

        status = api_circuit_breaker_status()
        details_lines = [
            f"Service: {status['service']}",
            f"State: {status['state']}",
            f"Recent failure count: {status['failure_count']}",
            f"Recovery timeout: {status['recovery_timeout_seconds']}s",
        ]
        if status["seconds_until_recovery"] is not None:
            details_lines.append(f"Estimated recovery in: {status['seconds_until_recovery']:.0f}s")

        if status["state"] == "open":
            result = DiagnosticResult(
                name="API Resilience",
                status="warn",
                message="OpenAI circuit breaker is open (too many recent failures)",
                details="\n".join(details_lines),
                fix_suggestion=(
                    "Wait for the cooldown, verify network connectivity, then retry. "
                    "Run `scribe doctor` again to confirm the breaker has closed."
                ),
            )
        else:
            result = DiagnosticResult(
                name="API Resilience",
                status="pass",
                message="OpenAI API circuit breaker is closed",
                details="\n".join(details_lines),
            )

        self.results.append(result)
        return result

    def check_voice_readiness(self) -> DiagnosticResult | None:
        """Check resident-voice (tray/listen) environment readiness.

        Opt-in by design: if the user has not installed any voice dependency, this
        check stays silent so non-voice users get no extra noise. When voice is
        installed it surfaces the OS-permission (macOS) and display-protocol
        (Linux Wayland) caveats that dependency presence alone cannot prove - the
        same reason ``scribe tray --check`` shows them.
        """
        import importlib.util
        import os
        import platform

        # Only speak up if the user has opted into voice (pynput drives the hotkeys
        # and injection that the advisories are about).
        if importlib.util.find_spec("pynput") is None:
            return None

        from scribe.voice.service import missing_dependency_packages, resident_voice_advisories

        advisories = resident_voice_advisories(
            platform.system(),
            session_type=os.environ.get("XDG_SESSION_TYPE", ""),
            wayland_display=os.environ.get("WAYLAND_DISPLAY", ""),
            display=os.environ.get("DISPLAY", ""),
        )
        missing = missing_dependency_packages(include_tray=True)
        advisory_lines = [a.message for a in advisories]
        if missing:
            advisory_lines.insert(
                0,
                f"Missing optional voice packages: {', '.join(missing)}. "
                'Install with `pip install "scribe[tray]"` (and `scribe[kokoro]` for neural read-aloud).',
            )
        warnings = [a for a in advisories if a.level == "warning"]
        if missing or warnings:
            headline = (
                f"Missing packages: {', '.join(missing)}"
                if missing
                else warnings[0].message.split(".")[0]
            )
            result = DiagnosticResult(
                name="Voice Readiness",
                status="warn",
                message=headline,
                details="\n".join(advisory_lines),
                fix_suggestion="Run `scribe tray --check` for full voice diagnostics.",
            )
        else:
            result = DiagnosticResult(
                name="Voice Readiness",
                status="pass",
                message="Voice dependencies and platform checks look ready",
                details="\n".join(advisory_lines) or None,
            )
        self.results.append(result)
        return result

    def get_summary(self) -> tuple[int, int, int]:
        """Get summary counts of pass/warn/fail."""
        pass_count = sum(1 for r in self.results if r.status == "pass")
        warn_count = sum(1 for r in self.results if r.status == "warn")
        fail_count = sum(1 for r in self.results if r.status == "fail")

        return pass_count, warn_count, fail_count

    def get_recommendations(self) -> list[str]:
        """Get prioritized recommendations based on diagnostic results."""
        recommendations = []

        # Critical issues first
        for result in self.results:
            if result.status == "fail" and result.fix_suggestion:
                recommendations.append(f"CRITICAL: {result.name} - {result.fix_suggestion}")

        # Then warnings
        for result in self.results:
            if result.status == "warn" and result.fix_suggestion:
                recommendations.append(f"Warning: {result.name} - {result.fix_suggestion}")

        return recommendations
