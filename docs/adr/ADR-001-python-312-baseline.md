# ADR-001: Python 3.12 Development Baseline

## Status
Accepted in 2026; amended 2026-10-20

## Context
Scribe is a **local-first desktop CLI** with heavy native dependencies:
- PyTorch / CUDA wheels (Windows NVIDIA primary target)
- faster-whisper + CTranslate2
- ffmpeg, OBS WebSocket, yt-dlp, etc.

Python 3.12 remains the most conservative Windows GPU baseline, and Python 3.13
has a validated wheel set. A Windows Python 3.14 install probe on 2026-07-28
failed because the universal optional-ML graph selected NumPy and CTranslate2
releases without compatible CPython 3.14 wheels. Free-threaded 3.14 and the
optional ML extras were not re-probed on 2026-10-20. The base graph was.

A Windows wheel-only probe on 2026-09-01 found that the base dependency graph
now resolves on Python 3.14.7. That is necessary but not sufficient evidence:
the full runtime suite and required platform matrix have not passed on 3.14.

Python 3.15 was still prerelease on the same date. The official schedule targets
3.15.0 final for 2026-10-01. A CPython 3.15.0rc1 wheel-only probe failed because
Torch 2.13 had no `cp315` wheel, so the required base graph was unsatisfiable.

Python 3.15.0 final shipped on 2026-10-09. A 2026-10-20 index check found no
`cp315` or abi3 wheels for CTranslate2 4.8.3 or ONNX Runtime 1.31.0 across their
releases. faster-whisper 1.2.1 requires both. PyPI torch 2.14.1 has no `cp315`
wheel. The stable PyTorch CPU, cu130, and cu126 indexes have torch 2.14.1
`cp315` wheels for the desktop targets, including free-threaded builds. The
cu128 index has none. Publication of those Torch wheels is not a wheel-only
install of the Scribe base graph, and it is not a free-threaded support claim.
The optional ML extras were not probed.

## Decision
- Set `requires-python = ">=3.11,<3.15"` in both project metadata files. The cap
  stays until CTranslate2 and ONNX Runtime publish cp315 wheels and a wheel-only
  base install resolves. Torch wheels on the stable PyTorch index do not lift it.
- Run the CI-safe unit suite on Python 3.11, 3.12, 3.13, and 3.14.
- Use Python 3.14 as the default runtime for `.python-version`, single-version
  CI jobs, coverage, and documented installs, including Omarchy.
- Keep Ruff `target-version` on 3.11. Set mypy `python_version` to 3.12 because
  NumPy 2.5 stubs use PEP 695 `type` statements and mypy parses those stubs with
  the configured version. The Python 3.11 CI job runs `compileall` on
  `src/scribe`, so 3.12-only syntax still fails before the tag.
- Do not claim Python 3.15 support, including free-threaded 3.15, from a
  syntax-only probe, a prerelease probe, or the PyTorch index alone.
- NumPy 2.5 requires Python 3.12. The lock selects NumPy 2.4.6 below 3.12 and
  NumPy 2.5.4 on 3.12 and newer. Numba 0.68.0 and llvmlite 0.50.0 move with it.
- On 2026-10-20, a locked Windows sync on Python 3.14.7 installed NumPy 2.5.4,
  Torch 2.13.0, and CTranslate2 4.8.1 with source builds disabled for NumPy,
  SciPy, Numba, llvmlite, and Torch. That wheel install is the evidence for
  declaring standard 3.14 on the base graph. CI on the release commit is still
  required before the tag.

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
