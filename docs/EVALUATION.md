# Reproducible Evaluation

Scribe performance and quality claims must be backed by a versioned report, not
an anecdotal run. The repository includes a backend-independent evaluator for
word error rate (WER) and real-time factor (RTF):

```powershell
uv run python scripts/evaluate_transcripts.py evaluation.jsonl `
  --revision (git rev-parse HEAD) `
  --output evaluation-report.json
```

The evaluator does not invoke a model. Each backend runner records its reference
text, hypothesis, audio duration, and measured processing time in JSON Lines:

```json
{"id":"meeting-001","reference":"the expected words","hypothesis":"the transcribed words","audio_seconds":12.4,"processing_seconds":2.1,"metadata":{"backend":"faster-whisper","model":"large-v3"}}
```

Required fields:

- `id`: stable sample identifier
- `reference`: human-verified reference transcript
- `hypothesis`: Scribe output
- `audio_seconds`: source duration, greater than zero
- `processing_seconds`: measured end-to-end processing time, zero or greater
- `metadata`: optional string-to-string map for backend, model, device, language,
  corpus split, and other experimental controls

## Metrics

- WER is word-level Levenshtein distance divided by reference words.
- Corpus WER is micro-averaged, so long and short samples contribute by word
  count rather than receiving equal weight.
- RTF is total processing seconds divided by total audio seconds. Values below
  one are faster than real time.
- Exact-match rate is reported as a strict normalized-text diagnostic.

Default normalization applies Unicode NFKC, case folding, punctuation removal,
and whitespace tokenization. `--case-sensitive` and `--keep-punctuation` make
those choices explicit when a corpus protocol requires them. A sample with an
empty reference has no finite per-sample WER, but its insertion errors still
contribute to a corpus that contains reference words.

## Evidence required for published claims

A credible benchmark record includes:

1. Corpus name, license, version, split, and manifest SHA-256.
2. Scribe commit, backend, model, quantization, language, and decoding options.
3. Operating system, CPU, GPU, driver, Python, and dependency versions.
4. Whether model download and warm-up time are included.
5. At least three timed repetitions for performance claims, with raw results.
6. WER for transcription and a separate diarization metric such as DER when
   speaker attribution is evaluated.
7. Failure counts and excluded samples. Exclusions must be explained rather
   than silently removed.

The generated `scribe.evaluation/v1` report records the manifest hash, source
revision, environment, normalization policy, aggregate metrics, and every
per-sample result. The repository intentionally publishes no numeric accuracy
or speed claim until the corresponding corpus and report are available.

## Acoustic review evidence

The `max` profile adds comparison evidence, not a reference transcript. Evaluate
primary and secondary WER/CER separately against frozen licensed references.
Record language-window coverage, switches, names/numbers/negation, source-time
alignment, silence/gap behavior, related-checkpoint agreement errors, false
review alarms and reference-error review recall. Report both flagged and missed
errors; timestamp bucket overlap alone does not demonstrate acoustic detection.
Preserve raw primary output before glossary normalization. Synthetic joins test
boundary plumbing and cannot represent natural code-switching or meeting speech.

Use exact cached checkpoint paths, offline model flags and socket/DNS guards for
local-only evaluations. Record model hashes, original audio hashes, source tree,
actual precision, separate model loads/unloads, measured time and memory sampling
method. Tiny read-speech smoke tests cannot establish default superiority,
independent-checkpoint correctness, platform performance or an accuracy rate.
See [acoustic review limits](ACOUSTIC_REVIEW.md).
