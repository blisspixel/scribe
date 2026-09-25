"""Turn per-frame speaker probabilities into clean speaker turns.

Frame-level diarizers such as Nemotron-3 emit a speech probability per speaker
every 10 ms. A single threshold turns that into choppy segments: a probability
hovering near the threshold toggles a speaker on and off, and brief false
activations add phantom micro-turns. This applies the post-processing NeMo uses
for its Sortformer models:

- Hysteresis: speech starts when the probability rises above ``onset`` and
  continues until it falls below ``offset``.
- Padding: each segment is widened by ``pad_onset`` and ``pad_offset``.
- Filtering: segments shorter than ``min_duration_on`` are removed, then gaps
  shorter than ``min_duration_off`` are filled.
- Speakers with less than ``min_speaker_seconds`` of total speech are dropped as
  spurious (another speaker's echo or a split of one voice); the words they
  covered are attributed to neighbors during alignment.

The defaults start from NeMo's CallHome-tuned Sortformer presets, which suit
conversational meetings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from scribe.core.diarization.base import SpeakerTurn


@dataclass(frozen=True)
class BinarizeParams:
    """Post-processing thresholds (probabilities) and durations (seconds)."""

    onset: float = 0.60
    offset: float = 0.50
    pad_onset: float = 0.10
    pad_offset: float = 0.05
    min_duration_on: float = 0.30
    min_duration_off: float = 0.30
    min_speaker_seconds: float = 2.0

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def _hysteresis_runs(
    probs: np.ndarray[Any, Any], onset: float, offset: float
) -> list[tuple[int, int]]:
    """Frame ranges ``[start, end)`` where hysteresis thresholding marks speech.

    A run of frames at or above ``offset`` is speech from its first frame above
    ``onset`` to its end; a run that never exceeds ``onset`` is silence.
    """
    above_offset = probs >= offset
    edges = np.diff(np.concatenate(([0], above_offset.astype(np.int8), [0])))
    run_starts = np.flatnonzero(edges == 1)
    run_ends = np.flatnonzero(edges == -1)
    runs: list[tuple[int, int]] = []
    for start, end in zip(run_starts, run_ends, strict=True):
        triggered = np.flatnonzero(probs[start:end] > onset)
        if len(triggered):
            runs.append((int(start + triggered[0]), int(end)))
    return runs


def _clean(
    segments: list[tuple[float, float]], params: BinarizeParams, duration: float
) -> list[tuple[float, float]]:
    """Pad, merge overlaps, drop short speech, then fill short gaps."""
    padded = sorted(
        (max(0.0, start - params.pad_onset), min(duration, end + params.pad_offset))
        for start, end in segments
    )
    merged: list[list[float]] = []
    for start, end in padded:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    kept = [seg for seg in merged if seg[1] - seg[0] >= params.min_duration_on]
    filled: list[list[float]] = []
    for start, end in kept:
        if filled and start - filled[-1][1] < params.min_duration_off:
            filled[-1][1] = max(filled[-1][1], end)
        else:
            filled.append([start, end])
    return [(start, end) for start, end in filled]


def binarize(
    probs: np.ndarray[Any, Any], frame_seconds: float, params: BinarizeParams | None = None
) -> list[SpeakerTurn]:
    """Speaker turns from probabilities shaped ``(frames, speakers)``.

    Speakers are relabeled ``SPEAKER_00``, ``SPEAKER_01``, ... in order of first
    speech after filtering, so dropped channels leave no gaps in the numbering.
    Overlapping speech from different speakers is preserved.
    """
    params = params or BinarizeParams()
    if probs.ndim != 2 or probs.shape[0] == 0:
        return []
    duration = probs.shape[0] * frame_seconds

    per_speaker: dict[int, list[tuple[float, float]]] = {}
    for channel in range(probs.shape[1]):
        runs = _hysteresis_runs(probs[:, channel], params.onset, params.offset)
        segments = _clean(
            [(start * frame_seconds, end * frame_seconds) for start, end in runs], params, duration
        )
        if segments:
            per_speaker[channel] = segments

    totals = {ch: sum(end - start for start, end in segs) for ch, segs in per_speaker.items()}
    if len(per_speaker) > 1:
        per_speaker = {
            ch: segs for ch, segs in per_speaker.items() if totals[ch] >= params.min_speaker_seconds
        }

    order = sorted(per_speaker, key=lambda ch: per_speaker[ch][0][0])
    labels = {ch: f"SPEAKER_{index:02d}" for index, ch in enumerate(order)}
    turns = [
        SpeakerTurn(start=round(start, 3), end=round(end, 3), speaker=labels[ch])
        for ch, segs in per_speaker.items()
        for start, end in segs
    ]
    return sorted(turns, key=lambda t: (t.start, t.end, t.speaker))
