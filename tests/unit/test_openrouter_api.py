from __future__ import annotations

import base64
import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from scribe.core.openrouter_api import OpenRouterTranscriber
from scribe.exceptions import APIError, TranscriptionError


def _client(handler: httpx.MockTransport) -> httpx.Client:
    return httpx.Client(transport=handler)


def _transcriber(
    handler: httpx.MockTransport,
    *,
    attempts: int = 3,
    api_key: str = "sk-or-v1-test-key-1234567890",
    max_spend_usd: float = 5.0,
) -> OpenRouterTranscriber:
    return OpenRouterTranscriber(
        api_key=api_key,
        model="openai/whisper-large-v3",
        language="en",
        max_attempts=attempts,
        timeout_seconds=30,
        max_spend_usd=max_spend_usd,
        client=_client(handler),
    )


def _account_ok() -> httpx.Response:
    return httpx.Response(
        200,
        json={"data": {"limit": 5.0, "limit_remaining": 4.0}},
    )


def _mock_audio_pipeline(
    transcriber: OpenRouterTranscriber,
    source: Path,
    chunks: list[Path],
):
    standardized = source.with_name(f"{source.stem}_standardized.mp3")
    standardized.write_bytes(b"standardized")
    return (
        patch.object(transcriber, "standardize_audio", return_value=standardized),
        patch.object(transcriber, "split_audio_on_silence", return_value=chunks),
    )


def test_constructor_uses_stable_quality_default_model() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200))

    transcriber = OpenRouterTranscriber("test-key", client=_client(transport))

    assert transcriber.model == "openai/whisper-large-v3"


def test_boolean_usage_values_are_not_accepted_as_numbers() -> None:
    response = httpx.Response(
        200,
        json={"text": "Confirmed.", "usage": {"seconds": True, "cost": False}},
    )

    result = OpenRouterTranscriber._parse_success(response)

    assert result.seconds is None
    assert result.cost_usd is None


def test_success_uses_documented_json_contract_and_writes_complete_transcript(
    tmp_path: Path,
) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"source")
    chunk = tmp_path / "meeting_chunk_1.mp3"
    chunk.write_bytes(b"bounded-audio")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/key"):
            return _account_ok()
        requests.append(request)
        body = json.loads(request.content)
        assert request.url == "https://openrouter.ai/api/v1/audio/transcriptions"
        assert request.headers["Authorization"] == "Bearer sk-or-v1-test-key-1234567890"
        assert body == {
            "model": "openai/whisper-large-v3",
            "input_audio": {
                "data": base64.b64encode(b"bounded-audio").decode("ascii"),
                "format": "mp3",
            },
            "language": "en",
            "temperature": 0,
            "provider": {"sort": "price"},
        }
        return httpx.Response(
            200,
            json={"text": "Confirmed transcript.", "usage": {"seconds": 4.0, "cost": 0.01}},
            headers={"X-Generation-Id": "gen-1"},
        )

    transcriber = _transcriber(httpx.MockTransport(handler))
    standardize, split = _mock_audio_pipeline(transcriber, source, [chunk])
    with (
        standardize,
        split,
        patch("scribe.core.openrouter_api.get_audio_duration", return_value=4.0),
    ):
        result = transcriber.transcribe(source)

    assert len(requests) == 1
    assert result.read_text(encoding="utf-8").endswith("Confirmed transcript.\n")
    assert "INCOMPLETE TRANSCRIPT" not in result.read_text(encoding="utf-8")
    assert not result.with_name("meeting_transcription.partial.txt").exists()
    assert source.exists()
    assert not chunk.exists()
    assert transcriber.last_transcript is not None
    assert transcriber.last_transcript.backend == "openrouter"
    assert transcriber.last_transcript.model == "openai/whisper-large-v3"
    assert transcriber.last_transcript.metadata["generation_ids"] == ["gen-1"]
    assert transcriber.last_transcript.metadata["reported_cost_usd"] == 0.01
    assert transcriber.last_transcript.metadata["max_spend_usd"] == 5.0
    assert transcriber.last_transcript.metadata["spend_guard_status"] == "active"


