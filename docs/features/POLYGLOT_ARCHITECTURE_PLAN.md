# Polyglot Architecture Status and Plan

Scribe remains a Python application. Go and Rust are used only at measured native
boundaries where a smaller platform process or streaming media work might justify
the distribution cost.

The governing rule is: harden first, measure second, extract third. Prototype
source is not a released product surface.

## Current component map

| Component | Language | Location | Status |
|---|---|---|---|
| CLI, orchestration, providers, and resident voice | Python | `src/scribe/` | Product implementation |
| Tray controller | Go | `cmd/scribe-tray/` | Explicit developer prototype |
| Streaming audio analysis | Rust with PyO3 | `crates/scribe-audio-core/` | Optional source implementation |

CI tests and audits the Go and Rust sources. The portable root Python wheel does
not bundle either native artifact.

## Go tray boundary

The complete Python tray is the default. It owns user-facing menus, settings,
notifications, activation modes, recovery, model work, and lifecycle evidence.

The Go prototype explores a narrower operating-system boundary for tray and global
hotkey control. It communicates with the Python service over authenticated
loopback IPC. The Python service accepts it only from an explicit
`SCRIBE_TRAY_NATIVE_BIN` developer path and requires authenticated readiness plus
both hotkey registrations. Loss of the control connection is a failure.

No fixed memory or startup improvement is claimed. Release artifacts must be
benchmarked on supported platforms before a numeric comparison is published.

Remaining Go work:

- Reach the Python tray's user-visible menu, notification, activation, and error
  behavior where platform APIs permit it.
- Produce reproducible platform builds with embedded source identity.
- Add checksums, signing, attestations, and clean-install evidence.
- Decide whether the measured reliability benefit justifies maintaining a second
  desktop implementation.

## Rust audio boundary

The Rust crate exposes streaming audio-level and split-timestamp analysis through
PyO3. `openai_api.py` can use it opportunistically when the extension is installed.
The production portable fallback uses bounded duration-based FFmpeg chunking and
does not load an entire long recording into a Pydub `AudioSegment`.

The streaming parser keeps working buffers bounded by the active packet and split
metadata, but it still allocates and reuses data. The project does not claim a
literal zero-allocation implementation or constant total memory for an unbounded
number of output splits.

Remaining Rust work:

- Benchmark representative codecs, durations, silence patterns, and malformed
  media against the portable fallback.
- Build and clean-install a supported platform wheel matrix.
- Define compatibility and fallback behavior for each packaged extension.
- Sign and attest native artifacts before distribution.

## Distribution rules

Native components can become official only when all of these are true:

- The target has a measured user benefit on representative hardware.
- The Python fallback remains correct and covered.
- Supported platform artifacts build reproducibly from the tagged source.
- Each artifact carries a checksum, source identity, signature, and provenance.
- A clean machine can install, run, update, and remove it without a developer
  override.
- Failure or absence degrades visibly and never changes a local data boundary into
  a cloud one.

Until then, documentation must call both native components source prototypes or
optional development builds, not shipped binaries.

## Next decision

Finish clean-machine Python workflow evidence and macOS/Linux resident voice
validation before investing in native distribution. Those results identify actual
platform failures. Without them, native packaging would optimize an assumed
problem and add a larger signing and support surface.

Version baseline: Scribe 2.10.0.
