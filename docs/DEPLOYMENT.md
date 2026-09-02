# Deployment Guide

## Scope

Scribe is a local-first desktop CLI. It is not a hosted service, web app, multi-user platform, cloud sync product, or enterprise control plane.

This guide covers supported local installation and self-managed operation on machines you control. Containers, shared batch hosts, cloud VMs, and orchestrators are advanced adaptations for operators who accept their own support, security, and reliability burden.

## Supported Product Surface

Supported:
- Single-user workstation installs with `uv tool install` or project-local `uv sync`.
- Local transcription on GPU or CPU.
- Explicit opt-in cloud transcription with `--method openai` or `--method openrouter`.
- Explicit opt-in paid extras for notes, jokes, and memes.
- Local-only mode with `SCRIBE_LOCAL_ONLY=1`.
- OBS recording on the local desktop.
- Local logs under `logs/` and diagnostics through `scribe doctor` and `scribe info`.

Not supported as product surfaces:
- Public servers or REST APIs.
- Multi-user accounts, cloud storage, or shared tenant isolation.
- Kubernetes, autoscaling, or managed hosted deployments.
- Telemetry that phones home.

## Recommended Install

Use a global uv tool install when you want `scribe` available from any folder:

```bash
uv tool install --python 3.12 git+https://github.com/blisspixel/scribe.git@v2.9.2
uv tool update-shell
scribe init
scribe info
```

This project has not published a PyPI package. Install the versioned GitHub
release from this repository; a bare `pip install scribe` installs an unrelated
project.

Use a project-local install when developing Scribe:

```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
uv sync --locked --group dev
uv run scribe init
uv run scribe doctor
```

## Workstation Requirements

Required:
- Python 3.12 or 3.13. Python 3.12 remains the recommended GPU baseline. Python
  3.14 and 3.15 are not yet in the supported runtime matrix; see
  [ADR-001](adr/ADR-001-python-312-baseline.md) for current probe evidence.
- uv.
- FFmpeg.
- Disk space for local media, converted audio, transcripts, logs, and model caches.

Optional:
- NVIDIA GPU with working CUDA stack for the fastest default local backend.
- `scribe[mlx]` for Apple Silicon local acceleration.
- `scribe[whispercpp]` for AMD, Intel, or portable local acceleration.
- `scribe[providers]` for Anthropic and Google Gemini cloud intelligence SDKs.
- `scribe[diarize]` and `HF_TOKEN` for local speaker diarization.
- `scribe[voice]`, `scribe[tray]`, or `scribe[kokoro]` for voice I/O and read-aloud.
- OBS Studio for `scribe rec` and `scribe record`.
- The workspace `scribe-audio-core` build for native silence analysis during
  development. The portable root wheel uses bounded duration-based chunking when
  that unpublished acceleration artifact is absent.

Install tool extras from the Git repository, for example:

```bash
uv tool install --force --python 3.12 \
  "scribe[mlx] @ git+https://github.com/blisspixel/scribe.git@v2.9.2"
uv tool install --force --python 3.12 \
  "scribe[whispercpp] @ git+https://github.com/blisspixel/scribe.git@v2.9.2"
uv tool install --force --python 3.12 \
  "scribe[diarize] @ git+https://github.com/blisspixel/scribe.git@v2.9.2"
uv tool install --force --python 3.12 \
  "scribe[tray] @ git+https://github.com/blisspixel/scribe.git@v2.9.2"
```

The current base install includes the PyTorch and faster-whisper stack, so it is
portable in behavior but not small. Separating heavy ML dependencies is planned
for a compatible major release.

The Go tray is also source-only. Scribe ships no native tray executable and never
selects one implicitly. Developers can run `pwsh -File
scripts/check_native_tray.ps1` to produce ignored, unsigned verification builds
under `.agent/native-tray`, then deliberately point `SCRIBE_TRAY_NATIVE_BIN` at
one. Preflight labels any such path an unverified developer override. Do not treat
that local build as an official release artifact.

The portable root-wheel contract rejects platform-native payload members. Native
components require separate platform-tagged, signed, and attested distribution
contracts before they can become official release artifacts.

## Configuration

Configuration layers, highest precedence first:

1. CLI flags.
2. Environment variables and `.env`.
3. `~/.scribe/config.toml`.

Common environment values:

```env
SCRIBE_OUTPUT_FOLDER=/path/to/scribe/output
SCRIBE_DEFAULT_MODEL=large-v3
SCRIBE_DEFAULT_LANGUAGE=en
SCRIBE_LOCAL_ONLY=false
SCRIBE_ENABLE_NOTES=false
SCRIBE_ENABLE_JOKE=false
SCRIBE_ENABLE_MEME=false
OPENAI_API_KEY=
OPENROUTER_API_KEY=
SCRIBE_OPENROUTER_MODEL=openai/whisper-large-v3
SCRIBE_OPENROUTER_MAX_SPEND_USD=5
XAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
SCRIBE_LOG_LEVEL=INFO
```

Cost safety:
- A plain `scribe meeting.mp4` transcribes locally and does not spend on an API.
- API transcription requires `--method openai` or `--method openrouter`.
- OpenRouter has a $5 per-transcription reported-cost circuit breaker by default.
  Set a provider-side key limit for an absolute cap, including ambiguous retries.
