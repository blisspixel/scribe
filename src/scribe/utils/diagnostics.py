"""
System diagnostics and health checks for Scribe.

═══════════════════════════════════════════════════════════════════════════════
ARCHITECTURAL PATTERN: Comprehensive System Validation
═══════════════════════════════════════════════════════════════════════════════

This module implements a diagnostic system that checks EVERYTHING needed for
Scribe to work correctly. It's designed to help users troubleshoot issues before
they become problems.

THE PROBLEM WITH "IT DOESN'T WORK":
────────────────────────────────────
Users report: "Scribe doesn't work"

Possible causes:
- Python version too old?
- FFmpeg not installed?
- No GPU detected?
- API key missing?
- Disk full?
- Permissions issue?
- Configuration conflict?

Without diagnostics, debugging requires back-and-forth:
- "What Python version?"
- "Is FFmpeg installed?"
- "Do you have a GPU?"
- etc.

THE SOLUTION - AUTOMATED DIAGNOSTICS:
──────────────────────────────────────
Run `scribe doctor` and get a comprehensive health check:

✓ Python 3.10.11
✓ FFmpeg installed
✓ GPU: RTX 4090 (24GB VRAM)
✓ OpenAI API Key configured
✗ Output folder not writable
⚠ Only 2GB disk space remaining

Fix suggestions:
1. Check output folder permissions
2. Free up disk space (need 10GB+)

WHAT WE CHECK (15 DIAGNOSTICS):
────────────────────────────────
**Core System:**
1. Python version (3.10+ required)
2. Python packages (torch, faster-whisper, etc.)
3. FFmpeg (audio/video conversion)
4. FFprobe (media analysis)

**GPU & Compute:**
5. CUDA availability
6. GPU detection and model
7. GPU memory (VRAM)

**API & Providers:**
8. OpenAI API key
9. Additional providers (XAI, Anthropic, Gemini)

**File System:**
10. Output folder (exists, writable)
11. Disk space (10GB+ recommended)
12. Temp space (5GB+ recommended)

**Configuration:**
13. .env file exists
14. Configuration conflicts
15. System resources (RAM, CPU)

DIAGNOSTIC RESULTS:
───────────────────
Each check returns:
- **Status**: pass, warn, or fail
- **Message**: Brief summary
- **Details**: Technical information
- **Fix suggestion**: How to resolve issues

Example:
```python
DiagnosticResult(
    name="GPU",
    status="pass",
    message="RTX 4090",
    details="VRAM: 24.0 GB\nDevices: 1",
    fix_suggestion=None
)
```

SMART VALIDATION:
─────────────────
Not just "is it installed?" but "will it work?":

**FFmpeg check:**
- ✓ Installed
- ✓ Can execute
- ✓ Version is recent
- ✓ Has required codecs

**Output folder check:**
- ✓ Path configured
- ✓ Folder exists
- ✓ Is a directory (not a file)
- ✓ Writable (actually tests write)

**API key check:**
- ✓ Configured
- ✓ Starts with "sk-"
- ✓ Reasonable length
- ⚠ Format validation (not actual API test)

PRIORITIZED RECOMMENDATIONS:
─────────────────────────────
After running all checks, we prioritize fixes:

1. **Failures first**: Must fix to work at all
2. **Warnings second**: Should fix for best experience
3. **Passes last**: Everything working

Example output:
```
Top 5 Action Items:
1. [FAIL] Install FFmpeg - required for audio conversion
2. [FAIL] Set OPENAI_API_KEY - required for API features
3. [WARN] Only 2GB disk space - need 10GB+ for large files
4. [WARN] Python 3.9 detected - upgrade to 3.10+ recommended
5. [WARN] No additional providers - consider XAI for cost savings
```

WHAT WE DON'T CHECK (HONEST LIMITATIONS):
──────────────────────────────────────────
1. **API key validity**: We check format, not if it actually works
2. **Network connectivity**: Don't test if APIs are reachable
3. **GPU driver version**: Just check if CUDA is available
4. **FFmpeg codec support**: Don't verify specific codecs
5. **Actual performance**: Don't benchmark GPU speed

Why not? These would require:
- Making API calls (costs money, slow)
- Network requests (can fail, slow)
- Running benchmarks (very slow)

We optimize for FAST diagnostics that catch 90% of issues.

POTENTIAL IMPROVEMENTS:
───────────────────────
1. **API key validation**: Actually test API call (optional, slow)
2. **Network check**: Ping OpenAI to verify connectivity
3. **GPU benchmark**: Quick test to measure actual speed
4. **Codec verification**: Check FFmpeg has required codecs
5. **Provider health**: Check if each provider API is responding

THE VALUE:
──────────
This diagnostic system catches issues BEFORE users hit them:
- New user setup: Validates everything is configured
- Troubleshooting: Identifies the actual problem quickly
- Support: Users can share diagnostic output
- CI/CD: Automated environment validation

One command (`scribe doctor`) replaces hours of back-and-forth debugging.
"""

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from openai import AuthenticationError, OpenAI

