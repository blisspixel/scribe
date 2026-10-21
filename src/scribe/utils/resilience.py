"""Pure defensive resilience primitives (retry, backoff, circuit breaker).

ADR-002: desktop tools must degrade gracefully under flaky hardware and
external processes. These helpers keep retry and breaker policy testable
without sleeping in unit tests.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

import deal

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry schedule for transient failures."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 30.0
    jitter_fraction: float = 0.0


@deal.pre(lambda attempt, **_kwargs: attempt >= 0)
@deal.post(lambda result, **_kwargs: result >= 0.0)
def retry_backoff_seconds(
    attempt: int,
    *,
    base: float = 0.5,
    max_delay: float = 30.0,
    jitter_fraction: float = 0.0,
    jitter_unit: float = 0.0,
) -> float:
    """Exponential backoff delay for ``attempt`` (0-based).

    ``jitter_unit`` must be in [0, 1] when jitter is enabled; inject it from the
    caller so Hypothesis can prove bounds without randomness in pure tests.
    """
    delay = float(min(max_delay, base * (2**attempt)))
    if jitter_fraction <= 0:
        return delay
    clamped = min(1.0, max(0.0, jitter_unit))
    spread = jitter_fraction * 2 * clamped
    return float(delay * (1.0 - jitter_fraction + spread))


@deal.pre(lambda _attempt, policy: policy.max_attempts >= 1)
def should_retry_attempt(attempt: int, policy: RetryPolicy) -> bool:
    """Return True while another attempt is allowed (``attempt`` is 0-based)."""
    return attempt + 1 < policy.max_attempts


def is_retriable_exception(
    exc: BaseException,
    *,
    retriable: Sequence[type[BaseException]] = (ConnectionError, OSError, TimeoutError),
) -> bool:
    """Return True when ``exc`` matches a transient failure type."""
    return isinstance(exc, tuple(retriable))


@dataclass(frozen=True)
class CircuitBreakerSnapshot:
    """Immutable circuit breaker state."""

    failure_count: int = 0
    opened_at: float | None = None


@deal.post(lambda result: result.failure_count == 0 and result.opened_at is None)
def circuit_breaker_after_success(_snapshot: CircuitBreakerSnapshot) -> CircuitBreakerSnapshot:
    """Reset breaker after a successful call."""
    return CircuitBreakerSnapshot()


def circuit_breaker_after_failure(
    snapshot: CircuitBreakerSnapshot,
    *,
    now: float,
    threshold: int,
) -> CircuitBreakerSnapshot:
    """Record a failure and open the breaker at ``threshold``."""
    if threshold < 1:
        raise ValueError("threshold must be >= 1")
    failures = snapshot.failure_count + 1
    opened_at = snapshot.opened_at
    if failures >= threshold:
        opened_at = now
    return CircuitBreakerSnapshot(failure_count=failures, opened_at=opened_at)


def circuit_breaker_allows_request(
    snapshot: CircuitBreakerSnapshot,
    *,
    now: float,
    recovery_timeout: float,
) -> bool:
    """Return False while the breaker is open and recovery has not elapsed."""
    if snapshot.opened_at is None:
        return True
    return (now - snapshot.opened_at) >= recovery_timeout


def run_fallback_chain(
    strategies: Sequence[Callable[[], T]],
    *,
    on_error: Callable[[BaseException, int], None] | None = None,
) -> T:
    """Try strategies in order; raise the last error when all fail."""
    last_error: BaseException | None = None
    for index, strategy in enumerate(strategies):
        try:
            return strategy()
        except BaseException as exc:
            last_error = exc
            if on_error is not None:
                on_error(exc, index)
    if last_error is None:
        raise RuntimeError("fallback chain invoked with no strategies")
    raise last_error
