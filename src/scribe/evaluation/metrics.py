"""Deterministic corpus metrics for transcription evaluation.

The evaluator deliberately separates measurement from model execution. A run
records reference text, hypothesis text, audio duration, and processing time;
this module then computes micro-averaged word error rate and real-time factor
without loading any transcription backend.
"""

from __future__ import annotations

import math
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class NormalizationConfig:
    """Explicit text normalization policy used before word alignment."""

    case_sensitive: bool = False
    strip_punctuation: bool = True


@dataclass(frozen=True, slots=True)
class EvaluationSample:
    """One measured transcription and the timing needed to reproduce its score."""

    sample_id: str
    reference: str
    hypothesis: str
    audio_seconds: float
    processing_seconds: float
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.sample_id.strip():
            raise ValueError("sample_id must not be blank")
        if not math.isfinite(self.audio_seconds) or self.audio_seconds <= 0:
            raise ValueError("audio_seconds must be finite and greater than zero")
        if not math.isfinite(self.processing_seconds) or self.processing_seconds < 0:
            raise ValueError("processing_seconds must be finite and not negative")


@dataclass(frozen=True, slots=True)
class SampleEvaluation:
    """Word-level accuracy and performance result for one sample."""

    sample_id: str
    reference_words: int
    hypothesis_words: int
    word_errors: int
    word_error_rate: float | None
    real_time_factor: float
    exact_match: bool
    metadata: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.sample_id,
            "reference_words": self.reference_words,
            "hypothesis_words": self.hypothesis_words,
            "word_errors": self.word_errors,
            "word_error_rate": self.word_error_rate,
            "real_time_factor": self.real_time_factor,
            "exact_match": self.exact_match,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class CorpusEvaluation:
    """Micro-averaged corpus result with per-sample evidence."""

    sample_count: int
    reference_words: int
    word_errors: int
    word_error_rate: float
    audio_seconds: float
    processing_seconds: float
    real_time_factor: float
    exact_match_rate: float
    samples: tuple[SampleEvaluation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "reference_words": self.reference_words,
            "word_errors": self.word_errors,
            "word_error_rate": self.word_error_rate,
            "audio_seconds": self.audio_seconds,
            "processing_seconds": self.processing_seconds,
            "real_time_factor": self.real_time_factor,
            "exact_match_rate": self.exact_match_rate,
            "samples": [sample.to_dict() for sample in self.samples],
        }


def normalize_words(text: str, config: NormalizationConfig | None = None) -> tuple[str, ...]:
    """Normalize text into the explicit token stream used for scoring."""
    policy = config or NormalizationConfig()
    normalized = unicodedata.normalize("NFKC", text)
    if not policy.case_sensitive:
        normalized = normalized.casefold()
    if policy.strip_punctuation:
        normalized = "".join(
            " " if unicodedata.category(character).startswith("P") else character
            for character in normalized
        )
    return tuple(normalized.split())


def word_edit_distance(reference: tuple[str, ...], hypothesis: tuple[str, ...]) -> int:
    """Return Levenshtein distance using memory linear in the shorter sequence."""
    if len(reference) < len(hypothesis):
        shorter, longer = reference, hypothesis
    else:
        shorter, longer = hypothesis, reference

    previous = list(range(len(shorter) + 1))
    for longer_index, longer_word in enumerate(longer, start=1):
        current = [longer_index]
        for shorter_index, shorter_word in enumerate(shorter, start=1):
            substitution_cost = 0 if longer_word == shorter_word else 1
            current.append(
                min(
                    current[-1] + 1,
                    previous[shorter_index] + 1,
                    previous[shorter_index - 1] + substitution_cost,
                )
            )
        previous = current
    return previous[-1]


def evaluate_samples(
    samples: Iterable[EvaluationSample],
    normalization: NormalizationConfig | None = None,
) -> CorpusEvaluation:
    """Compute micro WER and real-time factor for a non-empty corpus."""
    materialized = tuple(samples)
    if not materialized:
        raise ValueError("at least one evaluation sample is required")

    results: list[SampleEvaluation] = []
    total_reference_words = 0
    total_word_errors = 0
    total_audio_seconds = 0.0
    total_processing_seconds = 0.0
    exact_matches = 0

    for sample in materialized:
        reference_words = normalize_words(sample.reference, normalization)
        hypothesis_words = normalize_words(sample.hypothesis, normalization)
        errors = word_edit_distance(reference_words, hypothesis_words)
        reference_count = len(reference_words)
        is_exact = reference_words == hypothesis_words
        results.append(
            SampleEvaluation(
                sample_id=sample.sample_id,
                reference_words=reference_count,
                hypothesis_words=len(hypothesis_words),
                word_errors=errors,
                word_error_rate=errors / reference_count if reference_count else None,
                real_time_factor=sample.processing_seconds / sample.audio_seconds,
                exact_match=is_exact,
                metadata=dict(sample.metadata),
            )
        )
        total_reference_words += reference_count
        total_word_errors += errors
        total_audio_seconds += sample.audio_seconds
        total_processing_seconds += sample.processing_seconds
        exact_matches += int(is_exact)

    if total_reference_words == 0:
        raise ValueError("the corpus must contain at least one reference word")

    return CorpusEvaluation(
        sample_count=len(materialized),
        reference_words=total_reference_words,
        word_errors=total_word_errors,
        word_error_rate=total_word_errors / total_reference_words,
        audio_seconds=total_audio_seconds,
        processing_seconds=total_processing_seconds,
        real_time_factor=total_processing_seconds / total_audio_seconds,
        exact_match_rate=exact_matches / len(materialized),
        samples=tuple(results),
    )
