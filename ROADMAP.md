# Scribe Roadmap

This roadmap outlines completed features, current capabilities, and planned improvements for Scribe.

## Current Version: 2.4.0

**Latest: User Experience Polish + Code Quality**

This release focuses on professional UX improvements and maintaining S-tier code quality through systematic review and immediate fixes.

**What's New:**
- **Cleaner Recording UI**: Removed emoji bullet points, professional green panel
- **No Emojis in Output**: Text-based indicators (DONE, ERROR, WARNING) for consistency
- **Better Error Handling**: JSON refinement warnings moved to debug level (less noise)
- **Code Quality**: 100% clean codebase (54/54 files, zero diagnostics)
- **Outlier Detection**: Performance tracker ignores interrupted runs (better estimates)
- **Dead Code Removed**: 100+ lines of unreachable code cleaned up
- **Verified Diagnostics**: `scribe doctor` command tested and working perfectly

**Development Process:**
- **Find and Fix Mode**: Issues found during documentation are fixed immediately
- **Comprehensive Verification**: All files checked with diagnostics after changes
- **S-Tier Quality**: Maintain zero-diagnostic standard across entire codebase
- **Deep Documentation**: 14 modules with ~7,000+ lines of thoughtful analysis

**Status:** Production-ready - 595/595 tests passing, 100% clean code

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
- 589 test suite with 100% pass rate
- Comprehensive error handling with context
- Run context tracking with unique IDs
- AsyncIO support with contextvars

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

## Focus: Excellence Over Features (v2.4.0+)

**Philosophy:** Scribe is feature-complete. It transcribes audio, generates meeting notes, creates jokes and memes, and extracts music lyrics. The focus is doing all of this exceptionally well - clean code, thoughtful architecture, comprehensive testing, and careful attention to detail.

### Code Quality & Stability (Ongoing)
- **Thorough documentation** - Every module deserves deep, thoughtful explanation
  - Document the "why" behind architectural decisions
  - Explain edge cases and their handling
  - Include performance characteristics and trade-offs
  - Add references to research papers and best practices
  
- **Defensive programming** - Anticipate and handle every failure mode
  - Comprehensive input validation with clear error messages
  - Graceful degradation when resources are constrained
  - Atomic operations to prevent data corruption
  - Resource cleanup even in failure scenarios
  - Network resilience with exponential backoff
  
- **Test coverage excellence** - Not just coverage, but meaningful tests
  - Edge case testing (empty files, corrupted audio, network failures)
  - Integration tests for end-to-end workflows
  - Performance regression tests
  - Memory leak detection
  - Stress testing with large files and batch operations
  
- **Type safety** - Complete type hints with runtime validation
  - Full mypy strict mode compliance
  - Runtime type checking for external inputs
  - Pydantic models for configuration validation
  - Clear type documentation in docstrings

### Performance & Efficiency (Ongoing)
- **Memory optimization** - Efficient resource usage at scale
  - Streaming audio processing to minimize memory footprint
  - Lazy loading of ML models
  - Proper cleanup of GPU memory between operations
  - Memory profiling and leak detection
  
- **Processing optimization** - Fast without sacrificing quality
  - Parallel processing where safe (batch operations)
  - Efficient audio format conversion
  - Model caching and reuse
  - Benchmark suite to track performance regressions

### Reliability & Observability (Ongoing)
- **Error handling excellence** - Every error tells you what to do
  - Structured error messages with context
  - Actionable suggestions for resolution
  - Error categorization (user error vs system error vs transient)
  - Comprehensive logging with appropriate levels
  
- **Monitoring & diagnostics** - Know what's happening and why
  - Enhanced system health checks
  - Performance metrics collection
  - Resource usage tracking
  - Diagnostic tools for troubleshooting
  
- **Recovery mechanisms** - Fail gracefully, recover automatically
  - Checkpoint/resume for long operations
  - Automatic retry with exponential backoff
  - Fallback chains for provider failures
  - Partial success handling in batch operations

### User Experience Polish (Ongoing)
- **Progress transparency** - Users always know what's happening
  - Accurate time estimates based on machine learning
  - Clear stage indicators with context
  - Meaningful progress percentages
  - Cancellation support with cleanup
  
- **Output quality** - Professional, consistent, useful
  - Clean formatting across all output types
  - Consistent metadata structure
  - Proper character encoding handling
  - Accessibility considerations

