"""Pure OBS recording session policy (WebSocket vs CLI fallback).

ADR-002: connection failures may fall back to CLI control; authentication and
active-recording conflicts must not silently switch paths.
"""

from __future__ import annotations


class OBSActiveRecordingError(ConnectionError):
    """Raised when OBS appears to be recording and recovery must not attach."""


class OBSAuthenticationError(ConnectionError):
    """Raised when OBS WebSocket rejects the configured password."""


def should_fallback_websocket_to_cli(exc: BaseException) -> bool:
    """Return True when a WebSocket failure should trigger CLI fallback."""
    if isinstance(exc, OBSActiveRecordingError | OBSAuthenticationError):
        return False
    return isinstance(exc, ConnectionError)
