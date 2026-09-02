# Scribe Roadmap

Scribe favors recording integrity, privacy, truthful outcomes, and maintainability
over feature count. [CHANGELOG.md](CHANGELOG.md) records shipped changes. This
roadmap records only unfinished work and the evidence required to ship it.

## Current position

Version 2.9.2 is the current GitHub release. The source repository is ready for
public visibility. The supported package remains the versioned GitHub wheel and
source distribution. Scribe is not published on PyPI, and no native executable is
an official release artifact.

The current product contract includes:

- Local-first transcription with explicit OpenAI and OpenRouter opt-ins.
- Defensive OBS recording that requires positive startup evidence and preserves
  detected media on incomplete or failed sessions.
- Structured transcript and session evidence with complete, partial, failed, and
  instrumental outcomes.
- Live-validated Windows resident voice.
- Experimental macOS and Linux resident voice pending hardware evidence.
- Python 3.12 and 3.13 support. New interpreter support requires the complete
  dependency, CI, and platform matrix in
  [ADR-001](docs/adr/ADR-001-python-312-baseline.md).

## Planning rules

Version labels define dependency order, not calendar commitments. The roadmap
does not use delivery dates or effort-duration estimates. A version ships when
its exit criteria pass on the exact candidate commit.

- Patch releases preserve the current product contract and may contain
  reliability fixes, security fixes, documentation corrections, and evidence.
- Minor releases may add backward-compatible behavior after the preceding
  reliability gate is complete.
- Major releases may change installation, dependency, or compatibility
  contracts and must include migration guidance.
- An urgent data-loss, security, or release-blocking fix may become the next patch
  without waiting for a planned minor release.
- If scope, order, or a target version changes, update this roadmap and the
  `Unreleased` changelog before merging the changed implementation.

The detailed version-sync and release workflow is in
[RELEASE_PROCESS.md](docs/RELEASE_PROCESS.md).

## Version sequence

| Version | State | Purpose | Depends on |
|---|---|---|---|
| 2.9.1 | Released | Windows recording hardening and optional OpenRouter transcription | None |
| 2.9.2 | Released | Add the per-run OpenRouter spend control, correct explicit output routing, and establish the versioned release plan | 2.9.1 |
| 2.9.3 | Next | Produce clean-machine and real OBS evidence; fix every release-blocking finding | 2.9.2 |
| 2.10.0 | Planned | Validate and finish the cross-platform desktop experience | 2.9.3 evidence gate |
| 2.11.0 | Planned | Reduce orchestration complexity and deepen failure-path verification | 2.10.0 behavior contract |
| 3.0.0 | Gated | Redesign dependency extras and interpreter support without weakening local workflows | 2.11.0 boundaries and migration design |
| 3.1.0 | Conditional | Distribute signed native components only if measured evidence justifies them | 3.0.0 package contract and native decision gate |

Version numbers after 2.9.3 are planning targets. SemVer impact discovered during
implementation can change a target, but the reason and replacement target must be
recorded here before release preparation.

## Next release: 2.9.3 operational proof

### Objective

Prove that a new user can install Scribe, confirm readiness, record through real
OBS, preserve the media, and complete local or deliberately selected OpenRouter
transcription within the configured spend policy.

### Order of operations

1. Define a sanitized evidence record for the exact candidate commit, operating
   system, Python version, install command, detected backend, command exit status,
   and produced artifact types.
2. Run a clean install on Windows, macOS, and Linux, followed by `scribe init`,
   `scribe doctor`, and `scribe rec --check`.
3. Exercise the normal OBS WebSocket path and confirm both advancing OBS output
   counters and independent file growth.
4. Exercise the emergency path with an unreachable, non-recording OBS process and
   confirm positive file-growth detection without interrupting another capture.
5. Stop and finalize through every available safe control path. Confirm that an
   unexpected stop or incomplete finalization retains the source media and
   produces a non-success session outcome.
6. Transcribe authorized synthetic media locally and confirm the requested
   structured outputs and session summary.
7. Run an authorized OpenRouter transcription with the default $5 reported-cost
   guard and a lower per-run `--max-spend` override. Confirm the
   effective value in `scribe info`, request metadata, partial-result behavior,
   and `scribe doctor --live` provider-cap guidance without exposing the key or
   balance.
8. Turn every reproducible failure into a focused regression test, a fix, and an
   actionable recovery message. Narrow the support claim if a platform cannot
   meet the contract.
9. Update the platform matrix and linked recording and cloud documentation with
   sanitized evidence from the final candidate.

### Exit criteria

- Clean installation and upgrade work from the documented versioned GitHub
  source on each claimed core platform.
- Real OBS normal and emergency paths have positive startup, monitoring, stop,
  finalization, and recovery evidence.
- Scribe never reports capture success from process launch alone.
- An existing recording is never stopped, replaced, or adopted as Scribe's own.
- Detected media survives transcription, output, cleanup, and evidence failures.
- OpenRouter remains explicit opt-in, defaults to a $5 per-file reported-cost
  guard, accepts a validated per-run override, stops before a later chunk when the
  reported limit is reached, and preserves confirmed partial text.
- Documentation states that the local guard cannot cap a first or final request
  before cost is reported, and directs users to a provider key limit for absolute
  enforcement.
- Required CI, dependency audits, secret scanning, package checks, and the
  combined statement-and-branch coverage floor pass on the exact release commit.
- README, recording, cloud, deployment, troubleshooting, support matrix,
  changelog, and command help agree with observed behavior.

