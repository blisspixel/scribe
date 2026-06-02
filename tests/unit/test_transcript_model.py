"""Tests for the shared Transcript domain model (models/transcript.py)."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scribe.models.transcript import Transcript, TranscriptSegment, TranscriptWord


def test_segment_rejects_end_before_start():
    with pytest.raises(ValueError, match="must be >= start"):
        TranscriptSegment(start=5.0, end=1.0, text="x")


def test_segment_rejects_negative_start():
    with pytest.raises(ValueError, match="non-negative"):
        TranscriptSegment(start=-1.0, end=1.0, text="x")


@pytest.mark.parametrize("bad", [-0.1, 1.1, 2.0])
def test_confidence_out_of_range_rejected(bad):
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        TranscriptSegment(start=0.0, end=1.0, text="x", confidence=bad)
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        TranscriptWord(start=0.0, end=1.0, text="x", confidence=bad)


def test_speakers_first_appearance_order_and_dedup():
    t = Transcript(
        segments=[
            TranscriptSegment(0.0, 1.0, "a", speaker="S2"),
            TranscriptSegment(1.0, 2.0, "b", speaker="S1"),
            TranscriptSegment(2.0, 3.0, "c", speaker="S2"),
            TranscriptSegment(3.0, 4.0, "d", speaker=None),
        ]
    )
    assert t.speakers == ["S2", "S1"]
    assert t.has_speakers is True


def test_text_joins_nonblank_segments():
    t = Transcript(
        segments=[
            TranscriptSegment(0.0, 1.0, "  hello "),
            TranscriptSegment(1.0, 2.0, "   "),
            TranscriptSegment(2.0, 3.0, "world"),
        ]
    )
    assert t.text() == "hello world"


def test_iter_speaker_turns_groups_consecutive():
    segs = [
        TranscriptSegment(0.0, 1.0, "a", speaker="S1"),
        TranscriptSegment(1.0, 2.0, "b", speaker="S1"),
        TranscriptSegment(2.0, 3.0, "c", speaker="S2"),
        TranscriptSegment(3.0, 4.0, "d", speaker="S1"),
    ]
    turns = list(Transcript(segments=segs).iter_speaker_turns())
    assert [(spk, len(group)) for spk, group in turns] == [("S1", 2), ("S2", 1), ("S1", 1)]
    # Every segment appears exactly once across the turns.
    assert sum(len(group) for _, group in turns) == len(segs)


@st.composite
def _segments(draw):
    n = draw(st.integers(min_value=0, max_value=12))
    out = []
    for _ in range(n):
        start = draw(st.floats(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False))
        length = draw(st.floats(min_value=0, max_value=60, allow_nan=False, allow_infinity=False))
        speaker = draw(st.sampled_from([None, "S1", "S2", "S3"]))
        out.append(TranscriptSegment(start=start, end=start + length, text="word", speaker=speaker))
    return out


@given(_segments())
def test_speakers_is_subset_in_order(segs):
    t = Transcript(segments=segs)
    # Distinct, in first-appearance order, and a subset of the labels present.
    assert len(t.speakers) == len(set(t.speakers))
    present = [s.speaker for s in segs if s.speaker]
    for label in t.speakers:
        assert label in present


@given(_segments())
def test_speaker_turns_cover_all_segments_once(segs):
    t = Transcript(segments=segs)
    flat = [s for _, group in t.iter_speaker_turns() for s in group]
    assert flat == segs
