"""Scoped faster-whisper decoding with bounded audio and acoustic diagnostics."""

import gc
import importlib.metadata
import math
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import numpy as np
from numpy.typing import NDArray

from scribe.core.language_evidence import decoding_regions, scan_bounds
from scribe.exceptions import TranscriptionError
from scribe.models.transcript import Transcript, TranscriptSegment, TranscriptWord
from scribe.models.transcription_review import AcousticDiagnostic, AcousticPass, LanguageWindow
from scribe.utils.review_audio import PreparedAudio, prepare_review_audio
from scribe.utils.review_checkpoint import resolve_cached_checkpoint

PhaseCallback = Callable[[str], None]


class RuntimeModel(Protocol):
    compute_type: str

    def unload_model(self, to_cpu: bool = False) -> None: ...


class WordResult(Protocol):
    start: float
    end: float
    word: str
    probability: float


class SegmentResult(Protocol):
    start: float
    end: float
    text: str
    words: list[WordResult] | None
    avg_logprob: float
    no_speech_prob: float
    compression_ratio: float
    temperature: float


class WhisperEngine(Protocol):
    model: RuntimeModel

    def detect_language(self, **kwargs: Any) -> tuple[str, float, list[tuple[str, float]]]: ...

    def transcribe(
        self, audio: NDArray[np.float32], **kwargs: Any
    ) -> tuple[Iterable[SegmentResult], Any]: ...


@dataclass(frozen=True)
class PassSettings:
    model: str
    device: str = "cpu"
    compute_type: str = "int8"
    beam_size: int = 5
    batch_size: int = 0
    language: str | None = None
    prompt: str = ""
    cached_only: bool = True
    strict_compute_type: bool = False
    max_seconds: float = 86_400


def _score(value: float) -> float:
    result = float(value)
    if not math.isfinite(result):
        raise TranscriptionError("Model returned a non-finite acoustic score")
    return result


def scan_language(model: WhisperEngine, audio: PreparedAudio) -> list[LanguageWindow]:
    from faster_whisper.vad import get_speech_timestamps

    windows = []
    for start, end in scan_bounds(audio.duration):
        values = audio.read(start, end)
        spans = cast(list[dict[str, int]], get_speech_timestamps(values))
        speech_seconds = sum(span["end"] - span["start"] for span in spans) / 16_000
        if speech_seconds < 0.25:
            windows.append(LanguageWindow(start, end, (), speech_seconds, "no_speech"))
            continue
        _, _, probabilities = model.detect_language(audio=values, language_detection_segments=1)
        candidates = tuple((language, _score(score)) for language, score in probabilities[:5])
        if any(not 0 <= score <= 1 for _, score in candidates):
            raise TranscriptionError("Model returned an invalid language score")
        windows.append(
            LanguageWindow(
                start,
                end,
                candidates,
                speech_seconds,
                "speech",
                tuple(
                    (start + span["start"] / 16_000, start + span["end"] / 16_000) for span in spans
                ),
            )
        )
    return windows


def _owned_segment(
    segment: SegmentResult, offset: float, start: float, end: float
) -> TranscriptSegment | None:
    words = tuple(
        TranscriptWord(
            start=max(0.0, word.start + offset),
            end=word.end + offset,
            text=word.word,
            confidence=_score(word.probability),
        )
        for word in segment.words or []
        if start <= (word.start + word.end) / 2 + offset < end
    )
    if segment.words:
        if not words:
            return None
        return TranscriptSegment(
            words[0].start, words[-1].end, "".join(w.text for w in words), words=words
        )
    if not start <= (segment.start + segment.end) / 2 + offset < end:
        return None
    return TranscriptSegment(
        max(start, segment.start + offset), min(end, segment.end + offset), segment.text
    )


