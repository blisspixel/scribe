# Scribe Roadmap

**Philosophy:** Reliability over feature count. Releases prioritize predictable behavior, clearer output, and maintainable code.

See [CHANGELOG.md](CHANGELOG.md) for the complete history of changes, fixes, and releases.

---

## Current Focus

The project is currently focused on two tracks that run in parallel:

1. **Product reliability and polish** — continuing to harden the core transcription, recording, and intelligence features (see the Unreleased section of CHANGELOG.md for work in flight).
2. **Engineering excellence** — systematically raising the quality, reproducibility, and verifiability of the codebase itself so the project remains maintainable for years.

The remainder of this document addresses the second track.

---

## Scope and Focus

Scribe is a **local-first desktop CLI** for high-quality speech transcription, meeting notes, and optional context-aware humor. It excels at GPU-accelerated local processing with graceful fallback to API providers, professional OBS recording integration, and music transcription with vocal separation.

**We intentionally do not pursue:**
- Web UIs, servers, or multi-user/enterprise features.
- Real-time or streaming transcription (batch file processing is simpler and more reliable).
- Cloud storage, account sync, or data exfiltration features (users control their own transcripts).
- Library-first packaging or monorepo extraction — this remains a cohesive end-user product.
- Chasing the absolute newest Python runtime or heavy observability stacks that would complicate local GPU usage or CLI UX.
- Broad expansion into adjacent domains that would dilute the focused value of accurate, private, offline-capable transcription and analysis.

These boundaries exist so Scribe stays excellent at what it does rather than becoming a general-purpose media or AI platform.

---

## Version History

High-level summary. Full details live in [CHANGELOG.md](CHANGELOG.md).

| Version | Primary Focus                  | Status    |
|---------|--------------------------------|-----------|
| 2.4.3   | OBS recording reliability      | Current   |
| 2.4.2   | Code quality + .env handling   | Released  |
| 2.4.1   | OBS WebSocket hardening        | Released  |
| 2.4.0   | Recording UX polish            | Released  |
| 2.3.x   | Multi-provider AI + music mode | Released  |
| 2.0–2.2 | GPU acceleration + providers   | Released  |

---

## Product Direction (Competitive Gaps — Under Active Consideration)

As of 2026-06-01, a review of the 2026 local meeting-intelligence field (ownscribe, Meetily, OpenWhispr, transcriptionstream, WhisperX) surfaced capabilities that are now table stakes and where Scribe has gaps. These are candidate product directions, recorded so the roadmap reflects reality. The Engineering Excellence track below is unaffected by them.

1. **Local-only summarization (close the offline gap).** Notes and humor currently require a cloud provider (OpenAI/xAI/Anthropic/Gemini), so the "local-first, private, offline-capable" promise only holds for transcript-only use. Add an **Ollama / OpenAI-compatible local LLM provider** to the existing provider abstraction so notes can be generated fully offline. Highest priority — this reconciles a claim/reality gap rather than expanding scope, and slots into the current architecture cleanly.

2. **Local speaker diarization.** Diarization is currently API-only (`gpt-4o-transcribe-diarize`); the local GPU path produces no speaker labels. Evaluate **WhisperX + pyannote.audio** for word-level alignment and local "who said what." Pairs with the hardware-backend work below (item 4).

3. **Structured, queryable output.** Emit machine-readable artifacts (YAML frontmatter / JSON with timestamps, speakers, decisions, action items, confidence, provenance) so notes are both ingestible by sibling tools and queryable ("ask across my meetings"). Cheapest high-value item; in-scope regardless of the rest.

4. **Hardware-adaptive transcription backends.** Generalize the existing VRAM-based auto-selection from CUDA-only to `(vendor, memory)`: faster-whisper on NVIDIA, mlx-whisper / whisper.cpp (Metal) on Apple Silicon, whisper.cpp (Vulkan/ROCm) on AMD/Intel, int8 CPU fallback. Prerequisite for a credible cross-platform public release rather than a 4090/Windows-optimized tool.

5. **Voice I/O (deliberate mode decision).** Global-hotkey speech-to-type and read-aloud (local TTS) are strong QOL ideas but require real-time/streaming, which is an explicit non-goal below. Treat as a separate product mode to be adopted intentionally, not bolted onto the batch pipeline.