def test_retryable_response_honors_bounded_retry_after(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"audio")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/key"):
            return _account_ok()
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429, json={"error": {"message": "slow down"}}, headers={"Retry-After": "0"}
            )
        return httpx.Response(200, json={"text": "Recovered."})

    transcriber = _transcriber(httpx.MockTransport(handler))
    with patch("scribe.core.openrouter_api.time.sleep") as sleep:
        result = transcriber._transcribe_chunk(chunk)

    assert result.text == "Recovered."
    assert calls == 2
    sleep.assert_called_once_with(0.0)


def test_nonfinite_retry_after_uses_normal_backoff(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"audio")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("/key"):
            return _account_ok()
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "NaN"})
        return httpx.Response(200, json={"text": "Recovered."})

    transcriber = _transcriber(httpx.MockTransport(handler))
    with (
        patch("scribe.core.openrouter_api.retry_backoff_seconds", return_value=0.25),
        patch("scribe.core.openrouter_api.time.sleep") as sleep,
    ):
        result = transcriber._transcribe_chunk(chunk)

    assert result.text == "Recovered."
    sleep.assert_called_once_with(0.25)


@pytest.mark.parametrize("status_code", [401, 403])
def test_authentication_failure_never_retries(tmp_path: Path, status_code: int) -> None:
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"audio")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, json={"error": {"message": "rejected"}})

    transcriber = _transcriber(httpx.MockTransport(handler), attempts=3)
    with pytest.raises(APIError, match="authentication failed"):
        transcriber._transcribe_chunk(chunk)

    assert calls == 1


def test_insufficient_credits_never_retries(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"audio")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(402, json={"error": {"message": "payment required"}})

    transcriber = _transcriber(httpx.MockTransport(handler), attempts=3)
    with pytest.raises(APIError, match="insufficient credits"):
        transcriber._transcribe_chunk(chunk)

    assert calls == 1


def test_provider_error_cannot_echo_api_key(tmp_path: Path) -> None:
    key = "sk-or-v1-private-key-1234567890"
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"audio")

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": {"message": f"bad key {key}"}})

    transcriber = _transcriber(httpx.MockTransport(handler), attempts=1, api_key=key)
    with pytest.raises(APIError) as exc_info:
        transcriber._transcribe_chunk(chunk)

    assert key not in str(exc_info.value)
    assert "[REDACTED]" in str(exc_info.value)


@pytest.mark.parametrize("status_code", [400, 404, 422])
def test_nonretryable_client_error_fails_once(tmp_path: Path, status_code: int) -> None:
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"audio")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status_code, json={"error": {"message": "bad request"}})

    transcriber = _transcriber(httpx.MockTransport(handler), attempts=3)
    with pytest.raises(APIError, match="request failed"):
        transcriber._transcribe_chunk(chunk)

    assert calls == 1


def test_oversized_chunk_is_blocked_before_network(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"x" * (12 * 1024 * 1024 + 1))
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"text": "should not happen"})

    transcriber = _transcriber(httpx.MockTransport(handler))
    with pytest.raises(TranscriptionError, match="upload limit"):
        transcriber._transcribe_chunk(chunk)

    assert called is False


def test_invalid_success_response_is_retried_then_fails(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"audio")
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"text": ""})

    transcriber = _transcriber(httpx.MockTransport(handler), attempts=2)
    with (
        patch("scribe.core.openrouter_api.time.sleep"),
        pytest.raises(APIError, match="request failed"),
    ):
        transcriber._transcribe_chunk(chunk)

    assert calls == 2


def test_network_failure_retries_without_exposing_request_data(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"private-audio")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline", request=request)

    transcriber = _transcriber(httpx.MockTransport(handler), attempts=2)
    with (
        patch("scribe.core.openrouter_api.time.sleep"),
        pytest.raises(APIError) as exc_info,
    ):
        transcriber._transcribe_chunk(chunk)

    assert calls == 2
    assert "private-audio" not in str(exc_info.value)
    assert "sk-or-v1" not in str(exc_info.value)


