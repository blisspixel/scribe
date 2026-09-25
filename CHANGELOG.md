# Changelog

All notable changes to Scribe are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Version 2.10.0 is the current GitHub release. Version 2.8.1 was the first. Scribe
is not published on PyPI. Older versioned sections describe development
milestones that predate this repository's Git history.

---

## Unreleased

No changes yet.

## [2.10.0] - 2026-09-25

### Added

- Added optional speaker naming (`--name-speakers`, `name_speakers` under
  `[diarization]`). A language model proposes the names spoken in the meeting and
  Scribe assigns them to speakers from evidence across every mention, so a name is
  never given to the person who says it. Uses local Ollama by default (unloaded
  after use), or a configured cloud provider including OpenRouter. The transcript
  header lists best-guess names for easy correction.
- Added a speaker list at the top of labeled transcripts and one paragraph per
  speaker turn instead of a label on every sentence.
- Added hysteresis, padding, and minimum-duration post-processing for Nemotron
  diarization, and dropping of speakers with under 2 seconds of speech.
- Added pluggable local speaker diarization under `scribe.core.diarization`, with
  word-level alignment that splits a Whisper segment at speaker changes.
- Added token-free NVIDIA Nemotron-3 Diarization (`nvidia/Nemotron-3-Diarization`,
  up to eight speakers) as the preferred local backend on every platform. It runs
  on CUDA when the installed PyTorch build supports it and on CPU otherwise. Install
  it with the `diarize-nemotron` extra.
- Added the experimental `diarize-mlx` extra for Apple Silicon Metal diarization.
- Added the `--diarizer auto|nemotron|pyannote|mlx|none` option to `transcribe`,
  `url`, and `batch`, and `--diarize/--no-diarize` to `batch`.
- Added a `[diarization]` config section (`enabled`, `backend`,
  `pyannote_pipeline`) and the `SCRIBE_DIARIZATION_BACKEND` setting.
- Added a `speaker labels` line to `scribe info` that shows the backend and device
  that will run, including when PyTorch has no CUDA support.
- Added per-word timing and speakers to JSON output when diarization runs.
- Added a warning before local GPU transcription when other processes, such as a
  local LLM, leave too little free GPU memory for the Whisper model.

### Changed

- torchaudio is no longer a base dependency. Extras that need it (pyannote and
  WhisperX) still install it.
- Local NVIDIA transcription now uses faster-whisper's batched pipeline with a
  batch size chosen from the GPU tier and free VRAM, falling back to sequential
  decoding when memory is short or a batched run fails. Long batched chunks are
  split into sentence-sized segments with word timings. On an RTX 4090, a
  13-minute recording transcribed about nine times faster than with the previous
  settings, with word agreement within the variation between beam widths; the
  main difference is fewer filler words. Set `local_batch_size = 0` under
  `[transcription]` to restore sequential decoding.
- Every GPU tier now uses beam width 5. Widths 8 and 10 cost up to twice the
  decoding time with no measurable accuracy benefit on the same recording.
- pyannote now defaults to `pyannote/speaker-diarization-community-1`, falls back
  to 3.1, and is skipped in favor of Nemotron when no Hugging Face token is set.
- An unknown configured diarization backend now logs a warning and uses `auto`
  instead of being ignored silently.

### Fixed

- Fixed local sequential transcription (CPU, low-VRAM GPUs, Apple and AMD
  fallbacks, and the batched-decoding fallback) losing punctuation and casing
  after the first 30 seconds: the prompt applied only to the first window. It now
  uses Whisper's standard conditioned decoding with temperature fallback.
- Fixed one-to-three-word speaker flips inside sentences ("Is" / "he?") by
  smoothing speaker labels per sentence across segment boundaries.
- Fixed a development Transformers build printing `[ERROR] ... not documented`
  lines to the console while loading the diarization model.
- Fixed silence markers ("[NO AUDIO FOR ...]") never appearing, and audio slicing,
  vocal detection, and vocal separation failing: they loaded audio through
  torchaudio, whose current releases need the separate torchcodec package. Scribe
  now reads audio with the standard-library WAV reader and FFmpeg.
- Fixed speaker labels failing on GPU installs where uv selected a PyTorch CUDA
  build with no matching torchaudio build (for example CUDA 13.2), which broke
  Transformers imports.
- Fixed OpenAI `gpt-4o-transcribe-diarize` transcription returning no speaker
  labels. Scribe now requests `diarized_json`, stops sending the unsupported
  `timestamp_granularities` parameter, and merges fragments into speaker turns.
- Fixed pyannote diarization failing on pyannote.audio 4.x, which renamed the
  token argument and changed the pipeline output type.
- Locked `lightning` 2.6.6 for the optional pyannote extras to fix a high-severity
  checkpoint code-execution advisory.
- A speaker-labeling failure now keeps the unlabeled transcript instead of
  failing the transcription.
- Fixed finished transcriptions keeping the Whisper model (about 4 GB on a
  high-end GPU) and the diarizer in GPU memory for the life of the process. A
  `scribe rec` window launched from the desktop shortcut and left at its
  "Press Enter" prompt held that memory until closed, so several open windows
  starved later transcriptions and local LLM notes of VRAM. Models are now
  released as soon as each file finishes, including after failures.

## [2.9.3] - 2026-09-02

### Changed

- Reserved 2.9.3 for this urgent Windows output fix and moved the operational
  proof gate to 2.9.4 without changing its scope or evidence requirements.

### Fixed

- Switched subcommand help to Click's plain ASCII formatter. Redirected or piped
  Windows help now preserves complete long option names instead of sending a
  code-page ellipsis that PowerShell can render as a replacement character.

## [2.9.2] - 2026-09-02

### Added

- Added a validated `--max-spend` per-run OpenRouter option, with an explicit
  `--openrouter-max-spend` alias, to file, URL, recording, batch, music, and Quick
  Record commands.
- Added live CLI evidence for the default $5 guard and a non-default $0.01
  override using the synthetic 60-second OpenRouter round-trip clip.

### Changed

- Made `scribe info` show the effective OpenRouter model and reported-cost guard,
  and made live diagnostics use the effective `.env`, environment, or user-config
  spend value.
- Reworked the roadmap into a dependency-ordered, versioned release plan with
  explicit prerequisites, operations, exit criteria, and a continuous patch lane.
- Added a release-process guide that keeps version metadata, changelog, install
  examples, roadmap state, artifacts, exact-commit CI, and post-release
  verification synchronized without calendar or effort-duration promises.

### Fixed

- Replaced remaining decorative non-ASCII separators in redirected CLI and
  diagnostic output so Windows legacy encodings do not render replacement
  characters.
- Made an explicit `--output-dir` place the transcript and structured sidecars in
  that directory, while atomically preserving an existing transcript and keeping
  the newly generated source copy if relocation fails.

## [2.9.1] - 2026-09-01

### Added

- Added a default $5 per-transcription OpenRouter reported-cost circuit breaker.
  It preserves confirmed partial output and stops before another chunk when the
  reported total reaches the limit or provider cost becomes unavailable.
- Added a no-cost OpenRouter account preflight before conversion and upload. It
  fails early on rejected credentials or exhausted provider budget.
- Added safe hard-cap diagnostics to `scribe doctor --live`. The check reports
  whether a provider-side key limit is at or below Scribe's guard without
  displaying the account balance.
- Added live Windows round-trip evidence using OpenRouter TTS to create synthetic
  speech and the dedicated STT endpoint to transcribe a 60-second clip.
- Added a redacted full-history secret-scan baseline containing only exact,
  commit-pinned synthetic test-key false positives. New findings remain blocking.
- Added current interpreter compatibility evidence: the Windows Python 3.14
  wheel-only base graph now resolves, while Python 3.15 RC1 remains blocked by
  the absence of CPython 3.15 Torch wheels. Supported metadata stays at the fully
  tested Python 3.12 and 3.13 range.