Priority order: 1 → 3 → 2 → 4 → 5. Items 1 and 3 are low-risk and strengthen the local-first promise; 2 and 4 are larger lifts tied to going public; 5 is a conscious scope decision (see Explicit Non-Goals).

---

## Design Principles

### Quality Over Speed
- Uses Whisper large-v3 by default for strong accuracy.
- Audio normalization is enabled for consistency.
- Faster models remain available when speed is preferred.

### Defensive by Design
- All external inputs validated at the boundary.
- Atomic file operations prevent corruption.
- Comprehensive error handling with automatic fallback.
- Rich, typed exception hierarchy with structured context for every failure domain.

### Clean Code and Modern Engineering
- Ongoing removal of unused symbols and dead paths.
- Functions kept focused and testable.
- Large, high-quality test suite run on every change.
- Tooling and process upgrades follow the ordered plan below rather than ad-hoc adoption.

### High-Assurance Practices (Adapted for This Project)
We draw from strong engineering standards (type safety, Design by Contract, property-based testing, supply-chain hygiene, and architectural discipline) while remaining pragmatic for a local-first Windows GPU CLI with heavy ML dependencies.

Adopted where they add verifiable value:
- Design by Contract (via the `deal` library) on pure critical modules.
- Strict "Parse, Don't Validate" at system boundaries.
- Hypothesis (including state machines) on complex logic and lifecycles.
- Mutation testing and lightweight fault injection as advanced verification.
- Explicit pure-Python preference for new dependencies, with architecture review for any C extension.
- Free-threaded Python discipline (no implicit shared mutable state; message passing preferred).

Deliberately not adopted (or deferred):
- Rigid function-length caps or mandatory asserts in every public API.
- Default structured logging / OpenTelemetry stack (current dual Rich + file logging remains a strength for desktop UX).
- Full SLSA Level 3 provenance ceremony for a local desktop tool.
- Immediate 95%+ branch coverage gate or free-threaded 3.14t matrix (wheels for the core GPU stack are not yet reliable on Windows).

These choices are documented so the project stays focused and the roadmap cannot drift into purity theater. See Explicit Non-Goals below and the ADRs in `docs/adr/`.

See the Engineering Excellence section for the concrete, sequenced work required to raise the baseline.

---

## Engineering Excellence — Ordered Work Plan

The goal is a codebase that is reproducible, statically verifiable, and easy to maintain for the long term, while remaining pragmatic for a GPU-heavy CLI with complex ML dependencies (torch, faster-whisper, demucs, yt-dlp, etc.).

We follow a strict logical order. Each step builds the foundation the next step requires. Work is complete only when the Definition of Done for that step is met and the gates are enforced in CI and local development.

### 1. Reproducible Environment Foundation
Establish a single source of truth for Python version, dependencies, and development environment before changing anything else.

**Work in this step:**
- Add `.python-version` pinned to 3.12 and set `requires-python = ">=3.12"` in pyproject.toml. Update classifiers and all documentation.
- Adopt uv as the canonical package and project manager. Generate and commit `uv.lock`. Update all development and CI commands to use `uv sync` and `uv run`.
- Consolidate configuration into pyproject.toml: remove duplicate settings from pytest.ini, retire the Black configuration, and expand the Ruff configuration with preview rules, security rules, and appropriate complexity limits.
- Add `.pre-commit-config.yaml` with ruff (lint + format), mypy, and basic test hooks. Make `pre-commit install` part of the documented onboarding.
- Overhaul CI to use uv for all jobs, expand the Python matrix to 3.12 and 3.13, add a dedicated lint + types job, a coverage gate job, and a dependency vulnerability scan step.
- Update README, DEVELOPMENT.md, and related docs to present the uv workflow first while retaining pip instructions for accessibility.
- Mark `requirements.txt` and `requirements-dev.txt` as legacy compatibility shims with clear pointers to the pyproject/uv approach.

**Definition of Done:**
- A fresh clone on Windows, macOS, or Linux followed by `uv sync` and `uv run scribe doctor` produces a working, identical environment.
- All CI jobs pass using the new uv-based pipeline.
- `pre-commit run --all-files` passes cleanly for any contributor who has run the install step.
- No developer or CI runner can accidentally use an inconsistent Python version or dependency set.

