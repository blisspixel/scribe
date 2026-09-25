"""Tests for word-level speaker alignment and transcript resegmentation."""

from hypothesis import given
from hypothesis import strategies as st

from scribe.core.diarization.alignment import (
    align_diarization,
    align_words,
    resegment_by_words,
    resegment_transcript,
)
from scribe.core.diarization.base import DiarizationResult, SpeakerTurn
from scribe.models.transcript import Transcript, TranscriptSegment, TranscriptWord
from scribe.utils.transcript_writers import transcript_to_dict


def test_align_words_labels_each_word() -> None:
    words = (
        TranscriptWord(start=0.0, end=1.0, text="hello"),
        TranscriptWord(start=1.0, end=2.0, text="world"),
        TranscriptWord(start=5.0, end=6.0, text="later"),
    )
    turns = (
        SpeakerTurn(start=0.0, end=1.2, speaker="SPEAKER_00"),
        SpeakerTurn(start=1.2, end=3.0, speaker="SPEAKER_01"),
    )
    aligned = align_words(words, turns)
    assert len(aligned) == 3
    assert aligned[0].speaker == "SPEAKER_00"
    assert aligned[1].speaker == "SPEAKER_01"
    assert aligned[2].speaker is None


def test_resegment_by_words_splits_multi_speaker_segment() -> None:
    # A single segment where two speakers speak
    words = (
        # Whisper word tokens carry their own leading whitespace.
        TranscriptWord(start=0.0, end=0.8, text=" Can"),
        TranscriptWord(start=0.8, end=1.2, text=" we"),
        TranscriptWord(start=1.2, end=1.8, text=" ship?"),
        TranscriptWord(start=3.0, end=3.5, text=" No,"),
        TranscriptWord(start=3.5, end=4.2, text=" Friday."),
    )
    segment = TranscriptSegment(
        start=0.0,
        end=4.5,
        text="Can we ship? No, Friday.",
        words=words,
    )
    turns = (
        SpeakerTurn(start=0.0, end=2.0, speaker="NICK"),
        SpeakerTurn(start=2.5, end=5.0, speaker="SARAH"),
    )

    subsegments = resegment_by_words(segment, turns)
    assert len(subsegments) == 2
    assert subsegments[0].speaker == "NICK"
    assert subsegments[0].text == "Can we ship?"
    assert subsegments[0].start == 0.0
    assert subsegments[0].end == 1.8

    assert subsegments[1].speaker == "SARAH"
    assert subsegments[1].text == "No, Friday."
    assert subsegments[1].start == 3.0
    assert subsegments[1].end == 4.2


def test_gap_words_inherit_neighbor_speaker_instead_of_splitting() -> None:
    # "the" falls in the silence between two turns of the same speaker.
    words = (
        TranscriptWord(start=0.0, end=0.5, text=" Ship"),
        TranscriptWord(start=0.55, end=0.7, text=" the"),
        TranscriptWord(start=0.8, end=1.2, text=" build."),
    )
    segment = TranscriptSegment(start=0.0, end=1.2, text=" Ship the build.", words=words)
    turns = (
        SpeakerTurn(start=0.0, end=0.52, speaker="SPEAKER_00"),
        SpeakerTurn(start=0.75, end=1.3, speaker="SPEAKER_00"),
    )
    result = resegment_by_words(segment, turns)
    assert len(result) == 1
    assert result[0].speaker == "SPEAKER_00"
    assert all(w.speaker == "SPEAKER_00" for w in result[0].words or ())


def test_single_speaker_segment_keeps_original_text_and_timing() -> None:
    words = (
        TranscriptWord(start=0.1, end=0.5, text=" Hello"),
        TranscriptWord(start=0.5, end=0.9, text=" there."),
    )
    segment = TranscriptSegment(start=0.0, end=1.0, text=" Hello there.", words=words)
    turns = (SpeakerTurn(start=0.0, end=1.0, speaker="SPEAKER_01"),)
    (only,) = resegment_by_words(segment, turns)
    assert only.text == " Hello there."
    assert (only.start, only.end) == (0.0, 1.0)
    assert only.speaker == "SPEAKER_01"


def test_split_text_has_no_spaces_injected_between_cjk_tokens() -> None:
    words = (
        TranscriptWord(start=0.0, end=0.4, text="你好"),
        TranscriptWord(start=0.4, end=0.8, text="世界"),
        TranscriptWord(start=2.0, end=2.4, text="谢谢"),
    )
    segment = TranscriptSegment(start=0.0, end=2.4, text="你好世界谢谢", words=words)
    turns = (
        SpeakerTurn(start=0.0, end=1.0, speaker="SPEAKER_00"),
        SpeakerTurn(start=1.5, end=3.0, speaker="SPEAKER_01"),
    )
    first, second = resegment_by_words(segment, turns)
    assert first.text == "你好世界"
    assert second.text == "谢谢"


