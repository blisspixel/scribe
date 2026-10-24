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
scribe transcribe sample.wav --method local
```

Keep the input, model, language, backend, output formats, and power state constant
when comparing runs. The first run may include model download, cache population,
or native initialization and should not be treated as steady-state performance.

For reproducible quality and timing evidence, use the process in
[EVALUATION.md](EVALUATION.md).

## Model choice

The default file profile is `max`: full Whisper large-v3 on every hardware
tier. CPU capability, an importable accelerator package, or an out-of-memory
error never authorizes silently selecting a smaller model or uploading audio.
The same model can be slow on a laptop, including longer than the audio duration.
There is no reliable universal minutes-per-hour estimate. Measure a representative
file before committing to a long run, keeping download time separate.

Faster file profiles are explicit tradeoffs, not promises about every language or
recording. Turbo has fewer decoder layers than full large-v3. Compare actual
transcripts rather than assuming that model size alone predicts error rate.

| File profile | Model when unpinned | faster-whisper decoding |
| --- | --- | --- |
| `max` (default) | full `large-v3` | bounded regional sequential plus cached local acoustic review |
| `accurate` | full `large-v3` | conditioned sequential, beam 5, temperature fallback |
| `balanced` | `large-v3-turbo` | automatic GPU batching; sequential on CPU |
| `fast` | `small` | automatic GPU batching; sequential on CPU |

```bash
scribe transcribe sample.wav --quality accurate
scribe transcribe sample.wav --quality balanced
scribe transcribe sample.wav --quality fast
scribe transcribe sample.wav --model medium
```

`--quality` is available on `transcribe`, `url`, `batch`, `music`, `record` and `rec`. Persist it as
`quality = "max"` under `[transcription]` in `~/.scribe/config.toml`, or use
`SCRIBE_TRANSCRIPTION_QUALITY`. An explicit `--model`, `SCRIBE_DEFAULT_MODEL`, or
`[transcription] model` wins over any profile. Remove a pinned model to let a
profile select it. File profiles do not change resident voice settings.

`max` adds a second decode and source-review artifacts; `accurate` explicitly
retains the conditioned one-pass path. Cache the verifier before using `max`.
See [acoustic review](ACOUSTIC_REVIEW.md) for setup, language windows, independent
prompt settings, required/optional failure behavior and limits. No agreement or
quality-profile name establishes correctness on a recording.

The default precision remains CPU int8 and CUDA float16 where supported (float32
otherwise). An explicit faster-whisper precision can be set with
`local_compute_type = "float32"` under `[transcription]`, or
`SCRIBE_LOCAL_COMPUTE_TYPE=float32`. Unsupported types fail clearly instead of
falling back. This option is rejected for MLX/whisper.cpp, whose model/build
controls precision. No local WER comparison establishes that float32 improves
accuracy over int8 on your recordings.

Do not compare models only by elapsed time. Record WER and task-level errors on
the same synthetic, consented or licensed reference material. See the
[Whisper model descriptions](https://github.com/openai/whisper#available-models-and-languages)
and [CTranslate2 quantization documentation](https://opennmt.net/CTranslate2/quantization.html).

## Memory and failure behavior

Full large-v3 has about 1.55 billion parameters. CPU int8 weights alone occupy
about 1.6 GB; decoding, audio buffers, Python, the desktop and speaker labels need
additional RAM. CUDA float16 sequential decoding typically needs roughly 5 GB
free VRAM with faster-whisper; batching needs more. These are planning estimates,
not peak-memory guarantees, and native engines differ. Cached/downloaded weights
can be larger than the runtime quantized weights. `scribe info` reports system RAM
and the planned engine/model; `scribe doctor` reports current CUDA memory when
known.

Before loading faster-whisper, known free memory below the model's weight lower
bound fails with instructions. Passing this check does not prove the full workload
fits. Unknown memory does not select a smaller model. Other failures keep the
selected model and report the failure. Free memory, explicitly use the CPU backend,
or deliberately select another profile/model to proceed. Downloads are lazy;
inspection commands do not load full large-v3 weights.

## Backend choice

### CPU and NVIDIA

The default local path uses faster-whisper where supported. CPU operation is a
normal supported path. A CUDA-capable NVIDIA GPU can accelerate compatible model
loads when the installed Torch, TorchAudio, driver, and runtime agree.

Run `scribe doctor` after changing any driver or native ML package. If diagnostics
report a Torch or TorchAudio ABI mismatch, install a matching pair for the machine
using the official PyTorch selector, then rerun diagnostics.

The accurate profile uses conditioned sequential decoding. Automatic GPU batches
are available through faster profiles, or an explicit `local_batch_size`. Scribe
picks the batch size from the GPU tier and current free VRAM, uses sequential
decoding when too little is free, and retries a failed batch sequentially with the
same weights in the one-pass path. The bounded review path honors an explicit
batch cap and reports a failure without changing it. Long batched chunks are split using word timings. Batched decoding
has documented differences, including filler-word omissions in the existing RTX
4090 comparison; new profile tests do not establish a WER improvement. Set an
explicit cap in the [user config file](STORAGE.md):

```toml
[transcription]
local_batch_size = 0   # explicit sequential; e.g. 8 requests batches even with accurate
```

Other applications that keep models on the GPU, such as a local LLM server,
reduce the memory available to Scribe. Scribe warns when free VRAM is below what
the Whisper model needs; see
[Troubleshooting](TROUBLESHOOTING.md#transcription-is-slow-on-a-capable-gpu).

### Apple Silicon

The optional MLX backend is available through the `mlx` extra:

```bash
uv tool install --force --python 3.14 \
  "scribe[mlx] @ git+https://github.com/blisspixel/scribe.git@v2.13.1"
