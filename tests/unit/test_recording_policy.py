"""Tests for OBS WebSocket vs CLI fallback policy (ADR-002)."""

import pytest

from scribe.core.recording_policy import (
    OBSActiveRecordingError,
    OBSAuthenticationError,
    should_fallback_websocket_to_cli,
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
            should_fallback_websocket_to_cli(
                OBSActiveRecordingError("OBS is already recording")
            )
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
