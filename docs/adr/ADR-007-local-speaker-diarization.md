# ADR-007: Local speaker diarization

## Status

Accepted (2026-06).

## Context

The cloud path returns speaker-labeled segments (the OpenAI diarize model fills
`speaker` on each segment, which the `.txt` and the structured writers render). The
local path had no equivalent: `Transcript.speaker` was always None for faster-whisper,
mlx-whisper, and whisper.cpp output. "Who said what" is table stakes for meeting
intelligence, and doing it locally keeps the offline, no-API promise intact.

A stale integration test (`tests/integration/test_local_whisper.py`) referenced a
nonexistent `enable_diarization=` constructor argument, a leftover from an earlier
WhisperX experiment that never landed.

## Decision

Add `core/diarizer.py` with two clearly separated pieces:

- `LocalDiarizer`: runs a pyannote.audio pipeline
  (`pyannote/speaker-diarization-3.1`) to produce speaker turns. It needs a Hugging
  Face token (the pyannote models are license-gated) and ships behind the optional
  `scribe[diarize]` extra. `is_available()` reports whether pyannote can be imported.
- `assign_speakers` / `dominant_speaker`: pure functions that map speaker turns onto
  the existing `Transcript` segments. Each segment is assigned the speaker whose turns
  overlap it most (overlap summed per speaker, earliest turn breaking ties), or None
  when nothing overlaps. The result is a new, relabeled `Transcript`; the input is
  unchanged (segments are frozen dataclasses).

Diarization is injected into the engines as an optional `diarizer` parameter, applied
to the `Transcript` after transcription and before the `.txt` is written, so the
labels reach both the plain text and the structured outputs and the silence markers
stay intact. The transcriber resolves whether to build a diarizer from
`config.enable_speaker_diarization`, the presence of an HF token (`config.hf_token` or
`HF_TOKEN`), and pyannote availability. The CLI adds `--diarize/--no-diarize` on
`transcribe`. Music mode never diarizes.

The `.txt` writer now prefixes `SPEAKER_xx: ` when a segment has a speaker and is
otherwise unchanged, so non-diarized output stays byte-for-byte identical.

## Consequences

- Local "who said what" populates the same `Transcript.speaker` field the cloud path
  uses, so the Phase 1 writers (JSON/VTT/SRT/Markdown) render speakers with no further
  change.
- Diarization is a clean opt-in that degrades gracefully: a missing extra, missing
  token, or pipeline failure leaves the transcript unlabeled and logs why, rather than
  failing the transcription.
- The alignment is the correctness-critical part and is pure, so it is exhaustively
  unit-tested (overlap resolution, totality, determinism via a property test) without
  any model download. The pyannote run itself is covered by a marked integration test
  gated on CUDA, a token, and the extra; it is not run in CI, which is stated plainly
  rather than mocked into a false green.
- Word-level speaker assignment is intentionally out of scope for now: the local
  segments do not carry word timestamps, so alignment is segment-level. WhisperX-based
  word alignment can be layered on later behind its existing extra.
- The stale `enable_diarization=` integration stub is corrected to the current engine
  API and the new injected-diarizer design.