### Changed

- Changed the configurable OpenRouter default to `openai/whisper-large-v3`, the
  stable quality model in OpenRouter's current STT examples. Requests use
  temperature zero and price-prioritized provider routing.
- Documented model selection, per-file and provider-side spending controls,
  ambiguous retries, synthetic testing, and the exact cloud data boundary.

### Fixed

- Fixed FFmpeg conversion failures caused by Unicode Rich progress glyphs on
  Windows legacy or redirected output. Converter animation now follows the shared
  terminal policy and checks stream encoding before rendering.
- Replaced a non-ASCII command-summary separator that rendered as a replacement
  character in Windows redirected output.
- Made OpenRouter temporary-workspace cleanup remove incomplete conversion files,
  while continuing to preserve source media and confirmed transcript artifacts.

## [2.9.0] - 2026-09-01

### Added

- Added fully optional OpenRouter speech-to-text with `--method openrouter`, a
  separate `OPENROUTER_API_KEY`, configurable model and timeout, and no change to
  the local `auto` default.
- Added streaming local normalization in a collision-safe temporary workspace,
  five-minute upload chunks, a defensive chunk-size ceiling, retryable status
  handling, immediate auth and credit failures, provider-reported cost metadata,
  atomic confirmed partial output, and truthful `.previous` archives on reruns.
- Added OpenRouter setup discovery, `scribe info` key status, an opt-in no-cost
  `scribe doctor --live` key check, support-bundle redaction, and a dedicated
  cloud transcription guide.

### Changed

- Extended file, URL, recording, batch, and music method selection to accept
  OpenRouter without precompressing its source twice.
- Made `SCRIBE_LOCAL_ONLY=1` override both cloud transcription providers and kept
  `auto` entirely local even when either cloud key is configured.
- Updated the README, roadmap, CLI, deployment, architecture, API, responsible-use,
  and troubleshooting documentation for the new cloud boundary and recovery
  behavior.

### Fixed

- Made live provider diagnostics skip unconfigured optional providers and removed
  partial API-key fragments from diagnostic output.

## [2.8.1] - 2026-09-01

### Added
- Added a dedicated recording guide covering setup, positive startup proof,
  defensive control paths, monitoring, safe stop, and recovery on each platform.
- Added a sanitized README terminal screenshot generated from the real recording
  command, with a reproducible capture script and no personal runtime data.
- Enabled GitHub dependency alerts. Automated update pull requests remain
  intentionally disabled until the repository maintenance policy changes.
- Added contributor, conduct, support, issue, and pull-request guidance with
  explicit synthetic-data and privacy requirements.
- Added the PEP 561 typing marker to built artifacts and made the release contract
  reject wheels that omit it.
- Added the Rust audio extension to the required CI aggregate with formatting, Clippy warnings-as-errors, and unit-test gates.
- Added a versioned, backend-independent evaluation harness for micro-averaged word error rate, real-time factor, exact-match diagnostics, manifest hashes, revision metadata, and per-sample evidence.
- Added a security policy covering supported versions, private vulnerability reporting, cloud and local trust boundaries, and the experimental native-tray boundary.
- Added required Windows and Apple Silicon macOS Python smoke jobs. The Windows job executes the generated Quick Record batch wrapper through the real command interpreter.
- Added a locked CycloneDX runtime SBOM as a required CI artifact.
- Polyglot Architecture Phase B: Added `scribe-audio-core`, a native Rust extension via PyO3 that streams audio analysis without loading the complete recording into a Pydub silence splitter. Release performance claims remain blocked on reproducible benchmarks.
- Polyglot Architecture Phase C: Added a pure Go resident tray source prototype (`scribe-tray`). Reproducible platform packaging, menu parity, integrity verification, and performance evidence remain open before release claims.
- Protected the local native-tray IPC boundary with a process-scoped capability and authenticated READY handshake. Unauthenticated peers cannot receive state or issue dictation, read, or quit commands.
- Added a required Windows native-tray source contract that checks module tidiness and integrity, Go tests and vet, reachable vulnerabilities, reproducible build hashes, embedded commit identity, and a local evidence manifest.
- Added durable terminal evidence for started file, URL, batch-item, recording, and per-track music sessions. Terminal summaries preserve surviving artifact and correlated local-log paths and distinguish success, partial completion, failure, and confirmed instrumentals.

### Changed
- Selected Apache License 2.0 as the canonical project license and aligned source,
  package, and wheel metadata with those terms.
- Prepared the repository for public visibility: replaced the private-repository
  install and reporting caveats in the README, security policy, deployment guide,
  troubleshooting guide, changelog, and issue-template config with guidance that
  is correct for a public repository, and pointed vulnerability reports at
  GitHub's private reporting flow.
- Documented that Scribe bundles no third-party source and that dependencies keep
  their own licenses, naming the LGPL-3.0 `voice` and `tray` extras and the
  separately licensed models and executables.
- Recovered Quick Record from OBS processes that completed shutdown without
  exiting by attempting one non-destructive multi-instance relaunch when WebSocket
  is unavailable. Normal startup requires advancing OBS output counters and checks
  independently for a fresh growing file. Emergency startup requires file growth.
  Existing recordings are never stopped, emergency fallback uses OBS's supported
  start option, and live files are never moved during manual recovery. Unexpected
  stops preserve the partial file and fail truthfully. Doctor now reports a
  running OBS process whose configured WebSocket port is closed.
- Raised the development pip floor to 26.2 to remediate PYSEC-2026-3721 and keep
  the required zero-exception dependency audit passing.
- Constrained the optional WhisperX dependency graph to NLTK 3.10.3 or newer,
  remediating the current critical and high transitive advisories in the lock.
- Reworked the root README into a concise project landing page and moved detailed command and resident-voice operations into linked CLI and voice guides.
- Added a searchable CLI preview and documented CPU, NVIDIA, Apple Silicon, AMD,
  and Intel paths without treating one development GPU as a requirement.
- Kept `s` or `stop` plus Enter as the recording stop control, but coordinated command echo with the live timer so typed input appears in a clean prompt instead of attaching to the elapsed time.
- Split system diagnostics and media-cleaning implementations out of the central CLI entrypoint, with an architecture contract that keeps those command wrappers thin. Raised the enforced combined statement-and-branch coverage floor from 80 to 81 percent.
- Replaced the eight Torch audit exceptions with a secure universal ML resolution: the WhisperX extra now selects 3.7.2, while Torch 2.13, TorchAudio 2.11, Transformers 5.14, and Hugging Face Hub 1.25 satisfy a zero-exception dependency audit.
- Refreshed the universal Python lock, pre-commit hooks, immutable GitHub Actions, Go modules, and Rust dependencies to current compatible releases. The Rust extension now targets edition 2024, PyO3 0.29, and Symphonia 0.6.
- Aligned package metadata with the validated Python 3.12 and 3.13 matrix after a Python 3.14 install probe exposed unavailable native wheels in the universal ML dependency graph.
- Documented explicit matching Torch and TorchAudio backends for GPU installs and made diagnostics import both native packages, catching CUDA ABI mismatches before recording or transcription.
- Reduced trivial CLI startup from roughly 1.8 seconds to about 0.5 seconds on the development machine by moving recorder, transcriber, settings, DOCX, session, GPU, and humor construction behind lazy command boundaries.
- Enabled branch measurement in the enforced coverage run and added regression contracts for heavyweight CLI imports and acyclic internal imports.
- Removed the provider catalog and meme bake-off import cycles by extracting a dependency-light provider catalog and injecting meme concept analysis.
- Pinned every third-party GitHub Action and the uv toolchain to reviewed immutable revisions instead of mutable major-version or latest tags.
- Removed the redundant startup banner from the Windows Quick Record launcher so its console opens directly on Scribe's recording output.
- Hardened `scribe tray --check` and resident-voice readiness advisories for macOS and Linux: platform validation tier and startup path are printed, headless Linux no longer claims X11 hotkey support, Wayland guidance references portal GlobalShortcuts and desktop-shortcut fallbacks, macOS notes LaunchAgent login plus Accessibility for `inject=type`, and setup docs state experimental status until live hardware records exist.
- `scribe tray --startup install` now prints OS-specific follow-up notes for macOS permissions and Linux Wayland/autostart limits after creating the login entry.
- Consolidated installation and contributor setup on `pyproject.toml` and one locked uv development group, removing two drifting legacy requirements files, a duplicate incomplete dev extra, and contradictory commands.
- Moved responsible-use guidance into the canonical documentation tree, removed stale tracked agent-loop files from the root, and repaired documentation discovery and release instructions.
- Replaced unsupported MIT claims with one verified Apache-2.0 package contract;
  release validation checks project, source, packaged runtime, and wheel evidence.
