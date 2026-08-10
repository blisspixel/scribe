"""Tests for deterministic transcription evaluation metrics."""

import json

import pytest

from scribe.evaluation import (
    EvaluationSample,
    NormalizationConfig,
    evaluate_samples,
    normalize_words,
    word_edit_distance,
)


def test_normalize_words_has_explicit_unicode_case_and_punctuation_policy() -> None:
    assert normalize_words("Hello, WORLD!") == ("hello", "world")
    assert normalize_words(
        "Hello, WORLD!",
        NormalizationConfig(case_sensitive=True, strip_punctuation=False),
    ) == ("Hello,", "WORLD!")


@pytest.mark.parametrize(
    ("reference", "hypothesis", "expected"),
    [
        (("the", "cat"), ("the", "cat"), 0),
        (("the", "cat"), ("the", "dog"), 1),
        (("the", "cat"), ("the", "small", "cat"), 1),
        (("the", "small", "cat"), ("the", "cat"), 1),
        ((), ("unexpected",), 1),
    ],
)
def test_word_edit_distance(reference, hypothesis, expected) -> None:
    assert word_edit_distance(reference, hypothesis) == expected


def test_evaluate_samples_micro_averages_wer_and_real_time_factor() -> None:
    evaluation = evaluate_samples(
        [
            EvaluationSample("a", "the cat sat", "the dog sat", 10.0, 1.0),
            EvaluationSample(
                "b",
                "hello world",
                "hello brave world",
                5.0,
                0.5,
                metadata={"backend": "local"},
            ),
        ]
    )

    assert evaluation.sample_count == 2
    assert evaluation.reference_words == 5
    assert evaluation.word_errors == 2
    assert evaluation.word_error_rate == pytest.approx(0.4)
    assert evaluation.real_time_factor == pytest.approx(0.1)
    assert evaluation.exact_match_rate == 0.0
    assert evaluation.samples[1].metadata == {"backend": "local"}
    json.dumps(evaluation.to_dict())


def test_empty_reference_is_reported_without_non_finite_json() -> None:
    evaluation = evaluate_samples(
        [
            EvaluationSample("silence", "", "noise", 1.0, 0.1),
            EvaluationSample("speech", "hello", "hello", 1.0, 0.1),
        ]
    )

    assert evaluation.samples[0].word_error_rate is None
    assert evaluation.word_error_rate == 1.0


def test_evaluation_sample_rejects_invalid_measurements() -> None:
    with pytest.raises(ValueError, match="sample_id"):
        EvaluationSample("", "a", "a", 1.0, 1.0)
    with pytest.raises(ValueError, match="audio_seconds"):
        EvaluationSample("a", "a", "a", 0.0, 1.0)
    with pytest.raises(ValueError, match="processing_seconds"):
        EvaluationSample("a", "a", "a", 1.0, -1.0)
    with pytest.raises(ValueError, match="audio_seconds"):
        EvaluationSample("a", "a", "a", float("nan"), 1.0)
    with pytest.raises(ValueError, match="processing_seconds"):
        EvaluationSample("a", "a", "a", 1.0, float("inf"))


def test_evaluate_samples_requires_reference_evidence() -> None:
    with pytest.raises(ValueError, match="at least one evaluation sample"):
        evaluate_samples([])
    with pytest.raises(ValueError, match="at least one reference word"):
        evaluate_samples([EvaluationSample("silence", "", "", 1.0, 0.1)])
