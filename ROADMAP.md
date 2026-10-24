# Scribe Roadmap

Scribe favors recording integrity, privacy, truthful outcomes, and maintainability
over feature count. [CHANGELOG.md](CHANGELOG.md) records shipped changes. This
roadmap records only unfinished work and the evidence required to ship it.

## Current position

Version 2.13.1 is the current GitHub release. The source repository is public.
The supported package remains the versioned GitHub wheel and
source distribution. Scribe is not published on PyPI, and no native executable is
an official release artifact.

The current product contract includes:

- Local-first transcription with explicit OpenAI and OpenRouter opt-ins.
- Full-model `max` file default with cached local acoustic review, explicit
  one-pass `accurate`, and uncertainty/source-retention evidence.
- Defensive OBS recording that requires positive startup evidence and preserves
  detected media on incomplete or failed sessions.
- Structured transcript and session evidence with complete, partial, failed, and
  instrumental outcomes.
- Optional local speaker labels (token-free Nemotron by default) and opt-in
  best-guess speaker names from a local or explicitly chosen cloud model.
- Optional transcript notes default to local Ollama, preserve explicit provider
  choices, and require source review. Broader note-quality claims need measured
  evidence across transcript genres and local models.
- Live-validated Windows resident voice.
- Experimental macOS and Linux resident voice pending hardware evidence.
- Omarchy (Arch, Hyprland, Quickshell, and PipeWire) is the Linux desktop
  reference. The distro Python is 3.14 and is a supported interpreter. Hardware
  proof of the Omarchy voice path is still outstanding.
- Experimental Omarchy compositor voice (`scribe voice`) reuses that resident
  owner. A GitHub release does not validate microphone selection, focus changes,
  correct-target insertion, cancellation, device loss, or recovery.
- Python 3.11 through 3.14. Python 3.14 is the default runtime. Python 3.15
  stays unsupported until CTranslate2 and ONNX Runtime publish cp315 wheels.
  Torch wheels on the stable PyTorch index do not lift that cap. See
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
| 2.9.3 | Released | Keep redirected Windows subcommand help ASCII-only and preserve complete option names | 2.9.2 |
| 2.10.0 | Released | Local speaker labels and names, faster GPU transcription, and transcript quality fixes | 2.9.3 |
| 2.11.0 | Released | Experimental Omarchy compositor voice, install and removal packaging, and Linux OBS launch fixes | 2.10.0 |
| 2.12.0 | Released | Accuracy-first multilingual file transcription, security updates, and recording, install, storage, and cleanup fixes | 2.11.0 |
| 2.13.0 | Released | Terminal interface, notes honesty and opt-in source references, current Gemini pins, Python 3.11-3.14, and the aiohttp audit fix | 2.12.0 |
| 2.13.1 | Released | Close the filelock, virtualenv, and setuptools advisories and require Pillow 13 in package metadata | 2.13.0 |
| 2.13.2 | Next | Produce clean-machine and real OBS evidence; fix every release-blocking finding | 2.13.1 |
| 2.14.0 | Planned | Validate desktop recording and resident voice on real hardware, including Omarchy | 2.13.2 evidence gate |
| 2.15.0 | Planned | Reduce orchestration complexity and deepen failure-path verification | 2.14.0 behavior contract |
| 3.0.0 | Gated | Redesign dependency extras and interpreter support without weakening local workflows | 2.15.0 boundaries and migration design |
| 3.1.0 | Conditional | Distribute signed native components only if measured evidence justifies them | 3.0.0 package contract and native decision gate |

2.10.0 shipped local speaker labels, speaker naming, and transcription quality
fixes ahead of the operational-proof patch at the maintainer's request. That proof
moved from 2.9.4 to 2.10.1 with unchanged scope and evidence requirements, and
later targets moved one minor version.

2.11.0 then shipped the experimental Omarchy compositor voice path, the
install and removal scripts, and the Linux OBS launch fixes before that proof
existed. The proof moved from 2.10.1 to 2.11.1 with the same evidence
requirements. The live desktop record, including Omarchy microphone selection,
focus changes, correct-target insertion, cancellation, device loss, and
recovery, moved to 2.12.0. Linux voice stays experimental. A green CI run and
this GitHub release are not that record.

