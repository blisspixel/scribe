"""
Support bundle generation for troubleshooting and debugging.

Creates a comprehensive diagnostic package containing:
- System information (OS, Python, hardware)
- Environment configuration
- Recent durable session summaries
- Diagnostic results
- Recent log metadata without filenames or contents

The bundle is exported as a JSON file that can be shared with
support or used for debugging issues.

Example:
    bundle = create_support_bundle()
    save_support_bundle(bundle, Path("support_bundle.json"))
"""

import hashlib
import json
import os
import platform
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scribe import __version__
from scribe.models.config import ScribeConfig
from scribe.utils.diagnostics import SystemDiagnostics
from scribe.utils.logging import get_logger

logger = get_logger(__name__)

try:
    _HOME_PATH: Path | None = Path.home()
except (OSError, RuntimeError):
    _HOME_PATH = None

_MAX_SUMMARY_BYTES = 1_000_000
_MAX_DIRECTORY_ENTRIES = 5_000
_MAX_DISCOVERED_FILES = 1_000
_MAX_RECENT_RUNS = 100
_MAX_RECENT_LOGS = 20
_SENSITIVE_KEY_SUFFIXES = (
    "_api_key",
    "_auth",
    "_auth_header",
    "_authorization",
    "_credential",
    "_password",
    "_secret",
    "_token",
)
_AUTHORIZATION_PATTERN = re.compile(
    r"(?i)(\bAuthorization\s*[:=]\s*)"
    r"(?:(?:Basic|Bearer|Digest|Token|ApiKey)\s+)?[^\s,;\"']+"
)
_QUOTED_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|authorization|token|password|secret|credential)"
    r"(\s*[:=]\s*)([\"'])[^\"']*\3"
)
_INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|authorization|token|password|secret|credential)"
    r"(\s*[:=]\s*)([^\s,;\"']+)"
)
_COMMON_CREDENTIAL_PATTERN = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{6,}|ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})\b"
)


def _redact_user(text: str) -> str:
    """Replace the home directory and username in a path-bearing string.

    The support bundle is meant to be shared, and PATH/cwd/home routinely embed the
    account username (and sometimes host details). This keeps the structure useful
    for diagnosis while removing the personally-identifying parts.
    """
    if not text:
        return text
    home = str(_HOME_PATH) if _HOME_PATH is not None else ""
    user = _HOME_PATH.name if _HOME_PATH is not None else ""
    if home:
        text = re.sub(re.escape(home), "~", text, flags=re.IGNORECASE)
    if user:
        text = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(user)}(?![A-Za-z0-9_])",
            "<user>",
            text,
            flags=re.IGNORECASE,
        )
    return text


def _is_sensitive_key(key: str) -> bool:
    """Return whether a mapping key conventionally contains a credential value."""
    snake_case = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key)
    normalized = re.sub(r"[^a-z0-9]+", "_", snake_case.lower()).strip("_")
    return normalized in {
        "api_key",
        "auth",
        "auth_header",
        "authorization",
        "credential",
        "password",
        "secret",
        "token",
    } or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)


def _redact_sensitive_text(text: str) -> str:
    """Redact local identity and common credential forms from diagnostic text."""
    redacted = _redact_user(text)

    for key, value in os.environ.items():
        if _is_sensitive_key(key) and value and len(value) >= 4:
            redacted = redacted.replace(value, "[REDACTED]")

    redacted = _AUTHORIZATION_PATTERN.sub(r"\1[REDACTED]", redacted)
    redacted = _QUOTED_SECRET_PATTERN.sub(r"\1\2[REDACTED]", redacted)
    redacted = _INLINE_SECRET_PATTERN.sub(r"\1\2[REDACTED]", redacted)
    return _COMMON_CREDENTIAL_PATTERN.sub("[REDACTED]", redacted)


