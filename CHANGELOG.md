# Changelog

All notable changes to Scribe are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
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

### Fixed
- OBS "not ready" (code 207) errors with proper retry and backoff.
- Windows input handling for stop/quit commands during recording.
- OBS WebSocket client cleanup, reconnect logic, and auth mismatch detection.
- Download temp file leaks on transcription failure (now cleaned in `finally`).
- Various runtime bugs, undefined variables, missing f-string placeholders, and unused imports.
- Test isolation issues (mocks, environment variables, Rich display conflicts).

### Engineering
- 1,143 tests collected with strong coverage of error paths.
- Significant code quality cleanup (40+ unused symbols removed, multiple bug fixes).
- **Step 4 (Error Handling / Security / Observability)**: Full diagnostic sweep of broad `except Exception`, bare `pass`/`continue`, `print()`, and subprocess usage across `src/`. One minor silent `pass` in OBS cleanup tightened with structured log. All other broad handling classified as intentional graceful degradation for hardware variability (OBS, GPU, providers, ffmpeg) and documented with module comments. Verified zero `shell=True`; all subprocess calls use explicit argument lists. Doctor + support bundle already perform safe partial redaction of API keys. Created first three ADRs (Python 3.12 baseline with 3.14 gate; exception taxonomy + graceful degradation rationale; Ruff confusable allowance for readability in a language/humor tool). Ruff S-bandit survivors (55) accepted as inherent to a local desktop tool that must launch external processes; no functionality removed.

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

[2.4.3]: https://github.com/blisspixel/scribe/releases/tag/v2.4.3
[2.4.2]: https://github.com/blisspixel/scribe/releases/tag/v2.4.2
[2.4.1]: https://github.com/blisspixel/scribe/releases/tag/v2.4.1
[2.4.0]: https://github.com/blisspixel/scribe/releases/tag/v2.4.0
[2.3.1]: https://github.com/blisspixel/scribe/releases/tag/v2.3.1
[2.3.0]: https://github.com/blisspixel/scribe/releases/tag/v2.3.0