At the maintainer's request, 2.12.0 releases the completed accuracy-first file
transcription, security, and reliability changes. Its new configurable acoustic
review is a backward-compatible capability, so this is a minor release. It does
not claim completion of the clean-machine, real OBS, or desktop hardware evidence.
The unchanged operational-proof scope moves to 2.12.1, desktop validation to
2.13.0, and maintainability to 2.14.0. Linux and macOS resident voice remain
experimental. No broader package or native binary distribution is introduced.

At the maintainer's request, 2.13.0 then ships the terminal interface, notes
comparison honesty, opt-in source-linked next steps, current Gemini model pins,
the Python 3.11 through 3.14 runtime, and the aiohttp advisory fix. Retired
Gemini ids fail with a named replacement. Evidence mode is off unless
`scribe notes --evidence` is passed. A matching quote is not a factual-quality
or acoustic-accuracy claim. This release does not claim the clean-machine, real
OBS, or desktop hardware record. That unchanged operational-proof scope moves
from 2.12.1 to 2.13.1, desktop validation to 2.14.0, and maintainability to
2.15.0.

2.13.1 then shipped ahead of that proof because scheduled CI was red. The
October 24 audit named filelock 3.32.0, virtualenv 21.14.5, and setuptools
83.0.0. The release locks filelock 4.2.4, virtualenv 21.14.13, and setuptools
84.2.1, and it requires Pillow 13.0.0 in package metadata. Pillow 13.0.0 was
already the locked wheel. The partial-exit log fix and the Gemini diagnostic
redaction ship in the same patch. The unchanged operational-proof scope moves
from 2.13.1 to 2.13.2. Desktop validation stays 2.14.0 and now depends on
2.13.2. Issue #66, the optional content-free Omarchy status indicator, stays
outside this patch and with the 2.14.0 desktop record.

Version numbers after 2.13.1 are planning targets. SemVer impact discovered during
implementation can change a target, but the reason and replacement target must be
recorded here before release preparation.

## Next release: 2.13.2 operational proof

### Objective

Prove that a new user can install Scribe, confirm readiness, record through real
OBS, preserve the media, and complete local or deliberately selected OpenRouter
transcription within the configured spend policy.

### Order of operations

1. Define a sanitized evidence record for the exact candidate commit, operating
   system, Python version, install command, detected backend, command exit status,
   and produced artifact types.
2. Run a clean install on Windows, macOS, and Omarchy, followed by `scribe init`,
   `scribe doctor`, and `scribe rec --check`. On Omarchy, install `uv` first and
   pass `--python 3.14`. Confirm the preinstalled FFmpeg, yt-dlp, and
   `/usr/bin/obs` before treating a missing tool as a Scribe defect. Another
   Linux distribution may be recorded as well, and it does not replace the
   Omarchy record.
3. Exercise the normal OBS WebSocket path and confirm both advancing OBS output
   counters and independent file growth. On Omarchy, use OBS PipeWire sources
   for the microphone, the output monitor, and a screen or window chosen through
   `xdg-desktop-portal-hyprland`. Do not run Omarchy's Alt+Print Screen capture
   at the same time, and do not stop or adopt that other capture.
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
  source on each claimed core platform. The Omarchy install uses Python 3.14
  and records whether that interpreter is uv-managed or the distro Python.
- Omarchy OBS evidence includes a Hyprland PipeWire capture, and the docs keep
  that path distinct from Omarchy's own screen recorder.
- The Omarchy proof does not use the resident tray or F9. Those keys stay with
  Omarchy dictation when a dictation backend is installed.
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

### Supporting evidence from installed 2.13.0

These observations were made on 2026-10-20 with the published `v2.13.0` tool
(`f3d000034c342677573fbc1cbc5f47545cd53420`) on one Windows machine. The
interpreter was Python 3.14.7. The install command was `uv tool install --with
"av<19" --torch-backend auto --python 3.14` from that tag. This is supporting
evidence. The 2.13.2 gate remains open until the same checks pass on the exact
release commit, from a clean install, and on macOS and Omarchy.

Shown on that Windows install:

