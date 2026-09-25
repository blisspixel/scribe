# ADR-007: Pluggable local speaker diarization and word-level alignment

## Status

Accepted (2026-06), amended (2026-09) to supersede the pyannote-only architecture
with pluggable backends, word-level timestamp reconciliation, and NVIDIA Nemotron-3.

## Context

The cloud path returns speaker-labeled segments (the OpenAI diarize model fills
`speaker` on each segment, which the `.txt` and the structured writers render). The
initial local implementation introduced `LocalDiarizer` based on pyannote 3.1. While
functional, it exhibited architectural limitations:

1. Diarization was tightly coupled to pyannote 3.1, requiring gated HF token access even
   when non-gated models were available.
2. The alignment layer collapsed entire ASR segments into a single "dominant" speaker.
   Rapid back-and-forth dialogue within a single Whisper segment lost attribution accuracy.
3. NVIDIA Nemotron-3 Diarization (`nvidia/Nemotron-3-Diarization`) provides 10 ms resolution
   at up to 8 speakers in a single pass. Pyannote Community-1 also introduced exclusive
   speaker tracks for clean ASR reconciliation.

## Decision

1. Modularize diarization into `scribe.core.diarization`:
   - `base.py`: defines `SpeakerTurn`, `DiarizationResult`, `DiarizationBackend`, and `SpeakerDiarizer`.
   - `alignment.py`: pure math for dominant speaker resolution, word-level alignment, and transcript resegmentation.
   - `registry.py`: hardware-adaptive selection (`select_diarizer`), availability probes, overrides, and deterministic fallback.
   - `nemotron.py`: `NemotronDiarizer` using Hugging Face Transformers.
   - `pyannote.py`: `PyannoteDiarizer` supporting configurable pipelines (`community-1` and `3.1`) and exclusive tracks.
   - `mlx.py`: `NemotronMLXDiarizer` for Apple Silicon Metal acceleration.
   - `core/diarizer.py`: preserved as a backward-compatible shim re-exporting legacy symbols.
2. Implement word-level timestamp reconciliation & resegmentation:
   - When diarization is requested, `LocalWhisperTranscriber` sets `word_timestamps=True` in `faster-whisper`.
   - `TranscriptWord` records word timestamps and receives speaker attribution.
   - Contiguous same-speaker words are resegmented into speaker-homogeneous `TranscriptSegment`s.
   - Backends lacking word timestamps fall back to segment-level dominant speaker assignment.
3. Decouple inference from alignment:
   - Diarization backends emit normalized `DiarizationResult` instances without modifying transcripts.
   - The application layer applies alignment via `align_diarization()`, preserving overlap in structured metadata.
4. Selection and configuration:
   - Preference order: Apple Silicon prefers MLX, then Nemotron, then pyannote. Every
     other vendor, including plain CPU, prefers Nemotron, then pyannote. Nemotron
     (`nvidia/Nemotron-3-Diarization`, ungated, openmdw-1.1) needs no Hugging Face
     token and runs well on CPU, so it is the default everywhere.
   - `resolve_diarizer` tries an explicit backend first, then the preference order,
     and skips any backend whose extra or credentials are missing. pyannote without
     a token is skipped rather than chosen and then abandoned.
   - Torch backends request CUDA only when the installed PyTorch build can use it.
     Scribe's GPU detection also counts CTranslate2's CUDA runtime, so a GPU machine
     with a CPU-only PyTorch build diarizes on CPU instead of failing.
   - The `[diarization]` config section maps `enabled`, `backend`, and
     `pyannote_pipeline`. An unknown configured backend logs a warning and uses
     `auto`; an unknown `--diarizer` value is a usage error.
   - The CLI adds `--diarizer auto|nemotron|pyannote|mlx|none` alongside
     `--diarize/--no-diarize` on `transcribe`, `url`, and `batch`.
5. Dependencies:
   - `diarize-nemotron` requires Transformers with the `nemotron3_diarization`
     model package and librosa for its feature extractor. The model is newer than
     Transformers 5.17.0, so the extra pins a reviewed upstream commit until 5.18.0
     is released.
   - `diarize-mlx` requires an mlx-audio build with the `nemotron_diarization`
     model, which is newer than mlx-audio 0.5.5. Availability probes the model
     package itself, so an older mlx-audio falls back to Nemotron via Transformers.
   - pyannote 4.x renamed `use_auth_token` to `token` and returns a
     `DiarizeOutput`; the adapter supports both 3.x and 4.x.

## Consequences

- Speaker attribution is resolved at word boundaries, so rapid back-and-forth
  dialogue inside one Whisper segment produces distinct speaker turns. Words in the
  short silences between turns inherit a neighbor's speaker instead of splitting a
  sentence, and single-speaker segments keep their original text.
- Measured on an RTX 4090: Nemotron diarized a 61-minute recording in about 6
  seconds with under 1 GB of VRAM, and a 13-minute recording in about 11 seconds on
  CPU. A synthetic two-voice dialog was attributed correctly at every turn.
- Diarization never fails a transcription. Missing extras, tokens, or runtime
  errors fall back to the next backend or leave the transcript unlabeled, with the
  reason logged.
- `TranscriptSegment.speaker` remains the label for every writer (TXT, JSON, VTT,
  SRT, Markdown). JSON output also carries per-word timing and speakers when
  diarization ran.
- The alignment and selection logic are pure and covered by unit and property
  tests. Model inference is verified manually on real hardware and is not run in
  CI.
