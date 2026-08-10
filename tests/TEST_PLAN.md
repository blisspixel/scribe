# Scribe Test Plan

## Purpose

Scribe combines deterministic Python logic with hardware, desktop, native-code,
media, and provider boundaries. The test strategy keeps default CI hermetic while
making live validation explicit.

## Required automated gates

Every change to `main` must pass:

- Ruff formatting and linting.
- Strict mypy for `src/scribe`.
- Python 3.12 and 3.13 unit tests.
- The combined statement-and-branch coverage gate at or above 81 percent.
- Windows and macOS platform smoke tests.
- Pre-commit repository hygiene checks.
- A zero-exception dependency vulnerability audit.
- Root-wheel build, metadata, license, and isolated-install checks.
- Go tray source validation on Windows.
- Rust formatting, Clippy with warnings denied, and tests.

CI results are the source of truth for current pass counts. Documentation records
the enforced contract rather than a test count that becomes stale whenever tests
are added.

## Test layers

### Unit tests

Use isolated tests for parsing, routing, configuration, validation, policy, state
machines, transcript models, writers, provider adapters, and error handling. Mock
GPU, OBS, microphone, OS, network, and provider boundaries by default.

### Integration and end-to-end tests

Use small generated fixtures to validate component boundaries such as conversion,
chunking, local transcription adapters, output persistence, and CLI workflows.
These tests must remain deterministic unless explicitly marked.

### Property and fault-injection tests

Use property tests for pure invariants and fault injection for atomic writes,
cleanup, retries, state transitions, and partial-result preservation.

### Manual and live tests

Real GPU, microphone, OBS, platform permissions, provider APIs, and long-media
tests require explicit selection. Paid or cloud validation also requires deliberate
approval of cost and data transfer.

## Data policy

All committed inputs and expected outputs must be synthetic. Never commit real
recordings, transcripts, customer or employer names, contact details, provider
responses, support bundles, private vocabulary, or identifying local paths.

## Standard commands

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy --strict src/scribe
uv run pytest tests/unit -m "not gpu and not slow and not e2e and not requires_openai and not requires_ffmpeg and not requires_whisperx and not requires_pillow" -q
uv run pytest --cov=scribe --cov-report=term-missing --cov-fail-under=81 -m "not gpu and not slow and not requires_openai and not requires_whisperx and not requires_pillow" -q
```

Run the smallest relevant test first, then the complete gate appropriate to the
risk of the change.

## Residual risk

Automated tests cannot fully establish behavior for every audio device, GPU and
driver combination, OBS installation, desktop permission model, media codec, or
external provider. User-facing claims must therefore stay bounded to validated
platforms and reproducible evidence.
