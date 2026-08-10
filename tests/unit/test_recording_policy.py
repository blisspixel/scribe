"""Tests for OBS WebSocket vs CLI fallback policy (ADR-002)."""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from scribe.core.recording_policy import (
    OBSActiveRecordingError,
    OBSAuthenticationError,
    RecordingDurationStep,
    RecordingEvent,
    RecordingPhase,
    RecordingSessionTracker,
    advance_recording_phase,
    allowed_recording_events,
    assess_recording_file_stability,
    format_recording_elapsed,
    is_terminal_recording_phase,
    media_discovery_poll_interval,
    recording_limit_seconds,
    recording_media_candidate_dirs,
    recording_warning_seconds,
    should_fallback_websocket_to_cli,
    step_recording_duration_limit,
)


class TestShouldFallbackWebsocketToCli:
    """Pure policy for when WebSocket failures may fall back to CLI control."""

    def test_connection_error_allows_fallback(self) -> None:
        assert should_fallback_websocket_to_cli(ConnectionError("OBS unreachable")) is True

    def test_auth_error_blocks_fallback(self) -> None:
        assert (
            should_fallback_websocket_to_cli(
                OBSAuthenticationError("OBS rejected the configured password")
            )
            is False
        )

    def test_active_recording_blocks_fallback(self) -> None:
        assert (
            should_fallback_websocket_to_cli(OBSActiveRecordingError("OBS is already recording"))
            is False
        )

    def test_unrelated_errors_do_not_fallback(self) -> None:
        assert should_fallback_websocket_to_cli(ValueError("bad state")) is False
        assert should_fallback_websocket_to_cli(RuntimeError("unexpected")) is False

    def test_obs_errors_are_connection_errors(self) -> None:
        """Typed OBS failures remain ConnectionError subclasses for callers."""
        with pytest.raises(ConnectionError):
            raise OBSAuthenticationError("rejected")
        with pytest.raises(ConnectionError):
            raise OBSActiveRecordingError("busy")


class TestRecordingPhaseTransitions:
    """Lifecycle state machine for OBS recording sessions."""

    def test_happy_path_websocket(self) -> None:
        phase = RecordingPhase.IDLE
        phase = advance_recording_phase(phase, RecordingEvent.BEGIN)
        phase = advance_recording_phase(phase, RecordingEvent.CONNECT_OK)
        phase = advance_recording_phase(phase, RecordingEvent.STOP_REQUESTED)
        phase = advance_recording_phase(phase, RecordingEvent.MEDIA_FOUND)
        phase = advance_recording_phase(phase, RecordingEvent.FINALIZED)
        assert phase == RecordingPhase.COMPLETE
        assert is_terminal_recording_phase(phase)

    def test_cli_fallback_path(self) -> None:
        phase = advance_recording_phase(RecordingPhase.IDLE, RecordingEvent.BEGIN)
        phase = advance_recording_phase(phase, RecordingEvent.USE_CLI_FALLBACK)
        assert phase == RecordingPhase.RECORDING

    def test_auth_failure_is_terminal(self) -> None:
        phase = advance_recording_phase(RecordingPhase.IDLE, RecordingEvent.BEGIN)
        phase = advance_recording_phase(phase, RecordingEvent.CONNECT_AUTH_FAIL)
        assert phase == RecordingPhase.FAILED
        assert allowed_recording_events(phase) == frozenset()

    def test_cancel_from_recording(self) -> None:
        phase = advance_recording_phase(RecordingPhase.RECORDING, RecordingEvent.CANCEL)
        assert phase == RecordingPhase.FAILED

    def test_invalid_transition_raises(self) -> None:
        with pytest.raises(ValueError, match="invalid recording transition"):
            advance_recording_phase(RecordingPhase.IDLE, RecordingEvent.MEDIA_FOUND)


class TestAdaptiveMediaDiscovery:
    """Bulletproof file discovery policy for OBS recordings."""

    def test_candidate_dirs_deduplicate_and_include_fallbacks(self, tmp_path) -> None:
        home = tmp_path / "home"
        primary = home / "Videos" / "OBS"
        dirs = recording_media_candidate_dirs(primary, home=home)
        assert dirs[0] == primary
        assert home / "Videos" in dirs
        assert len(dirs) == len({Path(p) for p in dirs})

    def test_poll_interval_is_bounded(self) -> None:
        assert media_discovery_poll_interval(0) == 0.5
        assert media_discovery_poll_interval(100) <= 2.0

    def test_file_stability_requires_matching_sizes(self) -> None:
        first = assess_recording_file_stability(10_000, None, min_bytes=4096)
        assert not first.ready
        stable = assess_recording_file_stability(10_000, 10_000, min_bytes=4096)
        assert stable.ready
        growing = assess_recording_file_stability(20_000, 10_000, min_bytes=4096)
        assert not growing.ready


class TestRecordingSessionTracker:
    def test_tracker_advances_happy_path(self) -> None:
        tracker = RecordingSessionTracker()
        tracker.advance(RecordingEvent.BEGIN)
        tracker.advance(RecordingEvent.CONNECT_OK)
        tracker.advance(RecordingEvent.STOP_REQUESTED)
        assert tracker.phase == RecordingPhase.AWAITING_MEDIA