- `scribe doctor` exited 0. Live provider checks were skipped. The machine
  reported Python 3.14.7, CUDA 13.0, an RTX 4090, faster-whisper on NVIDIA,
  FFmpeg, FFprobe, yt-dlp, a configured OBS WebSocket, and a writable output
  folder.
- `scribe rec --check` passed. The WebSocket answered, recording was inactive,
  the OBS process was running, and authentication was required.
- The normal OBS WebSocket path advanced the output counters and a new media
  file grew. The typed stop command stopped the capture. The process exited 0,
  OBS was idle afterward, and ffprobe reported about 10.1 seconds. The proof
  media was deleted. Scribe pointed OBS at the proof folder for that capture
  and left it there. The proof harness restored the previous OBS record
  directory afterward.
- An earlier capture in the same session ran for about 100 seconds because the
  external stop injection missed the console. It was safety-stopped and
  deleted. The 10.1-second capture above is the successful stop path.
- Local transcription of authorized synthetic speech at the default `max`
  quality exited 0. The session outcome was success, the method was local, the
  model was faster-whisper large-v3, acoustic review completed with no flagged
  spans, and the requested structured outputs were written. The synthetic
  sentence was recognized.
- An authorized OpenRouter run of the same clip used `--max-spend 0.25`. The
  CLI announced that per-run guard and `openai/whisper-large-v3`. `scribe info`
  still showed the configured $5.00 reported-cost guard. The run exited 1 with
  outcome partial because recording-wide primary language diagnostics are
  unavailable for that native/cloud primary. Acoustic review was partial, with
  one flagged span. The published tool environment had no `scribe_audio_core`
  module, so chunking used the portable duration path. That same run logged its
  own exit as a later session error. That logging defect is fixed in 2.13.1
  and still needs to be shown on the 2.13.2 candidate.
- On 2026-10-21, `scribe doctor --live` from this workspace tree exited 0 with
  22 passed checks and 2 warnings. OpenRouter was valid, and no provider hard
  cap at or below the configured $5.00 guard was reported. The guidance names
  that guard and tells the user to set a provider key limit. The output
  contained no API key and no account balance. OpenAI was valid. Anthropic was
  configured. Gemini was not configured. XAI could not be verified. This was
  the workspace tree at package version 2.13.0, including the Gemini
  diagnostic fix that is not in the installed v2.13.0 tag.
- An unexpected OBS stop on the installed 2.13.0 tool, while Scribe was still
  waiting, exited 1. Counters had advanced and the file had grown. The session
  outcome was failed, success was false, and the saved error said the partial
  recording was preserved. ffprobe reported about 9.9 seconds. The proof media
  was deleted, OBS was left idle, and the previous record directory was restored.

Still required before 2.13.2:

- A clean uninstall and reinstall from the documented tag.
- The emergency path with an unreachable, non-recording OBS process and a
  growing file, without adopting another capture. That path can start a second
  OBS instance, and its stop can fall back to a manual request, so it stays
  unrun until the stop is guaranteed.
- Ctrl-C and the recording-duration limit. Typed stop and an external
  unexpected stop are the two control results above. The duration limit's
  minimum is six minutes, so it has not been used for a short proof.
- Request metadata beyond the CLI announcement and the session summary.
- The Windows checks repeated on the exact 2.13.2 candidate, including
  `scribe doctor --live` and the unexpected-stop result.
- macOS and Omarchy clean installs, with OBS evidence. The Omarchy record
  includes a Hyprland PipeWire capture.

## Planned release: 2.14.0 desktop validation

### Objective

Make the desktop support statement evidence-based across recording and resident
voice, with tested fallbacks where an operating system cannot provide parity.
2.11.0 added the experimental `scribe voice` control plane. This release is the
live record that can promote or further limit that path. Source, CI, and a
GitHub release do not close it. Issue #66, the optional content-free Omarchy
status indicator, is a later feature and stays outside 2.13.2. A claim that the
indicator reflects a live microphone waits for this release's Omarchy voice
record.

### Order of operations

1. Complete the macOS, Linux X11, and Omarchy Wayland records in
   [VOICE_TRAY_MAC_LINUX_VALIDATION.md](docs/features/VOICE_TRAY_MAC_LINUX_VALIDATION.md).
   The Omarchy record is Hyprland plus Quickshell. A different compositor does
   not replace it.
