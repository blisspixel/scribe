"""Pure OBS recording session policy (WebSocket vs CLI fallback).

ADR-002: connection failures may fall back to CLI control; authentication and
active-recording conflicts must not silently switch paths.

Lifecycle phases and duration limits are modeled here so recorder I/O stays
thin and Hypothesis can verify transitions without OBS installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import deal


class OBSActiveRecordingError(ConnectionError):
    """Raised when OBS appears to be recording and recovery must not attach."""


class OBSAuthenticationError(ConnectionError):
    """Raised when OBS WebSocket rejects the configured password."""


def should_fallback_websocket_to_cli(exc: BaseException) -> bool:
    """Return True when a WebSocket failure should trigger CLI fallback."""
    if isinstance(exc, OBSActiveRecordingError | OBSAuthenticationError):
        return False
    return isinstance(exc, ConnectionError)


class RecordingPhase(StrEnum):
    """High-level OBS recording session phases."""

    IDLE = "idle"
    CONNECTING = "connecting"
    RECORDING = "recording"
    AWAITING_MEDIA = "awaiting_media"
    FINALIZING = "finalizing"
    COMPLETE = "complete"
    FAILED = "failed"


class RecordingEvent(StrEnum):
    """Events that advance the recording session."""

    BEGIN = "begin"
    CONNECT_OK = "connect_ok"
    CONNECT_AUTH_FAIL = "connect_auth_fail"
    CONNECT_BUSY = "connect_busy"
    USE_CLI_FALLBACK = "use_cli_fallback"
    STOP_REQUESTED = "stop_requested"
    MEDIA_FOUND = "media_found"
    MEDIA_MISSING = "media_missing"
    FINALIZED = "finalized"
    CANCEL = "cancel"


_TERMINAL_PHASES = frozenset({RecordingPhase.COMPLETE, RecordingPhase.FAILED})

_TRANSITIONS: dict[tuple[RecordingPhase, RecordingEvent], RecordingPhase] = {
    (RecordingPhase.IDLE, RecordingEvent.BEGIN): RecordingPhase.CONNECTING,
    (RecordingPhase.CONNECTING, RecordingEvent.CONNECT_OK): RecordingPhase.RECORDING,
    (RecordingPhase.CONNECTING, RecordingEvent.CONNECT_AUTH_FAIL): RecordingPhase.FAILED,
    (RecordingPhase.CONNECTING, RecordingEvent.CONNECT_BUSY): RecordingPhase.FAILED,
    (RecordingPhase.CONNECTING, RecordingEvent.USE_CLI_FALLBACK): RecordingPhase.RECORDING,
    (RecordingPhase.RECORDING, RecordingEvent.STOP_REQUESTED): RecordingPhase.AWAITING_MEDIA,
    (RecordingPhase.AWAITING_MEDIA, RecordingEvent.MEDIA_FOUND): RecordingPhase.FINALIZING,
    (RecordingPhase.AWAITING_MEDIA, RecordingEvent.MEDIA_MISSING): RecordingPhase.FAILED,
    (RecordingPhase.FINALIZING, RecordingEvent.FINALIZED): RecordingPhase.COMPLETE,
}


def is_terminal_recording_phase(phase: RecordingPhase) -> bool:
    """Return True when the session cannot advance further."""
    return phase in _TERMINAL_PHASES


def allowed_recording_events(phase: RecordingPhase) -> frozenset[RecordingEvent]:
    """Return events legal from ``phase``, including cancel on non-terminal phases."""
    allowed = {event for (from_phase, event) in _TRANSITIONS if from_phase == phase}
    if not is_terminal_recording_phase(phase):
        allowed.add(RecordingEvent.CANCEL)
    return frozenset(allowed)


def advance_recording_phase(phase: RecordingPhase, event: RecordingEvent) -> RecordingPhase:
    """Apply ``event`` and return the next phase.

    Raises:
        ValueError: When ``event`` is not valid for ``phase``.
    """
    if event == RecordingEvent.CANCEL and not is_terminal_recording_phase(phase):
        return RecordingPhase.FAILED
    try:
        return _TRANSITIONS[(phase, event)]
    except KeyError as exc:
        raise ValueError(f"invalid recording transition: {phase} + {event}") from exc


@deal.post(lambda result: result >= 0.0)
def recording_limit_seconds(max_hours: float) -> float:
    """Return the hard auto-stop limit in seconds."""
    return max(0.0, float(max_hours) * 3600.0)


@deal.pre(lambda _max_hours, warning_fraction: warning_fraction > 0)
@deal.post(lambda result: result >= 0.0)
def recording_warning_seconds(max_hours: float, warning_fraction: float) -> float:
    """Return the near-limit warning threshold in seconds."""
    limit_seconds = recording_limit_seconds(max_hours)
    fraction = min(1.0, max(0.1, float(warning_fraction)))
    return limit_seconds * fraction


@deal.post(lambda result: isinstance(result, str) and bool(result))
def format_recording_elapsed(elapsed_seconds: float) -> str:
    """Format elapsed seconds for recorder warnings."""
    total_seconds = max(0, int(elapsed_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


@dataclass(frozen=True)
class RecordingDurationStep:
    """Pure outcome of one duration-limit polling step."""

    warning_issued: bool
    auto_stop_announced: bool
    should_stop: bool
    emit_warning: bool
    emit_auto_stop: bool


@deal.pre(lambda elapsed_seconds, **_kwargs: elapsed_seconds >= 0.0)
def step_recording_duration_limit(
    elapsed_seconds: float,
    *,
    max_hours: float,
    warning_fraction: float,
    warning_issued: bool,
    auto_stop_announced: bool,
) -> RecordingDurationStep:
    """Compute the next duration-limit flags without side effects."""
    warning_seconds = recording_warning_seconds(max_hours, warning_fraction)
    limit_seconds = recording_limit_seconds(max_hours)

    emit_warning = (
        not warning_issued
        and warning_seconds > 0
        and elapsed_seconds >= warning_seconds
        and elapsed_seconds < limit_seconds
    )
    emit_auto_stop = (
        not auto_stop_announced and limit_seconds > 0 and elapsed_seconds >= limit_seconds
    )

    return RecordingDurationStep(
        warning_issued=warning_issued or emit_warning,
        auto_stop_announced=auto_stop_announced or emit_auto_stop,
        should_stop=emit_auto_stop,
        emit_warning=emit_warning,
        emit_auto_stop=emit_auto_stop,
    )


@dataclass
class RecordingSessionTracker:
    """Mutable lifecycle tracker for OBS recording orchestration."""

    phase: RecordingPhase = field(default=RecordingPhase.IDLE)

    def advance(self, event: RecordingEvent) -> RecordingPhase:
        """Advance session phase; invalid transitions propagate as ValueError."""
        self.phase = advance_recording_phase(self.phase, event)
        return self.phase


@deal.post(lambda result: len(result) >= 1)
def recording_media_candidate_dirs(
    primary_dir: str | Path,
    *,
    home: Path | None = None,
    temp_obs_dir: Path | None = None,
) -> tuple[Path, ...]:
    """Ordered, deduplicated directories to search for fresh OBS media."""
    home = home or Path.home()
    from scribe.paths import videos_dir

    candidates = [
        Path(primary_dir),
        videos_dir(home),
        videos_dir(home) / "OBS",
        home / "Videos",
        home / "Videos" / "OBS",
    ]
    if temp_obs_dir is not None:
        candidates.append(temp_obs_dir)

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return tuple(unique)


@deal.pre(lambda attempt, **_kwargs: attempt >= 0)
@deal.post(lambda result: result > 0.0)
def media_discovery_poll_interval(
    attempt: int,
    *,
    base: float = 0.5,
    max_interval: float = 2.0,
) -> float:
    """Adaptive delay between recording file discovery polls."""
    return min(max_interval, base * (1.25 ** min(attempt, 10)))


@dataclass(frozen=True)
class RecordingFileStability:
    """Pure assessment of whether a recording file has stabilized."""

    ready: bool
    reason: str


def assess_recording_file_stability(
    current_size: int,
    previous_size: int | None,
    *,
    min_bytes: int = 4096,
) -> RecordingFileStability:
    """Return whether a media file is large enough and no longer growing."""
    if current_size < min_bytes:
        return RecordingFileStability(False, "below_min_bytes")
    if previous_size is None:
        return RecordingFileStability(False, "awaiting_second_sample")
    if current_size == previous_size:
        return RecordingFileStability(True, "stable")
    return RecordingFileStability(False, "still_growing")
