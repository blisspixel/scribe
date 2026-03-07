"""
Run context management for observability and tracing.

Provides unique run IDs, context tracking, and structured metadata
for every Scribe operation. Essential for debugging, support, and
understanding system behavior in production.

Architecture:
    - Thread-local storage for run context
    - Automatic run ID generation (timestamp + random)
    - Context propagation across function calls
    - Structured metadata collection
    - Integration with logging system

Example:
    with RunContext.create("transcribe") as ctx:
        ctx.add_metadata("file", "meeting.mp4")
        ctx.add_metadata("method", "local")
        # ... do work ...
        ctx.mark_success()
"""

import contextvars
import os
import sys
import threading
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Optional

from scribe.utils.logging import get_logger

logger = get_logger(__name__)

# Context variable for async/await support (Python 3.7+)
# This works with both threading and asyncio
_context_var: contextvars.ContextVar[Optional["RunContext"]] = contextvars.ContextVar(
    "run_context",
    default=None
)


def _generate_run_id() -> str:
    """
    Generate a unique run ID.

    Format: YYYYMMDD_HHMMSS_<short-uuid>
    Example: 20251112_143022_a3f9

    The timestamp prefix makes IDs sortable and human-readable,
    while the UUID suffix ensures uniqueness even for concurrent runs.

    Returns:
        Unique run ID string
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    short_uuid = str(uuid.uuid4())[:8]
    return f"{timestamp}_{short_uuid}"


@dataclass
class RunContext:
    """
    Context for a single Scribe operation run.

    Tracks metadata, timing, and status for observability.
    Automatically captures system information and provides
    structured data for logging and debugging.

    Attributes:
        run_id: Unique identifier for this run
        operation: Operation type (e.g., "transcribe", "record")
        start_time: When the operation started
        end_time: When the operation completed (None if still running)
        success: Whether the operation succeeded (None if still running)
        error_message: Error message if operation failed
        metadata: Additional structured data about the run
        parent_run_id: ID of parent run if this is a sub-operation
    """

    run_id: str
    operation: str
    start_time: datetime
    end_time: datetime | None = None
    success: bool | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    parent_run_id: str | None = None

    def __post_init__(self):
        """Capture system information on initialization."""
        self.metadata["python_version"] = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        self.metadata["platform"] = sys.platform
        self.metadata["pid"] = os.getpid()

    @classmethod
    def create(cls, operation: str, parent_run_id: str | None = None) -> "RunContext":
        """
        Create a new run context.

        Args:
            operation: Operation type (e.g., "transcribe", "record")
            parent_run_id: Optional parent run ID for nested operations

        Returns:
            New RunContext instance
        """
        run_id = _generate_run_id()

        logger.info(
            f"Starting run: {run_id}",
            extra={
                "run_id": run_id,
                "operation": operation,
                "parent_run_id": parent_run_id
            }
        )

        return cls(
            run_id=run_id,
            operation=operation,
            start_time=datetime.now(),
            parent_run_id=parent_run_id
        )

    def add_metadata(self, key: str, value: Any) -> None:
        """
        Add metadata to the run context.

        Metadata is structured data that provides context about the run.
        Examples: file paths, model names, configuration values.

        Args:
            key: Metadata key
            value: Metadata value (must be JSON-serializable)
        """
        self.metadata[key] = value

        logger.debug(
            f"Run metadata: {key}={value}",
            extra={"run_id": self.run_id, "metadata_key": key}
        )

    def mark_success(self) -> None:
        """Mark the run as successful and record end time."""
        self.end_time = datetime.now()
        self.success = True

        duration = (self.end_time - self.start_time).total_seconds()

        logger.info(
            f"Run completed successfully: {self.run_id} ({duration:.2f}s)",
            extra={
                "run_id": self.run_id,
                "operation": self.operation,
                "duration_seconds": duration,
                "success": True
            }
        )

    def mark_failure(self, error_message: str) -> None:
        """
        Mark the run as failed and record error.

        Args:
            error_message: Description of the failure
        """
        self.end_time = datetime.now()
        self.success = False
        self.error_message = error_message

        duration = (self.end_time - self.start_time).total_seconds()

        logger.error(
            f"Run failed: {self.run_id} - {error_message}",
            extra={
                "run_id": self.run_id,
                "operation": self.operation,
                "duration_seconds": duration,
                "success": False,
                "error_message": error_message
            }
        )

    def get_duration(self) -> float | None:
        """
        Get run duration in seconds.

        Returns:
            Duration in seconds, or None if run hasn't ended
        """
        if self.end_time is None:
            return None

        return (self.end_time - self.start_time).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        """
        Convert context to dictionary for serialization.

        Returns:
            Dictionary representation with ISO timestamps
        """
        data = asdict(self)

        # Convert datetime objects to ISO format
        data["start_time"] = self.start_time.isoformat()
        if self.end_time:
            data["end_time"] = self.end_time.isoformat()
            data["duration_seconds"] = self.get_duration()

        return data

    @classmethod
    def get_current(cls) -> Optional["RunContext"]:
        """
        Get the current run context.

        Uses contextvars for async/await compatibility.
        Works with both threading and asyncio.

        Returns:
            Current RunContext, or None if no context is active
        """
        return _context_var.get()

    @classmethod
    def set_current(cls, context: Optional["RunContext"]) -> None:
        """
        Set the current run context.

        Uses contextvars for async/await compatibility.
        Works with both threading and asyncio.

        Args:
            context: RunContext to set as current, or None to clear
        """
        _context_var.set(context)

    def __enter__(self) -> "RunContext":
        """
        Enter context manager - set as current context.

        Returns:
            Self for use in with statement
        """
        # Store previous context for nesting support
        self._previous_context = self.get_current()
        self.set_current(self)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Exit context manager - mark success/failure and restore previous context.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred
        """
        if exc_type is not None:
            # Exception occurred - mark as failure
            error_msg = f"{exc_type.__name__}: {exc_val}"
            self.mark_failure(error_msg)
        elif self.success is None:
            # No exception and not explicitly marked - assume success
            self.mark_success()

        # Add to global history
        _run_history.add(self)

        # Restore previous context (for nested contexts)
        self.set_current(self._previous_context)