def test_later_chunk_failure_preserves_labeled_partial_transcript(tmp_path: Path) -> None:
    source = tmp_path / "important.wav"
    source.write_bytes(b"source")
    first_chunk = tmp_path / "important_chunk_1.mp3"
    second_chunk = tmp_path / "important_chunk_2.mp3"
    first_chunk.write_bytes(b"first")
    second_chunk.write_bytes(b"second")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("/key"):
            return _account_ok()
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "text": "Confirmed first chunk.",
                    "usage": {"seconds": 5.0, "cost": 0.01},
                },
            )
        return httpx.Response(503, json={"error": {"message": "temporarily unavailable"}})

    transcriber = _transcriber(httpx.MockTransport(handler), attempts=1)
    standardize, split = _mock_audio_pipeline(transcriber, source, [first_chunk, second_chunk])
    with (
        standardize,
        split,
        patch("scribe.core.openrouter_api.get_audio_duration", return_value=10.0),
        pytest.raises(TranscriptionError, match="before all chunks completed"),
    ):
        transcriber.transcribe(source)

    partial = tmp_path / "important_transcription.partial.txt"
    assert partial.exists()
    content = partial.read_text(encoding="utf-8")
    assert "INCOMPLETE TRANSCRIPT" in content
    assert "Confirmed first chunk." in content
    assert transcriber.last_transcript is not None
    assert transcriber.last_transcript.metadata == {
        "completed_chunks": 1,
        "total_chunks": 2,
        "max_spend_usd": 5.0,
        "reported_cost_usd": 0.01,
        "spend_guard_status": "active",
    }
    assert not first_chunk.exists()
    assert not second_chunk.exists()


@pytest.mark.parametrize("status_code", [401, 403])
def test_account_preflight_rejects_invalid_key_before_audio_work(
    tmp_path: Path, status_code: int
) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"source")
    transport = httpx.MockTransport(lambda _request: httpx.Response(status_code))
    transcriber = _transcriber(transport)

    with (
        patch.object(transcriber, "standardize_audio") as standardize,
        pytest.raises(TranscriptionError, match="account preflight failed"),
    ):
        transcriber.transcribe(source)

    standardize.assert_not_called()


def test_account_preflight_rejects_exhausted_budget_before_audio_work(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"source")
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"data": {"limit": 5.0, "limit_remaining": 0.0}},
        )
    )
    transcriber = _transcriber(transport)

    with (
        patch.object(transcriber, "standardize_audio") as standardize,
        pytest.raises(TranscriptionError, match="account preflight failed"),
    ):
        transcriber.transcribe(source)

    standardize.assert_not_called()


def test_reported_cost_limit_stops_before_next_chunk_and_keeps_partial(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"source")
    chunks = [tmp_path / "chunk-1.mp3", tmp_path / "chunk-2.mp3"]
    for chunk in chunks:
        chunk.write_bytes(b"audio")
    uploads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal uploads
        if request.url.path.endswith("/key"):
            return _account_ok()
        uploads += 1
        return httpx.Response(
            200,
            json={"text": "Confirmed first chunk.", "usage": {"seconds": 5.0, "cost": 0.5}},
        )

    transcriber = _transcriber(httpx.MockTransport(handler), max_spend_usd=0.5)
    standardize, split = _mock_audio_pipeline(transcriber, source, chunks)
    with (
        standardize,
        split,
        patch("scribe.core.openrouter_api.get_audio_duration", return_value=10.0),
        pytest.raises(TranscriptionError, match="reported-cost limit reached"),
    ):
        transcriber.transcribe(source)

    assert uploads == 1
    partial = tmp_path / "meeting_transcription.partial.txt"
    assert "Confirmed first chunk." in partial.read_text(encoding="utf-8")
    assert transcriber.last_transcript is not None
    assert transcriber.last_transcript.metadata["reported_cost_usd"] == 0.5
    assert transcriber.last_transcript.metadata["spend_guard_status"] == ("reported_limit_reached")


