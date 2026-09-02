# ADR-001: Python 3.12 Development Baseline

## Status
Accepted in 2026; amended 2026-09-01

## Context
Scribe is a **local-first desktop CLI** with heavy native dependencies:
- PyTorch / CUDA wheels (Windows NVIDIA primary target)
- faster-whisper + CTranslate2
- ffmpeg, OBS WebSocket, yt-dlp, etc.

Python 3.12 remains the most conservative Windows GPU baseline, and Python 3.13
has a validated wheel set. A Windows Python 3.14 install probe on 2026-07-28
failed because the universal optional-ML graph selected NumPy and CTranslate2
releases without compatible CPython 3.14 wheels. Standard and free-threaded 3.14
support therefore remain unproven for the stack that defines Scribe's value.

A Windows wheel-only probe on 2026-09-01 found that the base dependency graph
now resolves on Python 3.14.7. That is necessary but not sufficient evidence:
the full runtime suite and required platform matrix have not passed on 3.14.

Python 3.15 was still prerelease on the same date. The official schedule targets
3.15.0 final for 2026-10-01. A CPython 3.15.0rc1 wheel-only probe failed because
Torch 2.13 had no `cp315` wheel, so the required base graph was unsatisfiable.

## Decision
- Set `requires-python = ">=3.12,<3.14"` in pyproject.toml.
- Run the CI-safe unit suite on every declared standard CPython version: 3.12
  and 3.13.
- Add Python 3.14 only after CI validates installation and runtime behavior on
  the declared platform matrix.
- Reconsider Python 3.15 after its final release and compatible native wheels are
  available. Do not claim support from a prerelease syntax-only probe.
- `.python-version` file pins `3.12` for local development consistency (uv + pyenv compatible).
- No chasing of bleeding-edge runtime versions that would break the primary Windows + NVIDIA user base.

## Consequences
### Positive
- Users on current stable Python + current CUDA toolkit can install and use Scribe without friction.
- CI is fast and reliable (real wheels, no source builds or workarounds).
- Matches the "5-10 year local desktop tool" scope and non-goal of "no bleeding-edge runtime chasing."
- Preserves the excellent existing graceful degradation for "no GPU / wrong Python / missing deps."

### Negative / Trade-offs
- Cannot yet use 3.14-only language features or claim free-threaded performance wins in hot paths.
- Slight delay on some newer stdlib improvements (but most are backported or available via backports).

### Mitigations
- Review the decision when the native dependency graph changes materially.
- All new code is written with forward compatibility in mind (no 3.12-only deprecated patterns).
- Documentation clearly states the current baseline and the upgrade path.

## References
- ROADMAP.md (heavy dependency redesign priority)
- pyproject.toml `[project] requires-python`
- .github/workflows/ci.yml (matrix)
- [PEP 790: Python 3.15 release schedule](https://peps.python.org/pep-0790/)

## Related Decisions
- ADR-002: Exception taxonomy and intentional graceful degradation
- ADR-003: Ruff typography confusable allowance
