# ADR-009: Dependency-preference policy and mutation testing

## Status

Accepted (2026-06).

## Context

Across the recent product work (the shared transcript model, structured output,
hardware-adaptive backends, local diarization, and voice I/O) Scribe gained several
new capabilities. Each could have pulled a heavy or platform-specific library into
the base install. Keeping the default footprint small is what lets `scribe`
transcribe locally on a plain machine with only NVIDIA/CPU and an API key, so the
growth needs a stated rule rather than case-by-case judgement.

Separately, the test suite leans on Hypothesis property tests for the pure logic.
Line coverage confirms a line ran; it does not confirm an assertion would catch a
regression. Mutation testing is the tool that measures that, but it must not become
a flaky gate.

## Decision

**Dependency preference.** Prefer pure-Python dependencies. A dependency that is
heavy (large native/CUDA wheels) or platform-specific goes into an optional extra,
never the base `dependencies`. The base install stays NVIDIA/CPU transcription plus
API, and everything else is opt-in:

| Extra | Adds | For |
| --- | --- | --- |
| `mlx` | mlx-whisper | Apple Silicon (Metal) transcription |
| `whispercpp` | pywhispercpp | AMD/Intel/Apple via whisper.cpp |
| `diarize` | pyannote.audio | local speaker diarization |
| `voice` | sounddevice, pynput, pyperclip, pyttsx3 | dictation and read-aloud |
| `whisperx` | whisperx, pyannote.audio | word-aligned diarization |

Every optional path checks availability and degrades with a clear "install
`scribe[...]`" message rather than failing elsewhere. New runtime dependencies are
justified against this rule in review; a pure-Python alternative is preferred even
when slightly more code.

**Vulnerability policy.** `pip-audit` is blocking in CI. The only ignored advisories
are the tracked torch/CUDA ones (enumerated in the workflow), accepted while upstream
CUDA wheels settle and revisited when they do. This is documented, not silent.

**Mutation testing.** Add `mutmut` as a dev dependency and an advisory CI job over the
pure, property-tested core (transcript model, backend selection, diarization
alignment, voice endpointing, output writers). It is `continue-on-error` and outside
the CI gate aggregator: a surviving mutant is a prompt to add a test, not a build
failure. mutmut is Linux-only, so it runs in CI (or WSL locally), not on every dev
machine. As surviving mutants are killed and pure logic gains property tests, the
coverage floor ratchets toward 90% from its current 80%.

## Consequences

- The base install stays lean and cross-platform; capability growth lands in extras,
  so a user installs only what their hardware and workflow need.
- Coverage and mutation signal are kept honest: line coverage is the floor gate,
  mutation testing is the advisory quality signal, and neither is gamed. Hardware and
  live-I/O glue that cannot run in CI is marked `pragma: no cover` with a reason
  rather than padded with fake tests.
- The 90% coverage target is explicit and gated on real tests landing, not asserted
  prematurely.
