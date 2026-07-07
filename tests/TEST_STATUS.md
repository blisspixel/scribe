# Test Suite Status

## Current Reality

As of 2026-07-07:

- Pytest collection: 1592 tests across unit, integration, e2e, and manual coverage.
- Latest local CI-safe unit coverage gate: 1499 passed, 5 skipped, 1 deselected.
- Latest measured total coverage: 81.69 percent.
- Enforced project coverage floor: 80 percent.
- Standard quality gates: Ruff check, Ruff format check, mypy strict, CI-safe unit coverage, build, and pip-audit with the documented CI ignores.

## Standard Local Commands

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src/scribe
uv run pytest tests/unit -m "not gpu and not slow and not e2e" --cov=src/scribe --cov-report=term-missing --cov-fail-under=80
uv build --out-dir .agent/build
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
- TorchAudio emits deprecation warnings that should be handled in a future TorchCodec migration cycle.

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