```

Use only on a supported Apple Silicon host. The project still needs fresh-machine
macOS workflow evidence before describing this path as broadly validated.
MLX forwards vocabulary prompts. Its current Whisper decoder does not implement
beam search; Scribe explains this and records greedy decoding with temperature
fallback rather than claiming beam parity. See the
[upstream decoder](https://github.com/ml-explore/mlx-examples/blob/main/whisper/mlx_whisper/decoding.py).

### AMD, Intel, and portable acceleration

The optional whisper.cpp adapter is available through the `whispercpp` extra:

```bash
uv tool install --force --python 3.14 \
  "scribe[whispercpp] @ git+https://github.com/blisspixel/scribe.git@v2.13.1"
```

Actual acceleration depends on how the underlying native package was built for
the host. An importable PyPI wheel may run only on CPU. AMD/Intel Vulkan requires
a compatible driver and a Vulkan-enabled pywhispercpp build, not NVIDIA CUDA;
follow [upstream build instructions](https://github.com/absadiki/pywhispercpp#installation).
Linux physical GPU identity is detected separately from runtime support. Scribe
forwards vocabulary prompts and explicitly selects beam search when requested.
Its transcript metadata marks the native device as unverified because import
availability does not prove actual GPU use. Confirm native runtime output on the
target machine and benchmark against the default CPU path.

JSON transcript metadata records the model, device/engine limits, actual decoding
mode and supported settings. A batch retry is recorded as sequential; unknown
native device/precision remains unknown. No cross-engine accuracy equivalence is
claimed.

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

The untouched file default detects the speech language; it does not force English.
An explicit language from CLI, `SCRIBE_DEFAULT_LANGUAGE`, or `[transcription]
`language` wins. Use `--language auto` to override a forced setting for one run:

```bash
scribe transcribe sample.wav --language en
scribe transcribe sample.wav --language es
scribe transcribe sample.wav --language ja
scribe transcribe sample.wav --language auto
```

`primary_language = "en"` is a manual preset used only when
`auto_detect_language = false` and no explicit language is set. Environment
equivalents are `SCRIBE_PRIMARY_LANGUAGE` and `SCRIBE_AUTO_DETECT_LANGUAGE`.
Changing primary to `es` or `ja` does not bias automatic detection: the engines
have no shared safe preferred-language prior, so Scribe does not invent one or
insert a preferred language into a prompt. First-run setup keeps detection enabled;
existing explicit language choices are preserved.

faster-whisper reports its detected language and probability. MLX reports the
detected language but does not expose detection confidence through `transcribe`.
whisper.cpp uses its public language detector and records its chosen language and
probability. Forced-language runs are marked as forced, with no invented detection
confidence. Music uses the selected faster-whisper decoder for its existing speech
pre-pass and reuses that model for decoding. Native engines use their own language
detection and empty-transcript rejection; they do not load a second faster-whisper
model or apply its music pre-pass heuristic.
These probabilities are backend scores, not calibrated accuracy
guarantees. Automatic detection is file-level and may use only initial speech;
code-switching and short/noisy inputs need evaluation. See the
[faster-whisper API](https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py)
and [pywhispercpp API](https://github.com/absadiki/pywhispercpp/blob/v1.5.0/pywhispercpp/model.py).

A concise vocabulary can improve proper-noun recognition without a larger model:

```bash
scribe transcribe sample.wav --vocab tech
scribe transcribe sample.wav --vocab ./private-terms.txt
```

Do not commit a vocabulary containing private names, customer terms, or internal
project identifiers to a public repository.
Use terms that belong in the recording's language and context. Scribe forwards
the supplied terms without adding generic English meeting text. A vocabulary is
a decoding hint, not a guarantee that a name will be recognized or proof that it
was spoken. OpenAI and OpenRouter remain explicit cloud choices; a forced language
is forwarded, while automatic detection is provider-controlled.

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

Version baseline: Scribe 2.13.1.