def _sanitize_for_sharing(value: Any) -> Any:
    """Recursively sanitize every string before it reaches a support bundle."""
    if isinstance(value, Path):
        return _redact_sensitive_text(str(value))
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    if isinstance(value, dict):
        sanitized: dict[Any, Any] = {}
        for key, item in value.items():
            sanitized_key = _redact_sensitive_text(key) if isinstance(key, str) else key
            safe_status = item is None or (
                isinstance(item, str) and item in {"[CONFIGURED]", "[NOT CONFIGURED]"}
            )
            if isinstance(key, str) and _is_sensitive_key(key) and not safe_status:
                sanitized[sanitized_key] = "[REDACTED]"
            else:
                sanitized[sanitized_key] = _sanitize_for_sharing(item)
        return sanitized
    if isinstance(value, list | tuple | set):
        return [_sanitize_for_sharing(item) for item in value]
    return value


def _configured_directory(attribute: str) -> Path | None:
    """Resolve a configured local directory without failing bundle generation."""
    try:
        return Path(getattr(ScribeConfig(), attribute))
    except (OSError, TypeError, ValueError) as error:
        logger.warning(
            "Could not resolve configured %s for support bundle: %s",
            attribute,
            type(error).__name__,
        )
        return None


def _discover_local_files(
    directory: Path | None, pattern: str
) -> tuple[list[tuple[float, int, Path]], int, bool]:
    """Discover bounded, regular, non-symlinked files in one local directory."""
    if directory is None:
        return [], 0, False
    try:
        if not directory.is_dir():
            return [], 0, False
    except OSError:
        return [], 0, False

    discovered: list[tuple[float, int, Path]] = []
    skipped = 0
    truncated = False
    try:
        for entry_number, path in enumerate(directory.iterdir(), start=1):
            if entry_number > _MAX_DIRECTORY_ENTRIES:
                truncated = True
                break
            if not path.match(pattern):
                continue
            if len(discovered) >= _MAX_DISCOVERED_FILES:
                truncated = True
                break
            try:
                if path.is_symlink() or not path.is_file():
                    skipped += 1
                    continue
                metadata = path.stat()
            except OSError:
                skipped += 1
                continue
            discovered.append((metadata.st_mtime, metadata.st_size, path))
    except OSError as error:
        logger.warning(
            "Could not inspect %s for support evidence: %s", directory, type(error).__name__
        )
        return [], skipped, truncated

    discovered.sort(key=lambda item: item[0], reverse=True)
    return discovered, skipped, truncated


