# ADR-005: Structured transcript output and a shared transcript model

## Status

Accepted (2026-06).

## Context

Scribe wrote a single plain `.txt` per transcription. The local backend produced a
throwaway `list[dict]` of segments and the API path built speaker-aware lines as a
string, so timing, speaker, and confidence data was computed and then discarded. That
made the output hard to ingest by other tools and impossible to query ("who said what,
when, across my meetings"), which the 2026 local meeting-intelligence field treats as
table stakes.

## Decision

Introduce one shared `Transcript` domain model (`models/transcript.py`): frozen,
self-validating `TranscriptWord` / `TranscriptSegment` (start, end, text, speaker,
confidence, words) and `Transcript` (segments plus language, duration, backend, model,
metadata). Every transcription path builds it.

Add structured-output writers (`utils/transcript_writers.py`) for JSON
(schema `scribe.transcript/v1`), WebVTT, SRT, and Markdown with a YAML frontmatter
block. A JSON transcript is written next to the `.txt` by default; `--format` and the
`SCRIBE_OUTPUT_FORMATS` setting control the set. The plain `.txt` is unchanged.

Add `scribe query` for keyword and speaker search across the stored JSON transcripts.
This is deliberately lean: plain field and substring search over the output folder, not
an embedding index or semantic retrieval. That keeps the base install free of an
embedding/vector dependency while still answering "find the moment" questions. A
semantic layer can be added later behind an optional extra if it proves needed.

## Consequences

- The model is the single representation the hardware-adaptive backends (ADR to follow)
  and local speaker diarization populate, so those features extend it rather than
  reinventing per-path parsing.
- The `.txt` remains byte-for-byte the same; structured artifacts are additive, so no
  existing behavior or test output regresses.
- Provenance (backend, model) travels with the artifact, so downstream tools and the
  Markdown frontmatter can state honestly how a transcript was produced.
- `scribe query` will only find transcripts that were written with JSON output enabled
  (the default); transcript-only-`.txt` runs are not indexed.
