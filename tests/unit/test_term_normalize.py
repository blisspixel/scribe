"""Tests for deterministic domain-term normalization (utils/term_normalize.py)."""

from scribe.models.transcript import Transcript, TranscriptSegment
from scribe.utils.term_normalize import (
    build_replacements,
    normalize_text,
    normalize_transcript,
    normalize_txt_body,
)

ALIASES = {
    "PostgreSQL": ["post gray sequel", "postgres sql"],
    "Kubernetes": ["cooper netties"],
}


def _reps():
    return build_replacements(ALIASES)


def test_normalizes_known_misrecognitions():
    out = normalize_text("we run post gray sequel and cooper netties", _reps())
    assert out == "we run PostgreSQL and Kubernetes"


def test_is_case_insensitive_and_word_bounded():
    assert normalize_text("Post Gray Sequel rocks", _reps()) == "PostgreSQL rocks"
    # Substring inside a larger word is not replaced.
    assert normalize_text("postgres sqlish", _reps()) == "postgres sqlish"


def test_canonical_self_fixes_capitalization():
    assert normalize_text("use postgresql today", _reps()) == "use PostgreSQL today"


def test_longest_variant_wins_and_no_chaining():
    # "post gray sequel" must win over any shorter overlapping rule, and the
    # produced "PostgreSQL" must not be re-matched.
    reps = build_replacements({"PostgreSQL": ["post gray sequel", "sequel"]})
    assert normalize_text("the post gray sequel", reps) == "the PostgreSQL"


def test_normalize_transcript_rewrites_each_segment():
    t = Transcript(
        segments=[
            TranscriptSegment(0.0, 1.0, "post gray sequel"),
            TranscriptSegment(1.0, 2.0, "no terms here"),
        ],
        backend="faster-whisper",
    )
    out = normalize_transcript(t, ALIASES)
    assert [s.text for s in out.segments] == ["PostgreSQL", "no terms here"]
    # Original untouched.
    assert t.segments[0].text == "post gray sequel"


def test_normalize_txt_body_preserves_header():
    header = "Meeting: post gray sequel demo\nDate: x\n\n" + "─" * 80 + "\n\n"
    body = "we love post gray sequel\n"
    out = normalize_txt_body(header + body, _reps())
    # Header (meeting name) is untouched; only the body below the rule is rewritten.
    assert "Meeting: post gray sequel demo" in out
    assert "we love PostgreSQL" in out


def test_empty_inputs_are_safe():
    assert normalize_text("", _reps()) == ""
    assert normalize_text("hello", []) == "hello"
    assert build_replacements({}) == []
