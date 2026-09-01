# Performance Tuning

Scribe runs on CPU-only systems and can use supported accelerators. Hardware,
driver, media, language, model, and backend differences are large enough that
fixed speed or memory promises would be misleading. Measure the real workload on
the target machine before selecting defaults.

## Start with a valid baseline

Run local diagnostics and one representative authorized or synthetic file:

```bash
scribe doctor
scribe info
scribe transcribe sample.wav --method local --model small
```

Keep the input, model, language, backend, output formats, and power state constant
when comparing runs. The first run may include model download, cache population,
or native initialization and should not be treated as steady-state performance.

For reproducible quality and timing evidence, use the process in
[EVALUATION.md](EVALUATION.md).

## Model choice

Smaller Whisper models generally need less memory and finish sooner, while larger
models can improve difficult-audio accuracy. Begin with `small` on a supported GPU
or `base` on CPU, then increase only if a representative accuracy evaluation
justifies the added time and memory.

```bash
scribe transcribe sample.wav --method local --model base
scribe transcribe sample.wav --method local --model small
scribe transcribe sample.wav --method local --model medium
```

Do not compare models only by elapsed time. Record word error rate or a task-level
quality score on the same synthetic or properly authorized reference transcript.

## Backend choice

### CPU and NVIDIA

The default local path uses faster-whisper where supported. CPU operation is a
normal supported path. A CUDA-capable NVIDIA GPU can accelerate compatible model
loads when the installed Torch, TorchAudio, driver, and runtime agree.

Run `scribe doctor` after changing any driver or native ML package. If diagnostics
report a Torch or TorchAudio ABI mismatch, install a matching pair for the machine
using the official PyTorch selector, then rerun diagnostics.

### Apple Silicon

The optional MLX backend is available through the `mlx` extra:

```bash
uv tool install --force --python 3.12 \
  "scribe[mlx] @ git+https://github.com/blisspixel/scribe.git@v2.8.1"
```

Use only on a supported Apple Silicon host. The project still needs fresh-machine
macOS workflow evidence before public distribution.

### AMD, Intel, and portable acceleration

The optional whisper.cpp adapter is available through the `whispercpp` extra:

```bash
uv tool install --force --python 3.12 \
  "scribe[whispercpp] @ git+https://github.com/blisspixel/scribe.git@v2.8.1"
```

Actual acceleration depends on how the underlying native package was built for
the host. Confirm the selected backend in diagnostics and benchmark it against the
default CPU path rather than assuming it is faster.

## Input preparation

Scribe and its backends normalize media as needed. Manually re-encoding every file
can add time and reduce quality, so retain the original input unless diagnostics
identify a format problem.

For unusually long recordings:

- Keep adequate free disk space for temporary media and output artifacts.
- Close unrelated GPU-heavy applications before loading a large model.
- Use a smaller model when the larger model cannot fit reliably.
- Split only when operational limits or recovery needs justify it.
- Preserve session summaries so a partial result is visible rather than mistaken
  for success.

Use `scribe clean FILE --analyze` for a read-only media analysis. Apply trimming
or silence removal only after reviewing the proposed operation and retaining a
recoverable original.

## Language and vocabulary

Specify a known language to avoid detection work and ambiguity:

```bash
scribe transcribe sample.wav --language en
```

A concise vocabulary can improve proper-noun recognition without a larger model:

```bash
scribe transcribe sample.wav --vocab tech
scribe transcribe sample.wav --vocab ./private-terms.txt
```

Do not commit a vocabulary containing private names, customer terms, or internal
project identifiers to a public repository.

## Derived artifacts and cloud features

DOCX, structured formats, diarization, notes, jokes, memes, and provider bake-offs
add work beyond transcription. Disable anything not needed for the measurement:

```bash
scribe transcribe sample.wav --no-docx --no-notes --no-joke --no-meme
```

Provider features have variable latency, rate limits, data-processing terms, and
charges. Consult current provider documentation before measuring cost. Scribe
does not promise a fixed provider price or speed ratio.

## Resident voice

Resident dictation favors responsiveness over maximum batch accuracy. Start with
the default profile and use a smaller model if activation or transcription feels
slow:

```bash
scribe listen --model base
scribe tray --check --profile fast
```

Do not run competing local transcription processes on the same accelerator while
evaluating resident voice latency. Exit Scribe cleanly and let its model manager
release resources instead of terminating processes or deleting state files.

## A useful benchmark record

For each run, record:

- Scribe commit and version.
- Operating system, Python version, CPU, accelerator, and memory.
- Backend and relevant driver/runtime versions.
- Input duration, codec, sample rate, channels, and file size.
- Model, language, vocabulary, and optional features.
- Cold or warm cache status.
- Elapsed time, peak memory when available, exit status, and artifact types.
- Accuracy metric and reference-transcript provenance.

Store only synthetic or approved benchmark material. Remove local usernames,
paths, device names, secrets, and real participant or company data before sharing
a benchmark report.

Last verified against Scribe 2.8.1 on 2026-08-11.