2. Fix platform defects found by live permission, audio-device, hotkey, tray,
   startup, injection, read-aloud, and shutdown tests. On Omarchy, do not bind
   F9 or Super+Ctrl+X, and do not bind Right Alt (many users remap it for layout
   switching or compose). Do not claim pynput
   global hotkeys. Do not use `wtype` while Super is held: Omarchy injects
   clipboard shortcuts through Hyprland `send_key_state` because a virtual
   keyboard merges with that held modifier. Quickshell is not assumed to host a
   tray icon. Personal binds go in `~/.config/hypr/bindings.lua`, not under
   `/usr/share/omarchy`. An XDG autostart entry is not a Hyprland binding.
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
- The Omarchy record names the dictation keys it left alone, the terminal
  fallback it tested, and whether a tray icon was actually visible.
- The Omarchy voice record shows microphone selection, a focus change,
  correct-target insertion, cancellation, device loss, and recovery on the
  `scribe voice` path, or it documents the tested fallback and keeps that path
  experimental.

### Local speech models (also 2.14.0)

The pluggable diarization layer, token-free Nemotron default, and OpenAI diarized
output fix shipped in 2.10.0, along with speaker naming and batched GPU decoding.
Remaining evidence and follow-up work for 2.14.0:

1. Replace the pinned Transformers commit in `diarize-nemotron` with a validated
   released version after the diarization compatibility checks, and relock.
2. Record Nemotron speaker-label evidence on Windows NVIDIA, Linux NVIDIA, CPU-only,
   and Apple Silicon (MLX with a released mlx-audio that includes the model).
3. Confirm the `--torch-backend auto` install path on each platform and that
   `scribe info` reports the diarization device correctly.
4. Batched GPU decoding and beam width 5 are implemented from one RTX 4090
   measurement. Repeat the speed and quality comparison on a
   mid-range NVIDIA GPU and on a non-English recording, and record the results.
5. Evaluate current local ASR challengers against the full large-v3 file default
   before adding a dependency or promoting a model. Candidates include
   [Qwen3-ASR](https://huggingface.co/Qwen/Qwen3-ASR-1.7B),
   [Parakeet TDT v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3),
   [Nemotron 3.5 ASR](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
   and [Cohere Transcribe](https://huggingface.co/CohereLabs/cohere-transcribe-03-2026).
   Language coverage, task, access/license, vocabulary prompts, timestamps and
   offline behavior differ; English leaderboard rank is not a product-wide quality
   guarantee. No new ASR backend is selected automatically from these candidates.
6. Use the [evaluation protocol](docs/EVALUATION.md) on licensed human references
   and consented/synthetic controls: English plus target-language slices including
   Spanish and Japanese, noisy/overlapping speech, names/numbers/negation, silence,
   omissions, repetition and long recordings. Record WER/CER by language, task
   errors, failures, model revision and actual decoding/precision, peak memory,
   and cold/warm time. Do not compare unsupported languages as if they were covered,
   download a whole corpus for a small check, or add cloud cost to the local baseline.

Exit criteria: speaker labels never fail a transcription, the documented install
commands work on every claimed platform, and new model/backend promotions are
backed by measured multilingual quality and resource evidence. Current file
profiles and [acoustic review](docs/ACOUSTIC_REVIEW.md) express an accuracy/resource preference; hermetic policy tests alone do
not demonstrate a WER improvement on a laptop or across languages.

## Planned release: 2.15.0 maintainability and verification

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
5. Keep Python 3.15 unsupported until CTranslate2 and ONNX Runtime publish cp315
   wheels and the full CI and runtime matrix passes. Python 3.14 is already the
   default. Interpreter release status alone is insufficient.
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
- Actionable dependency advisories. The unused WhisperX extra is retired to
  remove the unpatched NLTK dependency tracked in
  [issue 31](https://github.com/blisspixel/scribe/issues/31); faster-whisper and
  Whisper large model support remain part of the base installation.
- Supported-platform installation failures and standard user-storage layout.
  Linux uses XDG config/data/state/runtime and localized Videos paths, with
  legacy config and vocabulary compatibility (issue #38). Clean-machine and
  upgrade proof must include both layouts and unsafe runtime failure.
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
