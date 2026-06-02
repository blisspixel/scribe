# ADR-002: Exception Taxonomy + Intentional Graceful Degradation for Hardware Variability

## Status
Accepted - 2026

## Context
Scribe's primary environment is a user's personal Windows desktop machine with highly variable:
- GPU presence and driver state (NVIDIA CUDA may be present, absent, or broken)
- OBS Studio installation and running state (WebSocket vs CLI control, version differences)
- FFmpeg / system tools availability and paths
- Microphone permissions and device enumeration
- Python environment (user may have multiple Pythons, conda, etc.)

The original "Python Project Standards Brief" (adapted NASA/JPL Power of 10) strongly discourages broad `except Exception` and bare `pass` / swallowed errors.

However, a rigid "fail fast on any unexpected state" approach would make Scribe unusable for the exact users it targets: solo creators, researchers, and professionals doing local transcription + humor analysis on real hardware.

## Decision
1. Maintain the rich, typed `ScribeError` hierarchy (already excellent in `src/scribe/exceptions.py`):
   - `ValidationError`, `ProcessError`, `TranscriptionError`, `GPUError`, `APIError`, etc.
   - All carry structured `context: dict` for debugging and recovery hints.

2. At **internal boundaries and hardware integration points**, allow controlled broader catching **only when**:
   - The failure is non-fatal to the primary user goal (e.g., "recording still succeeds via CLI fallback").
   - The site always logs at debug or warning level with context.
   - It either falls back to a secondary strategy or raises a typed `ScribeError` with actionable context.
   - A comment or ADR reference explains the "why".

3. **Never** swallow without logging in core transcription, conversion, or file I/O paths.

4. CLI command entry points may catch `ScribeError` (show user-friendly message + hints + exit 1) and have a final `except Exception` for truly unexpected crashes (still logs via `logger.exception`).

5. Bake-off / optional post-processing (jokes, memes) intentionally degrades: try N providers, use first success, fall back to first result if judging fails. This is documented in the modules themselves.

## Rationale
- The existing `ScribeError` taxonomy + Pydantic validation + atomic writes + dual logging already implements the spirit of defensive, verifiable error handling far better than most codebases.
- Blind removal of the graceful paths would regress reliability for the Windows + GPU + OBS primary use case.
- "Adapted NASA/JPL Power of 10" (as called for in the elevation) means applying the principles intelligently to a desktop tool, not purity theater that harms the product.

## Where Broad Catches Are Currently Accepted (with logging + recovery)
- `src/scribe/core/recorder.py` - OBS WebSocket connection failures → CLI fallback; best-effort process cleanup; crash sentinel handling.
- `src/scribe/utils/joke_bakeoff.py` and `meme_bakeoff.py` - individual provider or judging failures → continue or safe default.
- `src/scribe/core/local_whisper.py` - non-critical analysis (silence detection, language ID) → safe defaults + warning.
- `src/scribe/cli/main.py` - top-level command handlers (user UX boundary).
- Various subprocess probes (nvidia-smi, tasklist, pgrep) - return safe "not present" state.

All such sites were reviewed in Step 4 of the elevation. One minor `pass` without log was tightened; the rest were already correctly instrumented.

## Consequences
### Positive
- Scribe remains reliable and user-friendly on real, messy desktop hardware.
- Error messages carry structured context that makes support and self-debugging excellent.
- The architecture already satisfies the " >= 2 asserts/validators per public API" and "no hidden recursion" Power of 10 rules via Pydantic + existing checks.

### Negative / Trade-offs
- Slightly more code paths to reason about (the fallback branches).
- Static analysis (mypy, Ruff) cannot prove exhaustive handling as easily as in a pure "narrow exceptions only" codebase.

### Mitigations
- Heavy use of typed exceptions + context means most fallbacks are still type-directed.
- All intentional broad sites are now explicitly documented (module comments + this ADR).
- CI + pre-commit + mypy --strict on src/ + 80%+ coverage keep the surface under control.
- Future work (Step 4/5) can introduce more contextlib.suppress + explicit error contracts where it adds clarity without risk.

## References
- `src/scribe/exceptions.py` (full taxonomy and design rationale)
- `src/scribe/core/recorder.py` (primary hardware integration example)
- ROADMAP.md (Step 4 section, Scope, Explicit Non-Goals)
- Python Project Standards Brief (adapted Power of 10 guidance)

## Related Decisions
- ADR-001: Python 3.12 baseline
- Future ADR: Subprocess hygiene policy for desktop tools that must launch ffmpeg/OBS/etc.
