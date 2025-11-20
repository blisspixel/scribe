# Scribe Roadmap

This roadmap documents the evolution of Scribe from a basic transcription tool to a production-grade system focused on reliability, quality, and maintainability.

**Philosophy**: Feature-complete. The focus is making what exists work exceptionally well through defensive programming, comprehensive testing, and continuous refinement.

## Current Version: 2.4.1

**Latest: OBS Recording Reliability + Comprehensive Test Coverage**

This release addresses WebSocket connection issues in OBS recording and adds comprehensive test coverage for the recording system.

**What's New:**
- **OBS WebSocket Error Handling**: Hostname validation errors from the WebSocket library are now properly caught and suppressed
- **IPv4 Prioritization**: Connection attempts prioritize IPv4 addresses, only trying IPv6 if explicitly configured
- **Enhanced Connection Logic**: Better retry strategies, improved host fallback, cleaner error logging
- **Comprehensive Test Suite**: 46 new tests for OBS recorder covering WebSocket connection, hostname validation, recording lifecycle, file detection, error handling, thread safety, and edge cases
- **Test Count**: 642 tests total (up from 595), 100% pass rate
- **Code Quality**: Zero diagnostics maintained across entire codebase

**Technical Details:**
- Granular exception handling for `ValueError` with hostname validation pattern matching
- Debug-level logging for validation errors instead of stderr pollution
- Removed dead code and undefined variable references in CLI fallback mode
- Enhanced documentation explaining WebSocket library quirks and error handling strategies

**Status:** Production-ready - 642/642 tests passing, 100% clean code

---

## Version 2.4.0

**User Experience Polish + Code Quality**

- Cleaner recording UI with professional formatting
- Text-based indicators (DONE, ERROR, WARNING) for consistency
- JSON refinement warnings moved to debug level
- Performance tracker outlier detection for better time estimates
- Dead code removed, diagnostics verified

**Status:** Production-ready - 595/595 tests passing

---

## Version 2.3.1

**Gemini 3 Support + Joke Bake-off**

- **Gemini 3 Pro integration**: Advanced reasoning model with 1M token context
- **Joke bake-off**: All providers compete, Grok judges, best joke wins
- **Clean UX**: Bake-off runs silently, users get best result
- **Provider defaults updated**: Gemini 3 Pro for complex reasoning

**Status:** Production-ready - 595/595 tests passing

---

## Version 2.3.0

**Major Release: Production-Grade Music Transcription**

This release represents a fundamental architectural advancement in music transcription, implementing segment-based transcription for complete lyrics capture with aggressive hallucination filtering.

**Breakthrough Features:**
- **Segment-Based Transcription**: Slices vocals by VAD timestamps, transcribes each independently
- **Complete Lyrics Capture**: Gets full song lyrics from start to finish (no missing verses)
- **Hallucination Filtering**: Per-segment filtering removes "Thanks for watching", "Subscribe", etc.
- **Separation-First Architecture**: Hybrid Transformer Demucs isolates vocals before transcription
- **True Multi-Language**: Auto-detects and transcribes lyrics in 99 languages (Spanish, Portuguese, Japanese, etc.)
- **Intelligent Instrumental Detection**: Gracefully identifies tracks with no vocals (not treated as failures)
- **Measurable Metadata Only**: Shows Duration, BPM (if detected), Key (if detected) - no genre guessing
- **45s Processing**: Separation 25s + VAD 1s + slicing 1s + transcription 15s + filtering instant
- **Batch Processing**: Process entire music libraries efficiently

**Technical Improvements:**
- Audio slicing utility for segment-based transcription
- Hybrid Transformer Demucs (htdemucs) for vocal isolation
- Silero VAD v4/v5 for vocal segment detection (16-25 segments per song)
- Improved BPM detection with onset strength envelope
- Per-segment hallucination filtering (multilingual patterns)
- Automatic cleanup of intermediate files (slices, vocals, converted WAV)
- Clean, professional UX with progress indicators
- Instrumental tracks properly classified (not errors)

**Status:** Production-ready - 595/595 tests passing (100% pass rate)

---

## Completed (v2.0.0)