This step must be finished before meaningful progress on later steps. Reproducible environments are the prerequisite for reliable type checking, testing, and security scanning.

### 2. Automated Static Quality Gates
Lock in consistent formatting and strong linting with fast local and CI feedback before investing in stricter type checking.

**Work in this step:**
- Finalize the expanded Ruff configuration (line length, target version, full preview rule set, security plugins, selected flake8 extensions, and tuned complexity / cognitive complexity caps).
- Enforce `ruff format` and `ruff check` in pre-commit and in every CI run. Treat violations as hard failures.
- Remove any remaining Black or isort configuration and usage.
- Add a clear CONTRIBUTING or development section that states the formatting and linting expectations for all new code.

**Definition of Done:**
- `ruff format --check` and `ruff check` pass on the entire tree in CI and locally via pre-commit.
- The project has a single, documented style enforced by the toolchain (no more "we use Black for this and Ruff for that").
- New pull requests cannot introduce formatting or lint drift.

Only after this step is solid does it make sense to raise the cost of type checking.

### 3. Type Safety and Static Verification
Make the public surface and core logic statically verifiable.

**Work in this step:**
- Drive the codebase to a clean `mypy --strict` (or equivalent high-performance checker) result across src/, with only minimal, documented overrides for third-party ML libraries that lack stubs.
- Complete type annotations on all public functions, classes, and module boundaries in the CLI, providers, core orchestration, and widely used utilities.
- Progressively enable stricter Ruff rules that become valuable once formatting is locked (unused arguments, comprehensions, simplification rules, etc.).
- Introduce Hypothesis for property-based testing on pure logic modules (vocabulary handling, cost calculation, validation helpers, etc.), including state machines for complex object lifecycles (recorder state, session management, provider health).
- Introduce Design by Contract (`deal`) on pure critical modules for preconditions, postconditions, and invariants. Contracts run in dev/test and are stripped in production builds.
- Strengthen "Parse, Don't Validate": audit Pydantic models for `strict=True` + `extra='forbid'`, prefer domain types (frozen dataclasses, NewTypes) at boundaries so illegal states are unrepresentable.
- Raise the coverage fail-under threshold and enable branch coverage reporting on core modules where it provides signal.

**Definition of Done:**
- `uv run mypy --strict src/scribe` (or equivalent) exits zero with no new ignores or untyped public symbols.
- New code cannot be merged if it reduces type coverage or introduces unannotated public APIs.
- Property-based tests (including at least one state machine test for a complex lifecycle) run in CI under an appropriate marker.
- Design by Contract is in use on at least the core pure modules (costs, validation, atomic operations) with tests exercising the contracts.
- Coverage gate in CI reflects the current threshold (pragmatically raised over time toward higher branch coverage).

### 4. Error Handling, Security, and Operational Hygiene
Tighten runtime behavior and add security scanning only after the static foundations are in place.

**Status (as of this revision):** Diagnostic audit complete across `src/`. One minor silent swallow tightened. All remaining broad `except` / subprocess patterns classified as intentional for hardware/provider graceful degradation and documented (module comments + ADR-002). Doctor + support bundles already perform safe key redaction. Four ADRs created in `docs/adr/`. Ruff S-bandit items (inherent to launching ffmpeg/OBS/etc. on user hardware) accepted with explicit rationale; no scope or reliability regression. Blocking dependency vulnerability scanning is now enabled in CI with an explicit torch advisory ignore policy; further doctor hardening remains for completion of this step.

**Work in this step:**
- Systematic audit and tightening of remaining broad `except Exception` handlers. Prefer specific catches, structured logging of context, and re-raise using the existing `ScribeError` hierarchy.
- Add blocking dependency vulnerability scanning to CI (fail on high or critical findings).
- Document and optionally implement SBOM generation for users who require compliance artifacts.
- Add a security / environment surface check to `scribe doctor` (Python version, known vulnerable packages, CUDA driver age where detectable).
- Evaluate minimal structured logging additions only behind an opt-in flag that does not change the default excellent Rich console + detailed file log experience.
- Establish a lightweight `docs/adr/` practice for any future major tooling, dependency, or architectural decisions.

