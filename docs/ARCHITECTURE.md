# Scribe Architecture

**Last Updated:** 2025-11-18

## Overview

Scribe is a modular transcription and analysis pipeline built on a provider-agnostic architecture. The system is designed for reliability, performance, and extensibility.

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      CLI Layer                              │
│  (Typer-based command interface with Rich output)          │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
    ┌────────┐     ┌──────────┐    ┌─────────┐
    │ Record │     │Transcribe│    │Analysis │
    │        │     │          │    │         │
    └───┬────┘     └────┬─────┘    └────┬────┘
        │               │               │
        ▼               ▼               ▼
┌────────────────────────────────────────────────┐
│            Core Orchestration Layer            │
│  - Workflow management                         │
│  - Method selection (auto/local/api)           │
│  - Error handling and fallback                 │
│  - Progress tracking                           │
└────────────┬───────────────────────────────────┘
             │
    ┌────────┼────────┐
    ▼        ▼        ▼
┌────────┐ ┌────────┐ ┌────────┐
│Recorder│ │Convert │ │Transcr │
│        │ │        │ │        │
└────────┘ └───┬────┘ └───┬────┘
               │           │
               ▼           ▼
         ┌──────────────────────┐
         │  Transcription Layer │
         ├──────────┬───────────┤
         │  Local   │    API    │
         │ Whisper  │  OpenAI   │
         │  (GPU)   │           │
         └──────────┴───────────┘
                    │
                    ▼
         ┌─────────────────────┐
         │  Document Generator │
         │  - TXT transcripts  │
         │  - DOCX formatting  │
         │  - Metadata         │
         └──────────┬──────────┘
                    │
         ┌──────────┼──────────┐
         ▼          ▼          ▼
    ┌───────┐  ┌───────┐  ┌───────┐
    │ Notes │  │ Jokes │  │ Memes │
    │(GPT-5)│  │(GPT-5)│  │(GPT-5)│
    └───────┘  └───────┘  └───┬───┘
                               │
                               ▼
                        ┌──────────────┐
                        │ Image Gen    │
                        │ + QA Loop    │
                        └──────────────┘