class TestRecordingDurationPolicy:
    """Pure duration cap and warning thresholds."""

    def test_limit_and_warning_seconds(self) -> None:
        assert recording_limit_seconds(1.0) == 3600.0
        assert recording_warning_seconds(1.0, 0.5) == 1800.0

    def test_format_elapsed_hours_and_minutes(self) -> None:
        assert format_recording_elapsed(0) == "0m"
        assert format_recording_elapsed(90) == "1m"
        assert format_recording_elapsed(3661) == "1h 1m"

    def test_warning_emitted_once_before_limit(self) -> None:
        step = step_recording_duration_limit(
            1800.0,
            max_hours=1.0,
            warning_fraction=0.5,
            warning_issued=False,
            auto_stop_announced=False,
        )
        assert step == RecordingDurationStep(
            warning_issued=True,
            auto_stop_announced=False,
            should_stop=False,
            emit_warning=True,
            emit_auto_stop=False,
        )
        repeat = step_recording_duration_limit(
            2000.0,
            max_hours=1.0,
            warning_fraction=0.5,
            warning_issued=step.warning_issued,
            auto_stop_announced=step.auto_stop_announced,
        )
        assert not repeat.emit_warning

    def test_auto_stop_at_limit(self) -> None:
        step = step_recording_duration_limit(
            3600.0,
            max_hours=1.0,
            warning_fraction=0.5,
            warning_issued=True,
            auto_stop_announced=False,
        )
        assert step.should_stop is True
        assert step.emit_auto_stop is True
        repeat = step_recording_duration_limit(
            4000.0,
            max_hours=1.0,
            warning_fraction=0.5,
            warning_issued=step.warning_issued,
            auto_stop_announced=step.auto_stop_announced,
        )
        assert not repeat.emit_auto_stop
        assert not repeat.should_stop

    @given(
        st.floats(min_value=0.0, max_value=1e6, allow_nan=False, allow_infinity=False),
        st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
        st.booleans(),
        st.booleans(),
    )
    def test_duration_step_flags_are_monotonic(
        self,
        elapsed: float,
        warning_fraction: float,
        warning_issued: bool,
        auto_stop_announced: bool,
    ) -> None:
        step = step_recording_duration_limit(
            elapsed,
            max_hours=1.0,
            warning_fraction=warning_fraction,
            warning_issued=warning_issued,
            auto_stop_announced=auto_stop_announced,
        )
        assert step.warning_issued >= warning_issued
        assert step.auto_stop_announced >= auto_stop_announced
        if step.emit_auto_stop:
            assert step.should_stop


class RecordingPhaseMachine(RuleBasedStateMachine):
    """Stateful exploration of recording lifecycle invariants."""

    def __init__(self) -> None:
        super().__init__()
        self.phase = RecordingPhase.IDLE

    def _apply(self, required: RecordingPhase, event: RecordingEvent) -> None:
        if self.phase != required:
            return
        self.phase = advance_recording_phase(self.phase, event)

    @rule()
    def begin(self) -> None:
        self._apply(RecordingPhase.IDLE, RecordingEvent.BEGIN)

    @rule()
    def connect_ok(self) -> None:
        self._apply(RecordingPhase.CONNECTING, RecordingEvent.CONNECT_OK)

    @rule()
    def use_cli_fallback(self) -> None:
        self._apply(RecordingPhase.CONNECTING, RecordingEvent.USE_CLI_FALLBACK)

    @rule()
    def connect_auth_fail(self) -> None:
        self._apply(RecordingPhase.CONNECTING, RecordingEvent.CONNECT_AUTH_FAIL)

    @rule()
    def connect_busy(self) -> None:
        self._apply(RecordingPhase.CONNECTING, RecordingEvent.CONNECT_BUSY)

    @rule()
    def stop_requested(self) -> None:
        self._apply(RecordingPhase.RECORDING, RecordingEvent.STOP_REQUESTED)

    @rule()
    def media_found(self) -> None:
        self._apply(RecordingPhase.AWAITING_MEDIA, RecordingEvent.MEDIA_FOUND)

    @rule()
    def media_missing(self) -> None:
        self._apply(RecordingPhase.AWAITING_MEDIA, RecordingEvent.MEDIA_MISSING)

    @rule()
    def finalized(self) -> None:
        self._apply(RecordingPhase.FINALIZING, RecordingEvent.FINALIZED)

    @rule()
    def cancel(self) -> None:
        if is_terminal_recording_phase(self.phase):
            return
        self.phase = advance_recording_phase(self.phase, RecordingEvent.CANCEL)

    @invariant()
    def phase_is_valid_enum(self) -> None:
        assert self.phase in RecordingPhase

    @invariant()
    def allowed_events_match_phase(self) -> None:
        for event in allowed_recording_events(self.phase):
            next_phase = advance_recording_phase(self.phase, event)
            assert next_phase in RecordingPhase


TestRecordingPhaseMachine = RecordingPhaseMachine.TestCase
