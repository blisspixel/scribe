# Scribe

**Speech Transcription and Summarization CLI**

Scribe converts spoken content into transcripts, notes, and optional humor outputs. It supports local GPU transcription and API-based transcription with fallback behavior.

---

## Quickstart

```bash
# Install
git clone https://github.com/blisspixel/scribe.git
cd scribe
pip install -r requirements.txt
pip install -e .

# Configure (optional for transcript-only local GPU)
cp .env.example .env
# Add OPENAI_API_KEY only for API transcription, notes, jokes, or memes

# Verify local GPU detection
scribe info

# Use
scribe meeting.mp4                    # Transcribe single file
scribe transcribe meeting.mp4 --method local
scribe batch *.mp4                    # Process multiple files
scribe music song.mp3                 # Extract lyrics
scribe rec "Team Meeting"             # Record and transcribe
scribe doctor                         # System diagnostics
```

---

## What's New in v2.4.3

- **OBS Recording Reliability**: Fixed "OBS not ready" error (code 207) when OBS is starting up - now properly retries connection
- **Windows Input Fix**: Fixed stop commands (stop, q, quit) not working during recording on Windows
- **Better Error Handling**: Improved client cleanup and retry logic for OBS WebSocket connections

See [ROADMAP](ROADMAP.md) for version history and [Architecture Guide](docs/ARCHITECTURE.md) for technical details.

## Unreleased (Current Workspace)

- **OBS Self-Healing**: Complete overhaul of OBS recording lifecycle — automatic process cleanup, crash sentinel removal, safe-mode bypass, stale recording detection, WebSocket reconnect mid-recording, deadman timers, auth mismatch detection, and actionable error messages for every failure path
- **URL Transcription**: New `scribe url <link>` command — download and transcribe from YouTube, Vimeo, Twitter/X, direct media links, and 1000+ sites via yt-dlp
- **YouTube 403 Fix**: Upgraded yt-dlp, added browser cookie support (`--cookies`), hardened retries and User-Agent
- **Animated Banner**: Bold ANSI Shadow block font with animated gradient sweep (blue→purple), cross-platform (Windows, macOS, Linux)
- **CLI Polish**: Cleaner panel headers across all commands — lowercase branding, compact info lines
- **Doctor**: Added yt-dlp check to system diagnostics
- Added terminal UI configuration: `SCRIBE_ANIMATIONS`, `SCRIBE_COLOR`, `SCRIBE_FPS`
- Added `scribe info` UI diagnostics (resolved mode, fps, terminal capabilities)
- Added optional `full` mode shimmer for spinner/status lines
- Added optional gradient branding for header lines in capable terminals
- Added conservative fallback behavior for non-interactive terminals

---

## What Scribe Does

**Core Value:**
- Record or import audio/video files
- Get accurate transcripts with speaker identification
- Receive structured meeting notes with decisions and action items
- Optional context-aware humor (jokes and memes)
- Output in TXT, DOCX, Markdown, and PNG formats

**Key Features:**
- GPU-accelerated local processing (11x real-time on RTX 4090)
- Quality-first auto model selection based on detected VRAM
- Automatic fallback to OpenAI API when GPU unavailable
- Music transcription with vocal separation
- Batch processing for multiple files
- Custom vocabulary for domain-specific terms
- Multi-provider AI support (OpenAI, XAI/Grok, Anthropic, Gemini)
- OBS Studio integration for recording

**Quality Focus:** Clean code, thoughtful architecture, comprehensive testing. Every release focuses on making existing functionality more reliable and polished.

---

## CLI Cheatsheet

### Transcription
```bash
# Single file
scribe meeting.mp4
scribe transcribe meeting.mp4

# From URL (YouTube, Vimeo, direct links, etc.)
scribe url https://www.youtube.com/watch?v=VIDEO_ID
scribe url https://vimeo.com/123456789
scribe url https://example.com/podcast.mp3 --language es
scribe url https://youtu.be/abc123 --keep-download
scribe url https://youtu.be/abc123 --cookies edge    # Use browser cookies for auth

# Batch processing
scribe batch *.mp4
scribe batch file1.wav file2.wav file3.wav

# Transcript only (no docx, notes, jokes, memes)
scribe batch *.mp4 --no-docx --no-notes --no-joke --no-meme

# Music/lyrics
scribe music song.mp3
scribe music album/*.flac --method local

# With options
scribe transcribe meeting.mp4 --vocabulary tech-terms.txt --language es
```

