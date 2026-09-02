# Architecture

Scribe is a local-first Python CLI for authorized recording, transcription, and
optional transcript-derived artifacts. Go and Rust components support bounded
native experiments, but the Python package remains the product entry point.

## System boundary

```text
User or automation
       |
       v
Typer CLI and consent checks
       |
       +--> recording and media input
       |
       +--> transcription orchestrator
       |       +--> faster-whisper on CPU or supported GPU
       |       +--> MLX on supported Apple Silicon installs
       |       +--> whisper.cpp when configured
       |       +--> OpenAI only when explicitly selected
       |       +--> OpenRouter only when explicitly selected
       |
       +--> local artifact writers
       |
       +--> optional provider features
               +--> notes or jokes through a selected text provider
               +--> meme concept and image providers
```

The default `auto` transcription path is local-first. A local failure remains a
local failure; it does not become an unannounced paid upload. Cloud-backed notes,
jokes, memes, health checks, and cloud transcription are separate opt-in data
boundaries.

## Main components

### CLI layer

`src/scribe/cli/main.py` owns command registration and top-level orchestration.
Smaller command services live in `src/scribe/cli/`:

- `consent.py` enforces the recording acknowledgement.
- `errors.py` converts expected failures into consistent CLI output.
- `media.py` and `system.py` implement media and diagnostic commands.
- `voice.py` bridges the CLI to the resident voice service.
- `init.py`, `shortcut.py`, and `query.py` handle focused workflows.

The remaining size of `main.py` is a known maintenance risk and is tracked in
the roadmap.

### Recording and input

`src/scribe/core/recorder.py` coordinates OBS-based recording and applies the
limits from `recording_policy.py`. URL ingestion is isolated in `downloader.py`.
Media conversion and validation occur before transcription. Scribe records only
after the user accepts the consent prompt or supplies the explicit consent flag.
The recorder treats OBS control state as necessary but not sufficient: startup
requires advancing OBS output counters and a fresh growing media file. Recovery
never stops an existing recording, and finalization never moves a file that is
still growing.

### Transcription

`src/scribe/core/transcriber.py` selects the method and coordinates artifacts.
The local backend registry in `src/scribe/core/backends/` separates hardware
detection from faster-whisper, MLX, and whisper.cpp adapters. Optional diarization
uses `diarizer.py` and requires its extra plus a Hugging Face token.

OpenAI transcription is implemented in `openai_api.py`. Large files can use
provider-side chunking or temporary local preparation, depending on the active
configuration. Temporary files are cleaned unless preservation was requested.

OpenRouter transcription is implemented in `openrouter_api.py` against the
provider's dedicated speech-to-text JSON contract. Streaming FFmpeg normalization
and bounded duration chunks prevent a long recording from becoming one in-memory
payload. Confirmed chunks are atomically preserved as an explicitly incomplete
artifact until every request succeeds. The backend refuses to publish a normal
transcript if any chunk is missing.

### Sessions and artifacts

`src/scribe/models/session.py` maintains per-run evidence and writes the session
summary atomically. Depending on the command and options, a successful run may
create:

- Source recording or downloaded media.
- Plain-text transcript and optional structured transcript data.
- DOCX transcript.
- Notes, joke text, or meme image when explicitly enabled.
- Session summary JSON and logs.

Partial outcomes remain explicit when the core transcript succeeds but a requested
derived artifact fails.

### Provider layer

`src/scribe/providers/factory.py` resolves providers with this precedence:

1. Explicit command or Python argument.
2. Feature-specific environment setting.
3. `~/.scribe/config.toml` provider setting.
4. Built-in feature default.

Provider API keys are resolved only for the selected provider. Local-only mode
routes supported text features to Ollama and rejects cloud-only image generation.
Ordinary provider failures do not silently change the selected provider. Optional
health-check failover is a separate explicit configuration and is logged.
Provider catalogs and prices can change, so runtime code rather than documentation
is the source of truth for current model defaults.

### Resident voice

`src/scribe/voice/` implements single-instance control, local dictation, local
read-aloud, startup integration, and the tray surface. Windows is the validated
resident path. macOS and Linux remain experimental pending the live validation
matrix in
[VOICE_TRAY_MAC_LINUX_VALIDATION.md](features/VOICE_TRAY_MAC_LINUX_VALIDATION.md).

The Go tray under `cmd/scribe-tray/` and Rust audio crate under
`crates/scribe-audio-core/` are bounded prototypes and source-checked CI
components. They are not bundled into the Python wheel.

## State and configuration

Configuration sources are applied in documented precedence order by the config
models and `~/.scribe/config.toml`. Secrets belong in environment variables or a
local untracked `.env`, never in committed configuration.

Persistent state is limited to user-selected outputs and Scribe's local config,
logs, vocabulary files, performance history, and resident-service state. Support
bundles redact known secret and local-identity patterns, but users must inspect a
bundle before sharing it.

## Reliability and security properties

- Recording requires an explicit acknowledgement of authorization.
- Recording startup requires positive output progress, not only a control-state flag.
- Existing and still-growing OBS recordings are never stopped or moved by recovery.
- Local transcription does not silently fail over to cloud transcription.
- Provider features are opt-in and identify their cloud data boundary.
- Artifact writes that represent run state use atomic replacement where needed.
- Resource and duration limits constrain media ingestion and recording.
- Network calls use bounded timeouts and retry policy.
- Logs and support bundles avoid raw secret output by design.
- CI pins third-party actions and audits Python, Go, Rust, and built artifacts.

See [SECURITY.md](../SECURITY.md),
[RESPONSIBLE_USE.md](RESPONSIBLE_USE.md), and the accepted decisions in
[adr/](adr/).

## Testing architecture

Tests are organized by contract rather than by a mirrored source tree:

- `tests/unit/` covers deterministic behavior, error paths, CLI contracts, and
  platform simulations.
- Marked tests cover GPU, FFmpeg, external providers, slow paths, and end-to-end
  behavior when prerequisites are available.
- Repository hygiene tests validate documentation links, dependency policy,
  native boundaries, coverage configuration, and packaging constraints.

CI enforces Ruff, strict mypy, an 81 percent combined statement-and-branch
coverage floor, dependency audits, native source checks, and package build checks.

## Known constraints

- A fresh real install and local transcription have not yet been recorded on all
  three claimed desktop operating systems.
- Resident voice has not completed its live macOS and Linux matrix.
- The base dependency set is heavier than the long-term portable target because
  PyTorch-backed transcription remains in the core install.
- `cli/main.py` and `core/recorder.py` still concentrate too much orchestration.
- Native binary distribution needs signing and provenance before release.

These constraints are prioritized in [ROADMAP.md](../ROADMAP.md).

Version baseline: Scribe 2.9.2.
