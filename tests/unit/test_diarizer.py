"""Tests for local speaker diarization alignment (core/diarizer.py).

The pyannote pipeline itself is not exercised here (it needs a model download, a
Hugging Face token, and ideally a GPU). What is tested is the pure alignment that
maps speaker turns onto transcript segments, plus the graceful-degradation
behavior, which is the platform-independent surface that matters for correctness.
"""

from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from scribe.core.diarizer import (
    LocalDiarizer,
    SpeakerTurn,
    assign_speakers,
    dominant_speaker,
)
from scribe.models.transcript import Transcript, TranscriptSegment


def _transcript(*spans: tuple[float, float, str]) -> Transcript:
    return Transcript(
        segments=[TranscriptSegment(start=s, end=e, text=t) for s, e, t in spans],
        duration=spans[-1][1] if spans else 0.0,
        backend="faster-whisper",
    )


def test_dominant_speaker_picks_max_overlap():
    turns = [SpeakerTurn(0.0, 2.0, "A"), SpeakerTurn(2.0, 5.0, "B")]
    # Mostly inside B.
    assert dominant_speaker(1.8, 4.0, turns) == "B"
    # Entirely inside A.
    assert dominant_speaker(0.0, 1.5, turns) == "A"
    # No overlap at all.
    assert dominant_speaker(10.0, 11.0, turns) is None


def test_dominant_speaker_sums_overlap_across_turns():
    # A holds two short turns that together beat B's single longer one.
    turns = [
        SpeakerTurn(0.0, 1.0, "A"),
        SpeakerTurn(1.0, 2.4, "B"),
        SpeakerTurn(2.4, 3.4, "A"),
    ]
    # Segment 0..3.4 overlaps A for 2.0s total, B for 1.4s -> A.
    assert dominant_speaker(0.0, 3.4, turns) == "A"


def test_assign_speakers_labels_every_segment():
    transcript = _transcript((0.0, 1.0, "hi"), (1.0, 3.0, "there"), (9.0, 10.0, "gap"))
    turns = [SpeakerTurn(0.0, 1.2, "SPEAKER_00"), SpeakerTurn(1.2, 3.0, "SPEAKER_01")]
    labeled = assign_speakers(transcript, turns)

    assert [s.speaker for s in labeled.segments] == ["SPEAKER_00", "SPEAKER_01", None]
    # Original is untouched (frozen dataclasses, new instances returned).
    assert all(s.speaker is None for s in transcript.segments)
    # Other fields preserved.
    assert [s.text for s in labeled.segments] == ["hi", "there", "gap"]
    assert labeled.speakers == ["SPEAKER_00", "SPEAKER_01"]


def test_assign_speakers_empty_turns_leaves_unlabeled():
    transcript = _transcript((0.0, 1.0, "hi"))
    labeled = assign_speakers(transcript, [])
    assert labeled.segments[0].speaker is None
    assert labeled.has_speakers is False


@given(
    segs=st.lists(
        st.tuples(st.floats(0, 100), st.floats(0, 5)).map(lambda p: (p[0], p[0] + p[1])),
        min_size=0,
        max_size=8,
    ),
    turns=st.lists(
        st.tuples(st.floats(0, 100), st.floats(0, 5), st.sampled_from(["A", "B", "C"])).map(
            lambda t: SpeakerTurn(t[0], t[0] + t[1], t[2])
        ),
        min_size=0,
        max_size=8,
    ),
)
def test_assign_speakers_is_total_and_consistent(segs, turns):
    transcript = _transcript(*[(s, e, "x") for s, e in segs])
    labeled = assign_speakers(transcript, turns)
    # Totality: same number of segments, each label is a known speaker or None.
    assert len(labeled.segments) == len(transcript.segments)
    valid = {t.speaker for t in turns} | {None}
    assert all(s.speaker in valid for s in labeled.segments)
    # Determinism.
    again = assign_speakers(transcript, turns)
    assert [s.speaker for s in again.segments] == [s.speaker for s in labeled.segments]


def test_local_diarizer_not_available_here():
    # pyannote.audio is not installed in the test environment.
    assert LocalDiarizer.is_available() is False


def test_apply_is_noop_when_pipeline_yields_nothing(tmp_path: Path):
    transcript = _transcript((0.0, 1.0, "hi"))
    diarizer = LocalDiarizer("fake-token")

    # Simulate an unavailable/failed pipeline: no turns.
    diarizer._run_pipeline = lambda _p: []  # type: ignore[method-assign]
    result = diarizer.apply(tmp_path / "a.wav", transcript)
    assert result is transcript  # unchanged, not relabeled


def test_apply_labels_when_pipeline_returns_turns(tmp_path: Path):
    transcript = _transcript((0.0, 1.0, "hi"), (1.0, 2.0, "you"))
    diarizer = LocalDiarizer("fake-token")
    diarizer._run_pipeline = lambda _p: [  # type: ignore[method-assign]
        SpeakerTurn(0.0, 1.0, "SPEAKER_00"),
        SpeakerTurn(1.0, 2.0, "SPEAKER_01"),
    ]
    result = diarizer.apply(tmp_path / "a.wav", transcript)
    assert [s.speaker for s in result.segments] == ["SPEAKER_00", "SPEAKER_01"]
