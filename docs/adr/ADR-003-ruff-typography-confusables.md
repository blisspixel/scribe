# ADR-003: Ruff Typography — Allowed Confusables for Readability

## Status
Accepted — 2026

## Context
During Step 2 of the elevation (full Ruff enforcement), enabling `RUF001` (ambiguous unicode characters) surfaced a small number of intentional uses of characters that look similar to ASCII but improve readability or match external conventions in a transcription + humor analysis tool.

Examples of the class of characters involved (not exhaustive list of every use):
- Curly quotes / apostrophes in user-facing strings or test data that mirror real meeting notes.
- Em-dashes or en-dashes in help text / comments (occasional).
- Certain subscript/superscript or math-adjacent glyphs in analysis modules.

The project chose a line-length of 100 (slightly above the common 88/79) and values clarity for the specific domain (meetings, jokes, memes, notes) over strict ASCII purity.

## Decision
- Keep `allowed-confusables` in `[tool.ruff.lint]` (populated with the small set of characters that passed human review).
- Do **not** blanket-disable RUF001.
- New code should prefer ASCII unless the non-ASCII character genuinely improves human readability in the specific context (user-facing humor output, transcript fidelity, etc.).
- The list is maintained explicitly so it can be audited.

## Rationale
- A humor/transcription tool that deals with real human language (including punctuation, quotes, dashes in notes) benefits from being able to render text that matches user expectations and source material.
- Strict ASCII-only would have required escaping or replacement in many user-visible strings, harming the "feels like a thoughtful local tool" experience.
- The allowance is narrow, reviewed, and documented — not a free pass for Unicode golf.

## Consequences
- Slightly larger allowed-confusables list than a pure infrastructure library would have.
- Requires occasional human review when new characters appear in strings.
- Keeps the rest of the Ruff typography rules (RUF002, RUF003, etc.) at full strength.

## References
- pyproject.toml `[tool.ruff.lint] allowed-confusables`
- Step 2 commit in the elevation history (Ruff universal enforcement)
- ROADMAP.md Step 2 section

## Related Decisions
- ADR-001, ADR-002