### Recording
```bash
# Record and auto-transcribe
scribe rec "Team Meeting"
scribe record --name "Board Meeting"

# Record only (no transcription)
scribe record --no-auto-transcribe
```

### Intelligence
```bash
# Generate notes from transcript
scribe notes transcript.md

# Generate joke
scribe joke transcript.docx --spice 5

# Generate meme
scribe meme transcript.md --qa-threshold 8.5
```
Supported transcript input formats for `notes`, `joke`, and `meme`: `.txt`, `.md`, `.docx`

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

# Show animated banner
scribe --banner
```

### Common Options
- `--method auto|local|openai` - Transcription method
- `--model large-v3|large-v2|medium|small|base|turbo` - Whisper model
- `--language en|es|fr|de|zh|ja` - Language (ISO 639-1)
- `--vocabulary FILE` - Custom vocabulary
- `--provider openai|xai|anthropic|gemini` - AI provider
- `--cookies BROWSER` - Use browser cookies for URL downloads (edge, chrome, firefox)
- `--no-docx` - Skip DOCX generation (just .txt transcript)
- `--no-notes` - Skip meeting notes
- `--no-joke` - Skip joke generation
- `--no-meme` - Skip meme generation

**Tip:** For transcript-only batch processing, use all four `--no-*` flags together

---

## Installation

### Requirements

**For GPU Transcription (Optional):**
- NVIDIA GPU with CUDA support (RTX 4090 optimized)
- 8GB VRAM minimum, 24GB recommended
- NVIDIA driver with CUDA support for your card
- `faster-whisper` / CTranslate2 must be able to see the GPU

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

**Option B: Local GPU Transcription**
```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
pip install -r requirements.txt
pip install -e .
scribe info
```

If `scribe info` does not show your GPU, verify that CTranslate2 can see CUDA:
```bash
python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"
```

**Option C: PyTorch-backed GPU Features (music/source separation, extra tooling)**
```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
pip install -e .
```

**Optional: Additional AI Providers**
```bash
# XAI/Grok (current Grok 4.20/4.3 defaults for jokes/notes/memes)
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
# Optional unless you want API transcription or AI-generated extras
OPENAI_API_KEY=sk-proj-...

# Optional: XAI/Grok
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

# Terminal UI (optional)
# off|light|full
SCRIBE_ANIMATIONS=light
# auto|always|never
SCRIBE_COLOR=auto
# UI refresh rate (2-30)
SCRIBE_FPS=10
# off to disable ASCII banner on help screen
SCRIBE_BANNER=on

