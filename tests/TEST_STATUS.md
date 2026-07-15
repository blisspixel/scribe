# Test Suite Status

## Current Reality

As of 2026-07-15:

- Pytest collection: 1651 assertion-based tests across unit, integration, e2e, and manual coverage.
- Latest local CI-safe unit matrix: 1512 passed, 2 skipped, 37 deselected.
- Latest broader CI-equivalent gate: 1612 passed, 12 skipped, 27 deselected, and 83.07 percent coverage.
- Enforced project coverage floor: 80 percent.
- Standard quality gates: Ruff check, Ruff format check, mypy strict, 80 percent coverage, root-wheel artifact and isolated-install verification, build, and pip-audit with the documented CI ignores.

## Standard Local Commands

```bash
uv sync --locked --group dev
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src/scribe
uv run pytest tests/unit -m "not gpu and not slow and not e2e and not requires_openai and not requires_ffmpeg and not requires_whisperx and not requires_pillow" -q
uv run pytest --cov=scribe --cov-report=term-missing --cov-fail-under=80 -m "not gpu and not slow and not requires_openai and not requires_whisperx and not requires_pillow" -q
uv build --out-dir .agent/build
uv run python scripts/check_release_artifact.py .agent/build
```

Run nearby tests for focused work:

```bash
uv run pytest tests/unit/test_vocabulary.py -q
uv run pytest tests/integration/test_converter.py -q
```

## Coverage Strengths

- CLI command parsing and error paths.
- Configuration, validation, and safe file handling.
- Recording policy state machine and recorder behavior.
- Provider abstraction, provider health, and API resilience.
- Voice tray, shortcut, and startup logic.
- Vocabulary parsing and transcript output helpers.
- Fault-injection coverage for atomic writes and provider circuit breaker paths.

## Known Gaps

- Live GPU, microphone, OBS, diarization, and provider API paths require marked integration or manual validation.
- Some broad CLI, converter, provider, and media-composition branches remain below the project average and should receive targeted regression tests when touched.
- Runtime TorchAudio calls remain a future TorchCodec migration concern; unit tests mock invalid media boundaries explicitly and the current CI-equivalent run is warning-free.
- The three standalone hardware/environment scripts use `check_*` probes and are not pytest coverage; live device validation remains manual.

## Manual Or Slow Validation

Manual or slow tests are intentionally outside the default CI-safe loop because they can require hardware, API keys, or large media fixtures. Use explicit markers when validating those paths:

```bash
uv run pytest tests -m "slow"
uv run pytest tests -m "requires_api"
uv run pytest tests/manual
```

## Test Policy

- New behavior should include focused unit coverage before broader integration tests.
- Bug fixes should add or update a regression test when practical.
- External APIs must stay mocked in default local and CI-safe tests.
- Coverage must stay at or above 80 percent with meaningful assertions, not import-only tests.