- Removed the stale unsigned Go executable from tracking and ignored generated native developer builds. The source prototype remains explicit-only and is not published by the portable package.
- Hardened artifact boundaries by rejecting platform-native payloads from the portable wheel, isolating native verification from external Go workspaces, resolving modules read-only, and pinning checkout to a reviewed immutable revision.
- Made the root wheel portable by removing its mandatory dependency on the unpublished workspace-only `scribe-audio-core` artifact. The Rust crate remains an optional workspace acceleration until platform wheels have a verified distribution path.
- Promoted `deal` to a runtime dependency because contract-decorated production modules import it during normal CLI startup; clean wheel installs no longer fail after dependency resolution.
- Added a required release-artifact CI job that builds and inspects the root wheel, installs it without workspace packages, and smokes the installed `scribe` entry point.
- Changed client-side OpenAI chunking to prefer optional native silence analysis while retaining a visible duration-based fallback. Both paths normalize endpoints to a hard cap and export with the configured overlap and bitrate.
- Refactored `scribe.core.openai_api` to completely eliminate `pydub.silence.split_on_silence` dependency in favor of the new Rust streaming engine.
- Kept the complete Python tray as the deterministic default. Native selection now requires an explicit `SCRIBE_TRAY_NATIVE_BIN` path; checked-in and merely packaged builds are never launched implicitly before capability parity.
- Added backend and native selection-state output to `scribe tray --check`. Explicit files are labeled unverified developer overrides, and activation or hotkey incompatibilities are reported as Python fallback decisions before launch.
- Tightened broad exception handlers across core modules (`openai_api`, `local_whisper`, utilities) to specific typed tuples in compliance with ADR-002, preventing masked errors.
- Standardized CLI exit boundaries in `main.py` using a single `exit_on_cli_error` handler instead of scattered `typer.Exit(1)` calls.
- Added SBOM generation documentation, integrated CUDA driver age checks into
  `scribe doctor`, and documented the structured-logging decision in ADR-012.
- Corrected package metadata links to the canonical `blisspixel/scribe` repository.
- Refreshed roadmap, architecture, deployment, and test documentation so current
  status, local-first scope, and quality gates match the development version.
- Revalidated every tracked Markdown guide against the 2.8.1 CLI and source,
  replacing stale API examples, unsupported flags, unsafe credential diagnostics,
  contradictory voice plans, and incorrect coverage or exit-code claims.
- Fixed standalone notes, joke, and meme provider selection so an explicitly or
  centrally configured non-OpenAI provider is not blocked by a missing OpenAI key.
  Added `scribe meme --provider` and preserved bracketed extra names in rich help.
- Extended provider-correct selection to file, URL, recording, and batch derived
  outputs, used each provider's own default notes model unless overridden, and
  removed silent meme or joke fallback to OpenAI after another provider fails.
- Made file and URL transcription record requested derived-output failures as
  partial outcomes, preserve the reasons in session summaries, and exit nonzero.
- Added Pillow to the base dependency contract used by the default local meme
  compositor, and replaced bare `pip install scribe[...]` recovery text with
  source-aware extra guidance while the project has no PyPI release.
- Added recovery guidance and active log-file visibility to shared CLI error output.
- Made `scribe doctor` local-only by default, with `scribe doctor --live` as the explicit opt-in for provider API-key validation.
- Corrected diagnostic API documentation and source prose to match the local-first doctor behavior.
- Clarified warning-only `scribe doctor` summaries so they report "Ready with warnings" instead of implying notes are ready.
- Documented why macOS/Linux resident-tray validation is the next roadmap task and refreshed developer test guidance to match the current CI-safe coverage gate.
- Consolidated the prior contradictory license claims before selecting the
  canonical Apache-2.0 terms.
- Kept shared CLI error log-file paths on one literal line so CI and Linux terminals do not wrap the filename out of diagnostic output.
- Upgraded support bundles to read bounded durable session summaries across CLI processes and include opaque recent-log metadata. Log filenames, paths, and contents are excluded, and the CLI now asks users to review the redacted JSON before sharing it.
- Removed the unused parallel `RunContext` implementation so terminal evidence has one maintained session model and archive format.
- Standardized method help across file, URL, recording, batch, and music commands so `auto/local` is explicitly `$0` local on GPU or CPU and `openai` is explicitly paid cloud.
- Declared `psutil` as a required runtime dependency so the standard `scribe doctor` installation can report CPU and memory readiness instead of silently skipping the check.

### Fixed
- Fixed four path-validation tests that failed on any Windows profile whose name
  contains a space. Such profiles report `TEMP` as an 8.3 short path, which the
  product correctly canonicalizes but the shared `temp_dir` fixture did not, so
  fixture paths never compared equal to product output. CI runs on space-free
  profiles and could not surface this.
- `scribe info` now reports the local Whisper model that will actually run rather
  than the configured preference. On a machine without a GPU the default is
  auto-tuned down, so the previous output named a model the run would not use.
  The pipeline and `scribe info` now share one resolution helper.
- Corrected the no-GPU transcription warning, which claimed local transcription
  would "likely fail" on CPU. CPU transcription is a supported, working path, and
  the warning now states the real tradeoff and where the model comes from.
- Repaired mutation-test configuration for the current mutmut schema and stopped
  masking runner crashes as successful steps. The advisory run now builds a
  complete importable package, limits mutations to the intended pure-core files,
  uses the CI-safe unit-test subset, and keeps pytest startup errors visible.
- Corrected edge cases in CLI traceback logging, hand-edited boolean settings,
  JSON vocabulary validation, YAML frontmatter string preservation, and partial
  or instrumental session summaries.
- Prevented the CLI banner from crashing on Windows streams that cannot encode
  block and box-drawing characters by using an ASCII fallback for those streams.
- Closed replaced logging handlers during reconfiguration so repeated commands
  do not leak file descriptors or leave prior log files locked on Windows.
- Replaced nonexistent OBS request-client `close()` calls with the supported
  `disconnect()` API across preflight, startup, retry, and recording cleanup.
