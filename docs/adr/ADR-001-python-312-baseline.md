# ADR-001: Python 3.12 Baseline (with 3.14 Future Gate)

## Status
Accepted in 2026; amended 2026-07-28

## Context
The original Python Project Standards Brief (and early roadmap thinking) called for targeting Python 3.14 (or exact pin) with free-threaded builds for maximum performance and modernity.

Scribe is a **local-first desktop CLI** with heavy native dependencies:
- PyTorch / CUDA wheels (Windows NVIDIA primary target)
- faster-whisper + CTranslate2
- ffmpeg, OBS WebSocket, yt-dlp, etc.

Python 3.12 remains the most conservative Windows GPU baseline, and Python 3.13
has a validated wheel set. A Windows Python 3.14 install probe on 2026-07-28
failed because the universal optional-ML graph selected NumPy and CTranslate2
releases without compatible CPython 3.14 wheels. Standard and free-threaded 3.14
support therefore remain unproven for the stack that defines Scribe's value.

## Decision
- Set `requires-python = ">=3.12,<3.14"` in pyproject.toml.
- Run the CI-safe unit suite on every declared standard CPython version: 3.12
  and 3.13.
- Keep the **Step 5 decision gate** in ROADMAP.md for promoting 3.14 to the
  primary development baseline or claiming free-threaded and full GPU-extra support.
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
- The decision is explicitly time-bounded and reviewed in Step 5.
- All new code is written with forward compatibility in mind (no 3.12-only deprecated patterns).
- Documentation clearly states the current baseline and the upgrade path.

## References
- ROADMAP.md (Scope, Non-Goals, Step 1/Step 5 sections)
- pyproject.toml `[project] requires-python`
- .github/workflows/ci.yml (matrix)
- Python Project Standards Brief (original research input)

## Related Decisions
- ADR-002 (to be written): Exception taxonomy + intentional graceful degradation for hardware variability
- ADR-003 (to be written): Ruff typography confusable allowance (allowed-confusables) for readability in a humor/transcription tool