def test_missing_reported_cost_stops_before_next_chunk_and_keeps_partial(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"source")
    chunks = [tmp_path / "chunk-1.mp3", tmp_path / "chunk-2.mp3"]
    for chunk in chunks:
        chunk.write_bytes(b"audio")
    uploads = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal uploads
        if request.url.path.endswith("/key"):
            return _account_ok()
        uploads += 1
        return httpx.Response(
            200,
            json={"text": "Confirmed without cost.", "usage": {"seconds": 5.0}},
        )

    transcriber = _transcriber(httpx.MockTransport(handler))
    standardize, split = _mock_audio_pipeline(transcriber, source, chunks)
    with (
        standardize,
        split,
        patch("scribe.core.openrouter_api.get_audio_duration", return_value=10.0),
        pytest.raises(TranscriptionError, match="did not report the prior chunk cost"),
    ):
        transcriber.transcribe(source)

    assert uploads == 1
    assert transcriber.last_transcript is not None
    assert transcriber.last_transcript.metadata["spend_guard_status"] == (
        "provider_cost_unavailable"
    )


def test_final_chunk_above_reported_limit_is_preserved_and_labeled(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"source")
    chunk = tmp_path / "chunk.mp3"
    chunk.write_bytes(b"audio")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/key"):
            return _account_ok()
        return httpx.Response(
            200,
            json={"text": "Complete transcript.", "usage": {"seconds": 5.0, "cost": 0.6}},
        )

    transcriber = _transcriber(httpx.MockTransport(handler), max_spend_usd=0.5)
    standardize, split = _mock_audio_pipeline(transcriber, source, [chunk])
    with (
        standardize,
        split,
        patch("scribe.core.openrouter_api.get_audio_duration", return_value=5.0),
    ):
        result = transcriber.transcribe(source)

    assert result.exists()
    assert transcriber.last_transcript is not None
    assert transcriber.last_transcript.metadata["spend_guard_status"] == (
        "reported_limit_exceeded_on_final_chunk"
    )


def test_unique_workspace_preserves_same_named_user_file(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"source")
    user_file = tmp_path / "meeting_openrouter_standardized.mp3"
    user_file.write_bytes(b"keep-me")
    work_directory = tmp_path / "private-workspace"
    work_directory.mkdir()
    standardized = work_directory / "meeting_openrouter_standardized.mp3"
    chunk = work_directory / "meeting_openrouter_standardized_chunk_1.mp3"
    chunk.write_bytes(b"bounded-audio")

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, json={"text": "Safe transcript."})
    )
    transcriber = _transcriber(transport)

    def standardize(_source: Path, **_kwargs) -> Path:
        standardized.write_bytes(b"temporary")
        return standardized

    with (
        patch("scribe.core.openrouter_api.tempfile.mkdtemp", return_value=str(work_directory)),
        patch.object(transcriber, "standardize_audio", side_effect=standardize) as normalize,
        patch.object(transcriber, "split_audio_on_silence", return_value=[chunk]),
        patch("scribe.core.openrouter_api.get_audio_duration", return_value=1.0),
    ):
        transcriber.transcribe(source)

    normalize.assert_called_once_with(source, work_directory=work_directory)
    assert user_file.read_bytes() == b"keep-me"
    assert not work_directory.exists()


