# Scribe

**GPU-Accelerated Speech Intelligence for Teams, Creators, and Engineers**

Scribe transforms spoken content into structured understanding. It combines GPU-accelerated speech recognition with large language models to deliver accurate transcription, intelligent summaries, and creative humor automatically.

## Latest: v2.3.1

**What's New:**
- **Gemini 3 Pro support**: Advanced reasoning with 1M token context
- **Joke bake-off**: All providers compete, best joke wins (enabled by default)
- **Clean UX**: Competition runs in background, you just get the best result
- **Improved formatting**: No emojis or em-dashes in generated jokes

**Previous (v2.3.0): Production-Grade Music Transcription**
- Segment-based architecture that filters hallucinations
- Complete lyric extraction in 99 languages
- 45s processing for 3-minute songs

See [Music Mode Architecture](docs/MUSIC_MODE_ARCHITECTURE.md) and [Architecture Deep Dive](docs/ARCHITECTURE_DEEP_DIVE.md) for technical details.

## What Scribe Is

Scribe is a complete transcription and analysis pipeline optimized for NVIDIA RTX hardware (up to 12x real-time on RTX 4090). When GPU resources aren't available, it automatically falls back to OpenAI API. Every part of the workflow—from recording to final document generation—is automated and customizable.

**Core Value:**
- Record or import audio/video
- Get accurate transcripts with speaker identification (speech and music)
- Receive structured meeting notes with decisions and action items
- Optional context-aware humor (jokes and memes with QA loop)
- Output in TXT, DOCX, Markdown, and PNG formats

**Quality Focus:** Clean code, thoughtful architecture, comprehensive testing. See [Architecture Deep Dive](docs/ARCHITECTURE_DEEP_DIVE.md) for technical details and [Excellence Plan](docs/CODE_EXCELLENCE_PLAN.md) for our approach.

## Key Capabilities

### Transcription
- GPU-accelerated local processing (11x real-time on RTX 4090 with Whisper large-v3)
- Automatic fallback to OpenAI API when GPU unavailable
- Batch processing for multiple files
- **Production-grade music transcription** with separation-first architecture
  - Hybrid Transformer Demucs vocal isolation
  - Silero VAD vocal segment detection
  - Hallucination filtering on instrumental tracks
  - True multi-language lyric extraction (99 languages)
- Custom vocabulary for domain-specific terms
- Speaker diarization via OpenAI API
- Multi-language support (ISO 639-1 codes)
- Professional audio normalization

### Intelligence & Analysis
- GPT-5 structured meeting notes with business and technical insights
- Context-aware joke generation (10 comedy archetypes)
- Joke bake-off: All providers compete, best joke wins
- Meme generation with QA loop and quality scoring
- Meme bake-off: All providers compete, funniest concept wins
- Multi-provider support (OpenAI, XAI/Grok, Anthropic Claude, Google Gemini 3)
- Configurable humor intensity (0-10 spice levels)

### Recording & Integration
- OBS Studio integration via WebSocket v5
- Direct recording from CLI with defensive verification
- Detects if recording actually started (warns if not)
- Real-time feedback on recording status
- Auto-transcription after recording
- Clickable file paths in output (Ctrl+Click to open)
- Cross-platform (Windows, macOS, Linux)

