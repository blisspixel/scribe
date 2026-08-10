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

Scribe requires Python 3.12 or 3.13, FFmpeg, and uv. This private repository also
requires a GitHub account with access.

Install the current repository version as a tool:

```bash
uv tool install --force --python 3.12 \
  git+https://github.com/blisspixel/scribe.git
uv tool update-shell
```

Open a new terminal after `uv tool update-shell`. If the command is still missing,
run `uv tool list` and follow the path guidance printed by uv.

No package named `scribe` has been published for this project. Do not use a bare
`pip install scribe`, which can install an unrelated package.

If a cloud-synced home directory prevents hardlinks, reinstall with copy mode:

```bash
uv tool install --force --link-mode copy --python 3.12 \
  git+https://github.com/blisspixel/scribe.git
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
silently upload the recording as a fallback. Use `--method openai` only when the
upload is intentional and approved.

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
  "scribe[mlx] @ git+https://github.com/blisspixel/scribe.git"

uv tool install --force --python 3.12 \
  "scribe[whispercpp] @ git+https://github.com/blisspixel/scribe.git"
```

MLX is for supported Apple Silicon systems. whisper.cpp support depends on the
native build available for the target host. Neither extra guarantees acceleration
on every configuration.

## OBS recording fails

Run the non-recording preflight first:

```bash
scribe record --check
```

Confirm OBS is installed, can open normally, and has permission to capture the
intended display and audio devices. On macOS, review Screen Recording and
Microphone permissions. On Windows, verify the expected OBS profile and sources.

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

## Diarization is unavailable

Install the diarization extra and set `HF_TOKEN` in the local environment without
printing it:

```bash
uv tool install --force --python 3.12 \
  "scribe[diarize] @ git+https://github.com/blisspixel/scribe.git"
scribe doctor
```

The token's account must have access to the required gated models. Diarization is
local inference after model acquisition, but downloading the models contacts
Hugging Face.

## Resident voice fails

Install the tray extra and run its check without starting the resident process:

```bash
uv tool install --force --python 3.12 \
  "scribe[tray] @ git+https://github.com/blisspixel/scribe.git"
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

Last verified against Scribe 2.8.1 on 2026-08-11.
