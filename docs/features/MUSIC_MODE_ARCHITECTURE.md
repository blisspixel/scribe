# Music Mode Architecture

Music mode is a best-effort lyric transcription workflow. It can use optional
signal analysis, vocal separation, and voice-activity detection before sending
audio through the normal local or explicitly selected cloud transcription path.

It does not guarantee complete or accurate lyrics. Dense mixes, effects, backing
vocals, uncommon languages, and instrumental sections can reduce accuracy or
produce false text. Review every result against the authorized source material.

## Pipeline

For each requested track, `scribe music` performs these stages:

1. Validate the input and read its duration.
2. Analyze whether the file appears to contain music when the optional analysis
   dependencies are available.
3. Attempt vocal separation when Demucs is installed. If separation is unavailable
   or fails, continue with the original audio and report the fallback.
4. Attempt voice-activity detection. If it produces usable vocal intervals, slice
   the audio into temporary segments. Otherwise transcribe the full selected audio.
5. Transcribe each segment or the full track through Scribe's normal backend
   selection.
6. Filter a small set of known no-speech hallucination phrases, combine surviving
   text, write the lyric output, and preserve the session outcome.
7. Remove temporary slices and separated audio created by the run.

Optional stages are visible in terminal output. A skipped optimization is not
reported as if it ran successfully.

## Dependency boundaries

The base installation provides transcription and the full-audio fallback.
Additional analysis depends on libraries imported only when needed:

- `librosa` for music classification and metadata such as tempo and approximate
  key.
- `demucs` plus its supported TorchAudio stack for vocal separation.
- Scribe's VAD and slicing helpers for vocal intervals.

These libraries have large native and model dependencies, so they are not part of
the portable base package. Their compatibility must be validated against the
installed PyTorch and TorchAudio versions before relying on the enhanced path.

## Hardware behavior

No particular GPU is required. The fallback path uses the selected transcription
backend, including CPU. Optional source separation can run on CPU or a compatible
accelerator, with performance and memory use varying substantially by device,
driver, model, track length, and library version.

Do not publish fixed speed or accuracy claims from a single development machine.
Use the evaluation process in [EVALUATION.md](../EVALUATION.md) and record the
hardware, software revisions, corpus hashes, and per-sample evidence.

## Outcome semantics

Music mode distinguishes:

- `complete`: all requested work produced usable output.
- `partial`: output survived, but one or more segments or optional stages failed.
- `instrumental`: no usable vocal content was detected.
- `failed`: no usable requested output was produced.

Batch processing continues after an item failure unless fail-fast behavior is
selected. Any partial or failed requested item produces a nonzero final exit code
without discarding valid artifacts from other items.

## Privacy and authorization

Local music transcription keeps audio on the machine. An explicit cloud method
uploads the relevant audio to the selected provider. Users must have the legal
right and all required permissions to record, process, transcribe, store, and
share the material. See [Responsible Use](../RESPONSIBLE_USE.md).

## Known limitations

- Music classification uses heuristic thresholds and can misclassify unusual or
  quiet material.
- Source separation can leave instruments in the vocal stem or remove parts of a
  voice.
- VAD can miss soft vocals or treat non-vocal sounds as speech.
- Whisper can hallucinate text during sparse or instrumental sections.
- Temporary audio requires additional disk space during processing.
- Optional model downloads can be large and are controlled by their upstream
  libraries.

The command output and session evidence are authoritative for what occurred in a
specific run.
