"""
Support bundle generation for troubleshooting and debugging.

Creates a comprehensive diagnostic package containing:
- System information (OS, Python, hardware)
- Environment configuration
- Recent run history
- Diagnostic results
- Log files (if available)

The bundle is exported as a JSON file that can be shared with
support or used for debugging issues.

Example:
    bundle = create_support_bundle()
    save_support_bundle(bundle, Path("support_bundle.json"))
"""

import json
import os
import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from scribe import __version__
from scribe.utils.diagnostics import SystemDiagnostics
from scribe.utils.logging import get_logger
from scribe.utils.run_context import get_run_history

logger = get_logger(__name__)


def get_system_info() -> dict[str, Any]:
    """
    Collect comprehensive system information.
    
    Returns:
        Dictionary with system details
    """
    info = {
        "timestamp": datetime.now().isoformat(),
        "scribe_version": __version__,
        "python": {
            "version": sys.version,
            "version_info": {
                "major": sys.version_info.major,
                "minor": sys.version_info.minor,
                "micro": sys.version_info.micro
            },
            "executable": sys.executable,
            "platform": sys.platform
        },
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "architecture": platform.architecture()[0]
        },
        "environment": {
            "cwd": os.getcwd(),
            "home": str(Path.home()),
            "path": os.environ.get("PATH", ""),
            "pythonpath": os.environ.get("PYTHONPATH", "")
        }
    }

    # Add GPU info if available
    try:
        import torch
        info["gpu"] = {
            "cuda_available": torch.cuda.is_available(),
            "cuda_version": torch.version.cuda if torch.cuda.is_available() else None,
            "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0
        }

        if torch.cuda.is_available():
            info["gpu"]["devices"] = []
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                info["gpu"]["devices"].append({
                    "name": torch.cuda.get_device_name(i),
                    "total_memory_gb": props.total_memory / (1024**3),
                    "compute_capability": f"{props.major}.{props.minor}"
                })
    except ImportError:
        info["gpu"] = {"available": False, "reason": "PyTorch not installed"}

    return info


def get_environment_config() -> dict[str, Any]:
    """
    Collect Scribe-specific environment configuration.
    
    Sanitizes sensitive values like API keys.
    
    Returns:
        Dictionary with configuration
    """
    config = {}

    # Scribe environment variables
    scribe_vars = [
        "SCRIBE_OUTPUT_FOLDER",
        "SCRIBE_DEFAULT_MODEL",
        "SCRIBE_DEFAULT_LANGUAGE",
        "SCRIBE_DEFAULT_METHOD",
        "SCRIBE_OBS_HOST",
        "SCRIBE_OBS_PORT",
        "SCRIBE_MEME_QA_THRESHOLD",
        "SCRIBE_MEME_QA_ATTEMPTS",
        "SCRIBE_HUMOR_SPICE",
        "SCRIBE_ENABLE_NOTES",
        "SCRIBE_NOTES_MODEL"
    ]

    for var in scribe_vars:
        value = os.getenv(var)
        if value is not None:
            config[var] = value

    # API key status (sanitized)
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("SCRIBE_OPENAI_API_KEY")
    if api_key:
        config["OPENAI_API_KEY"] = f"{api_key[:10]}...{api_key[-4:]}" if len(api_key) > 14 else "[REDACTED]"
    else:
        config["OPENAI_API_KEY"] = None

    return config


def get_diagnostics_results() -> dict[str, Any]:
    """
    Run system diagnostics and collect results.
    
    Returns:
        Dictionary with diagnostic results
    """
    diagnostics = SystemDiagnostics()
    results = diagnostics.run_all_checks()

    # Convert to serializable format
    return {
        "summary": {
            "pass": sum(1 for r in results if r.status == "pass"),
            "warn": sum(1 for r in results if r.status == "warn"),
            "fail": sum(1 for r in results if r.status == "fail")
        },
        "checks": [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "details": r.details,
                "fix_suggestion": r.fix_suggestion
            }
            for r in results
        ]
    }


def get_run_history_summary(max_runs: int = 20) -> dict[str, Any]:
    """
    Get summary of recent runs.
    
    Args:
        max_runs: Maximum number of runs to include
        
    Returns:
        Dictionary with run history
    """
    history = get_run_history()
    recent = history.get_recent(count=max_runs)
    failed = history.get_failed_runs(count=10)

    return {
        "total_runs": len(history.runs),
        "recent_runs": [r.to_dict() for r in recent],
        "failed_runs": [r.to_dict() for r in failed],
        "summary": {
            "total": len(history.runs),
            "recent_count": len(recent),
            "failed_count": len(failed)
        }
    }


def create_support_bundle(
    include_run_history: bool = True,
    max_runs: int = 20
) -> dict[str, Any]:
    """
    Create a comprehensive support bundle.
    
    Args:
        include_run_history: Whether to include run history
        max_runs: Maximum number of runs to include in history
        
    Returns:
        Dictionary containing all support information
    """
    logger.info("Creating support bundle...")

    bundle = {
        "bundle_version": "1.0",
        "created_at": datetime.now().isoformat(),
        "system_info": get_system_info(),
        "environment_config": get_environment_config(),
        "diagnostics": get_diagnostics_results()
    }

    if include_run_history:
        bundle["run_history"] = get_run_history_summary(max_runs=max_runs)

    logger.info("Support bundle created successfully")
    return bundle


def save_support_bundle(
    bundle: dict[str, Any],
    output_path: Path,
    pretty: bool = True
) -> Path:
    """
    Save support bundle to a JSON file.
    
    Args:
        bundle: Support bundle dictionary
        output_path: Path to save the bundle
        pretty: Whether to pretty-print JSON
        
    Returns:
        Path to saved bundle file
    """
    from scribe.utils.safe_write import atomic_write_json

    output_path = Path(output_path)

    # Use atomic write for safety
    if pretty:
        content = json.dumps(bundle, indent=2, ensure_ascii=False)
        from scribe.utils.safe_write import atomic_write
        atomic_write(output_path, content, encoding="utf-8")
    else:
        atomic_write_json(output_path, bundle, indent=None)

    logger.info(f"Support bundle saved to: {output_path}")
    return output_path


def generate_support_bundle_cli(output_dir: Path | None = None) -> Path:
    """
    Generate support bundle for CLI command.
    
    Args:
        output_dir: Directory to save bundle (defaults to current directory)
        
    Returns:
        Path to generated bundle file
    """
    if output_dir is None:
        output_dir = Path.cwd()

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"scribe_support_bundle_{timestamp}.json"
    output_path = output_dir / filename

    # Create and save bundle
    bundle = create_support_bundle()
    save_support_bundle(bundle, output_path)

    return output_path
