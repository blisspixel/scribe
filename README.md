# Scribe

Local-first speech transcription, meeting notes, and recording tools for Windows,
macOS, and Linux.

Scribe transcribes on your machine by default, using an NVIDIA GPU when available
and CPU fallback otherwise. Paid cloud transcription and AI-generated extras are
explicit opt-ins.

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

If a cloud-synced home folder causes a hardlink error, repeat the install with
`--link-mode=copy`.

## Cost and privacy defaults

`scribe meeting.mp4`, `--method auto`, and `--method local` stay local and do not
require an API key. Cloud transcription requires `--method openai`. Notes, jokes,
and memes are off by default and require positive flags. `SCRIBE_LOCAL_ONLY=1`
prevents paid fallback. `scribe doctor` is local; `scribe doctor --live` is the
explicit provider-connectivity check.

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

CI requires Ruff, strict mypy, branch coverage above 81 percent, dependency and
artifact audits, and native source checks. Commands and release verification are
in the [development guide](docs/DEVELOPMENT.md).

## Project status

Version 2.8.1 is in development with a reliability-first focus: truthful
diagnostics and outcomes, resource-safe resident voice, reproducible artifacts,
and required CI evidence. See the [changelog](CHANGELOG.md) for completed changes
and the [roadmap](ROADMAP.md) for remaining work.

## Security, privacy, and responsible use

Local transcription stays on the device. Selecting cloud transcription or a
cloud intelligence provider sends the relevant audio or text to that provider.
Scribe does not add telemetry that phones home.

You are responsible for recording consent, provider terms, and handling sensitive
data. Read [Responsible Use](docs/RESPONSIBLE_USE.md) before recording other people
or processing regulated material. Report vulnerabilities through the
[security policy](SECURITY.md).

## License

Canonical license terms are pending owner confirmation. The repository currently
contains no `LICENSE` file and package metadata makes no license claim.

## Maintainer

[Nick Seal](https://github.com/blisspixel)
