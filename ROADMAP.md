# Scribe Roadmap

**Philosophy:** Excellence over features. Every release focuses on making existing functionality more reliable, more polished, and more delightful to use.

---

## Current Version: 2.4.2

**Focus: Code Quality + Bug Fixes**

- **Smart .env Loading**: Works from any directory - finds .env in current, home, or package directory
- **Cleaner Output**: Removed unnecessary warnings and tip messages
- **Bug Fixes**: Fixed undefined ValidationError, removed all unused variables and imports
- **Dependency Update**: Upgraded ctranslate2 to 4.6.3 (fixes pkg_resources deprecation warning)
- **Code Quality**: Zero pyflakes errors across all core modules

---

## Recent Releases

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
| 2.4.2 | Code Quality + Bug Fixes | ✅ Current |
| 2.4.1 | OBS Reliability | ✅ Production |
| 2.4.0 | UX Polish | ✅ Production |
| 2.3.1 | Gemini + Bake-off | ✅ Production |
| 2.3.0 | Music Transcription | ✅ Production |
| 2.2.x | Multi-Provider | ✅ Production |
| 2.1.x | Provider Abstraction | ✅ Production |
| 2.0.x | GPU Acceleration | ✅ Production |

---

## Design Principles

### Quality Over Speed

- Uses Whisper large-v3 (best accuracy available)
- Professional-grade audio normalization
- Could use faster models, but accuracy is non-negotiable

### Defensive by Design

- All external inputs validated
- Atomic file operations prevent corruption
- Comprehensive error handling with automatic fallback

### Clean Code

- Zero unused variables or imports
- Zero pyflakes errors
- Functions focused and testable

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

**Last Updated:** 2026-01-08
