"""Fault-injection and property tests for defensive resilience primitives."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scribe.utils.resilience import (
    CircuitBreakerSnapshot,
    RetryPolicy,
    circuit_breaker_after_failure,
    circuit_breaker_after_success,
    circuit_breaker_allows_request,
    is_retriable_exception,
    retry_backoff_seconds,
    run_fallback_chain,
    should_retry_attempt,
)


class TestRetryBackoff:
    def test_backoff_grows_then_caps(self) -> None:
        assert retry_backoff_seconds(0, base=0.5, max_delay=4.0) == 0.5
        assert retry_backoff_seconds(3, base=0.5, max_delay=4.0) == 4.0

    @given(st.integers(min_value=0, max_value=20))
    def test_backoff_is_non_negative(self, attempt: int) -> None:
        assert retry_backoff_seconds(attempt, max_delay=30.0) >= 0.0

    def test_should_retry_respects_policy(self) -> None:
        policy = RetryPolicy(max_attempts=3)
        assert should_retry_attempt(0, policy)
        assert should_retry_attempt(1, policy)
        assert not should_retry_attempt(2, policy)


class TestRetriableExceptions:
    def test_connection_and_os_errors_are_retriable(self) -> None:
        assert is_retriable_exception(ConnectionError("down"))
        assert is_retriable_exception(OSError("disk"))

    def test_logic_errors_are_not_retriable(self) -> None:
        assert not is_retriable_exception(ValueError("bad"))


class TestCircuitBreaker:
    def test_opens_after_threshold(self) -> None:
        snap = CircuitBreakerSnapshot()
        snap = circuit_breaker_after_failure(snap, now=10.0, threshold=3)
        snap = circuit_breaker_after_failure(snap, now=11.0, threshold=3)
        snap = circuit_breaker_after_failure(snap, now=12.0, threshold=3)
        assert snap.opened_at == 12.0
        assert not circuit_breaker_allows_request(snap, now=20.0, recovery_timeout=60.0)

    def test_recovers_after_timeout(self) -> None:
        snap = CircuitBreakerSnapshot(failure_count=3, opened_at=100.0)
        assert not circuit_breaker_allows_request(snap, now=120.0, recovery_timeout=60.0)
        assert circuit_breaker_allows_request(snap, now=161.0, recovery_timeout=60.0)

    def test_success_resets_failures(self) -> None:
        snap = CircuitBreakerSnapshot(failure_count=2, opened_at=1.0)
        reset = circuit_breaker_after_success(snap)
        assert reset.failure_count == 0
        assert reset.opened_at is None


class TestFallbackChain:
    def test_returns_first_success(self) -> None:
        calls: list[int] = []

        def fail() -> str:
            calls.append(1)
            raise ConnectionError("nope")

        def succeed() -> str:
            calls.append(2)
            return "ok"

        assert run_fallback_chain([fail, succeed]) == "ok"
        assert calls == [1, 2]

    def test_raises_last_error_when_all_fail(self) -> None:
        with pytest.raises(RuntimeError, match="final"):
            run_fallback_chain(
                [
                    lambda: (_ for _ in ()).throw(ConnectionError("a")),
                    lambda: (_ for _ in ()).throw(RuntimeError("final")),
                ]
            )

    def test_empty_chain_raises(self) -> None:
        with pytest.raises(RuntimeError, match="no strategies"):
            run_fallback_chain([])
