# ADR-010: Domain glossaries (named vocabularies, budgeted prompts, term normalization)

## Status

Accepted (2026-06).

## Context

Scribe had custom vocabulary: a `.txt`/`.json` term list passed to Whisper's
`initial_prompt` to bias recognition (ADR rationale in `utils/vocabulary.py`). Three
gaps limited it for real domain use (finance, tech, legal, medical jargon):

1. There was no reusable, named glossary; you passed a file path every time.
2. `to_whisper_format` joined every term verbatim, but Whisper only conditions on
   roughly the last 224 tokens of the prompt, so a large glossary was silently
   truncated by the model and the bias diluted.
3. Prompt biasing is a soft hint. It nudges the model but does not guarantee the
   output, so recurring misrecognitions ("post gray sequel" for "PostgreSQL") still
   slip through.

## Decision

Extend `CustomVocabulary` and add a normalization pass, three pieces:

- **Named glossaries.** `CustomVocabulary.load(name_or_path)` resolves a value that
  looks like a path via `from_file`, otherwise as a named glossary under
  `~/.scribe/vocab/<name>.{txt,json}` and then a bundled preset shipped with the
  package (`assets/glossaries/`). `--vocab finance` now works. A `scribe vocab`
  command lists glossaries and shows one's terms. Starter `finance` and `tech`
  presets ship with Scribe.
- **Budgeted prompt.** `to_prompt(max_chars=896)` deduplicates case-insensitively
  and trims to the prompt budget, logging how many terms were dropped, so biasing
  stays sharp and oversize glossaries degrade predictably. `to_whisper_format` is
  unchanged for backward compatibility; the transcriber now uses `to_prompt`.
- **Deterministic normalization.** Glossaries can record aliases, the `.txt` line
  `Canonical = variant1, variant2` or a JSON `{"terms": [...], "aliases": {...}}`.
  After transcription, `utils/term_normalize` rewrites those variants to the
  canonical form over the shared `Transcript` and the `.txt` body (header preserved),
  whole-word and case-insensitive, longest variant first, with no chained rewrites.
  It runs on every path in `Transcriber.transcribe`, so the `.txt` and the structured
  outputs stay consistent. This is the reliable complement to prompt biasing: the
  prompt nudges the model, normalization guarantees the final text.

## Consequences

- Biasing (prompt) and correction (normalization) are separate, composable layers.
  Biasing helps the model produce the term; normalization fixes the cases where it
  did not, deterministically and offline, with no model or network.
- The base install gains two small text presets and no new runtime dependency
  (normalization is stdlib `re`).
- Backward compatible: existing `--vocab file.txt`, plain term lists, JSON arrays,
  and `to_whisper_format` all behave exactly as before; aliases and budgeting are
  additive and default off.
- Honest limits: normalization only fixes misrecognitions you have listed as
  aliases, and word-boundary matching will not catch a variant fused into another
  word. It is a glossary, not a spell-checker. Effectiveness of prompt biasing
  remains unmeasured, as documented in `utils/vocabulary.py`.
- Language: glossaries are language-agnostic text; they should match the spoken
  language, which the existing `--language` flag controls.
