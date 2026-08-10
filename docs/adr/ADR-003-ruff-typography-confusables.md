# ADR-003: Ruff Typography - Allowed Confusables for Readability

## Status
Accepted - 2026

## Context
Enabling `RUF001` surfaced a small number of intentional characters that resemble
ASCII while matching an external format or improving user-facing readability.

Examples of the class of characters involved (not exhaustive list of every use):
- A multiplication sign used in human-readable speed output.

The project chose a line-length of 100 (slightly above the common 88/79) and values clarity for the specific domain (meetings, jokes, memes, notes) over strict ASCII purity.

## Decision
- Keep `allowed-confusables` in `[tool.ruff.lint]` (populated with the small set of characters that passed human review).
- Do **not** blanket-disable RUF001.
- New code should prefer ASCII unless the non-ASCII character genuinely improves human readability in the specific context (user-facing humor output, transcript fidelity, etc.).
- The list is maintained explicitly so it can be audited.

## Rationale
- A humor/transcription tool that deals with real human language (including punctuation, quotes, dashes in notes) benefits from being able to render text that matches user expectations and source material.
- The allowance is narrow, reviewed, and documented - not a free pass for Unicode golf.

## Consequences
- Slightly larger allowed-confusables list than a pure infrastructure library would have.
- Requires occasional human review when new characters appear in strings.
- Keeps the rest of the Ruff typography rules (RUF002, RUF003, etc.) at full strength.

## References
- pyproject.toml `[tool.ruff.lint] allowed-confusables`

## Related Decisions
- ADR-001, ADR-002
