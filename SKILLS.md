# SKILLS (Loop Engineering - Accumulated Capabilities)

This file tracks skills, patterns, and processes discovered or reinforced during the autonomous loop. Add only when they provide reusable value for future cycles. Keep minimal and exact.

## Established in this Project (internalized from docs)
- Ruff + mypy --strict as non-negotiable gates (pyproject + pre-commit + CI).
- Hypothesis for property testing pure modules (costs, selection, diarizer).
- Typed exception hierarchy + context for all error domains (ADR-002).
- Agentic Balance: rules for control flow / validation / hardware; model only for bounded content judgment.
- Atomic file writes + dual logging.
- uv as sole reproducible manager.
- Explicit ignore lists for torch vulns in security gate (ADR-004).
- Allowed confusables for typography only where documented (ADR-003) - prefer ASCII in new prose.

## Added by Loop (2026-06-21)
- Ruff hygiene enforcement: treat any RUF* violation as defect to fix immediately for Step 2 DoD. Use `_` idiom for intentionally unused unpack in tests.
- Doc accuracy as first-class quality bug: stale counts, tables, and status are defects equivalent to code bugs. Update atomically with code changes when they drift. Verify with grep after.
- Loop memory via PROGRESS-LOG.md (cycle by cycle), CURRENT-STATE-ANALYSIS.md (startup + refresh), SKILLS.md, todo_write for internal tracking.
- Validation protocol: always re-run exact gates (ruff check, ruff format --check, mypy --strict, relevant pytest -m, pip-audit) after every change. Brutal rubric review before ship.
- Introducing deal for Step 3: add only to dev group, target pure modules with clear numeric/token/invariant logic (costs example), use @deal.pre/@deal.post for non-negative and result guarantees, add pytest.raises(deal.PreContractError) tests. Keep public exceptions unchanged. Run `uv sync --group dev` after dep edit.
- Broad except tightening (Step 4/ADR-002): replace bare `except Exception` with specific (OSError, UnicodeDecodeError, etc) where the failure is I/O or decoding; always document remaining graceful cases with comments. Prefer re-raise of typed ScribeError when possible.

## Patterns to Reuse
- When fixing gates: read exact violation sites first for context. Minimal change that satisfies linter + keeps test intent explicit.
- When updating docs: make numbers and status match `pytest --collectonly` + actual gate runs. Remove or clearly mark resolved "known issues".
- Never introduce new em-dashes or emojis in prose/docs unless the change is typography in user strings covered by ADR-003.
- Spend: always $0 for this work (local tools only).

Use these to accelerate future cycles without repetition.
