# Scribe Roadmap

Scribe favors reliability, privacy, and maintainability over feature count. See
[CHANGELOG.md](CHANGELOG.md) for shipped work and release history.

## Current status

Version 2.8.1 is in development. Version 2.8.0 is the current release.

The core product is a local-first desktop CLI for transcription, recording,
structured transcript output, local notes, and explicitly selected cloud
features. Windows resident voice has live validation. macOS and Linux resident
voice remain experimental until their hardware validation records are complete.

## Current priorities

### 1. Complete macOS and Linux resident voice validation

Run and record the matrix in
[VOICE_TRAY_MAC_LINUX_VALIDATION.md](docs/features/VOICE_TRAY_MAC_LINUX_VALIDATION.md).
Do not describe these platforms as validated until the records cover:

- Supported macOS versions and Linux desktop sessions.
- Global hotkeys, tray behavior, and run-at-login behavior.
- Microphone, accessibility, and audio-device permissions.
- Clean shutdown, duplicate-process prevention, and recovery after control loss.

### 2. Reduce orchestration complexity

Split the remaining large command and lifecycle paths in `src/scribe/cli/main.py`
and `src/scribe/core/recorder.py`. Preserve CLI behavior and session evidence while
moving transcription, recording, music, and cleanup responsibilities behind
smaller tested boundaries.

### 3. Redesign heavy dependency extras

Separate portable base functionality from PyTorch-backed features in a compatible
major release. This work should restore a credible Intel macOS install path without
downgrading the validated Windows and Apple Silicon dependency stack.

### 4. Strengthen release provenance

Keep Python wheels reproducible and free of platform-native payloads. Before
distributing native tray binaries, add platform signing, checksums, embedded source
identity, and verifiable release provenance.

### 5. Raise verification depth

Maintain the enforced branch-coverage floor above 81 percent, then ratchet toward
85 percent with failure-path tests. Keep dependency audits, locked builds, native
source checks, portable-wheel checks, and platform smoke tests in required CI.

## Product maintenance

Ongoing work should improve existing workflows rather than expand the product
surface:

- Keep `init`, `doctor`, `info`, `shortcut`, `rec`, and `tray --check` consistent.
- Keep local and cloud boundaries explicit at every decision point.
- Preserve truthful complete, partial, failed, and instrumental outcomes.
- Continue hardening backend selection, OBS recovery, and evidence retention.
- Keep logs and support bundles free of transcripts, credentials, and personal data.
- Keep documentation aligned with the command help and supported platform matrix.

## Scope boundaries

Scribe is not intended to become a hosted service, web application, cloud storage
system, enterprise account platform, or general-purpose media framework. Batch
transcription remains file-oriented. The separate resident voice mode is the only
real-time exception and remains opt-in.

Local transcription and Ollama-backed notes can run offline. Cloud transcription,
cloud notes, humor providers, and image providers transmit the relevant user
content only when the user selects those features. Scribe does not add telemetry
that phones home.

## Completed foundation

The current foundation includes local GPU and CPU transcription, multiple local
backends, explicit cloud transcription, OBS recording, batch and music workflows,
structured TXT/JSON/DOCX/Markdown/VTT/SRT output, transcript search, optional local
speaker diarization, optional local notes, resident voice, redacted support bundles,
locked dependencies, SBOM generation, dependency auditing, and cross-platform
smoke tests.

Detailed release notes belong in [CHANGELOG.md](CHANGELOG.md), not this roadmap.

Last updated: 2026-08-10
