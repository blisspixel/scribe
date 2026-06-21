# ADR-001: Python 3.12 Baseline (with 3.14 Future Gate)

## Status
Accepted - 2026

## Context
The original Python Project Standards Brief (and early roadmap thinking) called for targeting Python 3.14 (or exact pin) with free-threaded builds for maximum performance and modernity.

Scribe is a **local-first desktop CLI** with heavy native dependencies:
- PyTorch / CUDA wheels (Windows NVIDIA primary target)
- faster-whisper + CTranslate2
- ffmpeg, OBS WebSocket, yt-dlp, etc.

In 2026 the PyTorch/CUDA and faster-whisper ecosystems on Windows still ship reliable wheels primarily for 3.12/3.13. 3.14 support (especially free-threaded) is incomplete or experimental for the GPU stack that defines Scribe's value proposition.

## Decision
- Set minimum `requires-python = ">=3.12"` in pyproject.toml.
- CI matrix tests on 3.12 and 3.13 (latest stable patch).
- Explicit **Step 5 decision gate** in ROADMAP.md: when the full GPU stack has mature 3.14 + free-threaded wheels on Windows, re-evaluate and raise the floor (or pin exactly).
- `.python-version` file pins `3.12` for local development consistency (uv + pyenv compatible).
- No chasing of bleeding-edge runtime versions that would break the primary Windows + NVIDIA user base.

## Consequences
### Positive
- Users on current stable Python + current CUDA toolkit can install and use Scribe without friction.
- CI is fast and reliable (real wheels, no source builds or workarounds).
- Matches the "5-10 year local desktop tool" scope and non-goal of "no bleeding-edge runtime chasing."
- Preserves the excellent existing graceful degradation for "no GPU / wrong Python / missing deps."

### Negative / Trade-offs
- Cannot yet use 3.14-only language features or free-threaded performance wins in hot paths.
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