### Core Transcription
- GPU-accelerated local transcription with faster-whisper
- Automatic GPU detection and fallback to OpenAI API
- RTX 4090 optimization (11x real-time speed with large-v3)
- Model support: large-v3 (local, maximum accuracy), gpt-4o-transcribe-diarize (API)
- Professional audio preprocessing with dynaudnorm (~10x real-time)
- Server-side chunking for long audio files
- Speaker diarization via OpenAI API
- Multi-language support (ISO 639-1 codes)
- Quality-first approach: prioritizes accuracy over speed

### Intelligence Features
- GPT-5 meeting notes with multi-step reasoning
- Context-aware joke generation (10 comedy archetypes)
- Meme generation with QA loop and scoring
- Configurable humor intensity (0-10 spice levels)
- Structured analysis: Current State, Drivers, Blockers, Future State, Next Steps

### Recording & Integration
- OBS Studio integration via WebSocket v5
- Direct recording from CLI with defensive verification
- Detects if recording actually started (warns if not)
- Real-time feedback on recording status
- Auto-transcription after recording
- Cross-platform support (Windows, macOS, Linux)

### Output & Documents
- TXT transcripts with metadata
- DOCX formatted documents
- Markdown meeting notes
- PNG meme images
- Structured session summaries

### Music Transcription (v2.3.0 - Major Advancement)

**The Problem We Solved:**
Traditional ASR models fail on music because they're trained on speech, not music mixes. Instruments (drums, bass, synths) confuse the model, causing:
1. **Hallucinations**: "Thank you for watching", "Subscribe", "Subtitle by Amara.org" on instrumental sections
2. **Incomplete lyrics**: Whisper stops early or skips verses when confused by instruments
3. **Language detection failure**: Vocals masked by instruments prevent accurate language detection

**The Solution - Segment-Based Transcription with Separation-First Architecture:**

1. **Phase 1: Music Analysis (~1s)**
   - Validates track is music (not silence/noise)
   - Extracts BPM using onset strength envelope (only if detectable)
   - Detects key using chroma features (only if detectable)
   - Shows only measurable facts (no genre guessing)

2. **Phase 2: Vocal Isolation (~25s)**
   - Hybrid Transformer Demucs separates vocals from instruments
   - Converts "music transcription" into "clean speech recognition"
   - Eliminates root cause of hallucinations

3. **Phase 3: Vocal Activity Detection (~1s)**
   - Silero VAD detects exactly where singing occurs
   - Creates 16-25 precise timestamp segments per song
   - Identifies instrumental tracks (no vocals = not a failure)

4. **Phase 4: Audio Slicing (~1s)**
   - Slices vocals.wav into chunks based on VAD timestamps
   - Each segment is a clean, isolated vocal phrase
   - Enables independent transcription per segment

5. **Phase 5: Segment Transcription (~15s)**
   - Faster-Whisper with int8 quantization
   - Transcribes each segment independently
   - Per-segment language detection
   - No context bleeding between segments

6. **Phase 6: Hallucination Filtering (instant)**
   - Per-segment filtering of false positives
   - Multilingual patterns (English, Spanish, Portuguese)
   - Removes "Thanks for watching", "Subscribe", watermarks
   - Preserves valid sparse lyrics

7. **Phase 7: Reassembly (instant)**
   - Combines segments into complete lyrics
   - Adds metadata header (Duration, BPM if detected, Key if detected)
   - Cleans up intermediate files (slices, vocals, converted WAV)

**Results:**
- **Complete lyrics**: Full song from start to finish (no missing verses)
- **Filtered hallucinations**: Per-segment filtering removes most false positives
- **Accurate multi-language**: 99 languages supported (Spanish, Portuguese, Japanese, etc.)
- **Intelligent instrumental detection**: Gracefully handles tracks with no vocals
- **45s processing time**: For 3-minute songs
- **Works on any genre**: Rock, EDM, jazz, classical, flamenco, post-punk, etc.

