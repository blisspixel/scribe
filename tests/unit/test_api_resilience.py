"""Tests for OpenAI API circuit breaker integration."""

from __future__ import annotations

import pytest
from openai import APIConnectionError

from scribe.exceptions import CircuitBreakerOpen
from scribe.utils.api_resilience import (
    api_circuit_breaker_status,
    ensure_api_circuit_closed,
    record_api_failure,
    record_api_success,
    reset_api_circuit_breaker,
)


@pytest.fixture(autouse=True)
def _reset_breaker() -> None:
    reset_api_circuit_breaker()


class TestApiCircuitBreaker:
    def test_closed_by_default(self) -> None:
        ensure_api_circuit_closed(now=0.0)
        status = api_circuit_breaker_status(now=0.0)
        assert status["state"] == "closed"
        assert status["failure_count"] == 0

    def test_opens_after_threshold(self) -> None:
        for second in range(5):
            record_api_failure(now=float(second))
        with pytest.raises(CircuitBreakerOpen, match="circuit open"):
            ensure_api_circuit_closed(now=5.0)
        status = api_circuit_breaker_status(now=5.0)
        assert status["state"] == "open"
        assert status["seconds_until_recovery"] == pytest.approx(59.0, abs=0.1)

    def test_recovers_after_timeout(self) -> None:
        for second in range(5):
            record_api_failure(now=float(second))
        ensure_api_circuit_closed(now=100.0)
        status = api_circuit_breaker_status(now=100.0)
        assert status["state"] == "closed"

    def test_success_resets_failures(self) -> None:
        record_api_failure(now=1.0)
        record_api_failure(now=2.0)
        record_api_success()
        status = api_circuit_breaker_status(now=3.0)
        assert status["failure_count"] == 0
        assert status["state"] == "closed"


class TestOpenAITranscriberCircuitBreaker:
    @pytest.fixture
    def transcriber(self):
        from unittest.mock import patch

        from scribe.core.openai_api import OpenAITranscriber

        with patch("scribe.core.openai_api.OpenAI"):
            yield OpenAITranscriber(api_key="sk-test")

    def test_transcribe_chunk_raises_when_breaker_open(self, transcriber, tmp_path) -> None:
        from unittest.mock import patch

        chunk = tmp_path / "chunk.mp3"
        chunk.write_bytes(b"fake")
        for second in range(5):
            record_api_failure(now=float(second))

        with patch("scribe.utils.api_resilience.time.time", return_value=5.0):
            with pytest.raises(CircuitBreakerOpen):
                transcriber.transcribe_chunk(chunk, retries=1)

    def test_transcribe_chunk_records_failure_on_connection_error(
        self, transcriber, tmp_path, monkeypatch
    ) -> None:
        chunk = tmp_path / "chunk.mp3"
        chunk.write_bytes(b"fake")

        def boom(*_args, **_kwargs):
            raise APIConnectionError(request=object())  # type: ignore[arg-type]

        monkeypatch.setattr(
            transcriber.client.audio.transcriptions,
            "create",
            boom,
        )
        monkeypatch.setattr("scribe.core.openai_api.time.sleep", lambda _s: None)

        success, text = transcriber.transcribe_chunk(chunk, retries=1)
        assert success is False
        assert text is None
        assert api_circuit_breaker_status()["failure_count"] == 1