```

## Core Components

### CLI Layer (`src/scribe/cli/`)

**main.py** - Primary command interface
- Command routing and argument parsing
- User input validation
- Output formatting with Rich
- Error presentation

**mobile.py** - Mobile/simplified interface
- Streamlined commands for quick access
- Reduced verbosity

**Design Principles:**
- Single responsibility per command
- Consistent error handling
- Clear progress feedback
- Graceful degradation

### Core Layer (`src/scribe/core/`)

**transcriber.py** - Orchestration hub
- Method selection (auto/local/api)
- Workflow coordination
- Fallback logic
- Resource management

**converter.py** - Audio/video processing
- Format conversion via FFmpeg
- Audio normalization (dynaudnorm)
- Quality optimization
- Progress tracking

**downloader.py** - URL media download
- yt-dlp integration (YouTube, Vimeo, Twitter/X, 1000+ sites)
- Audio-only download by default
- Browser cookie support for authenticated downloads
- Hardened retries (10 attempts), User-Agent spoofing
- Progress tracking with callback hooks
- File discovery with post-processor awareness
- Size and duration limit enforcement

**local_whisper.py** - GPU transcription
- faster-whisper integration
- GPU resource management
- Beam search optimization
- Silence detection

**openai_api.py** - API transcription
- OpenAI Whisper API integration
- Speaker diarization
- Server-side chunking
- Rate limiting and retry

**recorder.py** - OBS integration
- WebSocket v5 protocol with auto-reconnect
- Self-healing OBS lifecycle (kill stale → clean crash sentinels → launch → connect)
- Recording lifecycle management (stop stale → start fresh → deadman timer on stop)
- Auto-transcription trigger
- Defensive error recovery with actionable user messages

### Models Layer (`src/scribe/models/`)

**config.py** - System configuration
- Environment variable loading
- Validation and defaults
- Type-safe settings
- Pydantic-based models

**session.py** - Session tracking
- Unique run IDs
- Metadata collection
- Performance metrics
- Audit trail

**gpu.py** - GPU configuration
- Hardware detection
- Optimal settings per GPU
- Memory management
- Capability detection

### Providers Layer (`src/scribe/providers/`)

**base.py** - Provider abstraction
- Unified interface for all providers
- Feature capability declaration
- Error handling patterns
- Rate limiting support

**openai_provider.py** - OpenAI integration
- GPT-5.5 (default), GPT-5.4, GPT-5, GPT-Image-1
- Whisper API
- Structured output support

**xai_provider.py** - XAI/Grok integration
- Grok 4.3 (default for joke, meme, notes)
- Grok Imagine Image
- Cost optimization (request cost via `cost_in_usd_ticks`)

**anthropic_provider.py** - Anthropic integration
- Claude 3.5 Sonnet
- Text-only (no images)
- JSON repair logic

**gemini_provider.py** - Google Gemini integration (optional, not in default fallback chain)
- Gemini 3 Pro / Flash, Imagen 4
- Imagen 4
- Aspect ratio handling

**health.py** - Provider health monitoring
- Connectivity checks
- Response time tracking
- Failure counting
- Automatic failover

**factory.py** - Provider instantiation
- Dynamic provider selection
- Configuration injection
- Caching and reuse

### Utilities Layer (`src/scribe/utils/`)

**gpu_manager.py** - GPU resource management
- Singleton pattern for GPU access
- Model loading/unloading
- Memory monitoring
- Concurrent access prevention

**progress.py** - Adaptive progress tracking
- Kalman filter for time estimation
- Machine-specific learning
- Speed ratio calculation
- Persistent metrics

**safe_write.py** - Atomic file operations
- Platform-specific handling
- Corruption prevention
- Temporary file management
- Rollback on failure

**diagnostics.py** - System health checks
- 16 comprehensive checks (including yt-dlp)
- Actionable recommendations
- Priority ranking
- Configuration validation

**vocabulary.py** - Custom vocabulary handling
- TXT and JSON parsing
- Whisper prompt formatting
- Capitalization preservation
- Comment support

**notes_generator.py** - Meeting analysis
- GPT-5 multi-step reasoning
- Structured output (Current State, Drivers, Blockers, Future State, Next Steps)
- Transcript summarization
- Business and technical insights

**joke_generator.py** - Context-aware humor
- 10 comedy archetypes
- Tone and rhythm analysis
- Spice level control
- Reasoning display

**meme_generator.py** - Meme creation
- Template selection
- Image generation
- QA loop with scoring
- Retry logic

**meme_compositor.py** - Text overlay
- Pillow-based rendering
- Impact font styling
- Black outline for readability
- Aspect ratio handling

**banner.py** - Animated ASCII banner
- ANSI Shadow block font (6-line, 45-char wide)
- Gradient sweep animation (blue→purple, HSV color space)
- Rich Live animation engine with ease-out cubic easing
- Progressive degradation (full/light/off/plain)
- Cross-platform: Windows (8 FPS), macOS/Linux (10 FPS)
- Respects SCRIBE_ANIMATIONS, SCRIBE_BANNER, NO_COLOR env vars

**branding.py** - Gradient header markup
- Per-character HSV gradient generation
- Terminal capability-aware rendering

**terminal_ui.py** - Terminal capability detection
- Cross-platform animation mode resolution
- FPS and color mode configuration
- CI/dumb terminal detection

## Data Flow

### Transcription Workflow

```
Input File
    │
    ▼
┌─────────────────┐
│ Audio Conversion│  (~10% of duration)
│ - 16kHz mono    │
│ - dynaudnorm    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│Method Selection │
│ - GPU available?│
│ - File size OK? │
└────────┬────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────┐
│ Local  │ │  API   │
│Whisper │ │ OpenAI │
└───┬────┘ └───┬────┘
    │          │
    └────┬─────┘
         ▼
┌─────────────────┐
│  Transcript     │
│  - TXT format   │
│  - Metadata     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Post-Processing │
│ - DOCX          │
│ - Notes (opt)   │
│ - Joke (opt)    │
│ - Meme (opt)    │
└─────────────────┘
```

### Intelligence Workflow

```
Transcript
    │
    ▼
┌─────────────────┐
│ Provider Select │
│ (xai/openai/    │
│  anthropic/     │
│  gemini)        │
└────────┬────────┘
         │
    ┌────┼────┐
    ▼    ▼    ▼
┌──────┐ ┌──────┐ ┌──────┐
│Notes │ │Joke  │ │Meme  │
│      │ │      │ │      │
└──┬───┘ └──┬───┘ └──┬───┘
   │        │        │
   ▼        ▼        ▼
┌──────────────────────┐
│  Output Files        │
│  - notes.md          │
│  - joke (console)    │
│  - meme.png          │
└──────────────────────┘
```

## Design Patterns

### Provider Pattern
All AI providers implement a common interface:
```python
class AIProvider(ABC):
    @abstractmethod
    def chat_completion(self, messages, **kwargs) -> dict
    
    @abstractmethod
    def generate_image(self, prompt, **kwargs) -> bytes
    
    @abstractmethod
    def transcribe_audio(self, audio_path, **kwargs) -> dict