- Hardened resident fallback after startup: an authenticated native tray that loses IPC is stopped and replaced visibly, model warmup waits are bounded, and fallback is refused unless hotkey, microphone, read-aloud, worker, and model cleanup are confirmed. Python tray and terminal modes now return failure when shutdown remains uncertain instead of reporting a clean exit.
- Serialized hotkey-watchdog replacement with shutdown so a recovery hook cannot outlive the service inventory. Failed hotkey startup, reconnect, and microphone startup now retain any resource whose cleanup cannot be confirmed, and every lingering managed thread blocks fallback. Explicit CTranslate2 cleanup and legacy listen cleanup have bounded waits and surface inspection or unload failures instead of hanging or reporting success.
- Preserved unknown root values, nested tables, arrays, quoted keys, and TOML date/time values when voice settings rewrite the user config, preventing tray hotkey or setup saves from erasing future or custom configuration.
- Prevented duplicate resident voice processes from multiplying CUDA allocations. A stable per-user operating-system lock now spans updated editable installs, tool installs, `scribe tray`, `--no-tray`, legacy `scribe listen`, native fallback, and future upgrades; repeated launches exit before registering hotkeys or preloading Whisper. Retained ownership is left to the operating system to release at actual process termination instead of being released early from `atexit`; fallback refuses to overlap unfinished model work, and shutdown explicitly unloads the resident CTranslate2 model after its last active use.
- Made resident voice failures visible and recoverable: the Python icon becomes visible before model warmup, detached failures go to a bounded rotating resident log, dead global hooks report reconnect failures with bounded retry, failed hotkey saves roll back live state, preload thread failures clear the loading state, clipboard restoration failures warn, read-aloud fallback failures propagate, playback resources close, and run-at-login changes report filesystem or launch-service errors. Legacy listen mode moves transcription off the low-level keyboard hook, bounds its pending work, reports capture and worker failures, and unloads its model explicitly.
- Bounded resident resource growth with a five-minute limit per dictation capture, a 32-action dispatcher backlog with visible overflow recovery, serialized shutdown, process-safe native quit confirmation, unused native-watchdog removal, bounded neural-cache cleanup, and explicit device overflow warnings.
- Prevented voice settings from overwriting malformed or unreadable configuration. Mutating paths now use strict reads, quoted TOML keys and control characters round-trip safely, config replacement is atomic, and failed writes preserve the prior file and return failure instead of claiming setup completed.
- Made media trimming succeed when the original-duration probe is unavailable, prevented empty inputs from causing division by zero in cleanup summaries, normalized provider names in health checks, and rendered provider errors and media paths as literal terminal text.
- Bound each Python matrix test command to its declared interpreter and added a runtime assertion, preventing uv from silently recreating a Python 3.13 environment with the repository's 3.12 default.
- Migrated native audio probing, decoder construction, packet iteration, and sample conversion to Symphonia 0.6 without retaining deprecated APIs.
- Prevented a mismatched Torch and TorchAudio CUDA pair from being reported as healthy by the package diagnostic, and added verified same-backend GPU repair guidance.
- Replaced vacuous recorder and end-to-end assertions with behavioral checks that verify CLI fallback routing and forced-local transcription without cloud fallback.
- Made Windows Quick Record shortcuts and taskbar pins call the stable per-user wrapper instead of retaining removed Python or temporary test executables. Wrapper fallback checks and CRLF output are now deterministic.
- Made tray help assertions ignore terminal styling so Linux CI validates user-facing text independently of Rich ANSI boundaries.
- Kept native Go source and module files on LF in Windows checkouts so `go mod tidy -diff` remains stable across runner line-ending settings.
- Delayed music transcriber initialization until a track reaches transcription, so invalid, non-music, and confirmed instrumental outcomes do not fail early when ffmpeg is unavailable.
- Consolidated OpenAI duration lookup on one patchable dependency and replaced process-wide `Path.stat` mocks with real temporary inputs, preventing platform-specific path type failures in the Python matrix.
- Native tray IPC auth rejects wrong-length capability lines without killing the accept loop (`hmac.compare_digest` length safety).
- Linux tray readiness no longer treats `XDG_SESSION_TYPE` alone as proof of a graphical session, and macOS permission copy no longer claims silent mic failure when capture reports an error.
- Made the Go tray honor configured F6-F12 keys, reject collisions and unsupported keys, fail closed when either global registration fails, use the canonical visible icon, surface socket failures, and clean up native registrations.
- Removed the Go tray's focus-breaking read-selection menu action; the configured read hotkey remains the reliable native path.
- Updated the native verification toolchain past known unreachable Go and `x/sys` advisories, made its evidence fail-clean and atomic, and recorded the actual resolved module graph.
- Delayed native model preload until authenticated tray readiness, preventing a failed daemon startup from racing a second model load in the Python fallback.
- Made native startup timeouts, launch errors, and nonzero exits recover visibly through the complete Python tray instead of ending the resident workflow.
- Fixed long-audio chunking that could emit an over-cap final chunk when no useful silence was detected. Native decoder failures now become visible fallback events, MP3 encoder padding is reserved inside the cap, and partial ffmpeg exports are removed on failure.
- Batch and music continuation now has truthful automation semantics: remaining inputs are processed by default, but missing inputs, failed files, partial segment results, or missing requested artifacts appear in the final summary and return exit code 1. Fully complete and confirmed instrumental runs still return 0.
- Batch sessions now record requested DOCX, notes, joke, and meme failures as partial outcomes instead of reporting the transcript as wholly successful. Explicit provider-backed extras without `OPENAI_API_KEY` remain visible and preserve the usable transcript rather than being silently disabled.
- Music VAD failures now use the full-audio fallback instead of being mislabeled as instrumental. Mixed segment failures preserve usable lyrics as partial, while all-segment failure is reported as failed and never writes an instrumental marker.
- Recording commands now start evidence capture before OBS setup, retain the source recording when transcription fails, and report requested DOCX, notes, joke, meme, or cleanup failures as partial instead of complete success. Record-only runs also save a terminal summary.
- Music commands now save one durable outcome for every started track, retain the selected transcription backend and model, report exact non-music and cleanup failures, continue past confirmed instrumentals under `--stop-on-error`, write lyrics and markers atomically, and never delete conventionally named sibling files that were not created by the current run.
- A session-summary write failure is now visible without masking the original processing error, and evidence-path output can no longer turn a saved music result into a command failure when stdout closes early.
- `scribe init` now defaults to local `auto` transcription on machines with or without a GPU, and it asks for provider keys only when API transcription or a provider-backed extra is selected.
- `scribe health --provider NAME` now fails with an actionable message for unknown providers and providers without configured keys instead of treating an empty check set as healthy.
- `scribe tray --check` now reports a missing optional parent package, including Pillow, as an installable dependency instead of raising `ModuleNotFoundError` while probing a child module.
- Support bundles now report API keys only as `[CONFIGURED]`; they never include key prefixes or suffixes, including for short values.
- Recursively redacted known home-identifier and credential patterns, including configured secrets, authorization headers, quoted credentials, camelCase credential fields, and nested diagnostic or error values. Noncanonical legacy session IDs are opaque, and local path-bearing session errors omit their private tails.
- Included the privacy-safe session ID in summary filenames so repeated meeting names no longer overwrite earlier success or failure evidence.
- Replaced troubleshooting guidance for the nonexistent `logs/latest.log` alias with the exact active timestamped log path printed by command failures.
- The custom help screen now lists every registered command, including `record`, `init`, `shortcut`, `support-bundle`, and `version`.
- Restored clean Ruff format and lint gates, converted hardware-dependent boolean scripts from misleading pytest tests into explicit standalone checks, and raised meaningful CI-safe unit coverage above the 80 percent floor.
- CI now syncs from the committed lockfile and includes `toolchain-check` in the aggregate pass/fail decision.
- Synchronized the 2.8.1 workspace version in `uv.lock` with package metadata.
- Replaced Windows delete-before-rename behavior in every safe-write path with atomic same-filesystem replacement. Replacement failure preserves the prior file, and the documentation no longer overstates power-loss durability.
- Staged and verified WAV reconversion before atomic replacement, preserving an earlier usable WAV across analysis, conversion, verification, descriptor, cleanup, and replacement failures.
- Prevented post-save terminal failures from rewriting successful or partial file, URL, or recording evidence as failed. Summary notification remains best-effort and cleanup or presentation failures stay visible in logs.
- Made expected batch exits bypass unexpected-error reporting, escaped dynamic batch and shared error text, and preserved complete literal diagnostic messages without fixed-width truncation or Rich markup injection.
- Reserved support-bundle destinations exclusively so concurrent and same-second runs cannot overwrite one another, cleaned failed reservations, and replaced circular failure advice with context-aware recovery.
- Prevented closed pipes, closed streams, and output-encoding failures from recursively replacing CLI errors or saved outcomes. Unexpected failures reach an active UTF-8 file log before best-effort rendering, a failed Rich logging sink disables itself without a traceback, and progress display failure cannot change processing state.
- Made default batches with every input missing reach one ASCII-safe aggregate summary with exact zero, partial, and failed counts. Stop-on-error mode remains immediate after the first literal missing-path warning.