def test_interrupt_keeps_latest_confirmed_partial_and_metadata(tmp_path: Path) -> None:
    source = tmp_path / "important.wav"
    source.write_bytes(b"source")
    first_chunk = tmp_path / "important_chunk_1.mp3"
    second_chunk = tmp_path / "important_chunk_2.mp3"
    first_chunk.write_bytes(b"first")
    second_chunk.write_bytes(b"second")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/key"):
            return _account_ok()
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                json={
                    "text": "Confirmed before cancel.",
                    "usage": {"seconds": 5.0, "cost": 0.01},
                },
            )
        raise KeyboardInterrupt

    transcriber = _transcriber(httpx.MockTransport(handler), attempts=1)
    standardize, split = _mock_audio_pipeline(transcriber, source, [first_chunk, second_chunk])
    with (
        standardize,
        split,
        patch("scribe.core.openrouter_api.get_audio_duration", return_value=5.0),
        pytest.raises(KeyboardInterrupt),
    ):
        transcriber.transcribe(source)

    partial = tmp_path / "important_transcription.partial.txt"
    assert "Confirmed before cancel." in partial.read_text(encoding="utf-8")
    assert transcriber.last_transcript is not None
    assert transcriber.last_transcript.metadata["completed_chunks"] == 1


def test_failed_rerun_archives_prior_outputs_before_request(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"source")
    output = tmp_path / "meeting_transcription.txt"
    partial = tmp_path / "meeting_transcription.partial.txt"
    output.write_text("prior complete\n", encoding="utf-8")
    partial.write_text("prior partial\n", encoding="utf-8")
    chunk = tmp_path / "meeting_chunk_1.mp3"
    chunk.write_bytes(b"audio")

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(503, json={"error": {"message": "offline"}})
    )
    transcriber = _transcriber(transport, attempts=1)
    standardize, split = _mock_audio_pipeline(transcriber, source, [chunk])
    with (
        standardize,
        split,
        patch("scribe.core.openrouter_api.get_audio_duration", return_value=1.0),
        pytest.raises(TranscriptionError, match="before all chunks completed"),
    ):
        transcriber.transcribe(source)

    assert not output.exists()
    assert not partial.exists()
    assert output.with_name(f"{output.name}.previous").read_text(encoding="utf-8") == (
        "prior complete\n"
    )
    assert partial.with_name(f"{partial.name}.previous").read_text(encoding="utf-8") == (
        "prior partial\n"
    )


def test_output_path_cannot_replace_source_audio(tmp_path: Path) -> None:
    source = tmp_path / "meeting.wav"
    source.write_bytes(b"source")
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"text": "unused"}))
    transcriber = _transcriber(transport)

    with pytest.raises(TranscriptionError, match="cannot replace the source"):
        transcriber.transcribe(source, output_path=source)

    assert source.read_bytes() == b"source"


def test_constructor_rejects_invalid_retry_and_timeout_settings() -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"text": "ok"}))
    with pytest.raises(ValueError, match="max_attempts"):
        OpenRouterTranscriber("key", max_attempts=0, client=_client(transport))
    with pytest.raises(ValueError, match="timeout_seconds"):
        OpenRouterTranscriber("key", timeout_seconds=0, client=_client(transport))
    with pytest.raises(ValueError, match="timeout_seconds"):
        OpenRouterTranscriber("key", timeout_seconds=float("nan"), client=_client(transport))
    with pytest.raises(ValueError, match="max_attempts"):
        OpenRouterTranscriber("key", max_attempts=11, client=_client(transport))
    with pytest.raises(ValueError, match="max_spend_usd"):
        OpenRouterTranscriber("key", max_spend_usd=0, client=_client(transport))
    with pytest.raises(ValueError, match="max_spend_usd"):
        OpenRouterTranscriber("key", max_spend_usd=float("nan"), client=_client(transport))
    with pytest.raises(ValueError, match="model"):
        OpenRouterTranscriber("key", model="bad slug", client=_client(transport))


@patch("scribe.core.openrouter_api.Converter")
def test_standardization_uses_streaming_converter(converter_class, tmp_path: Path) -> None:
    source = tmp_path / "long-meeting.mkv"
    source.write_bytes(b"media")
    expected = tmp_path / "normalized.mp3"
    converter_class.return_value.convert_to_mp3.return_value = expected
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json={"text": "unused"}))
    transcriber = _transcriber(transport)

    result = transcriber.standardize_audio(source)

    assert result == expected
    converter_class.return_value.convert_to_mp3.assert_called_once_with(
        source,
        output_file=expected,
        bitrate=48,
    )
