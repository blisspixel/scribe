# Maximum-quality transcription and source review

File transcription now defaults to `max`: full Whisper large-v3, recording-wide
language observations, bounded regional decoding and a separate local acoustic
pass. This increases work and produces review evidence. It does not certify
accuracy or automatically rewrite the primary transcript.

```bash
scribe transcribe recording.wav                         # max, required review
scribe transcribe recording.wav --quality accurate      # full large-v3, one pass
scribe transcribe recording.wav --verification best-effort
scribe record --quality max --verification-model medium
```

These options also apply to `url`, `batch`, `music` and `rec`. `accurate` is the
explicit one-pass full-model option. `balanced` selects turbo and `fast` selects
small only when requested. An explicit primary model or backend remains in force.
Resident voice retains its separate profiles.

## Cache and configuration

The default secondary is faster-whisper large-v3-turbo. If the primary is turbo,
the secondary defaults to full large-v3. A deliberate same-model override is
labeled a same-checkpoint repeat. These Whisper models share training and weights;
a separate decode is not statistically independent evidence.

The verifier requires a complete existing local checkpoint, including its
configuration and tokenizer. It never downloads a missing model or tokenizer,
falls back to a paid API, or uses primary text as its prompt. In the Python
environment where Scribe is installed, explicitly populate the cache when desired:

```bash
python -c 'from faster_whisper.utils import download_model; download_model("large-v3"); download_model("turbo")'
```

This setup command downloads substantial weights. Inspection commands and
`scribe init` do not download them. The primary retains its existing first-use
model download behavior. Set `HF_HUB_OFFLINE=1` and `TRANSFORMERS_OFFLINE=1` to
require cached primary weights too. Full-v3 CPU int8 weights alone need about
1.6 GB of memory; the secondary is loaded after primary weights are unloaded.
Decoding and speaker labels need additional memory. No memory or speed guarantee
follows from this planning estimate.

```toml
[transcription]
quality = "max"
verification = "required"          # required, best-effort, off
verification_model = "large-v3-turbo"
# model = "medium"                 # explicit primary override
```

CLI flags override environment variables, which override TOML. Environment names
are `SCRIBE_TRANSCRIPTION_QUALITY`, `SCRIBE_TRANSCRIPTION_VERIFICATION` and
`SCRIBE_VERIFICATION_MODEL`. For a persistent one-pass choice, set quality to
`accurate` and remove an explicit verification setting, or set verification to
`off`. Unsupported precision, memory failure or missing primary weights never
silently selects a smaller primary or cloud processing.

## Language and timing evidence

The local faster-whisper review path samples overlapping 15-second windows every
7.5 seconds, including the recording's end. Speech activity and up to five model
language scores are recorded per window. Scores are not calibrated correctness
probabilities. Consensus above the fixed confidence and margin thresholds permits
same-language regions of up to five minutes. Uncertain regions are decoded
separately with previous-text conditioning disabled. A language change resets
context. One second of audio context overlaps boundaries; each timed word is
assigned once by its midpoint.

`--language`, configured manual language and operator vocabulary remain primary
controls. The secondary independently detects language and receives no glossary
prompt. Exact speech-activity spans are also compared with both decodes in five-second
buckets, so shared missing text can still require source review. Speech activity
is a model observation and can produce false alarms. Comparison uses raw primary acoustic text before glossary substitutions
or speaker naming. This is transcription, without an LLM rewrite or translation
step. A forced language conflicting with observed evidence is flagged.

Brief switches within a window, accents, overlapping speech, silence-detector
misses and timestamp errors can still lose words or select the wrong language.
The method does not guarantee code-switching accuracy. Media timestamp gaps are
preserved as silence relative to the media start. The clock advances by decoded
samples; tolerance is bounded by one sample or the container timestamp unit, so
small gaps cannot accumulate unnoticed. Larger overlaps fail with an explicit-export
instruction. PCM preparation streams to a temporary
disk spool; model input sections are bounded, while transcripts and diagnostics
grow with recording length.

Explicit native and cloud primaries remain selected. Their missing recording-wide
primary diagnostics currently make required review partial even if the secondary
succeeds. The primary is retained. Choose faster-whisper explicitly for that
capability, or deliberately choose `accurate` for a one-pass native/cloud run.
Music retains its existing specialized primary pipeline; required acoustic review
is currently unavailable for it. Choose `--quality accurate` for music one-pass
processing. A requested best-effort music review also records a partial comparison
receipt and retains the source, while processing remains successful. Neither
capability gap changes the primary automatically.

## Results and recovery

A unique `<source-stem>_review_<id>` directory contains raw primary JSON, available
secondary JSON, a timed Markdown report and governing `review.json`. Each file is
written atomically; the receipt is published last. The report records original
source location and SHA-256, model/backend/actual precision, language windows,
comparison policy and elapsed review time. Session and structured transcript
metadata point to these artifacts. A report can be incomplete if storage fails.
Capability-gap reports also retain an exact `primary-text.txt` snapshot with its
own SHA-256, so their text evidence remains available after the working transcript
is archived. The receipt labels the original text location separately.

Disagreements, numeric differences, speech coverage gaps, language uncertainty
and weak decoding diagnostics set `requires_review`. They do not replace primary
wording or count as a processing failure: a completed comparison can exit 0 while
requiring source listening. Timestamp jitter and segmentation can cause false
alarms. Attached numeric signs, currency symbols and percent markers are preserved
when comparing quantities; ordinary sentence punctuation is ignored. Time indexes
avoid rescanning the whole transcript for every comparison bucket.
Agreement can preserve the same wrong number or omitted phrase in both
models. Listen to flagged spans with context and sample unflagged audio too.

A required verifier, language-scan or report failure keeps available primary text
and source audio, reports a partial session and exits 1. Best-effort review keeps
processing successful but records the incomplete comparison. URL downloads are
retained when review requires the source, including completed disagreements;
otherwise the normal download-retention policy applies. Original local files and
recordings are not review-owned temporary files. The review source-retention
marker is explicit in the receipt and session so archival owners can preserve
its location. No comparison is presented as validated transcription.

For evidence required before quality claims, see [EVALUATION.md](EVALUATION.md).
Runtime behavior is based on the pinned
[faster-whisper implementation](https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1),
[Whisper model descriptions](https://github.com/openai/whisper#available-models-and-languages)
and [CTranslate2 model unloading](https://opennmt.net/CTranslate2/python/ctranslate2.models.Whisper.html#ctranslate2.models.Whisper.unload_model).