### Security
- Raised the `yt-dlp` dependency floor and lock to 2026.7.4, resolving `CVE-2026-55404` in generated URL and desktop shortcut handling.
- Raised the setuptools build requirement and lock to 83.0.0, resolving `PYSEC-2026-3447` in the build toolchain.
- Eliminated the previously documented Torch exceptions by constraining the incompatible WhisperX 3.8 dependency line and validating patched CPU and CUDA dependency sets. ADR-004 retains the model-checkpoint trust boundary and records the compatibility pin's removal trigger.

## 2.8.0 - 2026-07-01

### Added
- **`$0` local-processing readiness in `scribe doctor` and `scribe info`.** A headline verdict tells you plainly whether you can run for free on this machine - e.g. *"$0 LOCAL: You can transcribe and take notes on this machine with no API key."* - and, when something's missing, exactly how to fix it (install ffmpeg, start Ollama and `ollama pull`, or add the faster backend extra for your hardware). Reported by a shared `assess_local_readiness()` so `doctor`, `info`, and the new `Local Transcription/Notes ($0)` checks never disagree.
- **Local-only mode (`SCRIBE_LOCAL_ONLY=1` / `local_only` in config).** One switch runs everything at $0: forces local transcription (never the paid API, even on fallback) and routes notes/jokes/meme-concepts to local Ollama. It refuses cloud image generation cleanly (memes have no local backend) and, on failure, fails with guidance instead of silently reaching for a paid API.
- **Cross-machine backend nudges.** On Apple Silicon or AMD/Intel machines that fall back to the CPU floor, the readiness check now points you at the faster local engine for your hardware (`scribe[mlx]` for Metal, `scribe[whispercpp]` for Vulkan/ROCm).
- Per-run opt-in flags for the paid AI extras: `--notes/--no-notes`, `--joke/--no-joke`, and `--meme/--no-meme` on `transcribe`, `url`, `record`, and `batch`. They are idiomatic tri-state toggles - the bare flag forces the feature on for that one run, the `--no-` form forces it off, and omitting both falls back to your config default - so you can say `scribe meeting.mp4 --notes --meme` without changing config. `record` gains `--notes/--no-notes` it never had. The legacy `--no-*` flags keep working unchanged.
- Run the resident tray at login: `scribe tray --startup install|remove|status`, plus a "Start at login" toggle in the tray menu. Per-OS and user-scoped (Windows Startup-folder shortcut launched minimized, macOS LaunchAgent, Linux XDG autostart); never enabled silently.
- The tray menu now shows the current hotkeys ("Dictate (tap): F9", "Read (tap): F8") and lets you change either one live from a submenu (F6-F12); the choice is applied immediately and saved to config. Removed the "Read selection now" menu item, which couldn't reliably capture a selection because opening the menu steals focus from your app (use the read hotkey instead).
- Read-aloud speed control: set a playback speed multiplier (0.5-2.0x) via `scribe say --speed 1.2`, `scribe tray --speed 1.2`, a `tts_speed` value in `[voice.tray]` config, or a live "Read speed" submenu in the tray icon. Kokoro applies it natively; the system voice scales its words-per-minute.
- Tap-to-toggle dictation and read-aloud as the new default for `scribe tray` and `scribe listen`: tap F9 to start dictation and tap again to insert; tap F8 to read the selection and tap again to stop. This matches Windows Voice Access and macOS dictation / Speak Selection. Push-to-talk is still available via `scribe tray --activation hold` / `scribe listen --mode hold`.
- High-quality local neural read-aloud via Kokoro (82M, ONNX, CPU-capable) behind the optional `scribe[kokoro]` extra. Read-aloud is adaptive: it uses Kokoro when installed and its voice files are present, otherwise the pyttsx3 system voice. `scribe say`, the tray, and `scribe tray --check` all honor the configured backend and voice.
- `scribe tray --setup` (and an optional step in `scribe init`) pre-downloads the dictation model and sets up a read-aloud voice with a progress bar, so the first dictation/read no longer triggers a surprise multi-gigabyte download. Defensive throughout: missing packages, no network, and partial files degrade gracefully.
- `scribe tray --check` now reports the resolved read-aloud backend/voice, and warns about macOS Input Monitoring / Microphone permissions and Linux Wayland global-hotkey limitations.

### Changed
- **Cost-safety: paid AI extras now default to off.** Automatic meeting **notes** (`enable_notes`), **jokes** (`enable_joke`), and **memes** (`enable_meme`) are disabled by default, so a plain `scribe meeting.mp4` only transcribes and never spends on an API unprompted. Memes were the biggest risk - they call a paid *image* API (xAI Grok Imagine / OpenAI gpt-image-1) through a multi-attempt QA loop. Enable any of them via `scribe init`, `SCRIBE_ENABLE_NOTES/JOKE/MEME=true`, or `~/.scribe/config.toml`, or generate one on demand with `scribe notes|joke|meme <transcript>`. The `scribe init` wizard now also defaults these prompts to "no".
- **$0-first transcription.** `--method auto` now always transcribes locally - GPU when present, CPU int8 as the universal floor - so it **never silently spends on the paid API**, even on a machine with no GPU and an API key set. The paid OpenAI API is now an explicit opt-in (`--method openai`). This supersedes the earlier "warn then bill" fallback.
- Read-aloud is now much snappier: the Kokoro model is cached (loaded once, ~0ms on later reads instead of a ~2s reload every time) and warmed at tray startup, so the first read is fast too.
- The resident tray now runs a listener watchdog that recreates the global hotkey listener if its thread ever dies (Windows can silently remove a low-level keyboard hook), so the hotkeys stay live across an all-day session. On Windows the process also sets an explicit AppUserModelID so notifications and the taskbar show "Scribe Voice" instead of "Python".
- Voice dictation models are now latency-first. On a 12GB+ GPU the `balanced` profile uses `small` (fast to load, commonly cached) instead of `medium`, and `accurate` uses `large-v3-turbo` (~6GB, ~8x faster than large-v3 at near-equal accuracy) instead of `large-v3`. Short-utterance dictation cares about release-to-text latency, not batch throughput.
- The resident tray now warms the STT model at startup by default (opt out with `scribe tray --no-preload`) and shows a live "Loading voice model... Ns" indicator, only declaring the hotkeys ready once the model is actually warm. Previously it printed the "tap F9/F8" hint before loading finished, so the first dictation stalled.
- `scribe listen` now prints clear `recording` / `transcribing` / `(no speech detected)` feedback so a dictation attempt is never silent.

### Added / Changed (QOL & polish for setup)
- `scribe init` now includes a review panel before commit, confirmation, post-save verification (including real OBS preflight), immediate next steps, and optional Quick Record launcher creation. Non-interactive runs write safe defaults instead of hanging.
- `scribe doctor` now offers to launch `init --force` on failures for self-healing.
- `scribe shortcut` (and the .lnk it produces) is more robust for taskbar: targets cmd.exe with title/env/||pause for reliable icon + console persistence; adaptive wrapper still generated; clear taskbar icon troubleshooting in output and docs. Creation always prefers stable PATH resolution.
- Updated documentation across README, TROUBLESHOOTING, DEVELOPMENT, DEPLOYMENT etc. to match the defensive/adaptive launcher and polished init experience.