def get_current_run_id() -> str | None:
    """
    Get the current run ID from active context.

    Convenience function for accessing run ID without full context.

    Returns:
        Current run ID, or None if no context is active
    """
    context = RunContext.get_current()
    return context.run_id if context else None


def add_run_metadata(key: str, value: Any) -> None:
    """
    Add metadata to the current run context.

    Convenience function for adding metadata without accessing context directly.
    No-op if no context is active.

    Args:
        key: Metadata key
        value: Metadata value
    """
    context = RunContext.get_current()
    if context:
        context.add_metadata(key, value)


@contextmanager
def nested_operation(operation: str):
    """
    Create a nested operation within the current run.

    Useful for tracking sub-operations (e.g., "convert" within "transcribe").
    Automatically links to parent run via parent_run_id.

    Args:
        operation: Sub-operation name

    Yields:
        RunContext for the nested operation
    """
    parent_context = RunContext.get_current()
    parent_run_id = parent_context.run_id if parent_context else None

    with RunContext.create(operation, parent_run_id=parent_run_id) as ctx:
        yield ctx


class RunHistory:
    """
    Maintains history of recent runs for debugging and support.

    Stores run contexts in memory with a configurable limit.
    Useful for generating support bundles and debugging issues.

    Thread-safe for concurrent access.
    """

    def __init__(self, max_size: int = 100):
        """
        Initialize run history.

        Args:
            max_size: Maximum number of runs to keep in history
        """
        self.max_size = max_size
        self.runs: list[RunContext] = []
        self._lock = threading.Lock()

    def add(self, context: RunContext) -> None:
        """
        Add a run context to history.

        Args:
            context: RunContext to add
        """
        with self._lock:
            self.runs.append(context)

            # Trim to max size (FIFO)
            if len(self.runs) > self.max_size:
                self.runs = self.runs[-self.max_size:]

    def get_recent(self, count: int = 10) -> list[RunContext]:
        """
        Get most recent runs.

        Args:
            count: Number of recent runs to return

        Returns:
            List of recent RunContext objects (newest first)
        """
        with self._lock:
            return list(reversed(self.runs[-count:]))

    def get_by_id(self, run_id: str) -> RunContext | None:
        """
        Get a specific run by ID.

        Args:
            run_id: Run ID to search for

        Returns:
            RunContext if found, None otherwise
        """
        with self._lock:
            for run in reversed(self.runs):
                if run.run_id == run_id:
                    return run
            return None

    def get_failed_runs(self, count: int = 10) -> list[RunContext]:
        """
        Get recent failed runs.

        Args:
            count: Maximum number of failed runs to return

        Returns:
            List of failed RunContext objects (newest first)
        """
        with self._lock:
            failed = [r for r in self.runs if r.success is False]
            return list(reversed(failed[-count:]))

    def clear(self) -> None:
        """Clear all run history."""
        with self._lock:
            self.runs.clear()


# Global run history instance
_run_history = RunHistory(max_size=100)


def get_run_history() -> RunHistory:
    """
    Get the global run history instance.

    Returns:
        Global RunHistory instance
    """
    return _run_history
