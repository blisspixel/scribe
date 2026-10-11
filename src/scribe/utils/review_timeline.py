"""Owned time indexes for bounded acoustic comparison queries."""

from bisect import bisect_left
from dataclasses import dataclass

from scribe.models.transcript import Transcript


@dataclass(frozen=True)
class TimedTextIndex:
    midpoints: tuple[float, ...]
    entries: tuple[tuple[int, str], ...]
    starts: tuple[float, ...]
    ends: tuple[float, ...]

    @classmethod
    def build(cls, transcript: Transcript) -> "TimedTextIndex":
        """Read each source segment once; preserve its original text order."""
        timed: list[tuple[float, int, str]] = []
        intervals: list[tuple[float, float]] = []
        for segment in transcript.segments:
            fragments = (
                [(word.start, word.end, word.text) for word in segment.words]
                if segment.words
                else [(segment.start, segment.end, segment.text)]
            )
            for start, end, text in fragments:
                timed.append(((start + end) / 2, len(timed), text))
                if text.strip():
                    intervals.append((start, end))
        timed.sort()
        merged: list[tuple[float, float]] = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                previous = merged.pop()
                merged.append((previous[0], max(previous[1], end)))
            else:
                merged.append((start, end))
        return cls(
            tuple(midpoint for midpoint, _, _ in timed),
            tuple((ordinal, text) for _, ordinal, text in timed),
            tuple(start for start, _ in merged),
            tuple(end for _, end in merged),
        )

    def text_at(self, start: float, end: float) -> str:
        first = bisect_left(self.midpoints, start)
        last = bisect_left(self.midpoints, end)
        return " ".join(text for _, text in sorted(self.entries[first:last])).strip()

    def has_text(self, start: float, end: float) -> bool:
        last = bisect_left(self.starts, end) - 1
        return last >= 0 and self.ends[last] > start