### Fixed
- Hardened the resident voice service against a batch of concurrency and read-aloud bugs found in an adversarial review: a deadlock when pausing mid-recording (the state lock was held across audio-stream teardown, which the audio callback also needs); `stop()` not joining its worker/dispatcher threads, so a transcription/injection could run after stop; a stale finish clobbering an error state back to idle; the read hotkey giving no feedback when busy. Pausing mid-recording now discards the partial capture instead of injecting it. The audio callback was also made minimal (larger blocks, no per-frame lock) to reduce the chance of starving the global keyboard hook.
- Read-aloud: tapping the read hotkey to stop now reliably stops the current sentence (it no longer let the in-flight chunk finish), and a runtime Kokoro synth/playback failure falls back to the system voice for that read instead of permanently breaking read-aloud.
- Voice setup: a download truncated by a dropped connection is now rejected (byte count is verified against Content-Length) instead of being promoted to a "ready" but corrupt model file; and a malformed `[voice]` config entry no longer silently prevents the voice settings from being saved.
- Dictation could be silently dropped when the Windows clipboard was momentarily held by another process (`OpenClipboard` failures, common right after copying). Clipboard reads/writes now retry transient failures, and paste-injection falls back to typing the text if the clipboard stays wedged, so a dictation is never lost. Tray action feedback is also echoed to the console when the tray is launched from a terminal.
- Resident tray hotkeys went dead after the first dictation: opening the microphone inside the global keyboard-hook callback breaks subsequent key capture on Windows, so after one F9 the tray was stuck in "recording" and F8/F9 stopped responding. Hotkey actions now run on a dedicated dispatcher thread (the hook callback only enqueues and returns instantly), with a synchronous intent flag so rapid taps still toggle correctly. This is what made "tap F9 / F8, nothing happens".
- The tray gave no feedback for hotkey actions once it detached from the console, so a started recording, an empty result, or a microphone error all looked like nothing happened. The tray now shows desktop notifications (and the terminal/`--no-tray` mode prints) for "Recording…", the inserted text, "No speech detected", the text being read, and errors.
- `scribe listen` paste injection used Ctrl+V unconditionally, so the default paste mode inserted nothing on macOS (which pastes with Cmd+V). The clipboard modifier is now resolved per-OS through a single shared helper used by the CLI dictation, selection-copy, and tray paths.
- Resident voice: with `--preload`, a dictation finished while the model was still loading was silently dropped and left the service stuck in the "recording" state (the model load occupied the single worker slot). Preloading now runs on its own thread behind a load lock, and a dictation that cannot start its worker resets to idle instead of hanging.
- Read-aloud: an unknown or typo'd voice id (or a system-voice name passed to `--voice` while Kokoro is active) raised mid-playback and could crash `scribe say`; the voice id is now validated up front and falls back to a known-good voice, and `scribe say` reports synth errors instead of crashing.
- The `scribe[kokoro]` extra now includes `sounddevice` (needed to play the synthesized audio), so installing it without `scribe[voice]`/`[tray]` no longer fails at playback time.

---

## 2.7.0 - 2026-06-20

### Added
- Resident tray utility prototype: `scribe tray` adds a background tray process for push-to-hold dictation and selection read-aloud, behind the optional `scribe[tray]` extra.
- `scribe rec --check` and `scribe record --check` run a read-only OBS WebSocket preflight and exit without starting, stopping, or restarting OBS.
- `scribe init --force` can now persist OBS WebSocket settings, and `scribe doctor` includes OBS WebSocket configuration checks.
- Agentic balance and voice tray planning docs that state the prototype boundaries and the rule-vs-judgment design line.
- `scribe transcribe --method openai` with no API key now fails fast with a clear hint instead of erroring deep in the run.
- `scribe --version` / `-V` prints the version and exits.
- `scribe info` now shows the config file path (and whether it exists) plus which AI features (notes/joke/meme) are enabled.
- `scribe transcribe -o/--output-dir DIR` writes output to a chosen folder for that run.

### Fixed
- Quick Record now refuses to restart or kill OBS when OBS is already running or a recording mux appears active, and the preflight reports authentication, port, and mux-state details more clearly.
- Voice selection read-aloud no longer reads stale clipboard content when there is no active selection or copy access fails; clipboard state is restored on setup and paste failures.
- Tray startup and shutdown now handle hotkey/listener failures defensively and stop partially initialized services.
- Malformed config file sections are ignored rather than crashing config flattening or saving.
- Optional Pillow imports in the meme compositor remain optional while satisfying strict type checking.
- Clickable output-file links now percent-encode the path, so a transcript written to a folder whose name contains spaces (or characters like `#`/`?`) opens correctly when clicked in the terminal instead of producing a broken or non-clickable link. A single `file_uri` helper (built on `Path.as_uri()`) now backs every link on Windows, macOS, and Linux, replacing six slightly different hand-rolled versions.
- The joke's comedy-archetype selection used a 50-token budget on the legacy chat-completions path; reasoning models spend that entirely on hidden reasoning and return empty content, so the step always logged `invalid archetype ''` and fell back to the heuristic. Selection now uses the configured model on the Responses API with minimal reasoning effort and an adequate output budget, and the provider path gets the same headroom.
- A third QA pass over the previously-unreviewed setup/config/diagnostics code fixed:
  - The setup wizard hardcoded `notes_provider=openai`, so an xAI-only setup hit "No API key found for openai" when generating notes; it now uses the vendor you actually configured.
  - The support bundle leaked your home directory, working directory, and PATH (and therefore your username) despite claiming to sanitize; those are now redacted, and generating a bundle no longer makes live API network calls (`scribe doctor` still does).
  - `scribe doctor` no longer aborts the whole run if a single check raises an unexpected error; each check is isolated.
  - `normalize_path` strips only a balanced pair of surrounding quotes, so a path that legitimately contains a quote is not corrupted; `get_ffmpeg_path`/`get_ffprobe_path` only accept an executable file, not a directory or stub.
  - Filename date parsing validates the `YYYY-MM-DD` form (an impossible date is rejected, not echoed), and duration formatting clamps negative input.
  - `scribe music` no longer leaks a per-track temp slice directory on error/instrumental paths (cleaned in a finally on every outcome); the Gemini key check in `scribe doctor` has a network timeout; and `python-docx` is imported lazily so plain-text transcript loading does not depend on it.
- A second adversarial QA pass over the older core (recorder/OBS, audio conversion, providers, notes/joke/meme, music) fixed:
  - OBS process cleanup matched processes by substring (`pkill -f obs`), which could kill unrelated apps like obsidian or any process with "obs" in its command line; it now matches the exact process name, and the MKV-to-MP4 remux has a timeout so a locked file cannot hang the CLI.
  - Near-silent or instrumental audio made ffmpeg report `-inf` loudness, which then failed the conversion; Scribe now falls back to default normalization in that case.
  - Local Ollama notes on long transcripts silently dropped most of each chunk because the chunk size assumed a huge cloud context; the chunk budget is now sized to the provider's context window.
  - Vocal separation was hardcoded to CUDA and silently skipped on CPU-only machines; it now auto-detects the device so the CPU path actually runs.
  - Audio slicing now clamps to the real audio length and skips empty or reversed spans instead of writing zero-frame files; meme generation no longer permanently lowers the spice level of a run after a safety block; the bake-off judge's winner index is bounds-checked; the OpenAI provider raises a clean error instead of crashing on an empty response; and a music BPM probe no longer throws on newer librosa.
  - The notes JSON debug dump is now opt-in (`SCRIBE_DEBUG_JSON`) and written to the temp dir instead of the working directory.
