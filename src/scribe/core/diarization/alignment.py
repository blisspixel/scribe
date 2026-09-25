"""Pure alignment math mapping diarization speaker activity onto transcripts.

Keeps model execution and alignment math completely decoupled.
Supports both segment-level dominant speaker attribution and fine-grained
word-level timestamp reconciliation & resegmentation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from scribe.core.diarization.base import DiarizationResult, SpeakerTurn
from scribe.models.transcript import Transcript, TranscriptSegment, TranscriptWord


def _union_length(intervals: list[tuple[float, float]]) -> float:
    """Total length covered by a set of intervals, counting overlaps once."""
    if not intervals:
        return 0.0
    ordered = sorted(intervals)
    total = 0.0
    cur_lo, cur_hi = ordered[0]
    for lo, hi in ordered[1:]:
        if lo > cur_hi:
            total += cur_hi - cur_lo
            cur_lo, cur_hi = lo, hi
        else:
            cur_hi = max(cur_hi, hi)
    total += cur_hi - cur_lo
    return total


def dominant_speaker(start: float, end: float, turns: Sequence[SpeakerTurn]) -> str | None:
    """The speaker whose turns cover [start, end] the most, or None.

    Per-speaker coverage is the union length of that speaker's turns clipped to the
    segment, so overlapping same-speaker turns are counted once rather than
    double-counted. Ties keep the earliest turn's speaker, making the result
    deterministic given sorted turns.
    """
    clipped: dict[str, list[tuple[float, float]]] = {}
    order: dict[str, int] = {}
    for index, turn in enumerate(turns):
        lo = max(start, turn.start)
        hi = min(end, turn.end)
        if hi > lo:
            clipped.setdefault(turn.speaker, []).append((lo, hi))
            order.setdefault(turn.speaker, index)
    if not clipped:
        return None
    totals = {speaker: _union_length(intervals) for speaker, intervals in clipped.items()}
    # Most coverage wins; earliest-appearing speaker breaks ties.
    return min(totals, key=lambda s: (-totals[s], order[s]))


def assign_speakers(transcript: Transcript, turns: Sequence[SpeakerTurn]) -> Transcript:
    """Return a copy of ``transcript`` with each segment's dominant speaker set.

    Segment-level assignment preserved for backward compatibility and for backends
    that do not produce word timestamps.
    """
    ordered = sorted(turns, key=lambda t: (t.start, t.end))
    labeled: list[TranscriptSegment] = [
        replace(segment, speaker=dominant_speaker(segment.start, segment.end, ordered))
        for segment in transcript.segments
    ]
    return replace(transcript, segments=labeled)


def align_words(
    words: Sequence[TranscriptWord], ordered_turns: Sequence[SpeakerTurn]
) -> tuple[TranscriptWord, ...]:
    """Assign speaker labels to individual words based on overlap with speaker turns."""
    labeled_words: list[TranscriptWord] = []
    for w in words:
        speaker = dominant_speaker(w.start, w.end, ordered_turns)
        labeled_words.append(replace(w, speaker=speaker))
    return tuple(labeled_words)


def _fill_unlabeled(words: Sequence[TranscriptWord]) -> tuple[TranscriptWord, ...]:
    """Give words that fall in a gap between turns the nearest labeled neighbor's speaker.

    Diarizers leave short silences between turns, and a word straddling one would
    otherwise get no speaker and split its sentence. A word inherits the previous
    word's speaker, or the next labeled word's speaker at the start of a segment.
    Words stay unlabeled only when no word in the sequence has a speaker.
    """
    filled = list(words)
    previous: str | None = None
    for index, word in enumerate(filled):
        if word.speaker is None and previous is not None:
            filled[index] = replace(word, speaker=previous)
        previous = filled[index].speaker or previous
    following: str | None = None
    for index in range(len(filled) - 1, -1, -1):
        if filled[index].speaker is None and following is not None:
            filled[index] = replace(filled[index], speaker=following)
        following = filled[index].speaker or following
    return tuple(filled)


def _words_text(words: Sequence[TranscriptWord]) -> str:
    """Rebuild text from word tokens.

    Whisper word tokens carry their own leading whitespace, so concatenation keeps
    spacing correct for languages written without spaces between words.
    """
    return "".join(w.text for w in words).strip()


def resegment_by_words(
    segment: TranscriptSegment, ordered_turns: Sequence[SpeakerTurn]
) -> list[TranscriptSegment]:
    """Split a segment into speaker-homogeneous segments using word timestamps.

    Falls back to the segment's dominant speaker when it has no words. A segment
    spoken entirely by one speaker keeps its original text and timing.
    """
    if not segment.words:
        return [
            replace(segment, speaker=dominant_speaker(segment.start, segment.end, ordered_turns))
        ]

    labeled_words = _fill_unlabeled(align_words(segment.words, ordered_turns))
    speakers = {w.speaker for w in labeled_words}
    if len(speakers) == 1:
        (only,) = speakers
        speaker = only or dominant_speaker(segment.start, segment.end, ordered_turns)
        return [replace(segment, speaker=speaker, words=labeled_words)]

    # Group consecutive words sharing the same speaker into subsegments.
    groups: list[list[TranscriptWord]] = [[labeled_words[0]]]
    for word in labeled_words[1:]:
        if word.speaker == groups[-1][-1].speaker:
            groups[-1].append(word)
        else:
            groups.append([word])

    return [
        TranscriptSegment(
            start=group[0].start,
            end=group[-1].end,
            text=_words_text(group),
            speaker=group[0].speaker,
            confidence=segment.confidence,
            words=tuple(group),
        )
        for group in groups
        if _words_text(group)
    ]


def resegment_transcript(transcript: Transcript, turns: Sequence[SpeakerTurn]) -> Transcript:
    """Return a transcript resegmented into speaker-homogeneous segments when words exist.

    If segments contain word timestamps, turns are aligned at word boundaries,
    splitting single segments where multiple speakers converse. If words are
    absent, falls back cleanly to segment-level dominant speaker attribution.
    """
    ordered = sorted(turns, key=lambda t: (t.start, t.end))
    new_segments: list[TranscriptSegment] = []

    for seg in transcript.segments:
        if seg.words:
            new_segments.extend(resegment_by_words(seg, ordered))
        else:
            new_segments.append(replace(seg, speaker=dominant_speaker(seg.start, seg.end, ordered)))

    return replace(transcript, segments=new_segments)


def align_diarization(
    transcript: Transcript,
    result: DiarizationResult,
    *,
    prefer_word_alignment: bool = True,
) -> Transcript:
    """Apply a DiarizationResult onto a Transcript and record provenance in metadata."""
    if not result.turns:
        # Record diarization metadata even if no speech was detected
        meta = dict(transcript.metadata)
        meta["diarization"] = {
            "backend": result.backend,
            "model": result.model,
            "speaker_count": 0,
            "speaker_limit_reached": False,
            **(result.metadata or {}),
        }
        return replace(transcript, metadata=meta)

    aligned = (
        resegment_transcript(transcript, result.turns)
        if prefer_word_alignment
        else assign_speakers(transcript, result.turns)
    )

    meta = dict(aligned.metadata)
    meta["diarization"] = {
        "backend": result.backend,
        "model": result.model,
        "speaker_count": result.speaker_count,
        "speaker_limit_reached": result.speaker_limit_reached,
        **(result.metadata or {}),
    }
    return replace(aligned, metadata=meta)
