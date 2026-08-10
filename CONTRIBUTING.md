# Contributing to Scribe

Thank you for helping improve Scribe. Contributions should preserve its
local-first defaults, explicit cloud boundaries, and truthful failure reporting.

## Before opening a change

- Search existing issues and pull requests.
- Open an issue before a large feature or architectural change.
- Keep changes focused. Separate unrelated fixes.
- Read [Responsible Use](docs/RESPONSIBLE_USE.md) and
  [Security Policy](SECURITY.md) when changing recording, networking, provider,
  storage, or diagnostic behavior.

## Public data hygiene

Do not commit real recordings, transcripts, customer or employer names, contact
details, API responses, credentials, support bundles, local paths, private model
inputs, or internal project names. Tests and examples must use synthetic data.
Use ignored local files for live and manual validation.

Before submitting a change, inspect both the diff and the complete branch history
for secrets and private data. If sensitive material is committed, rotate the
credential when applicable and remove the data from history before publication.

## Development setup

Scribe uses Python 3.12 as the reproducible development baseline and also tests
Python 3.13.

```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
uv sync --locked --python 3.12 --group dev
uv run pre-commit install --install-hooks
```

FFmpeg is required for conversion and the full coverage suite. Hardware, OBS,
microphone, and paid-provider checks are opt-in.

## Required checks

Run focused tests while developing, then run the repository gates before opening
a pull request:

```bash
uv lock --check
uv run pre-commit run --all-files
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy --strict src/scribe
uv run pytest --cov=scribe --cov-report=term-missing --cov-fail-under=81 -m "not gpu and not slow and not requires_openai and not requires_whisperx and not requires_pillow"
uv run pip-audit --local --progress-spinner off --desc on
uv build --clear --package scribe --out-dir .agent/build
uv run python scripts/check_release_artifact.py .agent/build
```

Windows changes that affect the native tray source must also run:

```powershell
pwsh -File scripts/check_native_tray.ps1
```

Rust changes must pass formatting, Clippy with warnings denied, and tests from
`crates/scribe-audio-core`.

## Pull requests

- Explain the user-visible outcome and any tradeoffs.
- Add or update regression tests for behavior changes.
- Update documentation and the `Unreleased` changelog section when appropriate.
- Identify cloud transmission, cost, consent, privacy, security, and platform
  implications.
- Do not weaken required gates or add audit exceptions without documenting the
  reason and removal condition.

## Licensing

By submitting a contribution, you represent that you have the right to submit it
and agree that it is licensed under the repository's Apache License 2.0 terms.
Do not submit material copied from another project unless its license permits the
use and the required notices are included.
