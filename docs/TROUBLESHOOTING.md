# Troubleshooting

Start with local-only diagnostics:

```bash
scribe doctor
scribe info
```

`scribe doctor` does not contact configured providers unless `--live` is supplied.
Use `scribe doctor --live` only when a provider check is intended and authorized.
Never print, paste, echo, or place an API key in a diagnostic command, screenshot,
issue, or support bundle.

## Installation and command discovery

Scribe requires Python 3.12 or 3.13, FFmpeg, and uv.

Install the current GitHub release as a tool:

```bash
uv tool install --force --python 3.12 \
  git+https://github.com/blisspixel/scribe.git@v2.10.0
uv tool update-shell
```

Open a new terminal after `uv tool update-shell`. If the command is still missing,
run `uv tool list` and follow the path guidance printed by uv.

No package named `scribe` has been published for this project. Do not use a bare
`pip install scribe`, which can install an unrelated package.

If a cloud-synced home directory prevents hardlinks, reinstall with copy mode:

```bash
uv tool install --force --link-mode copy --python 3.12 \
  git+https://github.com/blisspixel/scribe.git@v2.10.0
```

For a development checkout:

```bash
uv sync --locked --group dev
uv run scribe doctor
```

## FFmpeg is missing

Install FFmpeg through the operating system's trusted package manager or the
official FFmpeg distribution guidance. Confirm both tools are on `PATH`:

```bash
ffmpeg -version
ffprobe -version
scribe doctor
```

Restart the terminal after changing `PATH`. Do not replace media files or delete
Scribe state to fix an FFmpeg discovery problem.

## Local transcription fails

Try a smaller local model and a known language:

```bash
scribe transcribe sample.wav --method local --model base --language en
```

Then check:

- The input opens in a trusted media player.
- The output and temporary locations have free disk space.
- Another application is not exhausting accelerator memory.
- The selected file is within configured size and duration limits.
- `scribe doctor` reports a usable local backend.

`auto` and `local` stay local if local transcription fails. Scribe does not
silently upload the recording as a fallback. Use `--method openai` or
`--method openrouter` only when the upload is intentional and approved.

## OpenRouter transcription fails

First validate the configured key without uploading audio:

```bash
scribe doctor --live
```

Then retry with a short non-sensitive file and an available speech-to-text model.
OpenRouter authentication failures and insufficient credits fail immediately.
Timeouts, rate limits, and temporary server failures use bounded retries. A
multi-chunk failure leaves a labeled `*_transcription.partial.txt`; do not treat
that file as complete. Scribe then attempts full local transcription unless the
workflow is music mode.

If `doctor --live` says the key is valid but its hard cap is not verified, set an
OpenRouter key limit at or below `SCRIBE_OPENROUTER_MAX_SPEND_USD`. Scribe's local
guard stops before another chunk when reported cost reaches the configured limit
or when cost is missing, but only OpenRouter can enforce an absolute account cap.

See the [Cloud Transcription Guide](CLOUD_TRANSCRIPTION.md) for model discovery,
chunk safeguards, privacy boundaries, and safe end-to-end testing.

## CUDA, Torch, or TorchAudio errors

Native package and driver versions must be compatible. Capture version numbers,
not keys or private paths:

```bash
nvidia-smi
scribe doctor
```

Use the official PyTorch installation selector for the host's supported backend
and install matching Torch and TorchAudio builds. There is no universal CUDA wheel
command that is correct for every machine. Rerun `scribe doctor` after any change.

If acceleration remains unavailable, CPU transcription is supported:

```bash
scribe transcribe sample.wav --method local --model base
```

## Apple Silicon, AMD, or Intel backend is unavailable

Install the applicable extra from this repository, then run diagnostics:

```bash
uv tool install --force --python 3.12 \
  "scribe[mlx] @ git+https://github.com/blisspixel/scribe.git@v2.10.0"

uv tool install --force --python 3.12 \
  "scribe[whispercpp] @ git+https://github.com/blisspixel/scribe.git@v2.10.0"
```

MLX is for supported Apple Silicon systems. whisper.cpp support depends on the
native build available for the target host. Neither extra guarantees acceleration
on every configuration.

## OBS recording fails

Read the [Recording Guide](RECORDING.md) for the complete startup, monitoring,
safe-stop, and recovery contract.

Run the non-recording preflight first:

```bash
scribe record --check
```

Confirm OBS is installed, can open normally, and has permission to capture the
intended display and audio devices. On macOS, review Screen Recording and
Microphone permissions. On Windows, verify the expected OBS profile and sources.

If OBS appears in the process list but its configured WebSocket port is closed,
Scribe attempts one non-destructive multi-instance relaunch before using emergency
fallback mode. It never terminates an existing OBS process and refuses recovery
when a recording mux is active. Emergency fallback uses OBS's supported startup
recording option, verifies that a new media file is growing, and reconnects to
WebSocket for a safe stop when possible. If WebSocket remains unavailable, stop
recording in OBS when prompted; Scribe waits for the file to finish instead of
using an unsupported stop option or moving a live file.