def bounded_pass(
    source: Path, settings: PassSettings, phase: PhaseCallback | None = None
) -> AcousticPass:
    """One model at a time; no preceding transcript is supplied as a prompt."""
    from faster_whisper import BatchedInferencePipeline, WhisperModel

    if settings.strict_compute_type:
        import ctranslate2  # type: ignore[import-untyped]

        supported = ctranslate2.get_supported_compute_types(settings.device, device_index=0)
        if settings.compute_type not in supported:
            raise TranscriptionError(
                f"Requested compute type {settings.compute_type} is unsupported on {settings.device}; no fallback selected"
            )
    import psutil  # type: ignore[import-untyped]

    from scribe.core.local_whisper import check_model_memory, warn_if_gpu_memory_contended

    free = (
        warn_if_gpu_memory_contended(settings.model)
        if settings.device == "cuda"
        else psutil.virtual_memory().available / 1024**3
    )
    check_model_memory(
        settings.model,
        free,
        device="GPU" if settings.device == "cuda" else "RAM",
        bytes_per_weight=1
        if settings.compute_type.startswith("int8")
        else 2
        if settings.compute_type == "float16"
        else 4,
    )
    started = time.monotonic()
    model: WhisperEngine | None = None
    checkpoint = (
        str(resolve_cached_checkpoint(settings.model))
        if settings.cached_only
        else "turbo"
        if settings.model == "large-v3-turbo"
        else settings.model
    )
    try:
        model = cast(
            WhisperEngine,
            WhisperModel(
                checkpoint,
                device=settings.device,
                compute_type=settings.compute_type,
                cpu_threads=4,
                num_workers=1,
                local_files_only=settings.cached_only,
            ),
        )
        with prepare_review_audio(source, settings.max_seconds) as audio:
            if phase:
                phase(
                    f"Scanning language evidence across recording (elapsed {time.monotonic() - started:.1f}s)"
                )
            scan_error: str | None = None
            try:
                windows = scan_language(model, audio)
            except Exception as error:
                # Preserve an acoustic primary when auxiliary language evidence fails.
                scan_error = f"{type(error).__name__}: {error}"
                windows = [
                    LanguageWindow(start, end, (), 0, "uncertain")
                    for start, end in scan_bounds(audio.duration)
                ]
            regions = decoding_regions(audio.duration, windows, settings.language)
            segments: list[TranscriptSegment] = []
            diagnostics = []
            if phase:
                phase(
                    f"Transcribing bounded acoustic sections (elapsed {time.monotonic() - started:.1f}s)"
                )
            for region in regions:
                offset = max(0.0, region.start - 1)
                values = audio.read(offset, min(audio.duration, region.end + 1))
                options: dict[str, Any] = {
                    "language": region.language,
                    "task": "transcribe",
                    "beam_size": settings.beam_size,
                    "best_of": settings.beam_size,
                    "initial_prompt": settings.prompt or None,
                    "word_timestamps": True,
                    "vad_filter": True,
                    "vad_parameters": {"min_silence_duration_ms": 400},
                }
                if settings.batch_size > 0:
                    # Explicit batching retains its distinct fallback semantics.
                    pipeline = BatchedInferencePipeline(model=model)
                    iterator, _ = pipeline.transcribe(
                        values, batch_size=settings.batch_size, **options
                    )
                else:
                    iterator, _ = model.transcribe(
                        values,
                        temperature=(0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
                        compression_ratio_threshold=2.4,
                        log_prob_threshold=-1.0,
                        no_speech_threshold=0.6,
                        condition_on_previous_text=not region.uncertain,
                        prompt_reset_on_temperature=0.5,
                        **options,
                    )
                for segment in cast(Iterable[SegmentResult], iterator):
                    owned = _owned_segment(segment, offset, region.start, region.end)
                    if owned is None:
                        continue
                    segments.append(owned)
                    diagnostics.append(
                        AcousticDiagnostic(
                            owned.start,
                            owned.end,
                            _score(segment.avg_logprob),
                            _score(segment.no_speech_prob),
                            _score(segment.compression_ratio),
                            _score(segment.temperature or 0.0),
                        )
                    )
            if not segments:
                raise TranscriptionError(
                    "No speech detected in audio; no acoustic transcript was produced"
                )
            languages = {window.stable_language for window in windows} - {None}
            transcript = Transcript(
                segments=segments,
                language=settings.language
                or (next(iter(languages)) if len(languages) == 1 else None),
                duration=audio.duration,
                backend="faster-whisper",
                model=settings.model,
                metadata={
                    "device": settings.device,
                    "compute_type": model.model.compute_type,
                    "beam_size": settings.beam_size,
                    "batch_size": settings.batch_size,
                    "decoding": "bounded regional batched"
                    if settings.batch_size
                    else "bounded regional sequential",
                    "language_mode": "forced" if settings.language else "regional automatic",
                    "requested_language": settings.language,
                    "language_evidence": {
                        "status": "mixed"
                        if len(languages) > 1
                        else "observed"
                        if languages
                        else "uncertain",
                        "languages": sorted(languages),
                    },
                    "initial_prompt_applied": bool(settings.prompt),
                    "checkpoint_revision": None,
                    "checkpoint_path": checkpoint if settings.cached_only else None,
                    "language_scan_error": scan_error,
                    "normalization": "streamed mono float32 PCM at 16000 Hz",
                    "timeline_policy": "relative to media start; cumulative timestamp gaps padded; sample/container timestamp granularity tolerated; overlaps rejected",
                    "runtime_versions": {
                        name: importlib.metadata.version(name)
                        for name in ("faster-whisper", "ctranslate2")
                    },
                    "overlap_policy": "one second context; each word owned by midpoint in original-time cell",
                },
            )
            return AcousticPass(
                transcript,
                windows,
                diagnostics,
                time.monotonic() - started,
                audio.source_sha256,
                str(audio.source_path),
                audio.duration,
            )
    finally:
        if model is not None:
            active_failure = sys.exc_info()[0] is not None
            try:
                model.model.unload_model(to_cpu=False)
            except Exception:
                if not active_failure:
                    raise
            model = None
        gc.collect()