### Reliability
- GPU resource management (prevents OOM crashes)
- Atomic file writes (prevents corruption)
- Adaptive progress tracking (learns your machine's performance)
- Comprehensive error handling with automatic fallback
- System diagnostics and health checks

## Quickstart

```bash
# Transcribe a single file
scribe meeting.mp4

# Batch process multiple files
scribe batch *.mp4

# Transcribe music/lyrics (handles instrumental tracks)
scribe music song.mp3

# With custom vocabulary for technical terms
scribe transcribe meeting.mp4 --vocabulary tech-terms.txt

# Record with OBS and auto-transcribe
scribe rec "Team Meeting"

# Generate notes from existing transcript
scribe notes transcript.txt

# System diagnostics
scribe doctor
```

## Installation

### Requirements

**For GPU Transcription (Optional):**
- NVIDIA GPU with CUDA support (RTX 4090 optimized)
- 8GB VRAM minimum, 24GB recommended
- CUDA 12.4 or newer
- FFmpeg

**For API Transcription (Automatic Fallback):**
- OpenAI API key
- Stable internet connection

**Common:**
- Python 3.10 or newer
- FFmpeg for media conversion
- OBS Studio (optional, for recording)

### Install Steps

**Option A: API-Only (No GPU)**
```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
pip install -r requirements.txt
pip install -e .
```

**Option B: Full GPU Acceleration**
```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
pip install -e .
```

**Optional: Additional AI Providers**
```bash
# XAI/Grok (47x cheaper for jokes/notes/memes)
pip install openai

# Anthropic Claude
pip install anthropic

# Google Gemini
pip install google-genai Pillow
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env`:
```env
# Required for API transcription
OPENAI_API_KEY=sk-proj-...

# Optional: XAI/Grok (recommended for cost savings)
XAI_API_KEY=xai-...

# Optional: Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-...

# Optional: Google Gemini
GEMINI_API_KEY=...

# Output directory
SCRIBE_OUTPUT_FOLDER=/path/to/scribe/output

# Defaults
SCRIBE_DEFAULT_MODEL=large-v3
SCRIBE_DEFAULT_LANGUAGE=en

# OBS WebSocket (for recording)
SCRIBE_OBS_HOST=localhost
SCRIBE_OBS_PORT=4455
SCRIBE_OBS_PASSWORD=your_password
```

## Core Concepts

### Transcription Pipeline

**1. Audio Preprocessing**
- Converts input to 16kHz mono WAV
- Applies professional audio normalization (dynaudnorm)
- Takes ~10% of recording duration (e.g., 5.5 min for 55 min recording)
- Ensures optimal transcription quality

**2. Transcription**
- **Local GPU:** Whisper large-v3 (maximum accuracy, 11x real-time on RTX 4090)
- **API Mode:** gpt-4o-transcribe-diarize (speaker separation, server-side chunking)
- Automatic method selection based on GPU availability

**3. Document Generation**
- Clean TXT transcript with metadata
- Formatted DOCX document
- Structured session summaries

### Meeting Notes

GPT-5 analyzes transcripts and generates structured notes:
- **Current State:** What's happening now
- **Drivers:** What's pushing things forward
- **Blockers:** What's in the way
- **Future State:** Where things are headed
- **Next Steps:** Concrete action items

### Humor Pipeline

**Jokes:**
- GPT-5 analyzes tone, rhythm, and intent
- Selects from 10 comedy archetypes
- Generates context-aware observations

**Memes:**
- AI proposes template and caption
- Generates base image without text (cleaner results)
- Overlays text locally with Pillow (readable, professional)
- QA loop evaluates image quality and template accuracy
- Iterates until quality threshold met (default 8.0/10)
- Note: Grok images may include watermark

### Multi-Provider Architecture

Scribe uses a provider-agnostic architecture. Mix and match AI providers based on cost, performance, and features.

**Supported Providers:**
- **OpenAI:** GPT-5, GPT-4, GPT-Image-1, DALL-E, Whisper
- **XAI/Grok:** Grok 4 Fast (reasoning), Grok 2 Image
- **Anthropic:** Claude 3.5 Sonnet (text only)
- **Google Gemini:** Gemini 3 Pro (advanced reasoning), Gemini 2.5 Flash/Pro (text), Imagen 4 (images)

**Configuration:**
```bash
# Use Grok for jokes, memes, notes (47x cheaper!)
export SCRIBE_JOKE_PROVIDER=xai
export SCRIBE_MEME_PROVIDER=xai
export SCRIBE_NOTES_PROVIDER=xai
export XAI_API_KEY=your_key

# Or use Gemini
export SCRIBE_JOKE_PROVIDER=gemini
export GEMINI_API_KEY=your_key

# Enable bake-off mode (all providers compete for best joke/meme)
export SCRIBE_ENABLE_JOKE_BAKEOFF=true
export SCRIBE_ENABLE_MEME_BAKEOFF=true

# Meme text rendering (default: local for clean text)
export SCRIBE_MEME_TEXT_METHOD=local  # or "ai" (not recommended - often gibberish)
```

**Cost Comparison (per 1M tokens):**
- Grok 4 Fast: $0.20 input / $0.50 output
- Claude 3.5 Sonnet: $3.00 input / $15.00 output
- GPT-5: $3.00 input / $15.00 output

**Images:**
- Grok 2 Image: $0.10 per image
- GPT-Image-1: $0.40 per image

### Custom Vocabulary

Improve accuracy for domain-specific terms, proper nouns, and technical jargon.

**Formats:**
- Plain text (.txt): One term per line, # for comments
- JSON (.json): Array of strings

**Example vocabulary.txt:**
```
# Cloud Services
Kubernetes
PostgreSQL
AWS Lambda

# Company Terms
Acme Corporation
Project Phoenix
```

**Usage:**
```bash
scribe transcribe meeting.mp4 --vocabulary tech-terms.txt
scribe batch *.mp4 --vocabulary company-names.json
```

### Music Mode

Production-grade music transcription using separation-first architecture for complete, accurate lyrics with aggressive hallucination filtering.

**Key Features:**
- **Segment-based transcription**: Slices vocals by VAD timestamps, transcribes each segment independently
- **Complete lyrics capture**: Gets full song lyrics from start to finish (no missing verses)
- **Hallucination filtering**: Per-segment filtering removes "Thanks for watching", "Subscribe", etc.
- **Multi-language support**: Auto-detects 99 languages (Spanish, Portuguese, Japanese, etc.)
- **Intelligent instrumental detection**: Gracefully identifies tracks with no vocals
- **Measurable metadata only**: Duration, BPM (if detected), Key (if detected) - no genre guessing
- **Batch processing**: Process entire folders or multiple files at once
- **Automatic cleanup**: Removes intermediate files after processing

**How It Works (Separation-First Architecture):**
1. **Music Analysis** (~1s): Validates track is music, extracts BPM/key if detectable
2. **Vocal Separation** (~25s): Hybrid Transformer Demucs isolates vocals from instruments
3. **Vocal Activity Detection** (~1s): Silero VAD finds 16-25 vocal segments per song
4. **Audio Slicing** (~1s): Cuts vocals.wav into segments based on VAD timestamps
5. **Segment Transcription** (~15s): Faster-Whisper transcribes each segment independently
6. **Hallucination Filtering**: Removes false positives per-segment (multilingual patterns)
7. **Reassembly**: Combines segments into complete, clean lyrics

**Total Processing Time**: ~45 seconds for a 3-minute song

**Output Files:**
- `song_lyrics.txt` - Complete lyrics with metadata header (Duration, BPM, Key)
- `instrumental_lyrics.txt` - "[Instrumental - No Speech Detected]" for instrumental tracks

**Usage:**
```bash
# Single file (auto-detects language)
scribe music song.mp3

# Multiple files with wildcards
scribe music album/*.flac

# Entire folder (processes all audio files)
scribe music /path/to/music/folder

# Force specific language (skips detection)
scribe music song.mp3 --language es

# Force local processing
scribe music song.mp3 --method local
```

**Supported Languages:**
English, Spanish, French, German, Italian, Portuguese, Dutch, Russian, Chinese, Japanese, Korean, Arabic, Hindi, and 86 more.

**Behavior:**
- Instrumental tracks detected early (no wasted transcription time)
- Multi-language lyrics transcribed accurately in original language
- Hallucinations filtered (e.g., "Thank you for watching", "Transcription by CastingWords")
- Sparse lyrics preserved (techno/EDM with few words)
- Original audio files never modified
- Converted WAV files automatically cleaned up

## CLI Cheatsheet

### Transcription
```bash
# Single file
scribe transcribe meeting.mp4
scribe meeting.mp4  # Shortcut

# Batch processing
scribe batch *.mp4
scribe batch file1.wav file2.wav file3.wav

# Music/lyrics transcription (handles instrumental tracks gracefully)
scribe music song.mp3                    # Single file
scribe music album/*.flac --method local # Multiple files
scribe music /path/to/music/folder       # Entire folder

# Force specific method
scribe transcribe audio.wav --method local
scribe transcribe audio.wav --method openai

# With options
scribe transcribe meeting.mp4 \
  --vocabulary tech-terms.txt \
  --language es \
  --no-joke \
  --no-meme
```

### Recording
```bash
# Record and auto-transcribe
scribe rec "Team Meeting"
scribe record --name "Board Meeting"

# Record only (no transcription)
scribe record --no-auto-transcribe
```

**Recording Behavior:**
- Connects to OBS via WebSocket (preferred method)
- Falls back to CLI control if WebSocket unavailable
- Monitors for new recording files in multiple locations
- Provides real-time feedback every 5 seconds while waiting
- Shows clear error with troubleshooting steps if recording doesn't start
- Verifies recording actually started before proceeding

**Output Display:**
- All file paths are clickable (Ctrl+Click or Cmd+Click to open)
- Works in Windows Terminal, iTerm2, VS Code terminal, and most modern terminals
- Shows full paths for easy copy/paste
- Cross-platform support (Windows, macOS, Linux)

### Intelligence
```bash
# Generate notes from transcript
scribe notes transcript.txt

# Generate joke
scribe joke transcript.txt --spice 5

# Generate meme
scribe meme transcript.txt --qa-threshold 8.5
```

### Utilities
```bash
# System diagnostics
scribe doctor

# Provider health check
scribe health
scribe health --provider gemini

# System info
scribe info

# Version
scribe version

# Clean up recordings (remove silence)
scribe clean long_recording.mp4
scribe clean recording.mp4 --analyze  # Preview only
```

### Key Options
- `--method auto|local|openai` - Transcription method
- `--model large-v3|large-v2|medium` - Whisper model
- `--language en|es|fr|de|zh|ja` - Language (ISO 639-1)
- `--vocabulary FILE` - Custom vocabulary
- `--provider openai|xai|anthropic|gemini` - AI provider
- `--no-joke` - Skip joke generation
- `--no-meme` - Skip meme generation
- `--no-notes` - Skip meeting notes
- `--no-docx` - Skip DOCX generation

## Architecture Overview

```
┌─────────────────────────────────────────┐
│            Scribe CLI                   │
├─────────────────────────────────────────┤
│  Commands: transcribe, batch, rec,      │
│            notes, joke, meme            │
└──────────────┬──────────────────────────┘
               │
    ┌──────────┴──────────┐
    ▼                     ▼
┌─────────┐         ┌──────────┐
│ Record  │         │Transcribe│
│ (OBS)   │         │          │
└────┬────┘         └────┬─────┘
     │                   │
     └───────┬───────────┘
             ▼
      ┌──────────────┐
      │  Converter   │
      │  (FFmpeg)    │
      └──────┬───────┘
             │
      ┌──────┴───────┐
      ▼              ▼
┌──────────┐   ┌──────────┐
│  Local   │   │ OpenAI   │
│ Whisper  │   │   API    │
│  (GPU)   │   │          │
└────┬─────┘   └────┬─────┘
     │              │
     └──────┬───────┘
            ▼
     ┌──────────────┐
     │  Documents   │
     │  Generator   │
     └──────┬───────┘
            │
     ┌──────┴───────┐
     ▼              ▼
┌──────────┐   ┌──────────┐
│  Notes   │   │  Humor   │
│  (GPT-5) │   │ (Jokes/  │
│          │   │  Memes)  │
└──────────┘   └──────────┘
```

### Key Components

**Core:**
- `transcriber.py` - Orchestrates transcription workflow
- `converter.py` - Audio/video format conversion
- `local_whisper.py` - GPU-accelerated transcription
- `openai_api.py` - API transcription with diarization
- `recorder.py` - OBS Studio integration

**Intelligence:**
- `notes_generator.py` - GPT-5 meeting analysis
- `joke_generator.py` - Context-aware humor
- `meme_generator.py` - Meme creation with QA loop
- `meme_compositor.py` - Text overlay rendering

**Providers:**
- `base.py` - Provider abstraction layer
- `openai_provider.py` - OpenAI integration
- `xai_provider.py` - XAI/Grok integration
- `anthropic_provider.py` - Anthropic Claude integration
- `gemini_provider.py` - Google Gemini integration
- `health.py` - Provider health monitoring

**Utilities:**
- `gpu_manager.py` - GPU resource management
- `progress.py` - Adaptive progress tracking
- `safe_write.py` - Atomic file operations
- `diagnostics.py` - System health checks
- `vocabulary.py` - Custom vocabulary handling

## Development

### Project Structure
```
scribe/
├── src/scribe/
│   ├── cli/              # Command-line interface
│   ├── core/             # Core transcription logic
│   ├── models/           # Configuration and data models
│   ├── providers/        # AI provider integrations
│   ├── utils/            # Utilities and helpers
│   └── exceptions.py     # Exception hierarchy
├── tests/
│   ├── unit/             # Unit tests
│   ├── integration/      # Integration tests
│   └── conftest.py       # Test configuration
├── docs/                 # Documentation
├── examples/             # Example files
└── output/               # Default output directory
```

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/

# With coverage
pytest --cov=scribe --cov-report=term-missing

# Quick check
pytest tests/unit/ --tb=no -q
```

**Test Status:**
- 595 tests passing (100% pass rate)
- Zero test failures
- Comprehensive defensive test coverage
- Exception handling fully tested

### Code Quality

**Standards:**
- PhD-level documentation for core modules
- Structured logging with context
- Comprehensive error handling
- Type hints throughout
- Defensive programming patterns

**Tools:**
- pytest for testing
- pytest-cov for coverage
- Rich for terminal output
- Typer for CLI

### Contributing

Priority areas:
1. Test coverage improvements
2. Performance optimizations
3. Documentation enhancements
4. Bug fixes and stability

See `docs/CODE_QUALITY_STANDARDS.md` for detailed guidelines.

## Performance and Tuning

### Local GPU Performance

| GPU | VRAM | Model | Beam Size | Speed |
|-----|------|-------|-----------|-------|
| RTX 4090 | 24GB | large-v3 | 10 | 11x real-time |
| RTX 4080 | 16GB | large-v3 | 8 | 8x real-time |
| RTX 3090 | 24GB | large-v3 | 5 | 6x real-time |

**Note:** Audio preprocessing adds ~10% of recording duration (e.g., 5.5 min for 55 min recording). We prioritize quality over speed.

### API Mode

- gpt-4o-transcribe handles long files with server-side chunking
- Typical cost: ~$0.006 per minute
- Files over 25MB compressed automatically

### Audio Recommendations

- 16kHz mono WAV input for best local results
- Normalize to -16 LUFS integrated loudness
- Minimize background noise
- Use quality microphones

## Troubleshooting

### GPU Not Detected
```bash
python -c "import torch; print(torch.cuda.is_available())"
```
If False, install CUDA-capable PyTorch:
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

### FFmpeg Not Found
```bash
# Windows
winget install FFmpeg.FFmpeg

# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

### Poor Transcription Quality
- Scribe uses large-v3 by default (maximum accuracy)
- Ensure clean audio with minimal background noise
- Check microphone quality and placement
- Audio normalization is automatic

### API Errors
- Verify API keys with `scribe info`
- Check API quota and billing
- Ensure stable network connection
- Use `scribe health` to check provider status

### Meme Generation Issues

**Text looks bad or gibberish:**

Scribe now defaults to LOCAL text overlay (clean, readable) instead of AI-generated text:
- Base image is generated WITHOUT text
- Text is overlaid using Pillow with Impact font
- Results in professional, readable memes

If you see gibberish text, you may have `SCRIBE_MEME_TEXT_METHOD=ai` set. Change to `local`:
```bash
export SCRIBE_MEME_TEXT_METHOD=local
```

**Grok watermark on images:**

Grok's image generation API adds a watermark to images. This is a limitation of the Grok service:
- Watermark appears in corner of Grok-generated images
- To avoid: Use OpenAI for meme images: `export SCRIBE_MEME_IMAGE_PROVIDER=openai`
- OpenAI's gpt-image-1 produces clean images without watermarks

**Meme quality too low:**

Adjust the QA threshold (default 8.0/10):
```bash
export SCRIBE_MEME_QA_THRESHOLD=7.5  # More lenient
export SCRIBE_MEME_QA_THRESHOLD=9.0  # More strict
```

### OBS Recording Issues

**"No recording file detected" error:**

Scribe monitors for new recording files and provides clear feedback if recording doesn't start:

1. **Check OBS is actually recording**: Look at OBS window - is the red recording indicator showing?
2. **Check recording folder**: OBS might be recording to a different folder than expected
3. **WebSocket connection**: If WebSocket fails, Scribe falls back to CLI mode with limited control
4. **Manual start**: If automatic start fails, manually click "Start Recording" in OBS

**What Scribe does to help:**
- Shows which folders it's monitoring for recording files
- Provides progress updates every 5 seconds while waiting
- Lists possible causes and fixes if recording doesn't start
- Verifies recording actually started before proceeding

**To fix permanently:**
1. Open OBS Studio manually
2. Go to Tools > WebSocket Server Settings
3. Enable WebSocket server on port 4455
4. Disable authentication or set password in `.env`

### Exit Codes
- 0: Success
- 1: General failure
- 2: Invalid arguments
- 3: External tool failure (FFmpeg, OBS, CUDA)
- 4: API error

## Documentation

### Core Documentation
- [Architecture Guide](docs/ARCHITECTURE.md) - System architecture and design patterns
- [API Reference](docs/API_REFERENCE.md) - Complete API documentation
- [Development Guide](docs/DEVELOPMENT.md) - Development setup and workflows
- [Troubleshooting Guide](docs/TROUBLESHOOTING.md) - Common issues and solutions
- [Performance Tuning](docs/PERFORMANCE_TUNING.md) - Optimization and benchmarking
- [Deployment Guide](docs/DEPLOYMENT.md) - Production deployment strategies

### Additional Resources
- [ROADMAP](ROADMAP.md) - Feature roadmap and version history
- [Code Quality Standards](docs/CODE_QUALITY_STANDARDS.md) - Development standards
- [Build Status](docs/BUILD_STATUS.md) - Current build and test status
- [Documentation Index](docs/README.md) - Complete documentation index

## Security and Privacy

- Transcripts stored locally in `SCRIBE_OUTPUT_FOLDER`
- API mode sends audio to provider for processing
- Logs avoid storing raw transcript text
- For sensitive material, use local GPU mode and disable humor features

## License

MIT License. See LICENSE file.

## Acknowledgments

- [OpenAI Whisper](https://github.com/openai/whisper) - Speech recognition
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) - GPU optimization
- [Rich](https://github.com/Textualize/rich) - Terminal output
- [Typer](https://github.com/tiangolo/typer) - CLI framework

## Author

**Nick Seal**  
GitHub: [@blisspixel](https://github.com/blisspixel)

---

**Current Version:** 2.4.0  
**Build Status:** PASSING (595/595 tests)  
**Code Quality:** 100% clean (54/54 files, zero diagnostics)  
**Test Coverage:** Core transcription fully tested, OBS integration requires manual testing  
**Focus:** Excellence over features - see [ROADMAP](ROADMAP.md)  
**Last Updated:** 2025-11-20
