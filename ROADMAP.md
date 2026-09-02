# Scribe Roadmap

Scribe favors reliability, privacy, and maintainability over feature count. See
[CHANGELOG.md](CHANGELOG.md) for shipped work and release history.

## Current status

Version 2.9.1 is the current GitHub release. The source repository is ready for
public visibility. No PyPI package or native binary has been published. Broader
package and binary distribution remains gated by the clean-machine and platform
evidence below.

The core product is a local-first desktop CLI for transcription, recording,
structured transcript output, local notes, and explicitly selected OpenAI or
OpenRouter cloud transcription. Windows resident voice has live validation.
macOS and Linux resident voice remain experimental until their hardware
validation records are complete.

The dedicated OpenRouter TTS and STT endpoints have a live Windows round-trip
record using a synthetic 60-second clip. This validates the cloud contract and
reported-cost metadata on one machine, but it does not replace clean-machine or
real OBS evidence on Windows, macOS, and Linux.

## Current priorities

### 1. Record clean-machine core workflow evidence

Install the exact candidate commit on fresh Windows, macOS, and Linux machines,
then run `scribe init`, `scribe doctor`, `scribe rec --check`, one authorized
short OBS recording, and one synthetic local transcription. The OBS run must
exercise positive byte and file-growth confirmation, safe stop and finalization,
and recovery from an unreachable non-recording OBS process. Record the operating
system, Python version, install command, backend, exit status, and produced
artifact types without committing local paths or user data.

CI proves the package contract and mocked platform behavior. It does not prove
that a first-time user can install FFmpeg, resolve the native ML stack, control a
real OBS installation, and finish the recording and transcription workflows on
each claimed platform. This evidence is the most important remaining check before
broader package or binary distribution.

### 2. Complete macOS and Linux resident voice validation

Run and record the matrix in
[VOICE_TRAY_MAC_LINUX_VALIDATION.md](docs/features/VOICE_TRAY_MAC_LINUX_VALIDATION.md).
Do not describe these platforms as validated until the records cover:

- Supported macOS versions and Linux desktop sessions.
- Global hotkeys, tray behavior, and run-at-login behavior.
- Microphone, accessibility, and audio-device permissions.
- Clean shutdown, duplicate-process prevention, and recovery after control loss.

### 3. Reduce orchestration complexity

Split the remaining large command and lifecycle paths in `src/scribe/cli/main.py`
and `src/scribe/core/recorder.py`. Preserve CLI behavior and session evidence while
moving transcription, recording, music, and cleanup responsibilities behind
smaller tested boundaries.

### 4. Redesign heavy dependency extras

Separate portable base functionality from PyTorch-backed features in a compatible
major release. This work should restore a credible Intel macOS install path,
allow cloud-only workflows to adopt new Python releases without waiting for
PyTorch wheels, and avoid downgrading the validated Windows and Apple Silicon
dependency stack.

The Windows Python 3.14.7 wheel-only base graph resolved on September 1, 2026,
but 3.14 still needs the complete runtime and platform matrix before support is
declared. Python 3.15 was at release candidate 2 on that date, with final planned
for October 1, 2026. A CPython 3.15 RC1 probe could not resolve Torch 2.13 because
no `cp315` wheel existed. Recheck after Python 3.15 final and compatible native
wheels are published.

### 5. Strengthen release provenance

Keep Python wheels reproducible and free of platform-native payloads. Before
distributing native tray binaries, add platform signing, checksums, embedded source
identity, and verifiable release provenance.

### 6. Raise verification depth

Maintain the enforced combined statement-and-branch coverage floor at 81 percent,
then ratchet toward 85 percent with failure-path tests. Keep dependency audits,
locked builds, native source checks, portable-wheel checks, and platform smoke
tests in required CI.

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

Local transcription and Ollama-backed notes can run offline. OpenAI and
OpenRouter transcription, cloud notes, humor providers, and image providers
transmit the relevant user content only when the user selects those features.
Scribe does not add telemetry that phones home.

## Completed foundation

The current foundation includes local GPU and CPU transcription, multiple local
backends, explicit OpenAI and OpenRouter cloud transcription, OBS recording,
batch and music workflows, structured TXT/JSON/DOCX/Markdown/VTT/SRT output,
transcript search, optional local speaker diarization, optional local notes,
resident voice, redacted support bundles, locked dependencies, SBOM generation,
dependency auditing, cross-platform smoke tests, and an OpenRouter reported-cost
circuit breaker backed by provider-limit diagnostics.

Detailed release notes belong in [CHANGELOG.md](CHANGELOG.md), not this roadmap.

Last updated: 2026-09-01