**Technical Stack:**
- Demucs 4.0+ (Facebook Research) - Hybrid Transformer architecture
- Silero VAD v4/v5 (Neural VAD) - Singing voice detection
- Faster-Whisper with CTranslate2 backend - GPU-optimized transcription
- TorchAudio - Audio slicing and manipulation
- Librosa - Music analysis (BPM, key detection)
- See [Music Mode Architecture](docs/MUSIC_MODE_ARCHITECTURE.md) for details

### Developer Experience
- System diagnostics (scribe doctor)
- Environment validation
- 642 test suite with 100% pass rate
- Comprehensive error handling with context
- Run context tracking with unique IDs
- AsyncIO support with contextvars
- Full OBS recorder test coverage (46 tests)

### Reliability & Performance
- GPU Resource Manager (prevents OOM)
- Atomic file writes (prevents corruption)
- Resource limits validation
- Smart cleanup of intermediate files
- Adaptive progress tracking with machine learning
- Step-by-step progress display with actual operations
- Meme refinement progress with QA scores
- Configuration display (shows enabled features upfront)
- Self-improving time estimates based on actual performance
- Graceful degradation on errors

---

## Completed (v2.1.2)

### Provider Architecture Refinements
- **Anthropic Claude 3.5 Sonnet** fully integrated and tested
- **589 passing tests** with comprehensive provider coverage (100% pass rate)
- **Provider-agnostic meme generator** updated to work with all providers
- **Enhanced test reliability** - fixed flaky tests, improved mocking
- **Defensive testing suite** - comprehensive edge case and error handling tests
- **Documentation updates** - README and ROADMAP clean, detailed, professional
- **Zero test failures** - all defensive tests passing

### Image Generation Improvements
- **GPT Image 1 support** - Switched from DALL-E 3 to gpt-image-1 (superior text rendering)
- **Multiple aspect ratios** - AI intelligently chooses between:
  - Square (1024x1024) - Classic memes, single subjects
  - Landscape (1536x1024) - Wide scenes, side-by-side comparisons
  - Portrait (1024x1536) - Tall subjects, vertical layouts
  - Auto - Let model decide based on template
- **Better guidance** - Updated prompts to explain when to use each size
- **Automatic fallback** - XAI image generation falls back to OpenAI GPT Image 1

### AI Reasoning Enhancements
- **All intelligence features now use reasoning** for higher quality output:
  - **Jokes**: grok-4-fast-reasoning - More clever, thoughtful humor with deeper context analysis
  - **Memes**: grok-4-fast-reasoning - Deep comedy theory application and template selection
  - **Notes**: grok-4-fast-reasoning - Structured business and technical analysis
- **Benefits**: More insightful, contextual, and clever output while maintaining speed and cost efficiency
- **Cost**: Still 47x cheaper than GPT-5 even with reasoning enabled

### New Utilities
- **Silence removal tool** - `scribe clean` command for cleaning up long recordings
  - Removes/reduces silent sections using FFmpeg
  - Analyze mode to preview silence without removing
  - Configurable threshold and duration
  - Makes transcription faster by reducing silent parts
- **File trimming** - `scribe clean --trim HH:MM:SS` to cut files at specific time
  - Fast operation (copies without re-encoding)
  - Perfect for recordings left running overnight
  - Example: trim 19.5 hour file down to 1.7 hours in seconds

### Bug Fixes
- **OpenAI API compatibility** - Fixed `response_format` for new diarization model (gpt-4o-transcribe-diarize-api-ev3)
  - Changed from `verbose_json` to `json` format as required by updated API
  - Maintains backward compatibility with response parsing
- **Meme provider selection** - Fixed CLI passing wrong API key to meme generator
  - CLI was hardcoding OpenAI key instead of letting provider system choose
  - Now respects `SCRIBE_MEME_PROVIDER` environment variable
- **Cleaner output** - Reduced log noise at WARNING level
  - JSON repair messages now at DEBUG level (normal operation, not a warning)
- **Image size validation** - Fixed meme image generation with invalid size formats
  - AI sometimes returns descriptive text like "1024x1026 (portrait)" instead of just "1024x1536"
  - Now strips extra text and validates against allowed sizes
  - Falls back to '1024x1024' if invalid
- **XAI image generation** - Enhanced with dual-format support and OpenAI fallback
  - Tries b64_json format first (more reliable)
  - Falls back to URL format if needed
  - Automatically falls back to OpenAI DALL-E 3 if XAI fails
  - Comprehensive error handling for missing data