```

Benefits:
- Easy to add new providers
- Consistent error handling
- Transparent switching
- Feature capability declaration

### Singleton Pattern
GPU resource manager ensures single point of access:
```python
class GPUResourceManager:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
```

Benefits:
- Prevents concurrent model loading
- Centralized memory management
- Avoids OOM crashes

### Strategy Pattern
Transcription method selection:
```python
def select_method(self, method: str) -> TranscriptionStrategy:
    if method == "auto":
        return self._auto_select()
    elif method == "local":
        return LocalWhisperStrategy()
    elif method == "openai":
        return OpenAIAPIStrategy()
```

Benefits:
- Runtime method selection
- Easy to add new strategies
- Testable in isolation

### Observer Pattern
Progress tracking with callbacks:
```python
def convert_audio(self, callback: Optional[Callable] = None):
    for progress in range(100):
        if callback:
            callback(progress / 100.0)
```

Benefits:
- Decoupled progress reporting
- Flexible UI updates
- Testable without UI

## Error Handling

### Exception Hierarchy
```
ScribeError (base)
├── ValidationError
├── ProcessError
├── TranscriptionError
├── FileOperationError
├── CircuitBreakerOpen
├── ConversionError
├── AudioFormatError
├── GPUError
├── APIError
└── DownloadError
```

### Error Context
All exceptions carry context:
```python
raise TranscriptionError(
    "Transcription failed",
    context={
        "audio_path": str(audio_path),
        "method": "local",
        "gpu_available": True,
        "error": str(e)
    }
)
```

### Fallback Strategy
```
Local GPU Fails
    │
    ▼
Try OpenAI API
    │
    ▼
Report Error with Context
```

## Performance Optimization

### GPU Optimization
- Beam size tuning per GPU model
- FP16 precision on supported hardware
- Tensor core utilization
- Memory-efficient batching

### Audio Processing
- Parallel FFmpeg operations where possible
- Streaming for large files
- Efficient temporary file management
- Smart caching

### API Optimization
- Request batching
- Rate limit respect
- Exponential backoff
- Connection pooling

## Testing Strategy

### Unit Tests (589 tests)
- Individual component testing
- Mock external dependencies
- Edge case coverage
- Defensive programming validation

### Integration Tests (Limited)
- Provider integration
- End-to-end workflows
- Error recovery scenarios

### Test Organization
```
tests/
├── unit/
│   ├── test_transcriber.py
│   ├── test_converter.py
│   ├── test_vocabulary.py
│   ├── test_meme_generator.py
│   └── providers/
│       ├── test_openai_provider.py
│       ├── test_xai_provider.py
│       ├── test_anthropic_provider.py
│       └── test_gemini_provider.py
└── integration/
    └── test_full_workflow.py
```

## Configuration Management

### Environment Variables
- `SCRIBE_*` prefix for all settings
- Provider-specific keys (OPENAI_API_KEY, XAI_API_KEY, etc.)
- Feature flags (SCRIBE_ENABLE_NOTES, etc.)
- Performance tuning (SCRIBE_MEME_QA_THRESHOLD, etc.)

### Configuration Precedence
1. CLI arguments (highest priority)
2. Environment variables
3. .env file
4. Default values (lowest priority)

## Security Considerations

### API Key Handling
- Never logged or printed
- Stored in environment variables
- Not included in error messages
- Validated before use

### File Operations
- Path validation and sanitization
- Atomic writes to prevent corruption
- Temporary file cleanup
- Permission checks

### External Process Execution
- Input sanitization for FFmpeg
- Timeout protection
- Resource limits
- Error output sanitization

## Extensibility

### Adding a New Provider
1. Implement `AIProvider` interface
2. Add to `factory.py`
3. Update configuration
4. Add tests
5. Document capabilities

### Adding a New Command
1. Create command function in `cli/main.py`
2. Add argument parsing
3. Implement core logic
4. Add error handling
5. Write tests
6. Update documentation

### Adding a New Feature
1. Design interface
2. Implement core logic
3. Add provider support
4. Write comprehensive tests
5. Update documentation
6. Add configuration options

## Future Architecture Considerations

### Planned Improvements
- Distributed processing across multiple GPUs
- Queue-based job processing
- REST API for remote transcription
- WebSocket for real-time progress
- Plugin system for custom processors

### Scalability
- Kubernetes deployment support
- Auto-scaling based on load
- Distributed caching
- Load balancing across providers

## References

- [Provider Pattern](https://refactoring.guru/design-patterns/provider)
- [Singleton Pattern](https://refactoring.guru/design-patterns/singleton)
- [Strategy Pattern](https://refactoring.guru/design-patterns/strategy)
- [faster-whisper Documentation](https://github.com/guillaumekln/faster-whisper)
- [OpenAI API Reference](https://platform.openai.com/docs/api-reference)
