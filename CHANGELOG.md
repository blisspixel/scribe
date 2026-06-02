# Changelog

All notable changes to Scribe are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Security
- Hardening from an adversarial security review (no critical issues were found; these are defense-in-depth):
  - `scribe url` now refuses loopback and internal addresses (localhost, 127.0.0.1, RFC1918, link-local, and the cloud metadata endpoint) and URLs with embedded credentials, to prevent SSRF if a link ever comes from an untrusted source. Set `SCRIBE_ALLOW_LOCAL_URLS=1` to allow a local media server.
  - `--cookies` accepts only a known browser keyword and warns that it reads that browser's cookie jar.
  - Named glossaries (`--vocab <name>`) are confined to a safe token, glossary files are size-capped, and one-character aliases are dropped, so a hostile or oversized glossary cannot read outside the glossary directory or stall normalization.
  - The transcript model rejects non-finite (NaN/inf) timings that could otherwise crash the SRT/VTT writers; `scribe query` skips oversized JSON; `sanitize_meeting_name` handles Windows reserved device names and trailing dots.
  - `silence_remover` and `doctor` invoke ffmpeg by resolved absolute path (matching the converter) to avoid PATH hijack; `~/.scribe` and its files are created owner-only on POSIX.
  - Voice dictation restores your clipboard on exit instead of clobbering it, shows a clear "DICTATION LIVE" indicator, and warns against dictating near terminals or password fields.
  - Provider failover is now surfaced at the console so you can see when a request is sent to a different cloud provider than you selected.

### Added
- Responsible-use guardrails: a one-time recording-consent notice on the first `record`/`rec` run (recording laws vary; some places require all-party consent), a `DISCLAIMER.md` and README "Responsible Use and Legal" section covering regulated/sensitive data, cloud data-sharing, output accuracy, and the no-warranty terms. The consent prompt is interactive-only and shown once; non-interactive runs print a one-line reminder, and `SCRIBE_ASSUME_CONSENT=1` silences it. None of this is legal advice.
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

## [2.6.0] - 2026-06-01

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

## [2.5.0] - 2026-06-01

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

## [2.4.3] - 2026-05

### Fixed
- OBS "not ready" error (code 207) during startup with improved retry logic.
- Windows stop command handling (stop, q, quit, etc.) during active recording.
- OBS WebSocket client cleanup and retry behavior.

### Changed
- Better error handling and actionable messages for OBS connection issues.

---

## [2.4.2] - 2026-04

### Added
- Smart `.env` loading that works from any directory (project root, home, or package location).

### Fixed
- Undefined `ValidationError` reference.
- Unnecessary warnings in normal operation.

### Changed
- Upgraded ctranslate2 to 4.6.3.

---

## [2.4.1] - 2026-03

### Added
- 46 new OBS recorder tests covering error paths and edge cases.

### Changed
- Enhanced WebSocket connection handling with graceful hostname validation.
- Improved host fallback and IPv4 prioritization for OBS.

---

## [2.4.0] - 2026-02

### Added
- Professional recording UI with consistent text indicators (DONE, ERROR, WARNING).
- Performance tracker outlier detection for better time estimates.

---

## [2.3.1] - 2025-12

### Added
- Gemini 3 Pro integration with 1M token context.
- Joke bake-off mode (all providers compete for best output).

---

## [2.3.0] - 2025-11

### Added
- Production-grade music/lyrics transcription.
- Vocal separation using Hybrid Transformer Demucs.
- Segment-based transcription with Silero VAD timestamps.
- Hallucination filtering for music output.
- Support for 99 languages in music mode.

---

## [2.2.x] - 2025

### Added
- Multi-provider AI abstraction (OpenAI, xAI/Grok, Anthropic, Gemini).
- Provider health checks and fallback chains.

---

## [2.1.x] - 2025

### Added
- Formal provider abstraction layer.
- Structured configuration and settings management.

---

## [2.0.x] - 2025

### Added
- GPU-accelerated local transcription via faster-whisper.
- Automatic method selection (local vs API) based on hardware.
- Core CLI command structure with Typer and Rich output.

---

[2.6.0]: https://github.com/blisspixel/scribe/releases/tag/v2.6.0
[2.4.3]: https://github.com/blisspixel/scribe/releases/tag/v2.4.3
[2.4.2]: https://github.com/blisspixel/scribe/releases/tag/v2.4.2
[2.4.1]: https://github.com/blisspixel/scribe/releases/tag/v2.4.1
[2.4.0]: https://github.com/blisspixel/scribe/releases/tag/v2.4.0
[2.3.1]: https://github.com/blisspixel/scribe/releases/tag/v2.3.1
[2.3.0]: https://github.com/blisspixel/scribe/releases/tag/v2.3.0
