# Scribe Roadmap

**Philosophy:** Reliability over feature count. Releases prioritize predictable behavior, clearer output, and maintainable code.

---

## Current Version: 2.4.3

**Focus: OBS Recording Reliability + Code Quality**

- **OBS Not Ready Fix**: Fixed error code 207 when OBS is starting up - now properly retries connection with backoff
- **Windows Input Fix**: Fixed stop commands (stop, q, quit, s, exit) not working during recording on Windows - now uses native keyboard input
- **Better Error Handling**: Improved client cleanup and retry logic for OBS WebSocket connections
- **Code Quality**: Fixed 2 runtime bugs (undefined variables), cleaned up 40+ unused imports/variables, fixed f-strings missing placeholders
- **Test Fixes**: Fixed 8 failing tests (mock paths, Rich display conflicts, environment variable isolation)
- **New Tests**: Added 2 new tests for OBS "not ready" scenario

---

## Unreleased (Current Workspace)

**Focus: URL Transcription + Cross-Platform CLI UX Controls**

- **URL Transcription**: New `scribe url <link>` command for downloading and transcribing from YouTube, Vimeo, Twitter/X, direct media links, and 1000+ sites via yt-dlp
  - Audio-only download by default (saves bandwidth)
  - Progress tracking, size/duration limits, automatic cleanup
  - Configurable via `SCRIBE_DOWNLOAD_TIMEOUT`, `SCRIBE_KEEP_DOWNLOADS`, `SCRIBE_DOWNLOAD_FOLDER`
- Added terminal UI controls: `SCRIBE_ANIMATIONS`, `SCRIBE_COLOR`, `SCRIBE_FPS`
- Added optional shimmer status effect in `full` mode with capability fallback
- Added optional gradient branding for command headers in `full` mode
- Added UI diagnostics output in `scribe info`
- Added tests for terminal UI config, shimmer, spinner, and branding helpers

---

## Recent Releases

### v2.4.2 - Code Quality + Bug Fixes

- Smart .env loading from any directory
- Cleaner output, removed unnecessary warnings
- Fixed undefined ValidationError
- Upgraded ctranslate2 to 4.6.3

### v2.4.1 - OBS Recording Reliability

- Enhanced WebSocket connection with graceful hostname validation error suppression
- IPv4 prioritization, improved host fallback strategies
- 46 new OBS recorder tests covering all error paths

### v2.4.0 - User Experience Polish

- Cleaner recording UI with professional formatting
- Text-based indicators (DONE, ERROR, WARNING) for consistency
- Performance tracker outlier detection for better time estimates

### v2.3.1 - Gemini 3 + Joke Bake-off

- Gemini 3 Pro integration with 1M token context
- Joke bake-off mode where all providers compete

### v2.3.0 - Production-Grade Music Transcription

- Segment-based transcription with VAD timestamps
- Complete lyrics capture (no missing verses)
- Hallucination filtering
- Separation-first architecture with Hybrid Transformer Demucs
- 99 language support

---

## Version History

| Version | Focus | Status |
|---------|-------|--------|
| 2.4.3 | OBS Recording Reliability | Current |
| 2.4.2 | Code Quality + Bug Fixes | Production |
| 2.4.1 | OBS Reliability | Production |
| 2.4.0 | UX Polish | Production |
| 2.3.1 | Gemini + Bake-off | Production |
| 2.3.0 | Music Transcription | Production |
| 2.2.x | Multi-Provider | Production |
| 2.1.x | Provider Abstraction | Production |
| 2.0.x | GPU Acceleration | Production |

---

## Design Principles

### Quality Over Speed

- Uses Whisper large-v3 by default for strong accuracy
- Audio normalization is enabled for consistency
- Faster models remain available when speed is preferred

### Defensive by Design

- All external inputs validated
- Atomic file operations prevent corruption
- Comprehensive error handling with automatic fallback

### Clean Code

- Ongoing cleanup of unused variables/imports
- 2 intentional pyflakes warnings (re-exports in providers/__init__.py)
- Functions focused and testable
- Test suite is run continuously during development

---

## Scope

### What Scribe Does Well

- GPU-accelerated transcription (11x real-time on RTX 4090)
- Multi-provider AI support (OpenAI, XAI/Grok, Anthropic, Gemini)
- OBS recording integration
- Music transcription with vocal separation
- Meeting notes, jokes, and memes
- Batch processing and custom vocabulary

### Intentionally Excluded

- Multi-user/enterprise features (local-first tool)
- Web UI (CLI-first design)
- Real-time transcription (batch is simpler and more reliable)
- Cloud storage sync (users control their data)

---

**Last Updated:** 2026-02-14