- **Defensive test suite** - Added 15 comprehensive edge case tests
  - Size normalization with various invalid formats
  - Empty/invalid JSON responses
  - Provider exceptions and safety blocks
  - XAI-specific image generation scenarios

## Completed (v2.1.1)

### Multi-Provider AI Support (Provider-Agnostic Architecture)
- **Provider abstraction layer** with unified interface for multiple AI providers
- **XAI/Grok integration** with full support for Grok 4 Fast and Grok 2 Image
- **Anthropic Claude integration** with Claude 3.5 Sonnet support
- **Provider configuration** via environment variables per feature
  - `SCRIBE_JOKE_PROVIDER=xai` (default: xai)
  - `SCRIBE_MEME_PROVIDER=xai` (default: xai)
  - `SCRIBE_NOTES_PROVIDER=xai` (default: xai)
  - `SCRIBE_TRANSCRIBE_PROVIDER=openai` (default: openai)
- **Cost optimization**: 47x cheaper with Grok vs GPT-5 for jokes/notes/memes
- **Universal logging** with single `SCRIBE_LOG_LEVEL` for all components
- **Provider-agnostic implementation** across all AI features:
  - Jokes: Works with XAI, OpenAI, Anthropic
  - Notes: Works with XAI, OpenAI, Anthropic (with enhanced JSON repair)
  - Meme concepts: Works with XAI, OpenAI, Anthropic
  - Meme images: Works with XAI, OpenAI (Anthropic doesn't support images)
- **CLI provider flags**: `--provider xai` or `--provider anthropic` for jokes and notes commands
- **Backward compatibility** with seamless fallback to OpenAI when provider unavailable
- **Easy extensibility**: Clean architecture makes adding new providers straightforward

---

## Completed (v2.2.0)

### Model Provider Expansion
- **Google Gemini integration**: Full support for Gemini 3 Pro (advanced reasoning), Gemini 2.5 Flash/Pro (text), and Imagen 4 (images)
- **Gemini 3 features**: Dynamic thinking levels, 1M token context, optimized for temperature=1.0
- **Provider health checks**: Monitor provider availability, response times, and consecutive failures
- **Health check CLI**: `scribe health` command to validate provider connectivity
- **Automatic failover**: Switch providers on errors or rate limits with configurable fallback chains
- **Provider-agnostic architecture**: All features work seamlessly across OpenAI, XAI, Anthropic, and Gemini
- **Cost optimization**: Gemini offers competitive pricing with high-quality output

### Humor Generation Enhancements
- **Joke bake-off**: Get jokes from all providers, judge and pick the funniest
- **Meme concept bake-off**: Get concepts from all providers, judge and pick the funniest
- **Separate image provider**: Configure concept provider separately from image provider
- **Local text overlay**: Optional Pillow-based text rendering to bypass AI text issues
- **Clean UX**: Bake-off runs silently, users just get the best result
- **Spice level refinement**: Clear guidance for NSFW/edgy content (levels 9-10)
- **XAI optimization**: Proper handling of 1024 char prompt limit

## Completed (v2.3.0)

### Batch Processing
- **Multi-file transcription** - Process multiple files with single command
  - Sequential processing with individual output files per input
  - Wildcard support for easy file selection
  - Continue-on-error mode for robust batch operations
  - Summary reporting with success/failure counts
  - All standard options available (method, model, language, vocabulary)

### Custom Vocabulary
- **Domain-specific accuracy** - Improve recognition of technical terms and proper nouns
  - Plain text (.txt) format with comment support (# prefix)
  - JSON (.json) format for programmatic generation
  - Works with both local GPU and OpenAI API transcription
  - Passed to Whisper as initial prompt for guided recognition
  - Preserves capitalization for proper nouns and acronyms
  - Example files provided in examples/ directory

### Enhanced System Diagnostics
- **Comprehensive diagnostics** - System analysis with intelligent recommendations
  - 15 diagnostic checks (up from 9 in v2.2)
  - Python package validation
  - GPU memory analysis with optimal model recommendations
  - Additional provider detection (XAI, Anthropic, Gemini)
  - Temporary directory space validation
  - Configuration conflict detection
  - System resource analysis (RAM, CPU)
  - Prioritized action items (top 5 recommendations)
  - Color-coded output with clear status indicators

### CLI/UX Improvements
- **Enhanced help system** - Structured, colorful help with practical examples
  - Organized sections: capabilities, quick start, workflows, configuration
  - Color-coded commands and options
  - Real-world usage examples
  - Clear system requirements
- **Improved output formatting** - Better visual hierarchy and readability
  - Color-coded status messages
  - Structured file listings
  - Clear success/warning/error indicators
  - ASCII-compatible (no problematic unicode characters)

---

## Strategic Direction: Continuous Refinement (v2.5.0+)

Scribe is feature-complete. The path forward is systematic improvement of existing capabilities through deeper analysis, better error handling, and adaptive behavior.

### Methodology: Deep Part-by-Part Analysis

Each release cycle focuses on one subsystem, applying rigorous analysis and refinement:

1. **Analyze**: Understand current behavior, identify edge cases, document failure modes
2. **Defend**: Add comprehensive error handling, input validation, resource management
3. **Adapt**: Implement learning mechanisms, fallback strategies, self-correction
4. **Test**: Comprehensive test coverage including edge cases and failure scenarios
5. **Document**: Explain design decisions, trade-offs, and operational characteristics

### Priority Areas for Refinement

**Transcription Pipeline** (Target: v2.5.0)
- Analyze audio preprocessing edge cases (corrupted files, unusual formats, extreme durations)
- Enhance GPU memory management with predictive allocation
- Implement checkpoint/resume for long transcriptions
- Add confidence scoring per segment
- Improve error recovery with partial results

**Provider System** (Target: v2.6.0)
- Analyze provider failure patterns and implement circuit breakers
- Add request/response caching for identical inputs
- Implement adaptive rate limiting based on provider feedback
- Enhanced health monitoring with predictive failover
- Cost tracking and optimization recommendations

**Recording System** (Target: v2.7.0)
- Analyze OBS integration failure modes beyond WebSocket
- Implement recording verification with audio analysis
- Add automatic recovery from recording interruptions
- Enhanced file monitoring with inotify/FSEvents
- Recording quality validation before transcription

**Music Transcription** (Target: v2.8.0)
- Analyze hallucination patterns across genres and languages
- Implement adaptive filtering based on music characteristics
- Add confidence scoring for lyric segments
- Enhanced instrumental detection with multiple signals
- Batch processing optimization with parallel vocal separation

### Principles for Refinement

**Defensive by Default**
- Every external input validated
- Every resource acquisition has cleanup
- Every network call has timeout and retry
- Every file operation is atomic
- Every error provides actionable context

**Adaptive Behavior**
- Learn from past performance to improve estimates
- Adjust strategies based on system resources
- Detect patterns in failures and adapt
- Self-tune parameters based on workload
- Provide recommendations based on usage patterns

**Observable Operations**
- Every operation logs its intent and outcome
- Progress is always visible and accurate
- Errors explain what happened and what to do
- Diagnostics reveal system state
- Metrics track performance over time

**Maintainable Code**
- Functions under 50 lines
- Clear separation of concerns
- Comprehensive type hints
- Self-documenting variable names
- Thorough docstrings with examples

---

## Scope Boundaries

### Intentionally Excluded

Features that would dilute focus or are better served by specialized tools:

**Enterprise/SaaS Features**
- Multi-user support, team workspaces, SSO, audit logging
- Reason: Scribe is a local-first CLI tool, not a service

**Advanced Analytics**
- Sentiment analysis, topic segmentation, meeting classification
- Reason: These are analytics features, not transcription features

**Project Management**
- Action item extraction with assignees, decision tracking
- Reason: Use dedicated project management tools

**Web UI**
- Dashboards, visual editors, search interfaces
- Reason: CLI-first design, web adds complexity without value

**Cloud Integration**
- REST APIs, webhooks, cloud storage sync
- Reason: Local-first tool, users control their data

**Real-time Features**
- Live transcription, streaming processing
- Reason: Batch processing is simpler and more reliable

### Evaluation Criteria for New Features

Before adding any feature, it must satisfy all criteria:

1. **Core Value**: Does it directly improve transcription or analysis quality?
2. **Simplicity**: Does it maintain or reduce complexity?
3. **CLI-First**: Does it align with command-line workflows?
4. **Local-First**: Does it respect user data ownership?
5. **Maintainability**: Can it be maintained to the same quality standard?

If any answer is no, the feature is rejected.

---

## Current Technical Debt

Tracked items for systematic resolution:

**Code Quality**
- [ ] Achieve 90%+ meaningful test coverage (currently 642 tests, ~85% coverage)
- [ ] Full mypy strict mode compliance (currently using standard mode)
- [ ] Refactor functions over 50 lines (12 functions identified)
- [ ] Eliminate code duplication (3 areas identified: error handling, file operations, provider calls)

**Documentation**
- [ ] Complete API reference for all public functions (currently 60% documented)
- [ ] Architecture decision records for major choices (need 8 ADRs)
- [ ] Performance tuning guide with benchmarks (need baseline measurements)
- [ ] Comprehensive troubleshooting guide (expand current guide with 20 more scenarios)

**Dependencies**
- [ ] Security audit of all dependencies (schedule quarterly)
- [ ] Pin dependencies with version ranges (currently using exact versions)
- [ ] Minimize dependency tree (currently 47 direct dependencies, target 35)
- [ ] Document optional vs required dependencies (need dependency matrix)

**Performance**
- [ ] Memory profiling for large files (need baseline for 1GB+ files)
- [ ] Benchmark suite for regression detection (need 10 benchmark scenarios)
- [ ] GPU memory optimization (currently uses fixed allocation)
- [ ] Parallel processing for batch operations (currently sequential)

---

## Design Principles

### Quality Over Speed

Scribe prioritizes correctness and reliability over raw performance:

**Model Selection**
- Uses Whisper large-v3 (best accuracy available)
- RTX 4090 achieves 11x real-time even with largest model
- Could use faster models, but accuracy is non-negotiable

**Audio Preprocessing**
- Professional-grade normalization with dynaudnorm
- Processes at ~10x real-time
- Could skip for speed, but quality would suffer

**Example: 55-minute recording on RTX 4090**
- Audio preprocessing: 5.5 minutes
- Transcription: 5 minutes
- Total: 10.5 minutes
- Acceptable for professional workflows where accuracy matters

### Defensive by Design

Every component assumes failure and handles it gracefully:

**Input Validation**
- All external inputs validated before use
- Clear error messages with actionable guidance
- Type checking at runtime for critical paths

**Resource Management**
- All resources have explicit cleanup
- Atomic file operations prevent corruption
- GPU memory managed with predictive allocation

**Error Handling**
- Errors categorized: user error, system error, transient
- Structured logging with context
- Automatic retry with exponential backoff where appropriate

### Adaptive Behavior

The system learns and improves from experience:

**Performance Tracking**
- Records actual performance for time estimates
- Ignores outliers (interrupted runs)
- Provides increasingly accurate predictions

**Provider Management**
- Tracks provider health and response times
- Implements circuit breakers for failing providers
- Automatically fails over to healthy alternatives

**Resource Optimization**
- Adjusts batch sizes based on available memory
- Tunes processing parameters based on workload
- Provides recommendations based on usage patterns

---

## Contributing

Contributions are welcome in these priority areas:

1. **Test Coverage**: Add tests for edge cases and failure scenarios
2. **Performance**: Optimize hot paths without sacrificing quality
3. **Documentation**: Improve clarity, add examples, document decisions
4. **Bug Fixes**: Address issues with comprehensive tests

See CONTRIBUTING.md for guidelines.

---

## Version History Summary

**v2.4.x**: Reliability and test coverage improvements
**v2.3.x**: Music transcription with segment-based architecture
**v2.2.x**: Multi-provider support with health monitoring
**v2.1.x**: Provider abstraction and cost optimization
**v2.0.x**: GPU acceleration and quality-first approach
**v1.x**: Initial releases with basic transcription