- A missing-ffmpeg error now prints the platform-specific install command and points to `scribe doctor`.

### Security
- Raised dependency floors for `pydantic-settings` and `msgpack` to clear current security advisories in the locked environment.
- Hardening from an adversarial security review (no critical issues were found; these are defense-in-depth):
  - `scribe url` now refuses loopback and internal addresses (localhost, 127.0.0.1, RFC1918, link-local, and the cloud metadata endpoint) and URLs with embedded credentials, to prevent SSRF if a link ever comes from an untrusted source. Set `SCRIBE_ALLOW_LOCAL_URLS=1` to allow a local media server.
  - `--cookies` accepts only a known browser keyword and warns that it reads that browser's cookie jar.
  - Named glossaries (`--vocab <name>`) are confined to a safe token, glossary files are size-capped, and one-character aliases are dropped, so a hostile or oversized glossary cannot read outside the glossary directory or stall normalization.
  - The transcript model rejects non-finite (NaN/inf) timings that could otherwise crash the SRT/VTT writers; `scribe query` skips oversized JSON; `sanitize_meeting_name` handles Windows reserved device names and trailing dots.
  - `silence_remover` and `doctor` invoke ffmpeg by resolved absolute path (matching the converter) to avoid PATH hijack; `~/.scribe` and its files are created owner-only on POSIX.
  - Voice dictation restores your clipboard on exit instead of clobbering it, shows a clear "DICTATION LIVE" indicator, and warns against dictating near terminals or password fields.
  - Provider failover is now surfaced at the console so you can see when a request is sent to a different cloud provider than you selected.

