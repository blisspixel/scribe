"""
System diagnostics and health checks for Scribe.

Validates environment, dependencies, and configuration.
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

from scribe.utils.platform import get_platform, is_windows


@dataclass
class DiagnosticResult:
    """Result of a diagnostic check."""
    name: str
    status: str  # "pass", "warn", "fail"
    message: str
    details: Optional[str] = None
    fix_suggestion: Optional[str] = None


class SystemDiagnostics:
    """System diagnostics and health checks."""
    
    def __init__(self):
        self.results: List[DiagnosticResult] = []
    
    def run_all_checks(self) -> List[DiagnosticResult]:
        """Run all diagnostic checks."""
        self.results = []
        
        # Core checks
        self.check_python_version()
        self.check_ffmpeg()
        self.check_ffprobe()
        
        # GPU checks
        self.check_cuda()
        self.check_gpu()
        
        # API checks
        self.check_openai_api_key()
        
        # File system checks
        self.check_output_folder()
        self.check_disk_space()
        
        # Configuration checks
        self.check_env_file()
        
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
        """Check OpenAI API key."""
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("SCRIBE_OPENAI_API_KEY")
        
        if api_key:
            # Basic validation
            if api_key.startswith("sk-") and len(api_key) > 20:
                result = DiagnosticResult(
                    name="OpenAI API Key",
                    status="pass",
                    message="Configured",
                    details=f"Key: {api_key[:10]}...{api_key[-4:]}"
                )
            else:
                result = DiagnosticResult(
                    name="OpenAI API Key",
                    status="warn",
                    message="Invalid format",
                    details="API key doesn't match expected format",
                    fix_suggestion="Get a valid API key from https://platform.openai.com/api-keys"
                )
        else:
            result = DiagnosticResult(
                name="OpenAI API Key",
                status="fail",
                message="Not configured",
                details="Required for API transcription, notes, jokes, and memes",
                fix_suggestion="Set OPENAI_API_KEY in your .env file"
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
            if output_path.exists():
                check_path = output_path
            else:
                check_path = output_path.parent
            
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
    
    def get_summary(self) -> Tuple[int, int, int]:
        """Get summary counts of pass/warn/fail."""
        pass_count = sum(1 for r in self.results if r.status == "pass")
        warn_count = sum(1 for r in self.results if r.status == "warn")
        fail_count = sum(1 for r in self.results if r.status == "fail")
        
        return pass_count, warn_count, fail_count
