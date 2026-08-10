"""Process-wide API circuit breaker state for defensive cloud transcription.

ADR-002: repeated OpenAI failures should not hammer the API or burn quota in a
tight retry loop. State lives in-module so ``scribe doctor`` can surface it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from scribe.exceptions import CircuitBreakerOpen
from scribe.utils.resilience import (
    CircuitBreakerSnapshot,
    circuit_breaker_after_failure,
    circuit_breaker_after_success,
    circuit_breaker_allows_request,
)

_DEFAULT_FAILURE_THRESHOLD = 5
_DEFAULT_RECOVERY_TIMEOUT = 60.0
_snapshot = CircuitBreakerSnapshot()


@dataclass(frozen=True)
class ApiCircuitBreakerConfig:
    """Tunable breaker thresholds for an external API."""

    service_name: str = "openai"
    failure_threshold: int = _DEFAULT_FAILURE_THRESHOLD
    recovery_timeout_seconds: float = _DEFAULT_RECOVERY_TIMEOUT


def reset_api_circuit_breaker() -> None:
    """Reset breaker state (tests and support tooling)."""
    global _snapshot
    _snapshot = CircuitBreakerSnapshot()


def record_api_success() -> None:
    """Mark a successful API call; clears accumulated failures."""
    global _snapshot
    _snapshot = circuit_breaker_after_success(_snapshot)


def record_api_failure(
    *,
    now: float | None = None,
    config: ApiCircuitBreakerConfig | None = None,
) -> None:
    """Record a transient API failure and open the breaker at the threshold."""
    global _snapshot
    cfg = config or ApiCircuitBreakerConfig()
    _snapshot = circuit_breaker_after_failure(
        _snapshot,
        now=now if now is not None else time.time(),
        threshold=cfg.failure_threshold,
    )


def ensure_api_circuit_closed(
    *,
    now: float | None = None,
    config: ApiCircuitBreakerConfig | None = None,
) -> None:
    """Raise ``CircuitBreakerOpen`` when the breaker is still cooling down."""
    cfg = config or ApiCircuitBreakerConfig()
    current = now if now is not None else time.time()
    if circuit_breaker_allows_request(
        _snapshot,
        now=current,
        recovery_timeout=cfg.recovery_timeout_seconds,
    ):
        return
    raise CircuitBreakerOpen(
        f"Too many {cfg.service_name} API failures; circuit open for "
        f"{cfg.recovery_timeout_seconds:.0f}s",
        context={
            "service": cfg.service_name,
            "failure_count": _snapshot.failure_count,
            "opened_at": _snapshot.opened_at,
            "recovery_timeout_seconds": cfg.recovery_timeout_seconds,
        },
    )


def api_circuit_breaker_status(
    *,
    now: float | None = None,
    config: ApiCircuitBreakerConfig | None = None,
) -> dict[str, Any]:
    """Return a doctor-friendly snapshot of breaker state."""
    cfg = config or ApiCircuitBreakerConfig()
    current = now if now is not None else time.time()
    is_open = not circuit_breaker_allows_request(
        _snapshot,
        now=current,
        recovery_timeout=cfg.recovery_timeout_seconds,
    )
    seconds_until_recovery: float | None = None
    if is_open and _snapshot.opened_at is not None:
        remaining = cfg.recovery_timeout_seconds - (current - _snapshot.opened_at)
        seconds_until_recovery = max(0.0, remaining)
    return {
        "service": cfg.service_name,
        "state": "open" if is_open else "closed",
        "failure_count": _snapshot.failure_count,
        "opened_at": _snapshot.opened_at,
        "recovery_timeout_seconds": cfg.recovery_timeout_seconds,
        "seconds_until_recovery": seconds_until_recovery,
    }