### Documentation Excellence (Ongoing)
- **Architecture documentation** - Deep understanding of system design
  - Component interaction diagrams
  - Data flow documentation
  - Decision records for major choices
  - Performance characteristics
  
- **Troubleshooting guides** - Solve problems quickly
  - Common issues with solutions
  - Diagnostic procedures
  - Performance tuning guidance
  - Platform-specific considerations
  
- **Code examples** - Show best practices
  - Real-world usage patterns
  - Integration examples
  - Custom vocabulary examples
  - Provider configuration examples

---

## Not Planned (Intentionally Excluded)

These features would dilute Scribe's focus and are better served by specialized tools:

### Enterprise Features
- Multi-user support, team workspaces, SSO, audit logging
- **Why not:** Scribe is a personal/team CLI tool, not SaaS

### Advanced Analytics
- Sentiment analysis, topic segmentation, meeting classification
- **Why not:** These are analytics features, not transcription features

### Project Management
- Action item extraction with assignees, decision tracking
- **Why not:** Use dedicated project management tools

### Web UI
- Dashboards, visual editors, search interfaces
- **Why not:** CLI-first design, web adds complexity without value

### Cloud Integration
- REST APIs, webhooks, cloud storage sync
- **Why not:** Local-first tool, users control their data

### Real-time Features
- Live transcription, streaming processing
- **Why not:** Batch processing is simpler and more reliable

---

## Potential Enhancements (Only If They Improve Core Value)

These might be worth considering if they make transcription/analysis better:

### Model Improvements
- **Whisper large-v4** - Only if it improves accuracy over v3
- **Local diarization** - Only if it matches or exceeds OpenAI API quality
- **Custom fine-tuning** - Only if users have domain-specific needs

### Output Enhancements
- **Timestamp precision** - Sub-second accuracy for video editing workflows
- **Speaker labels** - Better speaker identification and naming
- **Confidence scores** - Per-word or per-segment confidence metrics

### Workflow Improvements
- **Resume capability** - Restart failed transcriptions from checkpoint
- **Incremental processing** - Process only new content in updated files
- **Format templates** - User-defined output formatting

**Criteria for inclusion:** Does it make Scribe better at transcription and analysis? Does it maintain simplicity? Does it align with CLI-first philosophy?

---

## Technical Debt & Maintenance

### Code Quality
- Achieve 90%+ meaningful test coverage
- Full mypy strict mode compliance
- Refactor large modules (keep functions under 50 lines)
- Eliminate code duplication

### Documentation
- Complete API reference for all public functions
- Architecture decision records (ADRs) for major choices
- Performance tuning guide with benchmarks
- Comprehensive troubleshooting guide

### Dependencies
- Regular security audits and updates
- Pin dependencies with version ranges
- Minimize dependency tree
- Document optional vs required dependencies

---

## Status Legend

- Completed: Feature implemented and tested
- In Progress: Active development
- Planned: Scheduled for upcoming release
- Future Consideration: Under evaluation
- Technical Debt: Maintenance and refactoring
- Community: Open source and ecosystem

---

## Design Philosophy

### Quality Over Speed
Scribe intentionally prioritizes transcription quality:

**Model Selection:**
- Uses Whisper large-v3 (best accuracy available)
- RTX 4090 achieves 11x real-time speed even with the largest model
- We could use faster models (large-v2, medium, turbo), but accuracy is non-negotiable

**Audio Preprocessing:**
- Uses dynaudnorm for professional-grade audio normalization
- Processes at ~10x real-time (5.5 min for 55 min recording)
- Ensures optimal audio quality for transcription
- We could skip normalization for speed, but quality would suffer

**Total Time Example (55-minute recording on RTX 4090):**
- Audio preprocessing: ~5.5 minutes
- Transcription: ~5 minutes
- Total: ~10.5 minutes
- This is acceptable for professional workflows where accuracy matters

## Version History

### v2.1.0
UX and intelligence improvements: AI-powered joke archetype selection, stricter meme QA with automatic retry, unified command interface, improved progress display, and cleaner output formatting.

### v2.0.0
Major release with GPT-5 integration, meme generation, GPU resource management, comprehensive reliability improvements, and quality-first transcription with large-v3.

### v1.x
Initial releases with basic transcription, OBS integration, and document generation.

---

## Contributing

We welcome contributions! Priority areas:
1. Test coverage improvements
2. Performance optimizations
3. Documentation enhancements
4. Bug fixes and stability

See CONTRIBUTING.md for guidelines.
