"""Defensive, opt-in speech-to-text through OpenRouter's dedicated API."""

from __future__ import annotations

import base64
import math
import secrets
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from scribe.core.converter import Converter
from scribe.core.openai_api import OpenAITranscriber
from scribe.exceptions import APIError, TranscriptionError
from scribe.models.transcript import Transcript, TranscriptSegment
from scribe.utils.audio import get_audio_duration
from scribe.utils.files import extract_date_from_filename, format_date, format_duration_minutes
from scribe.utils.logging import console, get_logger
from scribe.utils.resilience import retry_backoff_seconds
from scribe.utils.safe_write import atomic_write

logger = get_logger(__name__)

_TRANSCRIPTIONS_URL = "https://openrouter.ai/api/v1/audio/transcriptions"
_KEY_URL = "https://openrouter.ai/api/v1/key"
_MAX_CHUNK_BYTES = 12 * 1024 * 1024
_MAX_ERROR_DETAIL_CHARS = 400
_CHUNK_MINUTES = 5
_CHUNK_OVERLAP_SECONDS = 0.6
_RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class _ChunkResult:
    """Validated data retained from one OpenRouter response."""

    text: str
    seconds: float | None
    cost_usd: float | None
    generation_id: str | None


@dataclass(frozen=True)
class _AccountStatus:
    """Non-sensitive OpenRouter budget facts returned by the key endpoint."""

    checked: bool
    provider_limit_usd: float | None
    remaining_usd: float | None


