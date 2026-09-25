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


#: A different-speaker run inside a sentence at or under these bounds is treated as
#: diarization jitter at a turn edge and takes the sentence's majority speaker.
_ISLAND_MAX_WORDS = 3
_ISLAND_MAX_SECONDS = 1.0
#: Sentences this short are attributed to a single speaker.
_SHORT_SENTENCE_WORDS = 8
#: A pause longer than this also ends a sentence (NeMo uses the same 1 s break).
_SENTENCE_PAUSE = 1.0
#: Longer unpunctuated runs are not treated as one sentence.
_MAX_SENTENCE_WORDS = 60
# Latin plus CJK full stop, question mark, and exclamation mark.
_SENTENCE_END = (".", "?", "!", chr(0x3002), chr(0xFF1F), chr(0xFF01))


def _sentences(words: Sequence[TranscriptWord]) -> list[range]:
    """Index ranges of sentences: split at sentence punctuation or a pause over 1 s."""
    ranges: list[range] = []
    start = 0
    for index, word in enumerate(words):
        at_end = word.text.strip().endswith(_SENTENCE_END)
        pause = index + 1 < len(words) and words[index + 1].start - word.end > _SENTENCE_PAUSE
        if at_end or pause or index - start + 1 >= _MAX_SENTENCE_WORDS:
            ranges.append(range(start, index + 1))
            start = index + 1
    if start < len(words):
        ranges.append(range(start, len(words)))
    return ranges


def smooth_word_speakers(words: Sequence[TranscriptWord]) -> tuple[TranscriptWord, ...]:
    """Remove speaker flips that are diarization jitter rather than real turns.

    Diarizers are least certain at turn edges, so word-level assignment can hand
    one to three words of a sentence to the wrong person ("Is" / "he?"). Within
    each sentence, short sentences take their majority speaker (by speaking time)
    and short minority runs in longer sentences are absorbed into the majority.
    Sentences are never merged, so a one-word backchannel such as "Yeah." from
    another participant is kept.
    """
    smoothed = list(words)
    for sentence in _sentences(smoothed):
        members = [smoothed[i] for i in sentence]
        durations: dict[str, float] = {}
        for word in members:
            if word.speaker is not None:
                durations[word.speaker] = durations.get(word.speaker, 0.0) + max(
                    word.end - word.start, 0.01
                )
        if len(durations) < 2:
            continue
        majority = max(durations, key=lambda speaker: durations[speaker])
        if len(members) <= _SHORT_SENTENCE_WORDS:
            for i in sentence:
                smoothed[i] = replace(smoothed[i], speaker=majority)
            continue
        # Absorb short minority runs into the sentence majority.
        run_start = sentence.start
        for i in range(sentence.start, sentence.stop + 1):
            boundary = i == sentence.stop or smoothed[i].speaker != smoothed[run_start].speaker
            if not boundary:
                continue
            run = range(run_start, i)
            speaker = smoothed[run_start].speaker
            seconds = smoothed[i - 1].end - smoothed[run_start].start
            if speaker != majority and (
                len(run) <= _ISLAND_MAX_WORDS or seconds <= _ISLAND_MAX_SECONDS
            ):
                for j in run:
                    smoothed[j] = replace(smoothed[j], speaker=majority)
            run_start = i
    return tuple(smoothed)


def _words_text(words: Sequence[TranscriptWord]) -> str:
    """Rebuild text from word tokens.

    Whisper word tokens carry their own leading whitespace, so concatenation keeps
    spacing correct for languages written without spaces between words.
    """
    return "".join(w.text for w in words).strip()


def _split_by_speaker(
    segment: TranscriptSegment, labeled_words: Sequence[TranscriptWord]
) -> list[TranscriptSegment]:
    """Split a segment's labeled words into speaker-homogeneous segments.

    A segment spoken entirely by one speaker keeps its original text and timing.
    """
    speakers = {w.speaker for w in labeled_words}
    if len(speakers) == 1:
        (only,) = speakers
        return [replace(segment, speaker=only, words=tuple(labeled_words))]

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


def label_words(
    words: Sequence[TranscriptWord], ordered_turns: Sequence[SpeakerTurn]
) -> tuple[TranscriptWord, ...]:
    """Label, gap-fill, and smooth a word sequence against sorted speaker turns."""
    return smooth_word_speakers(_fill_unlabeled(align_words(words, ordered_turns)))


def resegment_by_words(
    segment: TranscriptSegment, ordered_turns: Sequence[SpeakerTurn]
) -> list[TranscriptSegment]:
    """Split a segment into speaker-homogeneous segments using word timestamps.

    Falls back to the segment's dominant speaker when it has no words.
    """
    if not segment.words:
        return [
            replace(segment, speaker=dominant_speaker(segment.start, segment.end, ordered_turns))
        ]
    return _split_by_speaker(segment, label_words(segment.words, ordered_turns))


def resegment_transcript(transcript: Transcript, turns: Sequence[SpeakerTurn]) -> Transcript:
    """Return a transcript resegmented into speaker-homogeneous segments.

    Words from every segment are labeled and smoothed as one sequence, because
    sentences (and the jitter around turn edges) often cross segment boundaries.
    Segments without word timestamps fall back to segment-level attribution.
    """
    ordered = sorted(turns, key=lambda t: (t.start, t.end))
    all_words = [w for seg in transcript.segments for w in (seg.words or ())]
    labeled = iter(label_words(all_words, ordered))

    new_segments: list[TranscriptSegment] = []
    for seg in transcript.segments:
        if seg.words:
            seg_words = [next(labeled) for _ in seg.words]
            new_segments.extend(_split_by_speaker(seg, seg_words))
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