Scribe reports recording as confirmed only after OBS byte or duration counters
advance. It separately checks that a media file not present before startup is
growing. If OBS reports active capture but its byte counter later stalls, check
OBS and available disk space immediately. If OBS stops before a Scribe stop
request, Scribe preserves the partial recording and reports the session as
incomplete rather than claiming success.

If `scribe rec --check` still fails, close all OBS instances only after confirming
that none is recording, reopen OBS, and rerun the check.

Do not delete OBS configuration files as a first troubleshooting step. They can
contain unrelated scenes and settings. Back up the OBS profile and use OBS itself
to repair or recreate a source when necessary.

## Provider notes, jokes, or memes fail

Select the intended provider explicitly where supported:

```bash
scribe notes transcript.txt --provider ollama
scribe notes transcript.txt --provider xai
scribe joke transcript.txt --provider xai
scribe meme transcript.txt --provider xai
```

Each provider validates its own key. A non-OpenAI provider does not require an
OpenAI key. Use `scribe health --provider NAME` or `scribe doctor --live` only when
a live request is acceptable.

Meme generation can use separate concept and image providers. Check both
`SCRIBE_MEME_PROVIDER` and `SCRIBE_MEME_IMAGE_PROVIDER`. Local-only mode rejects
image generation because Scribe does not currently ship a local image backend.

Provider model names, rate limits, prices, and availability change. Consult the
provider's current official documentation instead of relying on an old command
example.

## Speaker labels are missing

Run `scribe info` and read the `speaker labels` line. If it reports no backend,
install the token-free Nemotron extra:

```bash
uv tool install --force --python 3.12 --torch-backend auto \
  "scribe[diarize-nemotron] @ git+https://github.com/blisspixel/scribe.git@v2.10.0"
scribe info
```

For pyannote, install the `diarize` extra and set `HF_TOKEN` in the local
environment without printing it. The token's account must have accepted the
pyannote model terms. Nemotron handles at most eight speakers; use
`--diarizer pyannote` for larger groups.

If the line reports `cpu; this PyTorch build has no CUDA`, labels still work but
run on the CPU. Reinstall with `--torch-backend auto` to use the GPU. Labeling is
local inference after the first model download from Hugging Face. A labeling
failure keeps the unlabeled transcript and logs the reason.

## Speaker names are missing or wrong

Names appear only with `--name-speakers` and only when the conversation contains
clear evidence, such as introductions or people addressing each other. A speaker
stays `unidentified` rather than getting a guess. Check the log for the reason:
no local model (start Ollama and pull a model, or set `SCRIBE_SPEAKERS_PROVIDER`
to a cloud provider), a model reply that could not be parsed, or ambiguous
evidence. Correct any name in the header and the text; the labels in the JSON
output keep the original `SPEAKER_xx` identifiers.

## Transcription is slow on a capable GPU

Another process can hold most of the GPU's memory; a local LLM loaded by Ollama
is a common example. On Windows the driver then spills CUDA memory into system
RAM, which makes transcription many times slower instead of failing. Scribe warns
when free GPU memory is below what the Whisper model needs, and switches from
batched to sequential decoding when a batch will not fit. Check and free it:

```bash
nvidia-smi
ollama ps
ollama stop MODEL_NAME
```

## Resident voice fails

Install the tray extra and run its check without starting the resident process:

```bash
uv tool install --force --python 3.12 \
  "scribe[tray] @ git+https://github.com/blisspixel/scribe.git@v2.10.0"
scribe tray --check
```

Verify microphone, accessibility, notification, clipboard, and audio-device
permissions as applicable. Windows is the validated resident path. macOS and
Linux remain experimental until the documented live matrix is complete.

If a stale single-instance marker is suspected, first exit Scribe through its
normal control and confirm no Scribe voice process is running. Do not delete
state while a process is active. See [VOICE.md](VOICE.md) for platform-specific
recovery.

## Exit codes

Scribe's current CLI contract is:

| Code | Meaning |
|---:|---|
| 0 | Requested command completed successfully |
| 1 | Runtime, validation, dependency, or partial-artifact failure |
| 2 | Command-line usage or parsing error |

A session can return code 1 after producing a valid core transcript when a
requested derived artifact fails. Read the session summary before retrying work.

## Logs and support bundles

Use the log path reported by Scribe. To prepare a bounded diagnostic archive:

```bash
scribe support-bundle
```

The bundle applies redaction rules, but automated redaction is not a guarantee.
Inspect every file before sharing it. Remove transcripts, recordings, local paths,
usernames, hostnames, organization names, participant names, tokens, and any other
data that the recipient does not need.

When reporting a problem, include the Scribe version or commit, operating system,
Python version, command shape with private values replaced, exit code, and the
smallest relevant sanitized error excerpt. Never attach a real recording unless
all necessary permissions and an approved transfer method are in place.

Version baseline: Scribe 2.10.0.