def _opaque_id(value: str, prefix: str) -> str:
    """Create a stable correlation ID without exposing a local name or path."""
    digest = hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def _read_bounded_regular_file(path: Path, max_bytes: int) -> str:
    """Read one stable regular file descriptor without following a symlink."""
    before = os.lstat(path)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError("Support evidence must be a regular non-symlink file")

    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        after = os.lstat(path)
        before_id = (before.st_dev, before.st_ino)
        opened_id = (opened.st_dev, opened.st_ino)
        after_id = (after.st_dev, after.st_ino)
        if (
            stat.S_ISLNK(after.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or before_id != opened_id
            or opened_id != after_id
        ):
            raise ValueError("Support evidence changed during inspection")
        if opened.st_size > max_bytes:
            raise ValueError("Support evidence exceeds the size limit")

        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise ValueError("Support evidence exceeds the size limit")
        return payload.decode("utf-8")
    finally:
        os.close(descriptor)


def _redact_session_error(value: Any) -> str | None:
    """Keep useful failure text while removing path tails from shareable sessions."""
    if value is None:
        return None
    text = str(value)
    path_starts = [r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/]", r"(?<![A-Za-z0-9])~[\\/]"]
    if _HOME_PATH is not None:
        path_starts.append(re.escape(str(_HOME_PATH)))
    path_starts.extend((r"(?<![A-Za-z0-9])/(?:home|Users|tmp|var/tmp)/",))

    earliest: int | None = None
    for pattern in path_starts:
        match = re.search(pattern, text)
        if match is not None and (earliest is None or match.start() < earliest):
            earliest = match.start()
    if earliest is not None:
        text = f"{text[:earliest].rstrip()} [LOCAL_PATH]".strip()
    return _redact_sensitive_text(text)


def _utc_timestamp(value: float) -> str | None:
    """Convert file metadata without allowing an invalid timestamp to abort the bundle."""
    try:
        return datetime.fromtimestamp(value, tz=UTC).isoformat()
    except (OSError, OverflowError, ValueError):
        return None


def _shareable_session_record(data: dict[str, Any]) -> dict[str, Any]:
    """Reduce a local session summary to privacy-preserving diagnostic fields."""
    raw_session_id = str(data.get("session_id") or "unknown")
    if re.fullmatch(r"session_[0-9]{8}_[0-9]{6}_[a-f0-9]{8}", raw_session_id):
        session_id = raw_session_id
    else:
        session_id = _opaque_id(raw_session_id, "legacy_session")

    artifact_fields = {
        "audio": data.get("audio_file"),
        "document": data.get("docx_file"),
        "meme": data.get("meme_file"),
        "source": data.get("source_file"),
        "transcript": data.get("transcript_file"),
    }
    artifact_types = sorted(name for name, value in artifact_fields.items() if value)
    log_file = data.get("log_file")
    record: dict[str, Any] = {
        "session_id": session_id,
        "start_time": data.get("start_time"),
        "end_time": data.get("end_time"),
        "success": data.get("success"),
        "error_message": _redact_session_error(data.get("error_message")),
        "duration_seconds": data.get("duration_seconds"),
        "transcription_method": data.get("transcription_method"),
        "model_used": data.get("model_used"),
        "artifact_types": artifact_types,
        "files_created_count": len(data.get("files_created") or []),
        "files_cleaned_count": len(data.get("files_cleaned") or []),
        "log_id": _opaque_id(Path(str(log_file)).name, "log") if log_file else None,
    }
    sanitized = _sanitize_for_sharing(record)
    if not isinstance(sanitized, dict):
        raise TypeError("Sanitized session record must remain a dictionary")
    return sanitized


def get_system_info() -> dict[str, Any]:
    """
    Collect comprehensive system information.

    Returns:
        Dictionary with system details
    """
    info: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "scribe_version": __version__,
        "python": {
            "version": sys.version,
            "version_info": {
                "major": sys.version_info.major,
                "minor": sys.version_info.minor,
                "micro": sys.version_info.micro,
            },
            "executable": _redact_user(sys.executable),
            "platform": sys.platform,
        },
        "os": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "architecture": platform.architecture()[0],
        },
        "environment": {
            "cwd": _redact_user(os.getcwd()),
            "home": _redact_user(str(_HOME_PATH) if _HOME_PATH is not None else ""),
            "path": _redact_user(os.environ.get("PATH", "")),
            "pythonpath": _redact_user(os.environ.get("PYTHONPATH", "")),
        },
    }

    # Add GPU info if available
    try:
        import torch

        gpu_info: dict[str, Any] = {
            "cuda_available": torch.cuda.is_available(),
            "cuda_version": torch.version.cuda if torch.cuda.is_available() else None,
            "device_count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        }
        info["gpu"] = gpu_info

        if torch.cuda.is_available():
            devices: list[dict[str, Any]] = []
            gpu_info["devices"] = devices
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                devices.append(
                    {
                        "name": torch.cuda.get_device_name(i),
                        "total_memory_gb": props.total_memory / (1024**3),
                        "compute_capability": f"{props.major}.{props.minor}",
                    }
                )
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
    config: dict[str, Any] = {}

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
        "SCRIBE_NOTES_MODEL",
    ]

    for var in scribe_vars:
        value = os.getenv(var)
        if value is not None:
            config[var] = _redact_sensitive_text(value)

    # API key status (sanitized)
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("SCRIBE_OPENAI_API_KEY")
    if api_key:
        config["OPENAI_API_KEY"] = "[CONFIGURED]"
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
    # Skip the live API-key network checks so generating a bundle never spends an
    # API round trip or hangs offline.
    results = diagnostics.run_all_checks(live=False)

    # Convert to serializable format
    return {
        "summary": {
            "pass": sum(1 for r in results if r.status == "pass"),
            "warn": sum(1 for r in results if r.status == "warn"),
            "fail": sum(1 for r in results if r.status == "fail"),
        },
        "checks": [
            {
                "name": r.name,
                "status": r.status,
                "message": r.message,
                "details": r.details,
                "fix_suggestion": r.fix_suggestion,
            }
            for r in results
        ],
    }


