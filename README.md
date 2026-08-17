# Scribe

Local-first speech transcription, meeting notes, and recording tools for Windows,
macOS, and Linux.

Scribe transcribes on your machine by default and does not require a dedicated
GPU. The base install works on CPU, NVIDIA CUDA is used when available, and
optional backends support Apple Silicon, AMD, and Intel systems. Paid cloud
transcription and AI-generated extras are explicit opt-ins.

## Quick start

Scribe requires Python 3.12 or 3.13, [uv](https://docs.astral.sh/uv/), and FFmpeg.

```bash
uv tool install --python 3.12 git+https://github.com/blisspixel/scribe.git
uv tool update-shell

scribe init
scribe info
scribe meeting.mp4
```

After `uv tool update-shell`, open a new terminal. The `scribe` command then works
from any directory.

No package named `scribe` has been published for this project, so install from
this repository rather than PyPI, where an unrelated package holds that name.

If a cloud-synced home folder causes a hardlink error, repeat the install with
`--link-mode=copy`.

## CLI preview

![Scribe recording settings in a terminal](docs/assets/cli-recording-preview.png)

This preview is captured from the real `scribe record` command with a neutral
`./recordings` path and no user, recording, account, or provider data.

The complete command overview remains available as searchable text:

```text
$ scribe --help
scribe 2.8.1

  transcribe FILE  transcribe audio/video
  url LINK         transcribe from URL
  batch FILES      process multiple files
  rec NAME         record via OBS
  record NAME      advanced OBS recording
  music FILE       extract lyrics
  notes TRANSCRIPT meeting notes
  joke TRANSCRIPT  generate joke
  meme TRANSCRIPT  generate meme
  query TEXT       search transcripts
  vocab            domain glossaries
  listen           dictate (speech to type)
  tray             resident voice hotkeys
  say FILE         read a file aloud
  clean FILE       remove silence / trim
  compare          compare AI providers
  health           provider health check
  doctor           diagnostics
  info             configuration
  init             first-run setup
  shortcut         install Quick Record launcher
  support-bundle   create a diagnostic bundle
  version          show version
  help             show this help

scribe <cmd> -h for options
```

## Hardware support

No particular GPU model is required. The standard local backend runs on CPU and
automatically uses a compatible NVIDIA GPU when one is available. Apple Silicon
users can install the `mlx` extra for Metal acceleration. AMD, Intel, and other
portable configurations can install the `whispercpp` extra. These accelerators
improve speed but do not define whether Scribe can be used. Run `scribe doctor`
to see the local path available on a particular machine.

## Cost and privacy defaults

`scribe meeting.mp4`, `--method auto`, and `--method local` stay local and do not
require an API key. Cloud transcription requires `--method openai`. Notes, jokes,
and memes are off by default and require positive flags. `SCRIBE_LOCAL_ONLY=1`
adds a strict guard against cloud providers. `scribe doctor` is local;
`scribe doctor --live` is the explicit provider-connectivity check.

## What Scribe does

- Transcribes local audio and video files.
- Downloads and transcribes supported media URLs.
- Processes batches and music collections with truthful partial-failure summaries.
- Produces TXT, JSON, DOCX, Markdown, VTT, and SRT outputs.
- Adds local speaker labels with the optional diarization extra.
- Generates optional notes, jokes, and memes through selected local or cloud providers.
- Records through OBS and installs a Quick Record launcher.
- Provides opt-in speech-to-type and read-aloud through a resident tray.
- Searches structured transcript archives with `scribe query`.

## Common commands

```bash
scribe meeting.mp4
scribe url https://example.com/podcast.mp3
scribe batch *.mp4
scribe music album/*.flac --method local
scribe meeting.mp4 --notes
scribe rec "Team Meeting"
scribe doctor
scribe query "action item"
```

See the [CLI guide](docs/CLI.md) for workflows, common flags, exit behavior, and
failure evidence. The command itself remains authoritative: use `scribe --help`
or `scribe COMMAND --help` for the complete option set.

## Resident voice

The optional tray provides tap-to-toggle dictation and selection read-aloud:

```bash
# In a cloned development checkout
uv sync --locked --extra tray

scribe tray --setup
scribe tray --check
scribe tray
```

Only one updated `scribe tray`, `scribe tray --no-tray`, or `scribe listen`
process can own resident voice for an operating-system user. Duplicate launches
exit before registering hotkeys or loading another CUDA model. Shutdown and
native fallback also refuse to overlap an incompletely released backend.

The full Python tray is live-validated on Windows. macOS and Linux support remains
experimental pending completed hardware validation records. See the
[resident voice guide](docs/VOICE.md) for installation, hotkeys, startup,
platform permissions, resource ownership, diagnostics, and recovery.

## Installation options

For daily use, install the global command shown in Quick start. For development:

```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
uv sync --locked --group dev
uv run scribe doctor
```

Optional extras are installed only when needed:

```bash
uv tool install --python 3.12 "scribe[mlx] @ git+https://github.com/blisspixel/scribe.git"
uv tool install --python 3.12 "scribe[whispercpp] @ git+https://github.com/blisspixel/scribe.git"
uv tool install --python 3.12 "scribe[diarize] @ git+https://github.com/blisspixel/scribe.git"
uv tool install --python 3.12 "scribe[tray] @ git+https://github.com/blisspixel/scribe.git"
```

The [deployment guide](docs/DEPLOYMENT.md) covers global and development installs,
optional MLX, whisper.cpp, diarization, voice, and Kokoro extras, GPU setup,
upgrades, and backups.

## Configuration

Run `scribe init` to write `~/.scribe/config.toml`. CLI flags override environment
variables and `.env`, which override the config file. Provider, OBS, output, and
hardware settings are documented in the [deployment guide](docs/DEPLOYMENT.md).

## Reliable outcomes

Started workflows write unique session summaries and distinguish complete,
partial, failed, and instrumental outcomes. Incomplete runs exit nonzero without
discarding usable artifacts. `scribe support-bundle` creates a bounded, redacted
diagnostic bundle for review before sharing.

## Documentation

- [CLI guide](docs/CLI.md)
- [Resident voice guide](docs/VOICE.md)
- [Deployment guide](docs/DEPLOYMENT.md)
- [Troubleshooting guide](docs/TROUBLESHOOTING.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Development guide](docs/DEVELOPMENT.md)
- [Responsible use](docs/RESPONSIBLE_USE.md)
- [Security policy](SECURITY.md)
- [Roadmap](ROADMAP.md)
- [Changelog](CHANGELOG.md)
- [Documentation index](docs/README.md)

## Development quality gates

CI requires Ruff, strict mypy, an 81 percent combined statement-and-branch
coverage floor, dependency and artifact audits, and native source checks.
Commands and release verification are in the
[development guide](docs/DEVELOPMENT.md).

## Project status

Version 2.8.1 is the current development version. No public release has been
published. Installations from `main` should be treated as development builds.
See the [changelog](CHANGELOG.md) for completed changes and the
[roadmap](ROADMAP.md) for remaining work.

## Security, privacy, and responsible use

Local transcription stays on the device. Selecting cloud transcription or a
cloud intelligence provider sends the relevant audio or text to that provider.
Scribe does not add telemetry that phones home.

### Recording and authorization notice

Recording and transcription laws, consent requirements, workplace rules,
platform terms, and organizational policies vary by location and context. Use
Scribe only for lawful and authorized purposes. Before recording or processing a
conversation, obtain every permission and consent required by applicable law and
policy, and confirm that you are authorized to collect, use, store, and share the
audio and resulting transcript. Do not use Scribe where recording is prohibited
or where you do not have the required permission.

Scribe does not determine whether a recording is legal, authorized, or compliant.
You are solely responsible for your use of the software, provider terms, consent,
privacy, data protection, retention, disclosure, and handling of sensitive or
regulated material. If you are unsure whether a use is permitted, do not record
until you have obtained appropriate guidance. This information is not legal
advice. Read [Responsible Use](docs/RESPONSIBLE_USE.md) before recording other
people or processing sensitive material. Report vulnerabilities through the
[security policy](SECURITY.md).

## License

Copyright 2026 Nick Seal. Scribe is licensed under the
[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for the copyright notice and
[Responsible Use](docs/RESPONSIBLE_USE.md) for recording, privacy, cloud-sharing,
accuracy, and warranty guidance.

Scribe bundles no third-party source. Dependencies are installed from their own
publishers and keep their own licenses, which are not all Apache-2.0: the
optional `voice` and `tray` extras install `pynput` and `pystray` under
LGPL-3.0, and models and executables such as FFmpeg, Whisper checkpoints, and
Kokoro voices carry separate terms. Review the licenses of the extras and models
you choose to install, particularly if you redistribute Scribe as part of a
larger work.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution expectations and the
[development guide](docs/DEVELOPMENT.md) for technical setup. Community behavior
is covered by the [Code of Conduct](CODE_OF_CONDUCT.md), and usage questions by
[SUPPORT.md](SUPPORT.md). Report security issues through [SECURITY.md](SECURITY.md).