### Added
- Voice I/O v2: `scribe listen` now defaults to push-to-talk (hold F9, speak, release to insert) with `--mode continuous` for always-listening, and `--inject paste|type` to choose clipboard-paste or direct keystrokes. `scribe say` can now read the current selection (`--selection`) or the clipboard (`--clipboard`), not just a file, and Esc stops playback. Patterns drawn from established voice-typing and macOS Speak-Selection tools; push-to-talk also removes the always-on-microphone exposure flagged in the security review.
- Responsible-use guardrails: a one-time recording-consent notice on the first `record`/`rec` run (recording laws vary; some places require all-party consent), a `docs/RESPONSIBLE_USE.md` guide and README "Responsible Use and Legal" section covering regulated/sensitive data, cloud data-sharing, output accuracy, and the no-warranty terms. The consent prompt is interactive-only and shown once; non-interactive runs print a one-line reminder, and `SCRIBE_ASSUME_CONSENT=1` silences it. None of this is legal advice.
- Domain glossaries for recurring jargon (finance, tech, and your own). Use a named glossary with `--vocab finance` (or any `.txt`/`.json` path) on `transcribe`/`url`/`batch`; `scribe vocab` lists and shows them. Glossaries do two things: bias recognition toward your terms (now trimmed to fit Whisper's prompt budget with a warning instead of being silently truncated), and deterministically rewrite known misrecognitions to the canonical form after transcription (alias syntax `Canonical = variant1, variant2` in `.txt`, or `{"terms": [...], "aliases": {...}}` in JSON). Starter `finance` and `tech` presets ship with Scribe; add your own under `~/.scribe/vocab/`.

### Fixed
- `batch` and `record` now write the structured JSON/VTT/SRT/Markdown sidecars too, so `scribe query` can find everything you transcribe, not just single-file `transcribe`/`url` runs.
- `scribe url` gained `--format` and `--diarize/--no-diarize`, matching `transcribe`.
- Local CPU transcriptions are now labeled `faster-whisper-<model>` in session metadata instead of `cpu-<model>` (the CPU floor is faster-whisper on CPU).
- `Transcriber.last_transcript` is reset at the start of each call, so a structured sidecar can never carry over a previous file's transcript.
- `scribe query`: speaker filter is now case-insensitive substring (like text search), a malformed `start` value no longer crashes the whole search, and a non-positive `--limit` returns all matches.
- Markdown frontmatter quotes values that begin with a YAML indicator character, so a speaker label like `*VIP` keeps the frontmatter valid.
- Local diarization no longer double-counts overlapping same-speaker turns when assigning a segment's speaker.
- Non-CUDA backends (mlx-whisper, whisper.cpp) now report the real audio duration and emit the same long-silence markers as the faster-whisper path.
- Voice dictation: the final in-progress utterance is flushed on quit instead of being dropped, the utterance audio no longer includes a trailing silence frame, CRLF transcript/notes files read aloud correctly, and paused audio is cleared instead of prepended to the next utterance.
- The bare-filename shortcut (`scribe meeting.mp4`) derives its known-command list from the registered commands, so it stays correct as commands are added.

## 2.6.0 - 2026-06-01

### Added
- Shared `Transcript` domain model (segments, speakers, confidence, provenance) produced by the local and API transcription paths, so structured data is no longer discarded after writing the `.txt`.
- Structured output: every transcription writes a machine-readable JSON transcript next to the `.txt` by default, with optional WebVTT, SRT, and Markdown (YAML frontmatter) via `--format` or the `SCRIBE_OUTPUT_FORMATS` setting.
- `scribe query`: keyword and speaker search across your stored JSON transcripts ("find a moment across past meetings").
- Hardware-adaptive local backends: local transcription now picks the engine that fits the machine instead of being CUDA-only. NVIDIA and CPU stay on faster-whisper (unchanged), Apple Silicon can use mlx-whisper (Metal) via `pip install "scribe[mlx]"`, and AMD/Intel/Apple can use whisper.cpp via `pip install "scribe[whispercpp]"`. Selection is automatic by detected vendor, overridable with `SCRIBE_LOCAL_BACKEND` or `local_backend` in config, and always falls back to a working CPU path. `scribe info` reports the detected vendor, the selected backend, and which optional engines are installed.
- Local speaker diarization: local transcription can now label "who said what" on-device with pyannote.audio, populating the same speaker field the cloud path uses, so the `.txt` and the JSON/VTT/SRT/Markdown outputs all show speakers. Opt in with `--diarize` (or `enable_speaker_diarization` in config); it needs an `HF_TOKEN` and the `scribe[diarize]` extra, and degrades to unlabeled output when either is missing.
- Voice I/O mode: `scribe listen` dictates speech into the focused window (F9 toggles, Esc quits) and `scribe say` reads a transcript or notes file aloud with an offline local voice. A deliberate opt-in real-time mode separate from the batch pipeline, behind the `scribe[voice]` extra (sounddevice, pynput, pyperclip, pyttsx3).

### Engineering
- Dependency-preference policy (ADR-009): pure-Python by default, with heavy or platform-specific dependencies isolated in optional extras (`mlx`, `whispercpp`, `diarize`, `voice`, `whisperx`) so the base install stays lean and cross-platform.
- Advisory mutation-testing CI job (`mutmut`) over the pure, property-tested core (transcript model, backend selection, diarization alignment, voice endpointing, output writers). Non-blocking and outside the CI gate aggregator; a surviving mutant flags a missing test rather than failing the build.
- Hardware and live-I/O glue that cannot run in CI is marked `pragma: no cover` with a stated reason instead of being padded with fake tests; the 80% line-coverage gate stays honest with a documented path toward 90%.

## 2.5.0 - 2026-06-01

### Added
- Cross-platform "Quick Record" launcher: `scribe shortcut` installs a native, icon-bearing launcher into the OS application menu (a Windows Start Menu shortcut, a macOS `.app` bundle, a Linux `.desktop` entry) that runs `scribe rec`, with `--desktop` and `--remove`. It replaces the hand-made Windows batch file.
- Scribe application icon, a terminal prompt with a soundwave cursor, bundled as `.ico`, `.icns`, and `.png` and applied to the launchers.
- `python -m scribe` entry point.
- Documented global install via `uv tool install`, so `scribe` runs from any directory on Windows, macOS, and Linux.
- URL transcription command (`scribe url`) supporting YouTube, Vimeo, X/Twitter, direct links, and 1000+ sites via yt-dlp.
- Browser cookie support for yt-dlp downloads (`--cookies edge|chrome|firefox`).
- First-run configuration wizard (`scribe init`) that writes `~/.scribe/config.toml`.
- Animated gradient banner on help screen and via `scribe --banner`.
- Terminal UI controls: `SCRIBE_ANIMATIONS`, `SCRIBE_COLOR`, `SCRIBE_FPS`.
- `scribe info` UI diagnostics for resolved mode, FPS, and terminal capabilities.
- yt-dlp availability check in `scribe doctor`.
- Optional shimmer and gradient branding effects in full animation mode.

### Changed
- OBS recording lifecycle completely overhauled for self-healing: stale process cleanup, crash sentinel removal, safe-mode bypass, WebSocket auto-reconnect, deadman timers, better error messages, and verification at every step.
- Default models updated: OpenAI to GPT-5.5 for notes/joke/meme; xAI to Grok 4.3 (retired older IDs ahead of 2026-05-15 cutoff).
- Progress bars now cap at 99% until actual completion.
- `.env` discovery now walks up to project root for editable installs.
- Transcript input for `notes`, `joke`, and `meme` now accepts `.txt`, `.md`, and `.docx`.
- Cleaner CLI branding and panel headers across commands.
- Recorder now works correctly on macOS and Linux: the OBS configuration directory is resolved per platform (fixing the macOS path used for safe-mode handling), and OBS is launched via `open` on macOS.
- The CLI starts cleanly: connection retries the recorder already recovers from no longer print obsws-python tracebacks, and pydub's first-import warnings are suppressed.

### Fixed
- OBS "not ready" (code 207) errors with proper retry and backoff.
- CI pipeline (ruff, mypy --strict, test matrix, coverage 80%+ gate, blocking pip-audit) now passes cleanly on 3.12/3.13 after consolidating config, adding pragmatic per-file ignores for hardware graceful-degradation paths (ADR-002), updating outdated test expectations for current model defaults, and excluding optional Pillow-dependent tests from the basic matrix.
- Lightweight "Tests (Python X)" matrix jobs no longer incorrectly inherit the coverage gate (removed --cov* from global pytest addopts; the dedicated coverage job passes the flags explicitly).
- GitHub Actions now syncs each job with its explicit Python version so the 3.13 matrix leg no longer silently reuses `.python-version`.
- `TestConfigDefaults.test_config_defaults` is now hermetic (patches user config file loader) and passes on clean CI runners regardless of dev-machine ~/.scribe/config.toml contents.
- Windows input handling for stop/quit commands during recording.
- OBS WebSocket client cleanup, reconnect logic, and auth mismatch detection.
- Download temp file leaks on transcription failure (now cleaned in `finally`).
- Various runtime bugs, undefined variables, missing f-string placeholders, and unused imports.
- Test isolation issues (mocks, environment variables, Rich display conflicts).
- `default_method` from `SCRIBE_DEFAULT_METHOD` or `config.toml` is now honored when no `--method` flag is given; it was previously ignored.
- The setup wizard's AI vendor choice in `config.toml [providers]` is now used for provider selection; it was written but never read.
- Language validation resolves non-ASCII native language names to their ISO code instead of returning them unchanged.
- Filename date parsing rejects unrelated digit runs and impossible dates instead of producing a bogus date.
- OpenAI transcription fails fast on an invalid API key instead of retrying through the full backoff for every chunk.
- The cleanup summary reports the real space freed instead of always reporting 0.0 MB.
- The Anthropic provider no longer sends a null temperature (which the API rejects) on the structured-output path.
- Requesting JSON output alongside an image no longer raises a TypeError.
- Sub-minute durations render in seconds (for example `45s`) instead of `0m`.
- The `batch` and `music` error handlers no longer raise `UnboundLocalError` (masking the real error) when a file fails before its per-file logger is set up.
- A successful MKV to MP4 remux now removes the source MKV instead of leaving a full-size duplicate in the recording folder.
- Map-reduce notes segmentation actually overlaps its chunks now; the overlap was a no-op, so context could be lost at every chunk boundary.
- `convert_to_mp3` no longer returns an already-`.mp3` input unconverted (which skipped loudness normalization, 16k, and mono).
- Vocal-activity segment merging no longer truncates a segment when a later, padded segment ends earlier than the running one.
- The joke retry loop no longer sleeps after its final attempt.
- The notes judge accepts an integer candidate index returned as a float (for example `1.0`) instead of silently dropping that score.

### Engineering
- 1,143 tests collected with strong coverage of error paths.
- Added focused config-file and first-run wizard tests, raising the CI coverage baseline above 80%.
- Significant code quality cleanup (40+ unused symbols removed, multiple bug fixes).
- **Step 4 (Error Handling / Security / Observability)**: Full diagnostic sweep of broad `except Exception`, bare `pass`/`continue`, `print()`, and subprocess usage across `src/`. One minor silent `pass` in OBS cleanup tightened with structured log. All other broad handling classified as intentional graceful degradation for hardware variability (OBS, GPU, providers, ffmpeg) and documented with module comments. Verified zero `shell=True`; all subprocess calls use explicit argument lists. Doctor + support bundle already perform safe partial redaction of API keys. Created four ADRs (Python 3.12 baseline with 3.14 gate; exception taxonomy + graceful degradation rationale; Ruff confusable allowance for readability in a language/humor tool; dependency vulnerability audit policy). Ruff S-bandit survivors (55) accepted as inherent to a local desktop tool that must launch external processes. Dependency vulnerability scanning is now blocking in CI with an explicit torch advisory ignore policy while upstream CUDA wheel compatibility is monitored.

---

## 2.4.3 - 2026-05

### Fixed
- OBS "not ready" error (code 207) during startup with improved retry logic.
- Windows stop command handling (stop, q, quit, etc.) during active recording.
- OBS WebSocket client cleanup and retry behavior.

### Changed
- Better error handling and actionable messages for OBS connection issues.

---

## 2.4.2 - 2026-04

### Added
- Smart `.env` loading that works from any directory (project root, home, or package location).

### Fixed
- Undefined `ValidationError` reference.
- Unnecessary warnings in normal operation.

### Changed
- Upgraded ctranslate2 to 4.6.3.

---

## 2.4.1 - 2026-03

### Added
- 46 new OBS recorder tests covering error paths and edge cases.

### Changed
- Enhanced WebSocket connection handling with graceful hostname validation.
- Improved host fallback and IPv4 prioritization for OBS.

---

## 2.4.0 - 2026-02

### Added
- Professional recording UI with consistent text indicators (DONE, ERROR, WARNING).
- Performance tracker outlier detection for better time estimates.

---

## 2.3.1 - 2025-12

### Added
- Gemini 3 Pro integration with 1M token context.
- Joke bake-off mode (all providers compete for best output).

---

## 2.3.0 - 2025-11

### Added
- Production-grade music/lyrics transcription.
- Vocal separation using Hybrid Transformer Demucs.
- Segment-based transcription with Silero VAD timestamps.
- Hallucination filtering for music output.
- Support for 99 languages in music mode.

---

## 2.2.x - 2025

### Added
- Multi-provider AI abstraction (OpenAI, xAI/Grok, Anthropic, Gemini).
- Provider health checks and fallback chains.

---

## 2.1.x - 2025

### Added
- Formal provider abstraction layer.
- Structured configuration and settings management.

---

## 2.0.x - 2025

### Added
- GPU-accelerated local transcription via faster-whisper.
- Automatic method selection (local vs API) based on hardware.
- Core CLI command structure with Typer and Rich output.

---
