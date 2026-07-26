# Scribe Test Suite

## Current Status

- 1715 assertion-based tests collected across unit, integration, e2e, and manual paths.
- Latest local CI-safe unit matrix: 1574 passed, 1 skipped, 37 deselected.
- Latest broader CI-equivalent gate: 1677 passed, 11 skipped, 27 deselected, no warnings, and 83.54 percent coverage.
- Enforced coverage floor: 80 percent.
- Quality gates: Ruff check, Ruff format, mypy strict, pytest, pytest-cov, pre-commit, and pip-audit in CI.

## Standard Commands

```bash
uv sync --locked --group dev
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src/scribe
uv run pytest tests/unit -m "not gpu and not slow and not e2e" -q
uv run pytest tests/unit -m "not gpu and not slow and not e2e" --cov=src/scribe --cov-report=term-missing --cov-fail-under=80 -q
```

The full suite includes integration, e2e, GPU, FFmpeg, provider, Pillow, and manual paths. Use markers to keep local runs scoped to the risk of the change.

## Test Layout

- `tests/unit/`: fast, isolated tests for core logic, CLI wiring, providers, diagnostics, output writers, voice/tray policy, and utilities.
- `tests/integration/`: component interaction tests for converter, local Whisper, and OpenAI API paths.
- `tests/e2e/`: full workflow tests that may be slower or depend on heavier setup.
- `tests/manual/`: live provider, device, or timing checks that are not CI-safe.
- Root-level `tests/test_audio.py`, `test_devices.py`, and `test_startup.py`: standalone hardware and environment checks whose `check_*` functions feed script exit status and are intentionally not collected as pytest tests. Other root-level `test_*.py` files contain assertion-based platform tests.

## Markers

Important markers from `pyproject.toml`:
- `slow`
- `gpu`
- `windows`
- `macos`
- `linux`
- `integration`
- `e2e`
- `requires_ffmpeg`
- `requires_openai`
- `requires_whisperx`
- `requires_pillow`

Common filtered run:

```bash
uv run pytest tests/unit -m "not gpu and not slow and not requires_openai and not requires_ffmpeg and not requires_whisperx and not requires_pillow" -q
```

## Coverage Expectations

Coverage is a floor, not a substitute for meaningful assertions.

When adding or changing behavior:
- Test both happy paths and failure paths.
- Prefer pure unit tests for routing, parsing, policy, and state machines.
- Use mocks for provider, GPU, OBS, microphone, and OS integration boundaries.
- Mark live hardware or external-service tests so CI can exclude them.
- Keep the 80 percent gate green.

Known residual risk:
- Live GPU model execution.
- OBS behavior against a real desktop install.
- macOS and Linux tray/hotkey/audio matrix.
- Provider API behavior outside mocked clients.
- Long media files and unusual codec/container inputs.

## Test Data

Use fixtures in `tests/conftest.py` for temporary directories, sample audio, mocked OpenAI, mocked OBS, mocked GPU state, and temporary config.

Do not commit user media, generated transcripts, logs, local model caches, or large binary outputs.

## Adding Tests

1. Put new tests in the narrowest applicable test directory.
2. Follow existing fixture and marker patterns.
3. Keep tests deterministic and hermetic by default.
4. Add regression tests for every fixed failure mode where practical.
5. Run the smallest relevant test first, then the standard local gates.