- Notes, jokes, and memes default off unless enabled by config, env, or per-run flags.
- `SCRIBE_LOCAL_ONLY=1` adds a strict cloud-provider guard and routes supported
  intelligence features to local Ollama.

OpenRouter needs no additional Python extra. Scribe uses the base `httpx` runtime
dependency and OpenRouter's dedicated speech-to-text endpoint. Read the
[Cloud Transcription Guide](CLOUD_TRANSCRIPTION.md) before selecting it for
sensitive or long recordings.

## Local Operations

Health checks:

```bash
scribe info
scribe doctor
scribe rec --check
scribe tray --check
```

Logs:

```bash
# PowerShell
Get-ChildItem logs -Filter *.log | Sort-Object LastWriteTime -Descending | Select-Object -First 5
Get-Content logs/scribe_*.log -Tail 200
Select-String -Path logs/*.log -Pattern "ERROR|WARNING"
```

GPU checks:

```bash
nvidia-smi
scribe doctor
```

Output and cleanup:
- Keep transcripts and user media under a user-controlled `SCRIBE_OUTPUT_FOLDER`.
- Keep logs in `logs/`.
- Do not commit `.env`, logs, local media, generated transcripts, or model caches.
- Run `scribe doctor` after dependency, FFmpeg, GPU driver, OBS, or config changes.

## Self-Managed Batch Host

Use this only when one trusted operator controls the machine, inputs, outputs, secrets, and logs.

Recommended pattern:
- Install with `uv sync --locked` or a uv tool install.
- Keep input and output directories outside the repo.
- Use filesystem permissions so only trusted users can read media, transcripts, and logs.
- Run jobs as one service user rather than exposing Scribe directly to multiple untrusted users.
- Monitor disk space and GPU health with OS tooling.
- Avoid exposing OBS WebSocket or any wrapper command to a network you do not fully control.

Example:

```bash
uv sync --locked
$env:SCRIBE_OUTPUT_FOLDER = "D:\scribe-output"
uv run scribe doctor
uv run scribe batch D:\incoming\*.mp4 --no-notes --no-joke --no-meme
```

## Containers

Containers are useful for reproducible local or batch environments, but Scribe does not ship an official container interface.

If you build a container:
- Use Python 3.12 or newer.
- Install FFmpeg.
- Mount media and output directories explicitly.
- Pass API keys through your secret manager, not image layers.
- Keep `SCRIBE_LOCAL_ONLY=1` when no cloud transmission is intended.
- Verify GPU access with `nvidia-smi` inside the container before running a long job.

Do not expose a containerized Scribe command as a public network service without designing and reviewing authentication, authorization, upload validation, tenant isolation, logging, abuse controls, and consent flows.

## Backup And Recovery

Back up:
- `~/.scribe/config.toml`.
- Custom vocabulary files under `~/.scribe/vocab/`.
- User-selected output folders.
- Any operational scripts you maintain outside the repo.

Usually do not back up:
- `.venv/`.
- `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`.
- Model caches unless your environment needs offline rebuilds.
- Logs unless they are needed for audit or support.

Recovery smoke test:

```bash
scribe info
scribe doctor
scribe vocab
scribe rec --check
```

## Licensing and redistribution

Scribe bundles no third-party source. Python dependencies are installed from
their publishers and keep their own licenses. The optional `voice` and `tray`
extras include LGPL-3.0 dependencies. FFmpeg, OBS, Whisper checkpoints, Kokoro
voices, and other external models or executables also carry separate terms.

Review the licenses for every extra, model, and executable you install. A GitHub
release of Scribe does not grant redistribution rights for those separate
components.

## Security

Keep these rules:
- Never commit API keys, `.env`, local media, transcripts, or logs.
- Treat transcripts as sensitive by default.
- Use local transcription and `SCRIBE_LOCAL_ONLY=1` for private or regulated material.
- Review provider terms before using cloud transcription, notes, jokes, or memes.
- Keep OBS WebSocket local and password-protected.
- Restrict output and log directory permissions.
- Rotate API keys if they appear in a shell history, support bundle, log, or shared config.

## Maintenance

Regular checks:
- `scribe doctor` after installs, updates, GPU driver changes, or OBS changes.
- `uv run ruff check src tests` and `uv run mypy --strict src/scribe` before code changes.
- `uv run pytest tests/unit -m "not gpu and not slow and not e2e" -q` for fast local confidence.
- The CI `pip-audit` command before dependency upgrades.

Dependency policy:
- `pyproject.toml` and `uv.lock` are authoritative.
- Pip installs the project directly from `pyproject.toml`; no hand-maintained requirements shim is supported.
- Heavy or platform-specific capabilities should remain optional extras.

## Troubleshooting

Common local checks:
- `scribe doctor` for dependency and configuration issues.
- `scribe info` for backend and provider state.
- `scribe rec --check` for OBS readiness.
- `scribe tray --check` for voice and tray readiness.
- `logs/` for detailed local failure context.

See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for workflow-specific fixes.