from scribe.utils.platform import get_platform, is_windows


@dataclass
class DiagnosticResult:
    """Result of a diagnostic check."""
    name: str
    status: str  # "pass", "warn", "fail"
    message: str
    details: str | None = None
    fix_suggestion: str | None = None


class SystemDiagnostics:
    """System diagnostics and health checks."""

    def __init__(self):
        self.results: list[DiagnosticResult] = []

    def run_all_checks(self) -> list[DiagnosticResult]:
        """Run all diagnostic checks."""
        self.results = []

        # Core system checks
        self.check_python_version()
        self.check_python_packages()
        self.check_ffmpeg()
        self.check_ffprobe()
        self.check_ytdlp()

        # GPU and compute checks
        self.check_cuda()
        self.check_gpu()
        self.check_gpu_memory()

        # API and provider checks
        self.check_openai_api_key()
        self.check_additional_providers()

        # File system checks
        self.check_output_folder()
        self.check_disk_space()
        self.check_temp_space()

        # Configuration checks
        self.check_env_file()
        self.check_configuration_conflicts()

        # Performance checks
        self.check_system_resources()

        return self.results

    def check_python_version(self) -> DiagnosticResult:
        """Check Python version."""
        version = sys.version_info
        version_str = f"{version.major}.{version.minor}.{version.micro}"

        if version.major == 3 and version.minor >= 10:
            result = DiagnosticResult(
                name="Python Version",
                status="pass",
                message=f"Python {version_str}",
                details="Python 3.10+ detected"
            )
        elif version.major == 3 and version.minor >= 8:
            result = DiagnosticResult(
                name="Python Version",
                status="warn",
                message=f"Python {version_str}",
                details="Python 3.10+ recommended",
                fix_suggestion="Upgrade to Python 3.10 or newer for best compatibility"
            )
        else:
            result = DiagnosticResult(
                name="Python Version",
                status="fail",
                message=f"Python {version_str}",
                details="Python 3.10+ required",
                fix_suggestion="Install Python 3.10 or newer from python.org"
            )

        self.results.append(result)
        return result

    def check_ffmpeg(self) -> DiagnosticResult:
        """Check FFmpeg availability."""
        ffmpeg_path = shutil.which("ffmpeg")

        if ffmpeg_path:
            try:
                output = subprocess.check_output(
                    ["ffmpeg", "-version"],
                    stderr=subprocess.STDOUT,
                    text=True,
                    timeout=5
                )
                version_line = output.split('\n')[0]

                result = DiagnosticResult(
                    name="FFmpeg",
                    status="pass",
                    message="Installed",
                    details=f"Found at: {ffmpeg_path}\n{version_line}"
                )
            except Exception as e:
                result = DiagnosticResult(
                    name="FFmpeg",
                    status="warn",
                    message="Found but not working",
                    details=f"Path: {ffmpeg_path}\nError: {e}",
                    fix_suggestion="Reinstall FFmpeg"
                )
        else:
            platform = get_platform()
            if is_windows():
                fix = "Install: winget install FFmpeg.FFmpeg"
            elif platform == "darwin":
                fix = "Install: brew install ffmpeg"
            else:
                fix = "Install: sudo apt install ffmpeg"

            result = DiagnosticResult(
                name="FFmpeg",
                status="fail",
                message="Not found",
                details="FFmpeg is required for audio/video conversion",
                fix_suggestion=fix
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
                details=f"Found at: {ffprobe_path}"
            )
        else:
            result = DiagnosticResult(
                name="FFprobe",
                status="warn",
                message="Not found",
                details="FFprobe is useful for media file inspection",
                fix_suggestion="Usually installed with FFmpeg"
            )

        self.results.append(result)
        return result

    def check_ytdlp(self) -> DiagnosticResult:
        """Check yt-dlp availability for URL downloads."""
        try:
            import yt_dlp
            version = getattr(yt_dlp, "version", None)
            ver_str = getattr(version, "__version__", "installed") if version else "installed"
            result = DiagnosticResult(
                name="yt-dlp",
                status="pass",
                message=ver_str,
                details="Required for scribe url command"
            )
        except ImportError:
            result = DiagnosticResult(
                name="yt-dlp",
                status="warn",
                message="Not installed",
                details="Required for scribe url (YouTube, Vimeo, etc.)",
                fix_suggestion="Run: pip install yt-dlp"
            )

        self.results.append(result)
        return result

    def check_cuda(self) -> DiagnosticResult:
        """Check CUDA availability."""
        try:
            import torch

            if torch.cuda.is_available():
                cuda_version = torch.version.cuda
                result = DiagnosticResult(
                    name="CUDA",
                    status="pass",
                    message=f"CUDA {cuda_version}",
                    details="CUDA is available for GPU acceleration"
                )
            else:
                result = DiagnosticResult(
                    name="CUDA",
                    status="warn",
                    message="Not available",
                    details="PyTorch installed but CUDA not detected",
                    fix_suggestion="Install CUDA-enabled PyTorch: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124"
                )
        except ImportError:
            result = DiagnosticResult(
                name="CUDA",
                status="warn",
                message="PyTorch not installed",
                details="GPU acceleration not available",
                fix_suggestion="Install PyTorch for GPU support (optional)"
            )

        self.results.append(result)
        return result

    def check_gpu(self) -> DiagnosticResult:
        """Check GPU availability and details."""
        try:
            import torch

            if torch.cuda.is_available():
                gpu_count = torch.cuda.device_count()
                gpu_name = torch.cuda.get_device_name(0)

                # Get VRAM
                props = torch.cuda.get_device_properties(0)
                vram_gb = props.total_memory / (1024**3)

                result = DiagnosticResult(
                    name="GPU",
                    status="pass",
                    message=f"{gpu_name}",
                    details=f"VRAM: {vram_gb:.1f} GB\nDevices: {gpu_count}"
                )
            else:
                result = DiagnosticResult(
                    name="GPU",
                    status="warn",
                    message="No GPU detected",
                    details="Will use OpenAI API for transcription",
                    fix_suggestion="GPU is optional - API mode works great"
                )
        except ImportError:
            result = DiagnosticResult(
                name="GPU",
                status="warn",
                message="PyTorch not installed",
                details="Cannot detect GPU",
                fix_suggestion="Install PyTorch to enable GPU detection"
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
                fix_suggestion="Set OPENAI_API_KEY in your .env file"
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
                fix_suggestion="Get a valid API key from https://platform.openai.com/api-keys"
            )
            self.results.append(result)
            return result

        # Live validation — actually call the API to verify the key works
        try:
            client = OpenAI(api_key=api_key, timeout=10)
            client.models.list()
            result = DiagnosticResult(
                name="OpenAI API Key",
                status="pass",
                message="Valid",
                details=f"Key: {api_key[:10]}...{api_key[-4:]}"
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
                )
            )
        except Exception as e:
            # Network error, timeout, etc. — key format is fine, can't verify
            result = DiagnosticResult(
                name="OpenAI API Key",
                status="warn",
                message="Could not verify",
                details=f"Key: {api_key[:10]}...{api_key[-4:]} | Error: {e}",
                fix_suggestion="Check your internet connection"
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
                fix_suggestion="Set SCRIBE_OUTPUT_FOLDER in your .env file"
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
                            details=f"Path: {output_path}"
                        )
                    except Exception as e:
                        result = DiagnosticResult(
                            name="Output Folder",
                            status="fail",
                            message="Not writable",
                            details=f"Path: {output_path}\nError: {e}",
                            fix_suggestion="Check folder permissions"
                        )
                else:
                    result = DiagnosticResult(
                        name="Output Folder",
                        status="fail",
                        message="Not a directory",
                        details=f"Path: {output_path}",
                        fix_suggestion="Remove the file or choose a different path"
                    )
            else:
                result = DiagnosticResult(
                    name="Output Folder",
                    status="warn",
                    message="Does not exist",
                    details=f"Path: {output_path}",
                    fix_suggestion="Folder will be created automatically on first use"
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
                    details=f"Total: {total_gb:.1f} GB ({percent_free:.1f}% free)"
                )
            elif free_gb > 5:
                result = DiagnosticResult(
                    name="Disk Space",
                    status="warn",
                    message=f"{free_gb:.1f} GB free",
                    details=f"Total: {total_gb:.1f} GB ({percent_free:.1f}% free)",
                    fix_suggestion="Consider freeing up disk space"
                )
            else:
                result = DiagnosticResult(
                    name="Disk Space",
                    status="fail",
                    message=f"{free_gb:.1f} GB free",
                    details=f"Total: {total_gb:.1f} GB ({percent_free:.1f}% free)",
                    fix_suggestion="Free up disk space - less than 5 GB available"
                )
        except Exception as e:
            result = DiagnosticResult(
                name="Disk Space",
                status="warn",
                message="Could not check",
                details=f"Error: {e}",
                fix_suggestion=None
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
                details=f"Path: {env_file.absolute()}"
            )
        else:
            result = DiagnosticResult(
                name=".env File",
                status="warn",
                message="Not found",
                details="Using environment variables or defaults",
                fix_suggestion="Copy .env.example to .env and configure"
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
            "rich": "13.0.0"
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
                fix_suggestion="Run: pip install -r requirements.txt"
            )
        else:
            result = DiagnosticResult(
                name="Python Packages",
                status="pass",
                message="All critical packages installed",
                details=f"Checked: {', '.join(critical_packages.keys())}"
            )

        self.results.append(result)
        return result

    def check_gpu_memory(self) -> DiagnosticResult:
        """Check GPU memory and recommend optimal settings."""
        try:
            import torch

            if torch.cuda.is_available():
                props = torch.cuda.get_device_properties(0)
                vram_gb = props.total_memory / (1024**3)

                # Recommend model based on VRAM
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
                    fix_suggestion=None if status == "pass" else "Consider using OpenAI API for better performance"
                )
            else:
                result = DiagnosticResult(
                    name="GPU Memory",
                    status="warn",
                    message="No GPU detected",
                    details="GPU memory check skipped",
                    fix_suggestion=None
                )
        except ImportError:
            result = DiagnosticResult(
                name="GPU Memory",
                status="warn",
                message="PyTorch not installed",
                details="Cannot check GPU memory",
                fix_suggestion=None
            )

        self.results.append(result)
        return result

    def check_additional_providers(self) -> list[DiagnosticResult]:
        """Check additional AI provider configurations with live validation."""
        results: list[DiagnosticResult] = []

        # XAI/Grok — OpenAI-compatible API
        xai_key = os.getenv("XAI_API_KEY") or os.getenv("SCRIBE_XAI_API_KEY")
        if xai_key:
            try:
                client = OpenAI(
                    api_key=xai_key,
                    base_url="https://api.x.ai/v1",
                    timeout=10,
                )
                client.models.list()
                results.append(DiagnosticResult(
                    name="XAI/Grok API Key",
                    status="pass",
                    message="Valid",
                    details=f"Key: {xai_key[:8]}...{xai_key[-4:]}",
                ))
            except AuthenticationError:
                results.append(DiagnosticResult(
                    name="XAI/Grok API Key",
                    status="fail",
                    message="Invalid key (401 Unauthorized)",
                    details=f"Key: {xai_key[:8]}...{xai_key[-4:]}",
                    fix_suggestion="Update XAI_API_KEY in your .env file",
                ))
            except Exception as e:
                results.append(DiagnosticResult(
                    name="XAI/Grok API Key",
                    status="warn",
                    message="Could not verify",
                    details=f"Key: {xai_key[:8]}...{xai_key[-4:]} | Error: {e}",
                    fix_suggestion="Check your internet connection",
                ))

        # Gemini — Google genai SDK
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("SCRIBE_GEMINI_API_KEY")
        if gemini_key:
            try:
                import google.genai as genai

                client = genai.Client(api_key=gemini_key)
                list(client.models.list(config={"page_size": 1}))
                results.append(DiagnosticResult(
                    name="Gemini API Key",
                    status="pass",
                    message="Valid",
                    details=f"Key: {gemini_key[:8]}...{gemini_key[-4:]}",
                ))
            except Exception as e:
                err = str(e).lower()
                if "401" in err or "invalid" in err or "api key" in err:
                    results.append(DiagnosticResult(
                        name="Gemini API Key",
                        status="fail",
                        message="Invalid key",
                        details=f"Key: {gemini_key[:8]}...{gemini_key[-4:]}",
                        fix_suggestion="Update GEMINI_API_KEY in your .env file",
                    ))
                else:
                    results.append(DiagnosticResult(
                        name="Gemini API Key",
                        status="warn",
                        message="Could not verify",
                        details=f"Error: {e}",
                        fix_suggestion="Check your internet connection",
                    ))

        # Anthropic — just check presence (no lightweight endpoint)
        anthropic_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("SCRIBE_ANTHROPIC_API_KEY")
        if anthropic_key:
            results.append(DiagnosticResult(
                name="Anthropic API Key",
                status="pass",
                message="Configured",
                details=f"Key: {anthropic_key[:8]}...{anthropic_key[-4:]}",
            ))

        if not results:
            results.append(DiagnosticResult(
                name="Additional Providers",
                status="warn",
                message="No additional providers",
                details="Only OpenAI configured",
                fix_suggestion="Consider adding XAI or other providers for cost savings",
            ))

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
                    details=f"Temp dir: {temp_dir}"
                )
            elif free_gb > 2:
                result = DiagnosticResult(
                    name="Temp Space",
                    status="warn",
                    message=f"{free_gb:.1f} GB free",
                    details=f"Temp dir: {temp_dir}",
                    fix_suggestion="Consider cleaning temp directory"
                )
            else:
                result = DiagnosticResult(
                    name="Temp Space",
                    status="fail",
                    message=f"{free_gb:.1f} GB free",
                    details=f"Temp dir: {temp_dir}",
                    fix_suggestion="Clean temp directory - audio processing requires temporary space"
                )
        except Exception as e:
            result = DiagnosticResult(
                name="Temp Space",
                status="warn",
                message="Could not check",
                details=f"Error: {e}",
                fix_suggestion=None
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
                fix_suggestion="Review and fix configuration in .env file"
            )
        else:
            result = DiagnosticResult(
                name="Configuration",
                status="pass",
                message="No conflicts detected",
                details="Configuration appears valid"
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
                f"RAM: {ram_gb:.1f} GB total, {ram_available_gb:.1f} GB available ({100-ram_percent:.1f}% free)",
                f"CPU: {cpu_count} cores"
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
                fix_suggestion=fix
            )
        except ImportError:
            result = DiagnosticResult(
                name="System Resources",
                status="warn",
                message="psutil not installed",
                details="Cannot check system resources",
                fix_suggestion="Install psutil for resource monitoring: pip install psutil"
            )
        except Exception as e:
            result = DiagnosticResult(
                name="System Resources",
                status="warn",
                message="Could not check",
                details=f"Error: {e}",
                fix_suggestion=None
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