# OBS WebSocket (for recording)
SCRIBE_OBS_HOST=localhost
SCRIBE_OBS_PORT=4455
SCRIBE_OBS_PASSWORD=your_password
# Optional runaway-recording protection
SCRIBE_MAX_RECORDING_HOURS=9
SCRIBE_RECORDING_WARNING_FRACTION=0.9
```

---

## Key Features

### Transcription Pipeline

**1. Audio Preprocessing**
- Converts input to 16kHz mono WAV
- Applies professional audio normalization (dynaudnorm)
- Takes ~10% of recording duration (e.g., 5.5 min for 55 min recording)
- Ensures optimal transcription quality

**2. Transcription**
- **Local GPU:** Whisper large-v3 (11x real-time on RTX 4090 in project benchmarks)
- **API Mode:** gpt-4o-transcribe-diarize (speaker separation, server-side chunking)
- Automatic method selection based on GPU availability

**3. Document Generation**
- Clean TXT transcript with metadata
- Formatted DOCX document
- Structured session summaries

### Music Transcription

Music transcription uses a separation-first architecture to improve lyrics capture quality.

**Key Features:**
- Segment-based transcription with VAD timestamps
- Complete lyrics capture (no missing verses)
- Hallucination filtering (removes "Thanks for watching", "Subscribe", etc.)
- Multi-language support (99 languages)
- Intelligent instrumental detection
- Batch processing for entire music libraries

**How It Works:**
1. Music Analysis (~1s): Validates track, extracts BPM/key if detectable
2. Vocal Separation (~25s): Hybrid Transformer Demucs isolates vocals
3. Vocal Activity Detection (~1s): Silero VAD finds 16-25 vocal segments
4. Audio Slicing (~1s): Cuts vocals into segments
5. Segment Transcription (~15s): Faster-Whisper transcribes each segment
6. Hallucination Filtering: Removes false positives per-segment
7. Reassembly: Combines segments into complete lyrics

**Total Processing Time**: ~45 seconds for a 3-minute song

**Usage:**
```bash
scribe music song.mp3                    # Single file
scribe music album/*.flac                # Multiple files
scribe music /path/to/music/folder       # Entire folder
scribe music song.mp3 --language es      # Force language
```

See [Music Mode Architecture](docs/features/MUSIC_MODE_ARCHITECTURE.md) for technical details.

### Meeting Notes

GPT-5.2 analyzes transcripts and generates structured notes:
- **Current State:** What's happening now
- **Drivers:** What's pushing things forward
- **Blockers:** What's in the way
- **Future State:** Where things are headed
- **Next Steps:** Concrete action items

### Humor Pipeline

**Jokes:**
- GPT-5.2 analyzes tone, rhythm, and intent
- Selects from 10 comedy archetypes
- Generates context-aware observations
- Optional bake-off mode (all providers compete)

**Memes:**
- AI proposes template and caption
- Generates base image without text
- Overlays text locally with Pillow (clean, readable)
- QA loop evaluates quality (default 8.0/10 threshold)
- Optional bake-off mode (all providers compete)

### Multi-Provider Support

Mix and match AI providers based on cost, performance, and features.

**Supported Providers:**
- **OpenAI:** GPT-5.2, GPT-5, GPT-5 mini, GPT-Image-1, DALL-E, Whisper
- **XAI/Grok:** Grok 4.3, Grok 4.20 non-reasoning, Grok Imagine Image
- **Anthropic:** Claude 3.5 Sonnet (text only)
- **Google Gemini:** Gemini 3 Pro, Gemini 3 Flash, Imagen 4 (images)

**Configuration:**
```bash
# Example: use XAI for jokes, memes, notes
export SCRIBE_JOKE_PROVIDER=xai
export SCRIBE_MEME_PROVIDER=xai
export SCRIBE_NOTES_PROVIDER=xai

# Enable bake-off mode (all providers compete)
export SCRIBE_ENABLE_JOKE_BAKEOFF=true
export SCRIBE_ENABLE_MEME_BAKEOFF=true
```

**Cost Comparison (per 1M tokens):**
- Grok 4.3: $1.25 input / $2.50 output
- GPT-5.2: $1.75 input / $14.00 output
- GPT-5: $1.25 input
- Claude 3.5 Sonnet: $3.00 input / $15.00 output

**Images:**
- Grok Imagine Image: priced per image by xAI
- GPT-Image-1: $0.40 per image

**xAI lifecycle note:** Scribe defaults avoid the Grok 4/4.1 Fast model IDs retired by xAI on 2026-05-15.
When xAI returns exact `cost_in_usd_ticks`, Scribe records the converted request cost in AI metrics; otherwise it falls back to local estimates for known xAI defaults.

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

### OBS Recording Integration

**Features:**
- WebSocket v5 integration (preferred)
- CLI fallback if WebSocket unavailable
- Automatic OBS launch with safe-mode bypass
- Stale process cleanup before fresh launch
- Stops leftover recordings before starting new ones
- WebSocket auto-reconnect if connection drops mid-recording
- Deadman timer prevents infinite hangs on stop
- Ctrl-C works even without interactive terminal (piped stdin, CI)
- Auth mismatch detection with actionable error messages
- Verifies recording actually started
- Auto-transcription after recording

**Output:**
- Clickable file paths (Windows Terminal, iTerm2, VS Code)
- Full paths for easy copy/paste
- Cross-platform support

---

## Performance

### Local GPU Performance

| GPU | VRAM | Model | Beam Size | Speed |
|-----|------|-------|-----------|-------|
| RTX 4090 | 24GB | large-v3 | 10 | 11x real-time |
| RTX 4080 | 16GB | large-v3 | 8 | 8x real-time |
| RTX 3090 | 24GB | large-v3 | 5 | 6x real-time |

**Note:** Audio preprocessing adds ~10% of recording duration. We prioritize quality over speed.

### API Mode

- gpt-4o-transcribe handles long files with server-side chunking
- Typical cost: ~$0.006 per minute
- Files over 25MB compressed automatically

### Audio Recommendations

- 16kHz mono WAV input is recommended for local transcription
- Normalize to -16 LUFS integrated loudness
- Minimize background noise
- Use quality microphones

---

## Architecture

```
┌─────────────────────────────────────────┐
│            Scribe CLI                   │
├─────────────────────────────────────────┤
│  Commands: transcribe, url, batch, rec, │
│            notes, joke, meme            │
└──────────────┬──────────────────────────┘
               │
    ┌──────────┼──────────┐
    ▼          ▼          ▼
┌─────────┐ ┌──────────┐ ┌──────────┐
│ Record  │ │Transcribe│ │URL       │
│ (OBS)   │ │          │ │Download  │
└────┬────┘ └────┬─────┘ │(yt-dlp)  │
     │           │       └────┬─────┘
     └───────┬───┴────────────┘
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
│(GPT-5.2) │   │ (Jokes/  │
│          │   │  Memes)  │
└──────────┘   └──────────┘
```

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

### Key Components

**Core:**
- `transcriber.py` - Orchestrates transcription workflow
- `converter.py` - Audio/video format conversion
- `downloader.py` - URL media download (yt-dlp)
- `local_whisper.py` - GPU-accelerated transcription
- `openai_api.py` - API transcription with diarization
- `recorder.py` - OBS Studio integration

**Intelligence:**
- `notes_generator.py` - GPT-5.2 meeting analysis
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
- `banner.py` - Animated ASCII banner with gradient sweep
- `branding.py` - Gradient header markup
- `terminal_ui.py` - Terminal capability detection

See [Architecture Guide](docs/ARCHITECTURE.md) for detailed technical discussion.

---

## Development

### Running Tests

```bash
# All tests
pytest

# Unit tests only
pytest tests/unit/

# With coverage
pytest --cov=scribe --cov-report=term-missing
# Coverage must stay at or above 80%
pytest --cov=scribe --cov-report=term-missing --cov-fail-under=80

# Quick check
pytest tests/unit/ --tb=no -q

# Skip end-to-end tests that require external API access
pytest -q -k 'not e2e'
```

**Test Status:**
- Large unit/integration/e2e test suite
- Platform-specific skips in some environments
- End-to-end tests may require a valid `OPENAI_API_KEY`
- Use the commands above to verify in your environment

### Code Quality

**Standards:**
- Structured logging with context
- Error handling with fallback paths
- Type hints in core modules
- Test coverage for key workflows

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

See [Development Guide](docs/DEVELOPMENT.md) for detailed guidelines.

---

## Troubleshooting

### GPU Not Detected
```bash
scribe info
python -c "import ctranslate2; print(ctranslate2.get_cuda_device_count())"
```

If `ctranslate2.get_cuda_device_count()` returns `0`, Scribe will not use local faster-whisper. Check your NVIDIA driver and CUDA runtime first.

When local transcription runs for the first time, faster-whisper automatically downloads the selected model and caches it for later runs.

If you also want PyTorch-backed GPU features, verify PyTorch separately:
```bash
python -c "import torch; print(torch.cuda.is_available(), torch.__version__, torch.version.cuda)"
```

If PyTorch reports `False`, install CUDA-capable PyTorch:
```bash
pip install --upgrade torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
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
- Scribe uses large-v3 by default for strong baseline accuracy
- Ensure clean audio with minimal background noise
- Check microphone quality and placement
- Audio normalization is automatic

### API Errors
- Verify API keys with `scribe info`
- Check API quota and billing
- Ensure stable network connection
- Use `scribe health` to check provider status

### URL Download Errors (403 Forbidden)

YouTube and other sites frequently change their anti-bot protections. If `scribe url` fails with a 403:

```bash
# 1. Update yt-dlp (most common fix)
pip install --upgrade yt-dlp

# 2. Try with browser cookies (authenticates via your logged-in browser session)
scribe url https://youtu.be/VIDEO_ID --cookies edge
scribe url https://youtu.be/VIDEO_ID --cookies chrome
scribe url https://youtu.be/VIDEO_ID --cookies firefox

# 3. Run diagnostics
scribe doctor
```

Scribe automatically sets a browser User-Agent and retries with exponential backoff (up to 10 attempts).

### Meme Generation Issues

**Text looks bad or gibberish:**
- Scribe defaults to LOCAL text overlay (clean, readable)
- If you see gibberish, change: `export SCRIBE_MEME_TEXT_METHOD=local`

**Grok watermark on images:**
- Grok adds watermarks to images
- To avoid: `export SCRIBE_MEME_IMAGE_PROVIDER=openai`

**Meme quality too low:**
- Adjust threshold: `export SCRIBE_MEME_QA_THRESHOLD=7.5` (more lenient)

### OBS Recording Issues

**"Could not connect to OBS WebSocket":**

1. Ensure OBS WebSocket server is enabled: Tools → WebSocket Server Settings
2. Check `SCRIBE_OBS_PASSWORD` in `.env` matches the OBS WebSocket password
3. Scribe auto-launches OBS if not running — no need to start it manually

**"No recording file detected" error:**

1. Check OBS Settings → Output → Recording Path matches your `SCRIBE_OUTPUT_FOLDER`
2. Scribe searches the OBS recording directory for 15 seconds after stop
3. If OBS records to a different folder, Scribe will tell you where it looked

**OBS keeps asking about safe mode:**

Scribe now handles this automatically — it kills stale OBS processes, cleans crash sentinel files, and launches with `--disable-shutdown-check`. If you still see the safe mode dialog, delete `%APPDATA%/obs-studio/global.ini` manually.

**To configure OBS WebSocket:**
1. Open OBS Studio
2. Go to Tools > WebSocket Server Settings
3. Enable WebSocket server on port 4455
4. Set password in `.env`

### Exit Codes
- 0: Success
- 1: General failure
- 2: Invalid arguments
- 3: External tool failure (FFmpeg, OBS, CUDA)
- 4: API error

See [Troubleshooting Guide](docs/TROUBLESHOOTING.md) for more solutions.

---

## Documentation

### Core Documentation
- [Architecture Guide](docs/ARCHITECTURE.md) - System architecture and design patterns
- [API Reference](docs/API_REFERENCE.md) - Complete API documentation
- [Development Guide](docs/DEVELOPMENT.md) - Development setup and workflows
- [Troubleshooting Guide](docs/TROUBLESHOOTING.md) - Common issues and solutions
- [Performance Tuning](docs/PERFORMANCE_TUNING.md) - Optimization and benchmarking
- [Deployment Guide](docs/DEPLOYMENT.md) - Production deployment strategies

### Feature Documentation
- [Music Mode Architecture](docs/features/MUSIC_MODE_ARCHITECTURE.md) - Music transcription technical details

### Additional Resources
- [ROADMAP](ROADMAP.md) - Feature roadmap and version history
- [Documentation Index](docs/README.md) - Complete documentation index
- [Documentation Structure](docs/STRUCTURE.md) - How docs are organized

---

## Security and Privacy

- Transcripts stored locally in `SCRIBE_OUTPUT_FOLDER`
- API mode sends audio to provider for processing
- Logs avoid storing raw transcript text
- For sensitive material, use local GPU mode and disable humor features

---

## License

MIT License. See LICENSE file.

---

## Acknowledgments

- [OpenAI Whisper](https://github.com/openai/whisper) - Speech recognition
- [faster-whisper](https://github.com/guillaumekln/faster-whisper) - GPU optimization
- [Rich](https://github.com/Textualize/rich) - Terminal output
- [Typer](https://github.com/tiangolo/typer) - CLI framework

---

## Author

**Nick Seal**  
GitHub: [@blisspixel](https://github.com/blisspixel)

---

**Current Version:** 2.4.3
**Build Status:** Refer to local CI/test runs
**Focus:** Reliability and maintainability - see [ROADMAP](ROADMAP.md)
**Last Updated:** 2026-03-23


