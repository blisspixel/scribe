# Scribe Roadmap

## Current Version: 2.1.2 (November 2025)

This roadmap outlines completed features, current capabilities, and planned improvements for Scribe.

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
- Direct recording from CLI
- Auto-transcription after recording
- Cross-platform support (Windows, macOS, Linux)

### Output & Documents
- TXT transcripts with metadata
- DOCX formatted documents
- Markdown meeting notes
- PNG meme images
- Structured session summaries

### Developer Experience
- System diagnostics (scribe doctor)
- Environment validation
- 463 test suite with 45% coverage
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

## Completed (v2.1.2 - November 2025)

### Provider Architecture Refinements
- **Anthropic Claude 3.5 Sonnet** fully integrated and tested
- **548 passing tests** with comprehensive provider coverage (+16 defensive tests)
- **Provider-agnostic meme generator** updated to work with all providers
- **Enhanced test reliability** - fixed flaky tests, improved mocking
- **Defensive testing suite** - comprehensive edge case and error handling tests
- **Documentation updates** - README and ROADMAP clean, detailed, no emojis
- **42% test coverage** maintained across all features

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

## Completed (v2.1.1 - November 2025)

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

## In Progress (v2.2.0 - Q1 2026)

### Model Provider Expansion
- **Anthropic Claude support**: Claude 3.5 Sonnet integrated (needs production testing)
- **Google Gemini support**: Add Gemini 2.0 for additional provider choice
- **Provider health checks**: Monitor provider availability and performance
- **Automatic failover**: Switch providers on errors or rate limits
- **Production validation**: Test Anthropic and other providers in real meetings

### Transcription Improvements
- Batch processing for multiple files
- Resume interrupted transcriptions
- Custom vocabulary/glossary support
- Timestamp precision improvements
- Optional speed modes (large-v2, medium) for faster processing when accuracy is less critical

### Intelligence Enhancements
- Action item extraction with assignees
- Sentiment analysis per speaker
- Topic segmentation and tagging
- Meeting type classification

### Performance Optimization
- Model caching improvements
- Parallel chunk processing
- Memory usage optimization
- Faster audio conversion pipeline

---

## Planned (v2.3.0 - Q2 2026)

### Advanced Features
- Real-time transcription during recording
- Live speaker identification
- Multi-file project management
- Template system for different meeting types
- Custom output formatters

### API & Integration
- REST API for remote transcription
- Webhook support for completion notifications
- Slack/Teams integration for sharing
- Calendar integration for auto-naming
- Cloud storage sync (S3, GCS, Azure)

### UI Improvements
- Web dashboard for managing transcriptions
- Progress tracking across multiple jobs
- Search across all transcripts
- Visual timeline editor

---

## Future Considerations (v3.0+)

### Model Upgrades
- Support for NVIDIA NeMo Parakeet models (if accuracy exceeds large-v3)
- Mistral Voxtral-Mini integration for multimodal capabilities
- Local diarization without API (pyannote.audio integration)
- Fine-tuned models for specific domains (medical, legal, technical)
- Whisper large-v4 when released (if it improves on v3 accuracy)

### Advanced Intelligence
- Multi-meeting analysis and trends
- Decision tracking across meetings
- Automated follow-up generation
- Risk and opportunity detection
- Compliance checking for regulated industries

### Enterprise Features
- Multi-user support with permissions
- Team workspaces
- Audit logging
- SSO integration
- On-premise deployment options
- Custom model hosting

### Performance & Scale
- Distributed processing across multiple GPUs
- Kubernetes deployment
- Queue-based job processing
- Auto-scaling based on load

---

## Technical Debt & Maintenance

### Code Quality
- Increase test coverage to 80%
- Add integration tests for all API endpoints
- Improve type hints coverage
- Refactor large modules into smaller components

### Documentation
- API reference documentation
- Architecture decision records (ADRs)
- Video tutorials and demos
- Troubleshooting guide expansion

### Dependencies
- Regular security updates
- Dependency version pinning strategy
- Optional dependency management improvements
- Reduce package size for API-only installs

---

## Community & Ecosystem

### Open Source
- Plugin system for custom processors
- Community template library
- Example integrations repository
- Contribution guidelines and governance

### Education
- Best practices guide
- Performance tuning guide
- Use case examples
- Comparison with alternatives

---

## Legend

- Completed
- In Progress
- Planned
- Future Consideration
- Technical Debt
- Community

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

### v2.1.0 (November 2025)
UX and intelligence improvements: AI-powered joke archetype selection, stricter meme QA with automatic retry, unified command interface, improved progress display, and cleaner output formatting.

### v2.0.0 (November 2025)
Major release with GPT-5 integration, meme generation, GPU resource management, comprehensive reliability improvements, and quality-first transcription with large-v3.

### v1.x (2024)
Initial releases with basic transcription, OBS integration, and document generation.

---

## Contributing

We welcome contributions! Priority areas:
1. Test coverage improvements
2. Performance optimizations
3. Documentation enhancements
4. Bug fixes and stability

See CONTRIBUTING.md for guidelines.

---

## Feedback

Have ideas or requests? Open an issue on GitHub or reach out to [@blisspixel](https://github.com/blisspixel).

Last updated: November 13, 2025
