# Scribe

[![CI](https://github.com/blisspixel/scribe/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/blisspixel/scribe/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.12 | 3.13](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue.svg)](https://www.python.org/downloads/)

Local-first speech transcription, meeting notes, and defensive OBS recording for
Windows, macOS, and Linux.

Scribe runs transcription on your machine by default. It works on CPU, uses
compatible NVIDIA hardware automatically, and offers optional Apple Silicon, AMD,
and Intel backends. Cloud transcription and AI-generated extras are explicit
opt-ins.

## Quick start

Scribe requires Python 3.12 or 3.13, [uv](https://docs.astral.sh/uv/), and FFmpeg.
OBS Studio is required only for recording.

```bash
# For a private repository, first authenticate Git (not only the GitHub CLI).
gh auth setup-git
uv tool install --with "av<19" --torch-backend auto --python 3.12 git+https://github.com/blisspixel/scribe.git@v2.12.0
uv tool update-shell

scribe init
scribe doctor
scribe meeting.mp4
```

For a local checkout, `bash packaging/linux/omarchy/install.sh` provides the
Linux installation path without a private Git URL. Git authentication is only
needed to fetch private source; it adds no runtime transcription dependency.

Open a new terminal after `uv tool update-shell`. This project is not published
on PyPI, where an unrelated package uses the same name.

The current release needs `--with "av<19"` because its faster-whisper decoder
uses a PyAV argument removed in version 19. New source installs carry this bound
in package metadata. `--torch-backend auto` selects a matching PyTorch build,
including CPU wheels when no supported NVIDIA driver is found.

Allow disk space before installing: a reported Linux install used about 1.2 GB
for the CPU tool environment and 5.7 GB with CUDA packages. These are observations,
not fixed sizes; platform, selected extras and cached wheels change the download
and installed footprint. Model weights are a separate download on first use.

### Omarchy

Omarchy is the Linux desktop this project is set up for: Arch, Hyprland,
Quickshell, PipeWire, and a preinstalled OBS Studio. Its `python` is 3.14, which
Scribe does not run. Install uv, then pin the tool to Python 3.12:

```bash
omarchy pkg add uv
uv tool install --with "av<19" --torch-backend auto --python 3.12 --force \
  "scribe[tray] @ git+https://github.com/blisspixel/scribe.git@v2.12.0"
uv tool update-shell
scribe init
scribe doctor
scribe voice check
scribe voice omarchy-install
```

A git checkout can run `bash packaging/linux/omarchy/install.sh` instead. That
script installs the same extra and the Hyprland markers. Removal is
`bash packaging/linux/omarchy/uninstall.sh`: it drops the markers and the uv
tool, and it preserves XDG Scribe directories and legacy `~/.scribe`. Upgrade by
running the install script
again. These helpers are not a package-index submission and they are not a
tested Omarchy installation.

FFmpeg, yt-dlp, and OBS are already on a standard Omarchy install. `scribe rec`
records through OBS. That is separate from Omarchy's Alt+Print Screen capture.
Desktop dictation stays with Omarchy (F9, Super+Ctrl+X, and Right Alt when a
dictation backend is installed). Scribe's chords are Super+Alt+D, Super+Alt+Shift+D,
Super+Alt+Y, Super+Alt+I, Super+Alt+A, and Super+Alt+O. Confirm them with
Super+K before relying on them.

`scribe voice` reuses the resident voice owner. It does not open a second
microphone or load a second model. The microphone stays off until dictate, and
recording is marked MICROPHONE ON in the terminal overlay, in
`$XDG_STATE_HOME/scribe/voice-status.txt` (default
`~/.local/state/scribe/voice-status.txt`), and in a critical notification. Copy, insert, and
read run only when asked. Insert pastes through Hyprland, not `wtype`. Cloud
transcription is not available on this command. `scribe voice check` does not
open the microphone. A successful check is not a tested Omarchy installation:
microphone selection, focus changes, correct-target insertion, cancellation,
device loss, and recovery have not been demonstrated on Omarchy hardware. The
[deployment guide](docs/DEPLOYMENT.md#omarchy) has the install and removal steps.

For other setup variants, optional backends, upgrades, and recovery, see the
[deployment guide](docs/DEPLOYMENT.md).

The unused `whisperx` extra has been retired. Remove `[whisperx]` from old install
commands: the base install already supports faster-whisper, including Whisper
large models. Add `[diarize]` only for the existing pyannote speaker-label backend.
Reinstall into a fresh tool environment to remove dependencies left by an older
WhisperX installation. No Whisper model or transcription backend was removed.

## What Scribe does

- Transcribes local audio and video into TXT, JSON, DOCX, Markdown, VTT, and SRT.
- Downloads and transcribes supported media URLs.
- Processes batches and music collections with truthful partial-failure results.
- Records through OBS without taking control of an existing recording.
- Offers explicit OpenAI or OpenRouter cloud transcription when local processing is not desired.
- Adds optional local speaker labels (token-free NVIDIA Nemotron on GPU or CPU),
  best-guess speaker names from a local or chosen cloud model, and vocabulary
  correction.
- Generates opt-in transcript notes with local Ollama by default and cloud notes
  only by explicit provider choice. Notes show prose and relevant sections;
  generated claims still need source review. Jokes and memes use their selected
  local or cloud provider. See [generated outputs](docs/CLI.md#optional-generated-outputs).
- Provides optional speech-to-type, read-aloud, and resident voice hotkeys.
- Searches structured transcript archives.

## Common workflows

```bash
scribe meeting.mp4
scribe url https://example.com/podcast.mp3
scribe batch *.mp4
scribe meeting.mp4 --notes
scribe rec --check
scribe rec "Team Meeting"
scribe query "action item"
```

File, URL, and batch commands save transcripts, sidecars, notes, and session
summaries in the output folder selected by `scribe init`. `SCRIBE_OUTPUT_FOLDER`
overrides that setting; `-o PATH` overrides it for one run. For example,
`scribe batch *.mp4 -o ./archive --format json,md` writes a searchable archive
without moving the input media. `scribe query` searches the configured folder by
default; use `--folder ./archive` to search a one-run override.
Same-name recordings receive separate artifact filenames so earlier transcripts
and sidecars remain searchable. If a URL transcript cannot be archived, Scribe
retains the download and transcript and reports the failure.

Disposable audio conversions use an owned temporary folder and are removed even
when transcription fails. Original media and recoverable partial transcripts
remain intact. `--keep-all` retains conversions beside the input; existing copies
are preserved. Session summaries list deleted conversions separately from moved
transcripts. Logs use a user directory rather than creating `./logs` in the
current working directory; `SCRIBE_LOG_FOLDER` still overrides the location.

![Scribe recording settings in a terminal](docs/assets/cli-recording-preview.png)

Use `scribe --help` or `scribe COMMAND --help` for version-matched options. The
[CLI guide](docs/CLI.md) covers commands, common flags, exit behavior, and session
evidence.

## Recording that fails safe

Recording is a data-preservation workflow. The normal control path requires
advancing OBS output counters and independently checks for a fresh growing file.
The emergency path requires file growth before it reports confirmation. Scribe
never stops or replaces a recording that was already active. If capture ends
unexpectedly, it preserves the partial file and reports an incomplete session.

Run `scribe rec --check` before an important meeting. The
[recording guide](docs/RECORDING.md) explains OBS setup, normal and emergency
control paths, platform requirements, monitoring, safe stop, and recovery. The
[troubleshooting guide](docs/TROUBLESHOOTING.md) provides symptom-specific fixes.

Linux user files follow XDG config, data, state, and runtime directories. Legacy
`~/.scribe/config.toml` and vocabulary remain readable. Default output follows
the localized Videos directory; configured output still wins. Diagnostic logs
default to the user state directory on Linux and `~/.scribe/logs` elsewhere. See
[user storage and upgrade guidance](docs/STORAGE.md) for paths, precedence, and
private runtime requirements.

## Local and explicit by default

`scribe meeting.mp4`, `--method auto`, and `--method local` stay local and do not
require an API key. Cloud transcription requires `--method openai` or
`--method openrouter`; neither is selected by `auto`. Notes, jokes, and memes are
disabled by default and require positive flags.
`SCRIBE_LOCAL_ONLY=1` adds a strict cloud-provider guard. `scribe doctor` is local;
`scribe doctor --live` is the explicit provider-connectivity check.

File transcription defaults to `max`: full Whisper large-v3, recording-wide
language evidence and a separate cached local acoustic pass. It can take longer
than the recording on CPU and needs several GB of free memory. The review flags
disagreements and uncertainty for listening; agreement does not certify accuracy.
Scribe reports the model and cache requirements with `scribe info`. A missing
verifier or required report produces partial output while retaining primary text
and source audio. No smaller primary or paid fallback is silently selected.

```bash
scribe transcribe meeting.mp4 --quality accurate  # full large-v3, one pass
scribe transcribe meeting.mp4 --quality balanced  # turbo, opt-in
scribe transcribe meeting.mp4 --model medium     # explicit primary override
scribe transcribe meeting.mp4 --verification best-effort
```

The default secondary is large-v3-turbo and must already be cached. See
[acoustic review setup and limits](docs/ACOUSTIC_REVIEW.md). CLI flags override
`SCRIBE_TRANSCRIPTION_QUALITY`, `SCRIBE_TRANSCRIPTION_VERIFICATION` and
`SCRIBE_VERIFICATION_MODEL`, which override matching `[transcription]` TOML keys
`quality`, `verification` and `verification_model`. An explicit primary model or
backend wins. Resident voice retains its separate profiles. See the
[model, backend and memory guide](docs/PERFORMANCE_TUNING.md).

File speech language is detected automatically. `--language es` or another
explicit language forces that language; `--language auto` restores detection for
one run. A primary language is a manual preset, not an English bias in detection:

```toml
[transcription]
auto_detect_language = true
primary_language = "en"  # used only when detection is disabled and no language is forced
```

Set the primary to your usual language and disable detection when you deliberately
want that preset. Existing explicit `language = "en"` settings remain forced;
remove that setting or use `--language auto` to enable detection. No legacy user
preference is silently rewritten.

OpenRouter is fully optional and uses its dedicated speech-to-text endpoint with
bounded local chunking, price-prioritized routing, a $5 per-transcription
reported-cost circuit breaker, and confirmed partial preservation. A provider-side
key limit is required for an absolute spending cap. Override the guard for one
input with `--max-spend USD`. See the
[cloud transcription guide](docs/CLOUD_TRANSCRIPTION.md) for setup, data sharing,
model selection, spending limits, failure behavior, and safe testing.

No particular GPU is required. The standard backend runs on CPU and compatible
NVIDIA GPUs. Optional `mlx` and `whispercpp` installs support Apple Silicon and
portable AMD or Intel paths. Run `scribe doctor` to see the available backend.
Local speaker labels need the `diarize-nemotron` extra and run on any of these
machines; `scribe info` shows the backend and device. See the
[CLI guide](docs/CLI.md) for speaker-label options.

## Optional resident voice

The tray adds tap-to-toggle dictation and selection read-aloud:

```bash
scribe tray --setup
scribe tray --check
scribe tray
```

The full Python tray is live-validated on Windows. macOS and Linux remain
experimental until their hardware validation records are complete. On Omarchy,
`scribe voice` is the compositor path: Hyprland owns the shortcuts and a
terminal overlay shows recording state. That path is experimental and was not
demonstrated on Omarchy hardware. The tray does not take F9, Super+Ctrl+X, or
Right Alt. Installation, hotkeys, permissions, single-instance ownership, and
recovery are in the [resident voice guide](docs/VOICE.md).

## Reliable outcomes

Started workflows write unique session summaries and distinguish complete,
partial, failed, and instrumental outcomes. Incomplete work exits nonzero without
discarding usable artifacts. `scribe support-bundle` creates a bounded, redacted
diagnostic bundle for review before sharing.

## Documentation

- [Recording guide](docs/RECORDING.md)
- [CLI guide](docs/CLI.md)
- [Cloud transcription guide](docs/CLOUD_TRANSCRIPTION.md)
- [Deployment guide](docs/DEPLOYMENT.md)
- [Resident voice guide](docs/VOICE.md)
- [Troubleshooting guide](docs/TROUBLESHOOTING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development guide](docs/DEVELOPMENT.md)
- [Release process](docs/RELEASE_PROCESS.md)
- [Responsible use](docs/RESPONSIBLE_USE.md)
- [Security policy](SECURITY.md)
- [Roadmap](ROADMAP.md) and [changelog](CHANGELOG.md)
- [Complete documentation index](docs/README.md)

## Project status

Version 2.12.0 is the current GitHub release. It is not published on PyPI.
Linux compositor voice is experimental and is not a tested Omarchy installation.
CI
enforces Ruff, strict mypy, an 81 percent combined
statement-and-branch coverage floor, dependency and artifact audits, and native
source checks. The dependency-ordered version plan and remaining platform
evidence are tracked in the [roadmap](ROADMAP.md).

## Responsible use and security

Use Scribe only for lawful, authorized recording and processing. Obtain every
consent required by law, policy, and context. Cloud features send relevant audio
or text to the selected provider; local transcription does not. Review
[Responsible Use](docs/RESPONSIBLE_USE.md) before recording other people or
processing sensitive material. Report vulnerabilities through the
[security policy](SECURITY.md).

## License and contributing

Copyright 2026 Nick Seal. Scribe is licensed under the
[Apache License 2.0](LICENSE). Dependencies, models, and external executables keep
their own licenses; see
[deployment and redistribution](docs/DEPLOYMENT.md#licensing-and-redistribution).

See [CONTRIBUTING.md](CONTRIBUTING.md) and the
[development guide](docs/DEVELOPMENT.md) to contribute.