No broader package or binary distribution should start before this gate closes.

## Planned release: 2.10.0 desktop validation

### Objective

Make the desktop support statement evidence-based across recording and resident
voice, with tested fallbacks where an operating system cannot provide parity.

### Order of operations

1. Complete the macOS, Linux X11, and representative Linux Wayland records in
   [VOICE_TRAY_MAC_LINUX_VALIDATION.md](docs/features/VOICE_TRAY_MAC_LINUX_VALIDATION.md).
2. Fix platform defects found by live permission, audio-device, hotkey, tray,
   startup, injection, read-aloud, and shutdown tests.
3. Document a tested fallback for every unavailable core capability instead of
   making a parity claim.
4. Validate install, update, run-at-login, diagnostic, and removal paths on each
   supported desktop tier.
5. Promote a platform from experimental only when its exact completion record is
   reviewed and linked.

### Exit criteria

- Every supported desktop tier has a sanitized live record for the release
  candidate.
- Permission denial, unavailable devices, hotkey conflicts, duplicate launches,
  control loss, and shutdown failures have actionable tested behavior.
- Platform labels in the CLI, README, deployment guide, voice guide, and support
  matrix agree.
- Unsupported compositor or desktop behavior is explicit and has a tested
  terminal or shortcut fallback where practical.

## Planned release: 2.11.0 maintainability and verification

### Objective

Reduce the blast radius of future reliability work without changing established
CLI, recording-integrity, local-first, or evidence contracts.

### Order of operations

1. Split transcription, recording, music, and cleanup coordination out of
   `src/scribe/cli/main.py` behind typed command boundaries.
2. Split OBS discovery, startup proof, monitoring, safe stop, finalization, and
   recovery in `src/scribe/core/recorder.py` behind independently tested
   lifecycle boundaries.
3. Add deterministic fault-injection tests for process, filesystem, provider,
   encoder, terminal, and cleanup failures.
4. Ratchet combined statement-and-branch coverage toward 85 percent using useful
   failure-path assertions rather than low-value line execution.
5. Keep session evidence backward-compatible or publish a versioned schema and
   migration path before changing it.

### Exit criteria

- Large orchestrators delegate to smaller typed units with explicit ownership and
  cleanup contracts.
- Success, partial, failure, interruption, and recovery behavior remains covered
  at command and component boundaries.
- No refactor weakens local-only enforcement, media retention, single-instance
  ownership, or cloud opt-in behavior.
- Performance and memory evidence shows no material regression on representative
  workflows.

## Gated release: 3.0.0 dependency architecture

### Objective

Separate the portable command and cloud workflows from heavy local-ML stacks so
users install only the capabilities they select. This is a major release because
default dependencies and installation commands may change.

### Order of operations

1. Measure which commands require Torch, faster-whisper, CTranslate2, audio
   device libraries, desktop hooks, and platform-native packages.
2. Define named install profiles for portable core, local transcription, GPU
   acceleration, resident voice, diarization, and optional providers.
3. Specify deterministic capability discovery and actionable missing-extra
   messages before changing dependency metadata.
4. Build clean-install, upgrade, downgrade, and removal tests for every supported
   profile and platform.
5. Add Python 3.14 or 3.15 only when required wheels resolve and the full CI and
   runtime matrix passes. Interpreter release status alone is insufficient.
6. Publish a migration guide from 2.x commands and extras, including a rollback
   path that preserves user configuration and recordings.

### Exit criteria

- Cloud-only and lightweight workflows do not require unrelated local-ML
  packages.
- Every documented local workflow has an explicit install profile and a tested
  missing-capability message.
- Supported Python versions match wheel availability and live runtime evidence.
- Existing user configuration and output remain readable, or a tested migration
  is provided.
- The 2.x to 3.x migration and rollback paths pass clean-machine verification.

## Conditional release: 3.1.0 native distribution

Native Go or Rust artifacts advance only if benchmarks and platform evidence show
a meaningful reliability, performance, or lifecycle benefit over the portable
Python implementation. Otherwise, keep them as development prototypes or remove
the unsupported surface.

If the decision gate passes, 3.1.0 requires:

- Reproducible platform builds from the tagged source.
- Platform-appropriate signing, checksums, embedded source identity, SBOMs, and
  verifiable provenance.
- Clean install, update, rollback, and removal behavior.
- A correct Python fallback when a native component is absent or fails.
- No implicit change from a local data path to a cloud data path.

## Continuous maintenance lane

The following work can produce a patch release at any point:

- Recording data-loss risks or false success reports.
- Credential exposure, unsafe URL handling, or cloud-boundary regressions.
- Actionable dependency advisories, including the tracked optional WhisperX NLTK
  advisory in [issue 31](https://github.com/blisspixel/scribe/issues/31).
- Supported-platform installation failures.
- Incorrect session evidence, partial-result loss, or cleanup of user-owned data.
- Documentation that overstates support or disagrees with released behavior.

## Product boundaries

Scribe is not planned as a hosted service, web application, cloud storage system,
enterprise account platform, or general-purpose media framework. Batch
transcription remains file-oriented. Resident voice is the only opt-in real-time
exception.

Local transcription and Ollama-backed notes can run offline. OpenAI and
OpenRouter transcription and other cloud-generated extras transmit relevant
content only after explicit selection. Scribe does not add telemetry that phones
home.

Detailed shipped changes belong in [CHANGELOG.md](CHANGELOG.md), not this roadmap.
