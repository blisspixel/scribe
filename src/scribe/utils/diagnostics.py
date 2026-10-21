"""Local-first diagnostics used by `scribe doctor` and support bundles.

Default diagnostics are local-only and safe to run without spending money or
calling provider APIs. They inspect Python 3.11 through 3.14 readiness, critical packages,
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

import math
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
from openai import AuthenticationError, OpenAI

from scribe.core.backends.hardware import detect_hardware
from scribe.models.gpu import GPUConfig
from scribe.utils.obs_config import read_obs_websocket_config
from scribe.utils.platform import ffmpeg_install_command


def _obs_process_running() -> bool:
    """Return whether an OBS desktop process is present."""
    try:
        import psutil  # type: ignore[import-untyped]

        return any(
            (process.info.get("name") or "").lower() in {"obs", "obs64.exe", "obs32.exe"}
            for process in psutil.process_iter(["name"])
        )
    except (ImportError, OSError):
        return False


def _tcp_port_listening(host: str, port: int, timeout: float = 0.2) -> bool:
    """Return whether a local TCP endpoint accepts a connection."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


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
        backend_ok = availability.get(backend, False)
    except Exception:
        backend_ok = False

    ffmpeg = shutil.which("ffmpeg") is not None
    can_transcribe = backend_ok and ffmpeg
    transcribe_fix: str | None = None
    if not backend_ok:
        transcribe_detail = "no local Whisper backend importable"
        transcribe_fix = "Reinstall Scribe from its source; faster-whisper is a base dependency."
    elif not ffmpeg:
        transcribe_detail = f"{backend} ({vendor}) ready, but ffmpeg is missing"
        transcribe_fix = (
            "Install ffmpeg: winget install FFmpeg.FFmpeg / brew install ffmpeg / "
            "sudo pacman -S ffmpeg / sudo apt install ffmpeg."
        )
    else:
        if backend == "whispercpp":
            execution = "native device depends on the build; GPU acceleration not verified"
        elif backend == "mlx":
            execution = "Metal via MLX"
        elif backend == "faster-whisper":
            execution = "CUDA if the runtime is usable; otherwise CPU int8"
        else:
            execution = "CPU int8 (runtime depends on model and file, still $0)"
        transcribe_detail = f"{backend} on {vendor} - {execution}"
        # Nudge Apple/AMD/Intel users off the CPU floor toward their fast backend.
        if backend == "cpu" and vendor == "apple":
            transcribe_fix = 'For Metal acceleration, install Scribe with its "mlx" extra.'
        elif backend == "cpu" and vendor in ("amd", "intel"):
            transcribe_fix = (
                "Optional AMD/Intel acceleration needs a Vulkan/ROCm-enabled pywhispercpp build "
                'and compatible drivers; an importable "whispercpp" extra alone does not prove GPU use. '
                "See https://github.com/absadiki/pywhispercpp#installation"
            )

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

    def __init__(self, config: Any | None = None) -> None:
        self.results: list[DiagnosticResult] = []
        self.config = config

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
            checks += [
                self.check_openai_api_key,
                self.check_openrouter_api_key,
                self.check_additional_providers,
            ]
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

        if version.major == 3 and 11 <= version.minor <= 14:
            result = DiagnosticResult(
                name="Python Version",
                status="pass",
                message=f"Python {version_str}",
                details="Supported Python detected (3.11 through 3.14). 3.14 is the default.",
            )
        elif version.major == 3 and version.minor >= 15:
            result = DiagnosticResult(
                name="Python Version",
                status="fail",
                message=f"Python {version_str} is not supported",
                details=(
                    "Python 3.15 stays unsupported until CTranslate2 and ONNX Runtime "
                    "publish cp315 wheels. Torch wheels on the stable PyTorch index "
                    "do not lift that cap."
                ),
                fix_suggestion="Install with `uv tool install --python 3.14`.",
            )
        else:
            result = DiagnosticResult(
                name="Python Version",
                status="fail",
                message=f"Python {version_str}",
                details="Python 3.11 through 3.14 is required. Python 3.10 is end of life.",
                fix_suggestion="Install Python 3.14 from python.org, or use uv's Python 3.14.",
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
            result = DiagnosticResult(
                name="FFmpeg",
                status="fail",
                message="Not found",
                details="FFmpeg is required for audio/video conversion",
                fix_suggestion=f"Install: {ffmpeg_install_command()}",
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
                fix_suggestion="Reinstall or update Scribe from its source.",
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
        obs_running = _obs_process_running()
        obs_host = str(getattr(config, "obs_host", "localhost"))
        candidate_hosts = dict.fromkeys((obs_host, "127.0.0.1", "::1"))
        websocket_listening = obs_running and any(
            _tcp_port_listening(host, config.obs_port) for host in candidate_hosts
        )
        details = (
            f"OBS config: {obs_config.path}\n"
            f"OBS server enabled: {server_enabled}\n"
            f"OBS port: {server_port}\n"
            f"OBS auth required: {auth_required}\n"
            f"Scribe port: {config.obs_port}\n"
            f"Scribe password configured: {bool(config.obs_password)}\n"
            f"OBS process running: {obs_running}\n"
            f"OBS WebSocket listening: {websocket_listening if obs_running else 'not checked'}"
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
                    f"or PowerShell `$env:SCRIBE_OBS_PORT='{server_port}'`. "
                    f"On a Linux shell, `export SCRIBE_OBS_PORT={server_port}`."
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
                    "`$env:SCRIBE_OBS_PASSWORD='<password>'`. On a Linux shell, "
                    "`export SCRIBE_OBS_PASSWORD=<password>`. Persistent config: "
                    "add [obs].password to your Scribe config file."
                ),
            )
        elif obs_running and not websocket_listening:
            result = DiagnosticResult(
                name="OBS WebSocket",
                status="warn",
                message="OBS is running, but WebSocket is not listening",
                details=details,
                fix_suggestion=(
                    "Run `scribe rec --check`. Scribe will attempt a non-destructive "
                    "relaunch when recording starts. If the check still fails, close all "
                    "OBS instances and reopen OBS."
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
        elif detect_hardware().vendor != "nvidia":
            details = "CUDA is NVIDIA-specific. Local CPU transcription remains available at $0."
            fix = None
            try:
                import torch

                if torch.version.cuda:
                    details += " This PyTorch build includes CUDA despite no detected NVIDIA GPU."
                    fix = (
                        "To remove unused CUDA packages, reinstall Scribe using uv tool install "
                        "--force --python 3.14 --torch-backend auto with the original Scribe source."
                    )
            except ImportError:
                pass
            result = DiagnosticResult(
                name="CUDA",
                status="pass",
                message="N/A (no NVIDIA GPU detected)",
                details=details,
                fix_suggestion=fix,
            )
        else:
            result = DiagnosticResult(
                name="CUDA",
                status="warn",
                message="Not available",
                details=gpu_config.reason,
                fix_suggestion=(
                    "Check the NVIDIA driver and CTranslate2 CUDA requirements, or keep using "
                    "local CPU transcription. See https://opennmt.net/CTranslate2/installation.html"
                ),
            )

        self.results.append(result)
        return result

    def check_cuda_driver(self) -> DiagnosticResult:
        """Check CUDA driver version and age."""
        import subprocess

        if not GPUConfig.detect().has_gpu and detect_hardware().vendor != "nvidia":
            skipped = DiagnosticResult(
                name="CUDA Driver",
                status="pass",
                message="N/A (no NVIDIA GPU detected)",
                details="An NVIDIA driver is not required for local CPU, MLX or Vulkan transcription.",
            )
            self.results.append(skipped)
            return skipped
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
            hardware = detect_hardware()
            hint = None
            if hardware.vendor in ("amd", "intel"):
                hint = (
                    "CPU transcription works at $0. Optional whisper.cpp acceleration requires "
                    "a Vulkan/ROCm-enabled build and compatible drivers; installing the extra "
                    "alone does not establish acceleration. See "
                    "https://github.com/absadiki/pywhispercpp#installation"
                )
            elif hardware.vendor == "apple":
                hint = 'For optional Metal acceleration, install Scribe with its "mlx" extra.'
            result = DiagnosticResult(
                name="GPU",
                status="pass",
                message=hardware.accelerator_name or "CPU supported (no GPU detected)",
                details=(
                    f"Physical hardware: {hardware.vendor}. Presence does not verify backend acceleration. "
                    f"{gpu_config.reason}"
                ),
                fix_suggestion=hint,
            )

        self.results.append(result)
        return result

    def check_openai_api_key(self) -> DiagnosticResult | None:
        """Check OpenAI API key existence and validity."""
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("SCRIBE_OPENAI_API_KEY")

        if not api_key:
            return None

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
                details="An OpenAI API key is configured and valid.",
            )
        except AuthenticationError:
            result = DiagnosticResult(
                name="OpenAI API Key",
                status="fail",
                message="Invalid key (401 Unauthorized)",
                details="The configured OpenAI API key was rejected.",
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
                details=f"The configured OpenAI API key could not be verified: {type(e).__name__}",
                fix_suggestion="Check your internet connection",
            )

        self.results.append(result)
        return result

    def check_openrouter_api_key(self) -> DiagnosticResult | None:
        """Validate a configured OpenRouter key without making a paid request."""
        api_key = (
            getattr(self.config, "openrouter_api_key", None)
            if self.config is not None
            else os.getenv("OPENROUTER_API_KEY") or os.getenv("SCRIBE_OPENROUTER_API_KEY")
        )
        if not api_key:
            return None
        api_key = api_key.strip()

        if len(api_key) < 16 or any(character.isspace() for character in api_key):
            result = DiagnosticResult(
                name="OpenRouter API Key",
                status="warn",
                message="Invalid format",
                details="The configured key is too short or contains whitespace.",
                fix_suggestion="Create a key at https://openrouter.ai/settings/keys",
            )
            self.results.append(result)
            return result

        try:
            response = httpx.get(
                "https://openrouter.ai/api/v1/key",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10.0,
            )
            if response.status_code == 200:
                try:
                    body = response.json()
                except (TypeError, ValueError):
                    body = None
                data = body.get("data") if isinstance(body, dict) else None
                provider_limit = data.get("limit") if isinstance(data, dict) else None
                remaining = data.get("limit_remaining") if isinstance(data, dict) else None
                configured_limit = (
                    getattr(self.config, "openrouter_max_spend_usd", 5.0)
                    if self.config is not None
                    else os.getenv("SCRIBE_OPENROUTER_MAX_SPEND_USD", "5")
                )
                try:
                    local_limit = float(configured_limit)
                except (TypeError, ValueError):
                    local_limit = 5.0
                if not math.isfinite(local_limit) or not 0 < local_limit <= 1000:
                    local_limit = 5.0

                if (
                    isinstance(remaining, int | float)
                    and not isinstance(remaining, bool)
                    and remaining <= 0
                ):
                    result = DiagnosticResult(
                        name="OpenRouter API Key",
                        status="fail",
                        message="Valid key, no remaining budget",
                        details="The key is valid but cannot fund another request.",
                        fix_suggestion="Add credit or raise the key limit in OpenRouter settings",
                    )
                elif (
                    isinstance(provider_limit, int | float)
                    and not isinstance(provider_limit, bool)
                    and 0 <= provider_limit <= local_limit
                ):
                    result = DiagnosticResult(
                        name="OpenRouter API Key",
                        status="pass",
                        message="Valid with provider hard cap",
                        details=(
                            "The key is valid and its provider-side limit is at or below "
                            "Scribe's per-transcription guard."
                        ),
                    )
                else:
                    result = DiagnosticResult(
                        name="OpenRouter API Key",
                        status="warn",
                        message="Valid, hard cap not verified",
                        details=(
                            "The key is valid, but no provider-side limit at or below "
                            "Scribe's per-transcription guard was reported."
                        ),
                        fix_suggestion=(
                            "Set an OpenRouter key limit at or below "
                            f"${local_limit:.2f} for an absolute cap"
                        ),
                    )
            elif response.status_code in {401, 403}:
                result = DiagnosticResult(
                    name="OpenRouter API Key",
                    status="fail",
                    message=f"Invalid key ({response.status_code})",
                    details="The configured OpenRouter API key was rejected.",
                    fix_suggestion="Create a key at https://openrouter.ai/settings/keys",
                )
            else:
                result = DiagnosticResult(
                    name="OpenRouter API Key",
                    status="warn",
                    message="Could not verify",
                    details=f"OpenRouter key check returned HTTP {response.status_code}.",
                    fix_suggestion="Check OpenRouter service status and your internet connection",
                )
        except httpx.RequestError as exc:
            result = DiagnosticResult(
                name="OpenRouter API Key",
                status="warn",
                message="Could not verify",
                details=(
                    f"The configured OpenRouter API key could not be verified: {type(exc).__name__}"
                ),
                fix_suggestion="Check your internet connection",
            )

        self.results.append(result)
        return result

    def _output_path(self) -> Path:
        """Use the same file, environment, and default resolution as the CLI."""
        if self.config is None:
            from scribe.models.config import ScribeConfig

            self.config = ScribeConfig()
        return Path(self.config.output_folder).expanduser()

    def check_output_folder(self) -> DiagnosticResult:
        """Check output folder configuration and permissions."""
        try:
            output_path = self._output_path()
        except Exception as exc:
            result = DiagnosticResult(
                name="Output Folder",
                status="fail",
                message="Invalid configuration",
                details=str(exc),
                fix_suggestion="Check the configured output folder and its permissions",
            )
        else:
            if output_path.exists():
                if output_path.is_dir():
                    try:
                        # A unique probe cannot overwrite a user's existing file.
                        with tempfile.TemporaryFile(dir=output_path, prefix=".scribe-write-"):
                            pass

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
        try:
            output_path = self._output_path().resolve()
            # Get disk usage for the output folder's drive
            check_path = output_path
            while not check_path.exists() and check_path.parent != check_path:
                check_path = check_path.parent

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
        missing: list[str] = []
        broken: dict[str, str] = {}

        critical_packages = (
            "torch",
            "faster_whisper",
            "openai",
            "typer",
            "rich",
        )

        for package in critical_packages:
            try:
                __import__(package)
            except ImportError:
                missing.append(package)
            except (OSError, RuntimeError) as exc:
                broken[package] = str(exc)

        if missing or broken:
            problem_count = len(missing) + len(broken)
            detail_parts = []
            if missing:
                detail_parts.append(f"Missing: {', '.join(missing)}")
            if broken:
                broken_details = "; ".join(
                    f"{package}: {message}" for package, message in broken.items()
                )
                detail_parts.append(f"Broken: {broken_details}")
            result = DiagnosticResult(
                name="Python Packages",
                status="fail",
                message=f"{problem_count} critical package(s) unavailable",
                details="\n".join(detail_parts),
                fix_suggestion=(
                    "Reinstall Scribe from its original package source; "
                    "checkout users can run: uv sync --locked. For a GPU build of Torch, "
                    "reinstall with uv's --torch-backend auto."
                ),
            )
        else:
            result = DiagnosticResult(
                name="Python Packages",
                status="pass",
                message="All critical packages installed",
                details=f"Checked: {', '.join(critical_packages)}",
            )

        self.results.append(result)
        return result

    def check_dependency_security(self) -> DiagnosticResult:
        """Scan installed packages for known vulnerabilities (pip-audit)."""
        import importlib.util

        checkout = Path(__file__).resolve().parents[3]
        if not ((checkout / ".git").exists() and (checkout / "uv.lock").is_file()):
            result = DiagnosticResult(
                name="Dependency Security",
                status="pass",
                message="Not applicable to an installed tool",
                details="The developer dependency audit runs from a source checkout in CI.",
            )
            self.results.append(result)
            return result

        if importlib.util.find_spec("pip_audit") is None:
            result = DiagnosticResult(
                name="Dependency Security",
                status="warn",
                message="pip-audit not installed",
                details="Dependency vulnerability scan is only available in the dev environment.",
                fix_suggestion=(
                    "Developers: run `uv sync --locked --group dev` then re-run `scribe doctor`."
                ),
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
                message="No known vulnerabilities found",
                details=f"Scanned local packages with pip-audit (zero exceptions). {summary}",
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
        """Report CUDA memory without changing the selected quality/model policy."""
        gpu = GPUConfig.detect()
        if gpu.has_gpu and gpu.gpu_memory_gb > 0:
            free = GPUConfig.query_free_memory_gb()
            free_note = f"{free:.1f} GB currently free" if free is not None else "free VRAM unknown"
            result = DiagnosticResult(
                name="GPU Memory",
                status="pass" if free is not None and free >= 5 else "warn",
                message=f"{gpu.gpu_memory_gb:.1f} GB VRAM ({free_note})",
                details=(
                    "Full large-v3 CUDA float16 sequential decoding needs roughly 5 GB free VRAM; "
                    "batching and speaker labels need more. This is planning guidance, not a fit guarantee. "
                    "Hardware does not change the selected model."
                ),
                fix_suggestion=(
                    None
                    if free is not None and free >= 5
                    else "Free GPU memory, explicitly select SCRIBE_LOCAL_BACKEND=cpu, or choose "
                    "--quality balanced/fast or --model if willing to trade model capacity for resources."
                ),
            )
        elif gpu.has_gpu:
            result = DiagnosticResult(
                name="GPU Memory",
                status="warn",
                message="GPU detected; VRAM unknown",
                details="Unknown memory does not establish that the selected model fits.",
                fix_suggestion="Run nvidia-smi to inspect current free VRAM.",
            )
        else:
            result = DiagnosticResult(
                name="GPU Memory",
                status="pass",
                message="N/A (no CUDA transcription runtime)",
                details="CPU uses system RAM. MLX and whisper.cpp manage their own memory.",
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
                        details="An XAI API key is configured and valid.",
                    )
                )
            except AuthenticationError:
                results.append(
                    DiagnosticResult(
                        name="XAI/Grok API Key",
                        status="fail",
                        message="Invalid key (401 Unauthorized)",
                        details="The configured XAI API key was rejected.",
                        fix_suggestion="Update XAI_API_KEY in your .env file",
                    )
                )
            except Exception as e:
                results.append(
                    DiagnosticResult(
                        name="XAI/Grok API Key",
                        status="warn",
                        message="Could not verify",
                        details=f"XAI key verification failed: {type(e).__name__}",
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
                            details="The configured Gemini API key was rejected.",
                            fix_suggestion="Update GEMINI_API_KEY in your .env file",
                        )
                    )
                else:
                    results.append(
                        DiagnosticResult(
                            name="Gemini API Key",
                            status="warn",
                            message="Could not verify",
                            details=f"Gemini key verification failed: {type(e).__name__}",
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
                    details="An Anthropic API key is configured.",
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
            import psutil

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
                'Install Scribe with its "tray" extra and optionally its "kokoro" extra.',
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