def test_resegment_falls_back_gracefully_without_words() -> None:
    segment = TranscriptSegment(
        start=0.0,
        end=3.0,
        text="Whole segment without word timestamps",
        words=None,
    )
    turns = (SpeakerTurn(start=0.0, end=2.5, speaker="SPEAKER_00"),)
    transcript = Transcript(
        segments=[segment],
        duration=3.0,
        backend="faster-whisper",
    )
    resegmented = resegment_transcript(transcript, turns)
    assert len(resegmented.segments) == 1
    assert resegmented.segments[0].speaker == "SPEAKER_00"


def test_align_diarization_records_metadata() -> None:
    segment = TranscriptSegment(start=0.0, end=1.0, text="test")
    transcript = Transcript(segments=[segment], duration=1.0)
    result = DiarizationResult(
        turns=(SpeakerTurn(0.0, 1.0, "SPEAKER_00"),),
        backend="nemotron",
        model="nvidia/Nemotron-3-Diarization",
        speaker_count=1,
        speaker_limit_reached=False,
        metadata={"mode": "offline"},
    )
    aligned = align_diarization(transcript, result)
    assert aligned.segments[0].speaker == "SPEAKER_00"
    assert "diarization" in aligned.metadata
    assert aligned.metadata["diarization"]["backend"] == "nemotron"
    assert aligned.metadata["diarization"]["model"] == "nvidia/Nemotron-3-Diarization"
    assert aligned.metadata["diarization"]["speaker_count"] == 1


def test_transcript_to_dict_serializes_words() -> None:
    words = (
        TranscriptWord(start=0.0, end=0.5, text="Hello", speaker="SPEAKER_00"),
        TranscriptWord(start=0.5, end=1.0, text="world", speaker="SPEAKER_00"),
    )
    segment = TranscriptSegment(
        start=0.0,
        end=1.0,
        text="Hello world",
        speaker="SPEAKER_00",
        words=words,
    )
    transcript = Transcript(segments=[segment], duration=1.0)
    d = transcript_to_dict(transcript)
    seg_data = d["segments"][0]
    assert "words" in seg_data
    assert len(seg_data["words"]) == 2
    assert seg_data["words"][0]["text"] == "Hello"
    assert seg_data["words"][0]["speaker"] == "SPEAKER_00"


@given(
    words_data=st.lists(
        st.tuples(
            st.floats(min_value=0.0, max_value=50.0),
            st.floats(min_value=0.1, max_value=2.0),
            st.sampled_from(["cat", "dog", "fox"]),
        ),
        min_size=1,
        max_size=10,
    ),
    turns_data=st.lists(
        st.tuples(
            st.floats(min_value=0.0, max_value=60.0),
            st.floats(min_value=0.1, max_value=5.0),
            st.sampled_from(["SPEAKER_00", "SPEAKER_01"]),
        ),
        min_size=0,
        max_size=5,
    ),
)
def test_word_resegmentation_is_total_and_deterministic(
    words_data: list[tuple[float, float, str]],
    turns_data: list[tuple[float, float, str]],
) -> None:
    # Construct strictly monotonic non-overlapping words
    words: list[TranscriptWord] = []
    curr = 0.0
    for offset, dur, text in words_data:
        start = curr + offset
        end = start + dur
        words.append(TranscriptWord(start=start, end=end, text=text))
        curr = end + 0.01

    turns = [
        SpeakerTurn(start=start, end=start + dur, speaker=spk) for start, dur, spk in turns_data
    ]

    segment = TranscriptSegment(
        start=words[0].start,
        end=words[-1].end,
        text=" ".join(w.text for w in words),
        words=tuple(words),
    )
    transcript = Transcript(segments=[segment], duration=words[-1].end)

    resegmented1 = resegment_transcript(transcript, turns)
    resegmented2 = resegment_transcript(transcript, turns)

    assert len(resegmented1.segments) >= 1
    # No word is dropped or duplicated by resegmentation.
    out_words = [w for s in resegmented1.segments for w in (s.words or ())]
    assert [(w.start, w.text) for w in out_words] == [(w.start, w.text) for w in words]
    # Determinism
    assert [s.speaker for s in resegmented1.segments] == [s.speaker for s in resegmented2.segments]
    assert [s.text for s in resegmented1.segments] == [s.text for s in resegmented2.segments]
