# Development Guide

This guide covers the reproducible contributor environment and repository gates.
Read [CONTRIBUTING.md](../CONTRIBUTING.md) for contribution scope, data hygiene,
pull-request expectations, and licensing.

## Prerequisites

- Git
- [uv](https://docs.astral.sh/uv/)
- Python 3.12 or 3.13
- FFmpeg for conversion and the full coverage suite
- Optional platform tools for the feature being changed, such as OBS, Go, Rust,
  CUDA, or an Apple Silicon environment

Python 3.12 is the reproducible development baseline. CI also runs the unit suite
on Python 3.13.

## Setup

```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
uv sync --locked --python 3.12 --group dev
uv run pre-commit install --install-hooks
uv run scribe doctor
```

Copy `.env.example` to `.env` only when a test needs explicit configuration.
Cloud-provider checks are never part of the default test path and require
deliberate credentials and network use.

## Repository layout

```text
src/scribe/                 Python package and CLI
tests/unit/                 Hermetic unit and property tests
tests/integration/          Component integration tests
tests/e2e/                  End-to-end workflow tests
tests/manual/               Explicit live hardware and provider checks
cmd/scribe-tray/            Optional Go tray prototype source
crates/scribe-audio-core/   Optional Rust audio acceleration source
docs/                       User, architecture, and operational documentation
examples/                   Synthetic examples and generic vocabulary
```

## Validation ladder

Start with the narrowest relevant test:

```bash
uv run pytest tests/unit/test_target.py -q
```

Run the fast contributor checks:

```bash
uv lock --check
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy --strict src/scribe
uv run pytest tests/unit -m "not gpu and not slow and not e2e and not requires_openai and not requires_ffmpeg and not requires_whisperx and not requires_pillow" -q
```

Run the same combined statement-and-branch coverage contract enforced by CI:

```bash
uv run pytest --cov=scribe --cov-report=term-missing --cov-fail-under=81 -m "not gpu and not slow and not requires_openai and not requires_whisperx and not requires_pillow" -q
```

Run repository, dependency, and artifact checks:

```bash
uv run pre-commit run --all-files
uv run pip-audit --local --progress-spinner off --desc on
uv build --clear --package scribe --out-dir .agent/build
uv run python scripts/check_release_artifact.py .agent/build
```

The complete command output and the current CI workflow are authoritative. Do not
copy a test count into documentation because the count changes as coverage grows.

## Native source checks

On Windows, validate the Go tray source without publishing its unsigned output:

```powershell
pwsh -File scripts/check_native_tray.ps1
```

For the Rust crate:

```bash
cd crates/scribe-audio-core
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
cargo test --locked
```

Native tray and audio artifacts are source-only development surfaces until they
have platform-specific signing, provenance, packaging, and clean-install
contracts.

## Live validation

Hardware, microphone, OBS, paid-provider, and external-service checks are opt-in.
Use only authorized synthetic inputs, keep private data outside the repository,
and do not run paid or cloud validation without deliberately accepting the cost
and data transfer.

Useful local checks include:

```bash
uv run scribe doctor
uv run scribe rec --check
uv run scribe tray --check
```

`scribe doctor --live` contacts configured providers. Default `scribe doctor`
does not.

## Code expectations

- Preserve type coverage and the custom exception boundaries.
- Keep cloud use explicit and local-only mode fail-closed.
- Treat external executables, models, URLs, media, and provider responses as
  untrusted inputs.
- Add regression tests for success, partial, and failure outcomes as applicable.
- Keep user-facing output literal-safe and actionable.
- Keep examples and fixtures synthetic.
- Update the CLI guide, architecture decisions, changelog, or roadmap when the
  supported contract changes.

## Release verification

The canonical version-selection, candidate, publication, and post-release
workflow is [RELEASE_PROCESS.md](RELEASE_PROCESS.md). Before creating any
release:

1. Set the same version in `pyproject.toml` and `src/scribe/__init__.py`.
2. Refresh and verify `uv.lock`.
3. Move applicable entries from `Unreleased` into a dated changelog section.
4. Run every required local and CI gate.
5. Verify the wheel contains the Apache-2.0 license evidence, package metadata,
   `py.typed`, icons, and glossaries.
6. Confirm the repository contains no credentials, private data, recordings,
   transcripts, logs, support bundles, or generated native binaries.
7. Create a tag only after the exact commit has passed CI.

Roadmap targets are planning labels, not delivery dates. Keep work under the
`Unreleased` changelog while developing, then synchronize package metadata,
lockfile, install examples, changelog, and roadmap state in one release candidate
commit.

Version 2.11.0 is the current GitHub release. The source repository is ready for
public visibility. No PyPI package or native binary has been published. Broader
package and binary distribution remains gated by the live platform evidence in
the roadmap.

## Getting help

- Run `scribe doctor` for installation and backend diagnostics.
- Read [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
- Follow [SUPPORT.md](../SUPPORT.md) before opening an issue.
- Report vulnerabilities through [SECURITY.md](../SECURITY.md).