def get_run_history_summary(max_runs: int = 20, output_dir: Path | None = None) -> dict[str, Any]:
    """
    Get a privacy-preserving summary of durable recent sessions.

    Args:
        max_runs: Maximum number of valid summaries to include
        output_dir: Optional explicit summary directory for testing or embedding

    Returns:
        Dictionary with run history
    """
    limit = max(0, min(int(max_runs), _MAX_RECENT_RUNS))
    source_dir = (
        Path(output_dir) if output_dir is not None else _configured_directory("output_folder")
    )
    candidates, skipped, truncated = _discover_local_files(source_dir, "*_session_summary.json")

    recent: list[dict[str, Any]] = []
    for _, size_bytes, path in candidates:
        if len(recent) >= limit:
            break
        if size_bytes > _MAX_SUMMARY_BYTES:
            skipped += 1
            continue
        try:
            data = json.loads(_read_bounded_regular_file(path, _MAX_SUMMARY_BYTES))
            if not isinstance(data, dict):
                raise TypeError("Session summary root must be an object")
            recent.append(_shareable_session_record(data))
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
            skipped += 1

    failed = [run for run in recent if run.get("success") is False][:10]
    return {
        "source": "durable_session_summaries",
        "total_runs": len(candidates),
        "recent_runs": recent,
        "failed_runs": failed,
        "skipped_count": skipped,
        "discovery_truncated": truncated,
        "summary": {
            "total": len(candidates),
            "recent_count": len(recent),
            "failed_count": len(failed),
        },
    }


def get_recent_log_metadata(max_logs: int = 5, log_dir: Path | None = None) -> dict[str, Any]:
    """Return bounded, opaque metadata for recent logs without reading their contents."""
    limit = max(0, min(int(max_logs), _MAX_RECENT_LOGS))
    source_dir = Path(log_dir) if log_dir is not None else _configured_directory("log_folder")
    candidates, skipped, truncated = _discover_local_files(source_dir, "scribe_*.log")
    files = [
        {
            "log_id": _opaque_id(path.name, "log"),
            "size_bytes": size_bytes,
            "modified_at": _utc_timestamp(modified_at),
        }
        for modified_at, size_bytes, path in candidates[:limit]
    ]
    return {
        "total_files": len(candidates),
        "listed_count": len(files),
        "skipped_count": skipped,
        "discovery_truncated": truncated,
        "contents_included": False,
        "files": files,
    }


def create_support_bundle(include_run_history: bool = True, max_runs: int = 20) -> dict[str, Any]:
    """
    Create a comprehensive support bundle.

    Args:
        include_run_history: Whether to include run history
        max_runs: Maximum number of runs to include in history

    Returns:
        Dictionary containing all support information
    """
    logger.info("Creating support bundle...")

    bundle: dict[str, Any] = {
        "bundle_version": "2.0",
        "created_at": datetime.now().isoformat(),
        "privacy": {
            "review_before_sharing": True,
            "home_and_account_identifiers_redacted": True,
            "known_credential_patterns_redacted": True,
            "structured_session_paths_and_names_included": False,
            "redacted_error_messages_included": True,
            "log_filenames_included": False,
            "log_contents_included": False,
        },
        "system_info": get_system_info(),
        "environment_config": get_environment_config(),
        "diagnostics": get_diagnostics_results(),
        "recent_logs": get_recent_log_metadata(),
    }

    if include_run_history:
        bundle["run_history"] = get_run_history_summary(max_runs=max_runs)

    sanitized = _sanitize_for_sharing(bundle)
    if not isinstance(sanitized, dict):
        raise TypeError("Sanitized support bundle must remain a dictionary")
    logger.info("Support bundle created successfully")
    return sanitized


def save_support_bundle(bundle: dict[str, Any], output_path: Path, pretty: bool = True) -> Path:
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

    sanitized = _sanitize_for_sharing(bundle)
    if not isinstance(sanitized, dict):
        raise TypeError("Sanitized support bundle must remain a dictionary")

    # Use atomic write for safety
    if pretty:
        content = json.dumps(sanitized, indent=2, ensure_ascii=False)
        from scribe.utils.safe_write import atomic_write

        atomic_write(output_path, content, encoding="utf-8")
    else:
        atomic_write_json(output_path, sanitized)

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