**Definition of Done:**
- No high or critical vulnerabilities reported by the scanner on main.
- All new code follows the explicit error handling + logging rule (reviewable and preferably machine-checkable).
- The security model of the tool (local data, optional API transmission, user-controlled outputs) is clearly documented.

### 5. Governance and Long-Term Sustainability
Put the processes and artifacts in place that let the elevated standards survive beyond any single contributor.

**Work in this step:**
- When the PyTorch, CTranslate2, and demucs ecosystems publish reliable Python 3.14 wheels (including CUDA variants), evaluate promoting 3.14 as the primary development and static-analysis baseline (while keeping `requires-python = ">=3.12"` until wheels are widely available on Windows). Do not do this earlier.
- Add periodic mutation testing (mutmut or equivalent) as a non-blocking verification job to demonstrate that the test suite actually detects injected faults.
- Add lightweight fault-injection / chaos testing at I/O and external-process boundaries (malformed input, simulated timeouts, missing OBS, disk pressure on atomic writes, etc.).
- Formalize a pure-Python preference policy for new dependencies: high-quality pure-Python packages are required unless no viable alternative exists; any new C extension requires explicit architecture review and cp314t compatibility consideration.
- Produce or derive a minimal external template (Copier or GitHub template) from the final pyproject.toml, pre-commit config, and CI workflow so future projects can inherit the standards without copying by hand.
- Keep the Engineering Excellence section of this roadmap and the contributor documentation living and accurate so anyone joining the project knows exactly which gates apply.

**Definition of Done:**
- The elevated baseline is the default for any new work and is described in one place that is kept current.
- Future contributors can stand up a correctly configured environment and pass all gates with the documented commands.

---

## Explicit Non-Goals (Protecting Focus)

These are deliberate decisions to keep Scribe a focused, high-quality tool rather than a general platform:

- We will not declare Python 3.14 (or any future version) as a hard minimum until the full CUDA/ML dependency stack has mature, widely available wheels on Windows. User hardware compatibility and the primary GPU path come before chasing runtime features.
- We will not impose rigid function-length caps (<50 lines) or require a fixed number of asserts/validators in every public function. We use Ruff complexity + cognitive complexity rules, code review, Pydantic validators, the ScribeError hierarchy, and circuit breakers instead.
- We will not replace the current dual-output logging (clean Rich console for users + detailed rotating file logs for debugging) with a heavy structured logging or OpenTelemetry stack by default. The existing approach is a deliberate strength for desktop CLI UX.
- We will not pursue full SLSA Level 3 + in-toto + Sigstore provenance attestation for a local desktop CLI. These are high-ceremony measures with limited value until the project has a published package with many external dependents.
- We will not run the free-threaded 3.14t build in CI while the core GPU/ML wheels lack reliable support on Windows.
- We will not apply Design by Contract or strict parsing rules uniformly across CLI glue, UI layers, or provider code. These techniques are reserved for pure, critical business logic where they add clear value.
- We will not turn Scribe into a library, framework, or monorepo. It is a cohesive end-user CLI product.
- We will not add web UIs, multi-user features, cloud sync, or enterprise authentication. These remain out of scope (see Scope and Focus section above). Real-time/streaming is held out of the **batch pipeline**, but a separate opt-in voice-I/O mode (global-hotkey dictation, read-aloud) is under active consideration as a distinct product surface — see Product Direction item 5. Adopting it would be a deliberate decision, not a drift.
- "Local-first, private, offline-capable" is the goal, but note generation and humor currently require a cloud provider. Until the local LLM provider lands (Product Direction item 1), the fully-offline guarantee holds for transcript-only use; with a cloud provider, transcripts/notes are transmitted for analysis. This is documented honestly rather than overstated.
- We will not add observability or telemetry that phones home or increases the attack surface of a local tool.

Elevation work exists only to make the existing focused value more reliable, reproducible, and maintainable over time. Any proposal that would expand scope or compromise the local-first, private, offline-capable nature of the tool will be rejected.

Elevation work exists only to make the existing focused value more reliable, reproducible, and maintainable over time. Any proposal that would expand scope or compromise the local-first, private, offline-capable nature of the tool will be rejected.

---

**Last Updated:** 2026-06-01

