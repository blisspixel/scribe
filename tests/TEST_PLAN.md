# Scribe Test Plan

## Current Status

Date: 2026-07-15

- 1711 assertion-based tests collected.
- Latest local CI-safe unit matrix: 1570 passed, 1 skipped, 37 deselected.
- Latest broader CI-equivalent gate: 1673 passed, 11 skipped, 27 deselected, no warnings, and 83.54 percent coverage.
- Current enforced coverage floor: 80 percent.
- CI enforces Ruff, Ruff format, mypy strict, pytest, coverage, pre-commit,
  pip-audit, the root-wheel build and isolated-install contract, and the Windows
  native-tray source contract.

## Test Strategy

Scribe is a local-first CLI with heavy hardware and OS integration points. The test strategy separates deterministic logic from live environment behavior:

- Pure logic and policy should be unit-tested thoroughly.
- CLI wiring should be tested with mocked dependencies.
- Provider, OBS, GPU, microphone, tray, and filesystem edge paths should use mocks unless deliberately marked as live/manual.
- Live hardware and provider checks are not required for the default CI-safe subset.
- Coverage must stay above the 80 percent floor, but new tests should optimize for meaningful assertions.

## Current Strengths

- Strong recorder, CLI, provider, diagnostics, vocabulary, transcript, resilience, and voice/tray unit coverage.
- Hypothesis property tests for pure logic including costs, backend selection, diarizer behavior, transcript model, validation, vocabulary, recording policy, resilience backoff, and voice tray state.
- Fault-injection coverage for atomic writes and API circuit breaker behavior.
- Strict markers prevent accidental CI use of GPU, slow, provider, FFmpeg, WhisperX, and Pillow-dependent paths.
- Release-artifact tests reject workspace-only mandatory wheel metadata, while
  required CI builds, inspects, installs, and smokes the portable root wheel.

## Priority Coverage Areas

### 1. Audio And Codec Resilience

Why:
- Audio handling sits on external tools and deprecated TorchAudio surfaces.
- Current local tests show TorchAudio deprecation warnings pointing toward TorchCodec migration risk.

Target:
- Duration detection and metadata fallback behavior.
- FFmpeg/ffprobe absence, bad output, and timeout cases.
- Codec/container edge cases that can be represented with small fixtures or mocks.

### 2. CLI Flow Regression Protection

Why:
- `src/scribe/cli/main.py` is a large user-facing surface.
- Small copy, option, and feature-resolution regressions have high support cost.

Target:
- `transcribe`, `url`, `batch`, `record`, `notes`, `joke`, `meme`, `doctor`, `info`, `query`, `listen`, `say`, and `tray --check` option behavior.
- Cost-safety defaults and explicit opt-in behavior.
- Local-only mode refusal paths.

### 3. Provider Boundary Safety

Why:
- Cloud calls are explicit opt-in and must stay visible.

Target:
- Provider selection and failover messages.
- Missing key and invalid key paths.
- No transcript or API key leakage into logs.
- Local-only mode routes and refusal messages.

### 4. Voice And Tray Platform Matrix

Why:
- Windows is validated, but macOS/Linux live behavior remains the product priority.

Target:
- Pure state and settings tests stay in CI.
- Live macOS/Linux hotkey, tray, audio, and permission checks remain manual until stable fixtures exist.
- `scribe tray --check` should expose platform caveats clearly.

### 5. Documentation And Metadata Regression Checks

Why:
- Stale docs created product-trust issues.

Target:
- Keep README, ROADMAP, CHANGELOG, docs, package metadata, and test docs aligned.
- Consider adding a lightweight local check for known stale phrases only after the phrase set stabilizes.

## Standard Validation Ladder

Use the smallest useful subset first:

```bash
uv run pytest tests/unit/test_target.py -q
```

Then run local gates before a commit:

```bash
uv sync --locked --group dev
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src/scribe
uv run pytest tests/unit -m "not gpu and not slow and not e2e" -q
```

For coverage-sensitive work:

```bash
uv run pytest tests/unit -m "not gpu and not slow and not e2e" --cov=src/scribe --cov-report=term-missing --cov-fail-under=80 -q
```

For dependency/security work, mirror the CI `pip-audit` command including ADR-004 torch ignores.

## Manual Validation

Manual checks are appropriate for:
- Real OBS recording.
- Real microphone dictation.
- Real read-aloud.
- macOS Input Monitoring and microphone permissions.
- Linux X11 and Wayland global hotkey behavior.
- Real GPU throughput.
- Real provider calls.

Paid or cloud validation requires explicit approval before it runs.
