"""Numeric meaning, time index equivalence, and long-recording comparison work."""

from dataclasses import replace

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scribe.core.language_evidence import scan_bounds
from scribe.models.transcript import Transcript, TranscriptSegment, TranscriptWord
from scribe.models.transcription_review import LanguageWindow
from scribe.utils.review_timeline import TimedTextIndex
from scribe.utils.transcript_review import compare_passes
from tests.unit.test_transcription_review import acoustic, audio_file, transcript


@pytest.mark.parametrize(
    "first,second",
    [
        ("-15", "15"),
        ("+15", "-15"),
        ("15%", "15"),
        ("$15", "15"),
        ("€15", "$15"),
        ("€15", "15"),
        ("15€", "15"),
        ("15€", "15$"),
        ("15\u066a", "15"),
        ("-$15", "+$15"),
        ("±15", "15"),
        ("15‰", "15%"),
        ("₹15.5", "₹15.6"),
        ("\u221215", "15"),
    ],
)
def test_attached_numeric_semantics_require_review(tmp_path, first, second):
    source = audio_file(tmp_path / "source.wav")
    spans = compare_passes(
        transcript("The value is " + first), acoustic(source, "The value is " + second)
    )
    assert any("numeric disagreement" in span.reasons for span in spans)


@pytest.mark.parametrize(
    "first,second",
    [
        ("Hello, world!", "hello world"),
        ("The value is $15.", "the value is $15"),
        ("The value is \u221215", "the value is -15"),
        ("The value is \uff04\uff11\uff15\uff05", "the value is $15%"),
        ("The value is 15€.", "the value is 15€"),
        ("The value is \uff11\uff15\uff04", "the value is 15$"),
    ],
)
def test_ordinary_punctuation_and_unicode_numeric_controls(tmp_path, first, second):
    source = audio_file(tmp_path / "source.wav")
    assert compare_passes(transcript(first), acoustic(source, second)) == []


@given(
    st.lists(
        st.tuples(
            st.integers(0, 300),
            st.integers(0, 40),
            st.sampled_from(["one", "two", "", " "]),
            st.booleans(),
        ),
        max_size=30,
    ),
    st.integers(0, 300),
    st.integers(1, 50),
)
def test_index_preserves_midpoint_order_and_exact_overlap(items, start, length):
    end = start + length
    fragments = [(a, a + duration, text) for a, duration, text, _ in items]
    primary = Transcript(
        [
            TranscriptSegment(
                a,
                a + duration,
                text,
                words=(TranscriptWord(a, a + duration, text),) if words else None,
            )
            for a, duration, text, words in items
        ]
    )
    index = TimedTextIndex.build(primary)
    expected_text = " ".join(text for a, b, text in fragments if start <= (a + b) / 2 < end).strip()
    expected_overlap = any(text.strip() and a < end and b > start for a, b, text in fragments)
    assert index.text_at(start, end) == expected_text
    assert index.has_text(start, end) == expected_overlap


def test_four_hour_comparison_reads_each_source_segment_once(tmp_path):
    class CountedSegments(list):
        visits = 0

        def __iter__(self):
            for segment in super().__iter__():
                self.visits += 1
                yield segment

    duration = 4 * 3600
    segments = [
        TranscriptSegment(
            start,
            start + 5,
            " ".join(f"word{i}" for i in range(10)),
            words=tuple(
                TranscriptWord(start + i / 2, start + (i + 1) / 2, f"word{i}") for i in range(10)
            ),
        )
        for start in range(0, duration, 5)
    ]
    left, right = CountedSegments(segments), CountedSegments(segments)
    primary = Transcript(left, duration=duration)
    secondary = replace(
        acoustic(audio_file(tmp_path / "source.wav")),
        transcript=Transcript(right, duration=duration),
        normalized_seconds=duration,
        windows=[
            LanguageWindow(start, end, (("en", 0.95),), end - start, "speech", ((start, end),))
            for start, end in scan_bounds(duration)
        ],
    )
    assert compare_passes(primary, secondary) == []
    assert left.visits == right.visits == len(segments)