class OpenRouterTranscriber(OpenAITranscriber):
    """Transcribe bounded MP3 chunks through OpenRouter.

    The class reuses Scribe's portable audio normalization and FFmpeg chunk
    exporter, but it deliberately does not initialize or call the OpenAI SDK.
    OpenRouter's dedicated endpoint accepts JSON containing raw base64 audio,
    which is a different wire contract from OpenAI's multipart endpoint.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "openai/whisper-large-v3",
        *,
        language: str | None = None,
        max_attempts: int = 3,
        timeout_seconds: float = 90.0,
        max_spend_usd: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if max_attempts > 10:
            raise ValueError("max_attempts cannot exceed 10")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 600:
            raise ValueError("timeout_seconds must be finite and between 0 and 600")
        if not math.isfinite(max_spend_usd) or not 0 < max_spend_usd <= 1000:
            raise ValueError("max_spend_usd must be finite and between 0 and 1000")

        normalized_key = api_key.strip()
        if not normalized_key or any(character.isspace() for character in normalized_key):
            raise ValueError("api_key is required and cannot contain whitespace")
        normalized_model = model.strip()
        if (
            not normalized_model
            or len(normalized_model) > 200
            or any(character.isspace() for character in normalized_model)
        ):
            raise ValueError("model must be a non-empty provider slug without whitespace")

        self.api_key = normalized_key
        self.model = normalized_model
        self.language = language
        self.max_attempts = max_attempts
        self.timeout_seconds = timeout_seconds
        self.max_spend_usd = max_spend_usd
        self.http_client = client or httpx.Client()
        self._owns_client = client is None
        self.last_transcript: Transcript | None = None

        logger.debug("Initialized OpenRouter transcriber for model %s", self.model)

    @property
    def _headers(self) -> dict[str, str]:
        """Build authentication headers without retaining them in logs or errors."""
        return {"Authorization": f"Bearer {self.api_key}"}

    @staticmethod
    def _nonnegative_number(value: Any) -> float | None:
        if (
            isinstance(value, int | float)
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            and value >= 0
        ):
            return float(value)
        return None

    def _preflight_account(self) -> _AccountStatus:
        """Fail early on invalid credentials or exhausted provider-side credit."""
        try:
            response = self.http_client.get(
                _KEY_URL,
                headers=self._headers,
                timeout=min(10.0, self.timeout_seconds),
            )
        except httpx.RequestError as exc:
            logger.warning(
                "OpenRouter account preflight was unavailable (%s); continuing with the "
                "per-transcription spend guard",
                type(exc).__name__,
            )
            return _AccountStatus(False, None, None)

        if response.status_code in {401, 403}:
            raise APIError(
                "OpenRouter authentication failed. Check OPENROUTER_API_KEY",
                context={"status_code": response.status_code},
            )
        if response.status_code == 402:
            raise APIError(
                "OpenRouter has insufficient credits for transcription",
                context={"status_code": response.status_code},
            )
        if not response.is_success:
            logger.warning(
                "OpenRouter account preflight returned HTTP %d; continuing with the "
                "per-transcription spend guard",
                response.status_code,
            )
            return _AccountStatus(False, None, None)

        try:
            body = response.json()
        except ValueError:
            logger.warning(
                "OpenRouter account preflight returned invalid JSON; continuing with the "
                "per-transcription spend guard"
            )
            return _AccountStatus(False, None, None)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            logger.warning(
                "OpenRouter account preflight omitted account data; continuing with the "
                "per-transcription spend guard"
            )
            return _AccountStatus(False, None, None)

        provider_limit = self._nonnegative_number(data.get("limit"))
        remaining = self._nonnegative_number(data.get("limit_remaining"))
        if remaining is not None and remaining <= 0:
            raise APIError("OpenRouter has no remaining budget for transcription")
        return _AccountStatus(True, provider_limit, remaining)

    def standardize_audio(
        self,
        input_path: Path,
        target_bitrate_kbps: int = 48,
        *,
        work_directory: Path | None = None,
    ) -> Path:
        """Normalize through streaming FFmpeg without loading a long meeting into memory."""
        output_parent = work_directory or input_path.parent
        output_path = output_parent / "normalized.mp3"
        return Converter().convert_to_mp3(
            input_path,
            output_file=output_path,
            bitrate=target_bitrate_kbps,
        )

    def _safe_error_detail(self, response: httpx.Response) -> str:
        """Extract a bounded provider error without leaking credentials or payloads."""
        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error")
                if isinstance(error, dict):
                    detail = str(error.get("message") or error.get("code") or "")
                elif error is not None:
                    detail = str(error)
                elif body.get("message") is not None:
                    detail = str(body["message"])
        except (TypeError, ValueError):
            detail = ""

        detail = " ".join(detail.split())
        if self.api_key in detail:
            detail = detail.replace(self.api_key, "[REDACTED]")
        return detail[:_MAX_ERROR_DETAIL_CHARS]

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        """Parse a numeric Retry-After header and bound the wait."""
        value = response.headers.get("Retry-After")
        if value is None:
            return None
        try:
            delay = float(value)
            return min(60.0, max(0.0, delay)) if math.isfinite(delay) else None
        except ValueError:
            return None

    @staticmethod
    def _parse_success(response: httpx.Response) -> _ChunkResult:
        """Validate the documented OpenRouter STT response shape."""
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("response body is not a JSON object")

        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("response did not contain non-empty transcript text")

        usage = body.get("usage")
        usage = usage if isinstance(usage, dict) else {}

        seconds = OpenRouterTranscriber._nonnegative_number(usage.get("seconds"))
        cost = OpenRouterTranscriber._nonnegative_number(usage.get("cost"))
        generation_id = response.headers.get("X-Generation-Id")
        return _ChunkResult(
            text=text.strip(),
            seconds=seconds,
            cost_usd=cost,
            generation_id=generation_id,
        )

    def _transcribe_chunk(self, chunk_path: Path) -> _ChunkResult:
        """Upload one bounded chunk with deterministic retry and failure rules."""
        try:
            size_bytes = chunk_path.stat().st_size
        except OSError as exc:
            raise TranscriptionError(f"Cannot read cloud transcription chunk: {exc}") from exc
        if size_bytes <= 0:
            raise TranscriptionError(f"Cloud transcription chunk is empty: {chunk_path.name}")
        if size_bytes > _MAX_CHUNK_BYTES:
            raise TranscriptionError(
                "Cloud transcription chunk exceeds Scribe's defensive upload limit",
                context={
                    "chunk": chunk_path.name,
                    "size_mb": round(size_bytes / (1024 * 1024), 1),
                    "limit_mb": _MAX_CHUNK_BYTES // (1024 * 1024),
                },
            )

        try:
            encoded_audio = base64.b64encode(chunk_path.read_bytes()).decode("ascii")
        except OSError as exc:
            raise TranscriptionError(f"Cannot read cloud transcription chunk: {exc}") from exc

        payload: dict[str, Any] = {
            "model": self.model,
            "input_audio": {"data": encoded_audio, "format": chunk_path.suffix.lstrip(".")},
            "temperature": 0,
            "provider": {"sort": "price"},
        }
        if self.language:
            payload["language"] = self.language

        headers = {**self._headers, "Content-Type": "application/json"}

        last_error = "request failed"
        for attempt in range(self.max_attempts):
            try:
                response = self.http_client.post(
                    _TRANSCRIPTIONS_URL,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout_seconds,
                )
            except httpx.RequestError as exc:
                last_error = f"network error: {type(exc).__name__}"
                retryable = True
                retry_after = None
            else:
                if response.is_success:
                    try:
                        return self._parse_success(response)
                    except (TypeError, ValueError) as exc:
                        last_error = f"invalid success response: {exc}"
                        retryable = True
                        retry_after = None
                else:
                    detail = self._safe_error_detail(response)
                    suffix = f": {detail}" if detail else ""
                    last_error = f"HTTP {response.status_code}{suffix}"
                    if response.status_code in {401, 403}:
                        raise APIError(
                            "OpenRouter authentication failed. Check OPENROUTER_API_KEY",
                            context={"status_code": response.status_code},
                        )
                    if response.status_code == 402:
                        raise APIError(
                            "OpenRouter has insufficient credits for transcription",
                            context={"status_code": response.status_code},
                        )
                    retryable = response.status_code in _RETRYABLE_STATUS_CODES
                    retry_after = self._retry_after_seconds(response)

            if not retryable or attempt == self.max_attempts - 1:
                break

            delay = retry_after
            if delay is None:
                delay = retry_backoff_seconds(
                    attempt,
                    jitter_fraction=0.2,
                    jitter_unit=secrets.randbelow(1_000_001) / 1_000_000,
                )
            logger.warning(
                "OpenRouter chunk request failed on attempt %d/%d (%s); retrying in %.2fs",
                attempt + 1,
                self.max_attempts,
                last_error,
                delay,
            )
            time.sleep(delay)

        raise APIError(
            "OpenRouter transcription request failed",
            context={"attempts": self.max_attempts, "error": last_error},
        )

    @staticmethod
    def _clean_stem(audio_path: Path) -> str:
        clean_stem = audio_path.stem
        for suffix in ("_16k_mono", "_standardized", "_converted"):
            clean_stem = clean_stem.replace(suffix, "")
        return clean_stem

    @staticmethod
    def _archive_existing(path: Path) -> Path | None:
        """Move an earlier output aside so it cannot masquerade as this run's result."""
        if not path.exists():
            return None
        if not path.is_file():
            raise OSError(f"Expected an output file but found a directory: {path}")

        candidates = [path.with_name(f"{path.name}.previous")]
        candidates.extend(
            path.with_name(f"{path.name}.previous.{index}") for index in range(1, 1000)
        )
        for candidate in candidates:
            if not candidate.exists():
                path.replace(candidate)
                logger.info("Archived prior transcript output as %s", candidate)
                return candidate
        raise OSError(f"Could not allocate a prior-output archive name for {path}")

    @staticmethod
    def _render_transcript(transcript: Transcript, audio_path: Path, *, partial: bool) -> str:
        """Render a cloud transcript without exposing technical request details."""
        date_value = extract_date_from_filename(audio_path.name)
        rendered_date = (
            format_date(date_value) if date_value else datetime.now().strftime("%B %d, %Y")
        )
        duration = (
            format_duration_minutes(transcript.duration) if transcript.duration else "Unknown"
        )
        lines = [
            f"Meeting: {OpenRouterTranscriber._clean_stem(audio_path)}",
            f"Date: {rendered_date}",
            f"Duration: {duration}",
            "",
        ]
        if partial:
            lines.extend(
                [
                    "INCOMPLETE TRANSCRIPT: One or more later audio chunks were not transcribed.",
                    "This file contains only the confirmed chunks received before the failure.",
                    "",
                ]
            )
        lines.extend(["─" * 80, ""])
        lines.extend(
            segment.text.strip() + "\n" for segment in transcript.segments if segment.text.strip()
        )
        return "\n".join(lines).rstrip() + "\n"

    def _build_transcript(
        self,
        segments: list[TranscriptSegment],
        *,
        duration: float | None,
        generation_ids: list[str],
        total_cost: float | None,
        completed_chunks: int,
        total_chunks: int,
        cost_reporting_complete: bool,
    ) -> Transcript:
        metadata: dict[str, Any] = {
            "completed_chunks": completed_chunks,
            "total_chunks": total_chunks,
            "max_spend_usd": self.max_spend_usd,
        }
        if generation_ids:
            metadata["generation_ids"] = generation_ids
        if total_cost is not None:
            metadata["reported_cost_usd"] = total_cost
        if not cost_reporting_complete:
            metadata["spend_guard_status"] = "provider_cost_unavailable"
        elif (
            total_cost is not None
            and total_cost >= self.max_spend_usd
            and completed_chunks < total_chunks
        ):
            metadata["spend_guard_status"] = "reported_limit_reached"
        elif total_cost is not None and total_cost > self.max_spend_usd:
            metadata["spend_guard_status"] = "reported_limit_exceeded_on_final_chunk"
        else:
            metadata["spend_guard_status"] = "active"
        return Transcript(
            segments=list(segments),
            language=self.language,
            duration=duration,
            backend="openrouter",
            model=self.model,
            metadata=metadata,
        )

    def transcribe(
        self,
        audio_path: Path,
        output_path: Path | None = None,
        prompt: str | None = None,
        cleanup_temp: bool = True,
        initial_prompt: str | None = None,
    ) -> Path:
        """Transcribe a file, preserving confirmed partial text on interruption or failure."""
        if prompt or initial_prompt:
            logger.info(
                "OpenRouter STT has no provider-neutral prompt field; the prompt was not uploaded"
            )
        clean_stem = self._clean_stem(audio_path)
        output_path = output_path or audio_path.parent / f"{clean_stem}_transcription.txt"
        partial_path = output_path.with_name(f"{output_path.stem}.partial{output_path.suffix}")
        if output_path.resolve() == audio_path.resolve():
            raise TranscriptionError("Transcript output path cannot replace the source audio")
        source_duration = get_audio_duration(audio_path)
        temp_files: list[Path] = []
        work_directory: Path | None = None

        console.print(
            "[yellow]Cloud transcription selected:[/yellow] audio will be sent to "
            f"OpenRouter using [bold]{self.model}[/bold]."
        )
        console.print(
            f"[dim]Cloud spend guard: ${self.max_spend_usd:.2f} for this transcription, "
            "checked between chunks using provider-reported cost.[/dim]"
        )
        logger.info("Starting explicit OpenRouter transcription with model %s", self.model)

        try:
            try:
                account_status = self._preflight_account()
            except APIError as exc:
                raise TranscriptionError(
                    "OpenRouter account preflight failed",
                    context={"error": str(exc)},
                ) from exc
            if (
                not account_status.checked
                or account_status.provider_limit_usd is None
                or account_status.provider_limit_usd > self.max_spend_usd
            ):
                console.print(
                    "[yellow]Hard-cap warning:[/yellow] this key has no verified provider-side "
                    f"limit at or below ${self.max_spend_usd:.2f}. Set one in OpenRouter for "
                    "an absolute cap."
                )
            self._archive_existing(output_path)
            self._archive_existing(partial_path)
            work_directory = Path(tempfile.mkdtemp(prefix="scribe-openrouter-"))
            standardized_path = self.standardize_audio(
                audio_path,
                work_directory=work_directory,
            )
            temp_files.append(standardized_path)
            chunk_paths = self.split_audio_on_silence(
                standardized_path,
                max_chunk_minutes=_CHUNK_MINUTES,
            )
            temp_files.extend(chunk_paths)
            if not chunk_paths:
                raise TranscriptionError("Audio chunking produced no OpenRouter upload chunks")

            segments: list[TranscriptSegment] = []
            generation_ids: list[str] = []
            elapsed_seconds = 0.0
            reported_cost = 0.0
            has_reported_cost = False
            cost_reporting_complete = True

            for index, chunk_path in enumerate(chunk_paths, 1):
                if index > 1 and not cost_reporting_complete:
                    raise TranscriptionError(
                        "OpenRouter did not report the prior chunk cost, so Scribe refused "
                        "to upload another chunk under the cloud spend guard",
                        context={
                            "completed_chunks": index - 1,
                            "total_chunks": len(chunk_paths),
                            "partial_transcript": str(partial_path),
                            "max_spend_usd": self.max_spend_usd,
                        },
                    )
                if index > 1 and reported_cost >= self.max_spend_usd:
                    raise TranscriptionError(
                        "OpenRouter reported-cost limit reached; Scribe refused to upload "
                        "another chunk",
                        context={
                            "completed_chunks": index - 1,
                            "total_chunks": len(chunk_paths),
                            "partial_transcript": str(partial_path),
                            "reported_cost_usd": reported_cost,
                            "max_spend_usd": self.max_spend_usd,
                        },
                    )
                try:
                    result = self._transcribe_chunk(chunk_path)
                except (APIError, TranscriptionError) as exc:
                    if segments:
                        partial_transcript = self._build_transcript(
                            segments,
                            duration=source_duration,
                            generation_ids=generation_ids,
                            total_cost=reported_cost if has_reported_cost else None,
                            completed_chunks=len(segments),
                            total_chunks=len(chunk_paths),
                            cost_reporting_complete=cost_reporting_complete,
                        )
                        atomic_write(
                            partial_path,
                            self._render_transcript(partial_transcript, audio_path, partial=True),
                        )
                        self.last_transcript = partial_transcript
                    raise TranscriptionError(
                        "OpenRouter transcription stopped before all chunks completed",
                        context={
                            "failed_chunk": index,
                            "total_chunks": len(chunk_paths),
                            "partial_transcript": str(partial_path) if segments else "none",
                            "error": str(exc),
                        },
                    ) from exc

                chunk_duration = result.seconds or get_audio_duration(chunk_path) or 0.0
                segments.append(
                    TranscriptSegment(
                        start=elapsed_seconds,
                        end=elapsed_seconds + chunk_duration,
                        text=result.text,
                    )
                )
                elapsed_seconds += max(0.0, chunk_duration - _CHUNK_OVERLAP_SECONDS)
                if result.generation_id:
                    generation_ids.append(result.generation_id)
                if result.cost_usd is not None:
                    reported_cost += result.cost_usd
                    has_reported_cost = True
                else:
                    cost_reporting_complete = False

                partial_transcript = self._build_transcript(
                    segments,
                    duration=source_duration,
                    generation_ids=generation_ids,
                    total_cost=reported_cost if has_reported_cost else None,
                    completed_chunks=index,
                    total_chunks=len(chunk_paths),
                    cost_reporting_complete=cost_reporting_complete,
                )
                atomic_write(
                    partial_path,
                    self._render_transcript(partial_transcript, audio_path, partial=True),
                )
                self.last_transcript = partial_transcript

            transcript = self._build_transcript(
                segments,
                duration=source_duration,
                generation_ids=generation_ids,
                total_cost=reported_cost if has_reported_cost else None,
                completed_chunks=len(chunk_paths),
                total_chunks=len(chunk_paths),
                cost_reporting_complete=cost_reporting_complete,
            )
            atomic_write(
                output_path, self._render_transcript(transcript, audio_path, partial=False)
            )
            try:
                partial_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("Could not remove completed partial transcript: %s", exc)
            self.last_transcript = transcript
            logger.info(
                "OpenRouter transcription completed with %d/%d chunks",
                len(chunk_paths),
                len(chunk_paths),
            )
            if cost_reporting_complete:
                logger.info("OpenRouter reported transcription cost: $%.6f", reported_cost)
                if reported_cost > self.max_spend_usd:
                    console.print(
                        "[yellow]Spend guard notice:[/yellow] the final provider response "
                        "reported a total above the configured limit. The completed transcript "
                        "was preserved; set a provider-side key limit for a hard cap."
                    )
            else:
                console.print(
                    "[yellow]Spend guard notice:[/yellow] OpenRouter did not report cost for "
                    "every chunk. No additional chunk was uploaded after cost became unknown."
                )
            return output_path
        except OSError as exc:
            raise TranscriptionError(
                f"File operation failed during OpenRouter transcription: {exc}"
            ) from exc
        finally:
            if cleanup_temp:
                for temp_file in temp_files:
                    try:
                        temp_file.unlink(missing_ok=True)
                    except OSError as exc:
                        logger.warning(
                            "Could not delete temporary file %s: %s", temp_file.name, exc
                        )
                if work_directory is not None:
                    try:
                        shutil.rmtree(work_directory)
                    except OSError as exc:
                        logger.warning(
                            "Could not remove OpenRouter temporary directory %s: %s",
                            work_directory,
                            exc,
                        )
            elif work_directory is not None:
                logger.info("Retained OpenRouter intermediate files in %s", work_directory)
            if self._owns_client:
                try:
                    self.http_client.close()
                except (OSError, RuntimeError) as exc:
                    logger.warning("Could not close the OpenRouter HTTP client: %s", exc)


def transcribe_with_openrouter(
    audio_path: Path,
    api_key: str,
    model: str = "openai/whisper-large-v3",
    **kwargs: Any,
) -> Path:
    """Convenience wrapper for one explicit OpenRouter transcription."""
    transcriber = OpenRouterTranscriber(api_key=api_key, model=model)
    return transcriber.transcribe(audio_path, **kwargs)
