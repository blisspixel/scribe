# ADR-009: Dependency preference and mutation testing

## Status

Accepted (2026-06), updated 2026-08-11 to reflect the current dependency graph.

## Context

Hardware-adaptive transcription, diarization, cloud providers, and resident voice
can introduce large native wheels or platform-specific libraries. Scribe needs a
clear preference for portable and isolated dependencies without pretending the
current 2.x base install is already small.

The base dependency set currently includes Torch, TorchAudio, and faster-whisper.
That supports the validated CPU and NVIDIA path, but it is a heavy baseline and
complicates a credible Intel macOS install. Moving those packages now would be a
compatibility change, so a larger redesign is deferred to a major release.

Coverage also proves execution, not assertion strength. Advisory mutation testing
provides a second signal for deterministic logic without making time-sensitive
mutation runs a required merge gate.

## Decision

Prefer pure-Python, portable dependencies. New heavy or platform-specific
capabilities belong in an optional extra unless an explicit architecture decision
justifies expanding the base install. The current extras are:

| Extra | Adds | Purpose |
|---|---|---|
| `mlx` | mlx-whisper | Apple Silicon local transcription |
| `whispercpp` | pywhispercpp | Optional portable native transcription |
| `diarize` | pyannote.audio | Local speaker diarization with pyannote (needs an HF token) |
| `diarize-nemotron` | Transformers (pinned commit) and librosa | Token-free NVIDIA Nemotron-3 speaker diarization |
| `diarize-mlx` | mlx-audio (arm64 macOS only) | Apple Silicon Metal speaker diarization |
| `whisperx` | WhisperX and pyannote | Word-aligned diarization |
| `providers` | Anthropic and Gemini SDKs | Optional cloud text providers |
| `voice` | Audio, hotkey, clipboard, and system TTS packages | Direct dictation and read-aloud |
| `tray` | Voice plus tray dependencies | Resident voice surface |
| `kokoro` | Kokoro ONNX runtime packages | Higher-quality local read-aloud |

Optional paths must check availability at the command boundary and report the
applicable `scribe[...]` extra. The repository install URL must be included in
user installation docs while the project is not published on PyPI.

The long-term portable-core redesign will be proposed as a separate major-release
decision. It must preserve CPU behavior, produce real clean-install evidence, and
avoid silently removing the validated NVIDIA path.

`pip-audit` remains blocking with zero ignored advisories. Any future exception
requires a documented owner, rationale, compensating controls, and removal date.
The current workflow contains no `--ignore-vuln` entries.

Mutation testing remains advisory and Linux-based. It targets selected pure logic,
is time-bounded, and remains outside the required CI aggregator. Surviving mutants
guide better assertions; a timeout does not redefine the required test result.

The required coverage gate is 81 percent combined statement-and-branch coverage.
It can be ratcheted upward only with meaningful failure-path tests.

## Consequences

- The current 2.x base remains heavier than desired, and documentation states that
  limitation plainly.
- New peripheral capabilities do not expand every user's dependency graph by
  default.
- Platform extras still require real install validation; declaring an extra does
  not make its native wheels universally available.
- Dependency audits remain simple and reviewable because exceptions are not the
  routine compatibility mechanism.
- Coverage and mutation testing provide different signals without either being
  described as stronger than it is.
