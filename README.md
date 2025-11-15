# Scribe

**GPU-Accelerated Speech Intelligence for Teams, Creators, and Engineers**

Scribe is a complete system for transforming spoken content into structured understanding. It combines the raw speed of local GPU-accelerated speech recognition with the analytical depth of large-scale language models to deliver accurate transcription, intelligent summaries, and creative humor automatically. It is built for professionals who deal with large volumes of meetings, interviews, or recordings and want more than a simple transcript.

At its core, Scribe is optimized for NVIDIA RTX hardware, reaching up to twelve times real-time speed on an RTX 4090. When GPU resources are not available, it automatically falls back to the OpenAI API, ensuring consistent accuracy and reliability on any machine. Every part of the workflow, from recording to final report generation, is designed to be both automated and customizable. Users can record directly through OBS Studio, transcribe locally or via the cloud, and immediately receive clear, human-readable documents with speaker identification and metadata.

Scribe does more than produce transcripts. It interprets the conversation, identifies the structure and intent of discussions, and turns unstructured speech into organized information. With the GPT-5 meeting analysis module, it can extract decisions, next steps, blockers, and opportunities and present them in a consistent format that fits both technical and business contexts. Output can be generated in text, Markdown, and Word documents.

For lighter moments, Scribe can analyze tone and intent to produce context-aware jokes and visual memes that are grounded in the meeting content. The humor pipeline uses explicit criteria and a short QA loop to keep output relevant and professional.

Scribe integrates Whisper for speech recognition, GPT-4o and GPT-5 for analysis, PyTorch for GPU inference, and OBS Studio for capture. The result is a tool that merges speed, comprehension, and polish. It helps convert hours of recordings into useful insight within minutes.

## What's New in 2.1

**November 2025 Release - UX & Intelligence Update**

### New in 2.1.0
- **AI-Powered Joke Selection**: GPT-5 now intelligently selects comedy archetypes based on actual meeting content
- **Stricter Meme QA**: Enhanced quality checks catch cut-off or nonsensical text, automatically retry until quality threshold met
- **Unified Command UX**: Consistent, clean interface across all commands (transcribe, joke, meme, notes)
- **Improved Progress Display**: Clear headers showing version, file, duration, and what's being generated
- **Better Output Formatting**: Simplified joke display ("Joke:" instead of archetype names)

### Implemented in 2.1.1
- **Multi-Provider AI Support**: Fully implemented across all features
  - Use XAI/Grok 4 Fast for jokes, memes, and notes (47x cheaper, lightning fast)
  - Mix providers based on cost/performance needs
  - Configure via environment: `SCRIBE_JOKE_PROVIDER=xai`
  - Provider-agnostic architecture: jokes, notes, meme concepts, and meme images
  - Universal logging with `SCRIBE_LOG_LEVEL` for clean output

## What's New in 2.0

**November 2025 Release**

### Core Features
- Meeting Notes Generator with GPT-5 multi-step reasoning for structured analysis
- GPU Resource Manager prevents OOM and manages concurrent model access
- Resource limits validation (configurable file size and duration limits)
- AsyncIO support with contextvars for modern Python async/await patterns
- Run context tracking with unique IDs for complete observability
- Atomic file writes with platform-specific handling to prevent corruption

### Transcription
- Speaker diarization via OpenAI API for multi-speaker identification
- Server-side chunking for long audio files via OpenAI API
- Performance up to 12.6x real-time on RTX 4090 with optimized settings
- Automatic fallback from GPU to API with graceful degradation

### Intelligence and Humor
- Meme QA loop with scoring and configurable thresholds (default 8.0/10)
- Humor spice levels (0-10) for configurable intensity
- New comedy archetypes: Based Observer and Gen Z Commentator
- Humor control flags (--no-joke, --no-meme) for professional contexts

### Developer Experience
- System diagnostics command for environment validation
- Enhanced CLI including `scribe <file>` and `scribe rec` shortcuts
- Test suite at 463 tests with 45% coverage
- Comprehensive error handling with context preservation

## Multi-Provider AI Support

Scribe features a **provider-agnostic architecture** that lets you mix and match AI providers based on cost, performance, and feature needs. All intelligence features (jokes, notes, memes) work seamlessly across providers.

### Supported Providers
- **OpenAI**: GPT-5, GPT-4, GPT-Image-1, DALL-E, Whisper (transcription)
- **XAI/Grok**: Grok 4 Fast (reasoning & non-reasoning), Grok 2 Image
- **Anthropic**: Claude 3.5 Sonnet (text generation, no images)

### Configuration
Set providers per-feature via environment variables:

```bash
# Use Grok for jokes, memes, and notes (47x cheaper!)
export SCRIBE_JOKE_PROVIDER=xai
export SCRIBE_MEME_PROVIDER=xai
export SCRIBE_NOTES_PROVIDER=xai
export XAI_API_KEY=your_xai_key

# Or use Claude for notes
export SCRIBE_NOTES_PROVIDER=anthropic
export ANTHROPIC_API_KEY=your_anthropic_key

# Use OpenAI for transcription
export SCRIBE_TRANSCRIBE_PROVIDER=openai
export OPENAI_API_KEY=your_openai_key

# Universal logging level
export SCRIBE_LOG_LEVEL=WARNING  # DEBUG, INFO, WARNING, ERROR
```

Or use CLI flags:
```bash
scribe joke transcript.txt --provider xai
scribe notes transcript.txt --provider anthropic
```

### Cost Comparison (per 1M tokens)
- **Grok 4 Fast**: $0.20 input / $0.50 output (47x cheaper than GPT-5)
- **Claude 3.5 Sonnet**: $3.00 input / $15.00 output
- **GPT-5**: $3.00 input / $15.00 output

**Images:**
- **Grok 2 Image**: $0.10 per image (4x cheaper than DALL-E)
- **GPT-Image-1**: $0.40 per image

### Provider Architecture
The provider system uses a unified interface that abstracts away provider-specific details. This means:
- Switch providers without changing your workflow
- Automatic failover support (coming soon)
- Easy to add new providers (Gemini, Mistral, etc.)
- **Savings**: Up to 47x cheaper for text, 4x cheaper for images

### Feature Support by Provider

| Feature | OpenAI | XAI/Grok | Anthropic | Default |
|---------|--------|----------|-----------|---------|
| Jokes | GPT-5 (reasoning) | Grok 4 Fast (reasoning) | Claude 3.5 Sonnet | XAI |
| Notes | GPT-5 (reasoning) | Grok 4 Fast (reasoning) | Claude 3.5 Sonnet | XAI |
| Meme Concepts | GPT-5 (reasoning) | Grok 4 Fast (reasoning) | Claude 3.5 Sonnet | XAI |
| Meme Images | GPT-Image-1 | Fallback to OpenAI | Not supported | OpenAI |
| Transcription | Whisper | Not supported | Not supported | OpenAI |

## Feature Summary

### Transcription
- GPU-accelerated Whisper transcription (up to 11x real-time on RTX 4090)
- Automatic fallback to OpenAI API when GPU unavailable
- Maximum quality models: Whisper large-v3 (local, best accuracy) and gpt-4o-transcribe-diarize (API)
- Professional audio preprocessing with dynaudnorm (~10x real-time, ensures optimal quality)
- Speaker diarization with OpenAI API for multi-speaker meetings
- Server-side chunking for files over 25MB with automatic compression
- Resource limits validation prevents OOM and runaway processes

### Intelligence
- GPT-5 meeting notes with business and technical structure
- Context-aware jokes with 10 comedy archetypes
- Meme generation with QA loop and scoring
- Configurable humor intensity (0-10 spice levels)
- Multi-step reasoning for structured analysis

### Reliability
- GPU Resource Manager prevents concurrent access and OOM crashes
- System diagnostics command (scribe doctor) validates environment
- Atomic file writes with platform-specific handling prevent corruption
- Run context tracking with unique IDs for complete observability
- AsyncIO support with contextvars for modern async patterns
- Smart cleanup of intermediate files with configurable retention

### Utilities
- **Silence removal** - Clean up recordings left running overnight
  - `scribe clean` removes/reduces silent sections
  - Analyze mode to preview silence without removing
  - Configurable threshold and duration settings
- **File trimming** - Cut files at specific timestamps
  - `scribe clean --trim HH:MM:SS` for precise cuts
  - Fast operation (copies without re-encoding)
  - Perfect for fixing recordings left running too long

### Output
- TXT, DOCX, Markdown notes, PNG memes
- **Adaptive progress tracking** - learns your machine's performance over time
- Live progress bars with speed and ETA calculations
- Structured metadata and session summaries
- Clean formatting with meeting metadata

### Adaptive Progress System
Scribe learns your machine's actual performance and refines progress estimates over time:
- **Step-by-step visibility**: Shows actual operations (Preparing audio, Transcribing, Generating notes, Generating joke, Generating meme, Cleaning up)
- **Meme refinement tracking**: Displays attempt number and QA scores during meme generation loops
- **Configuration display**: Shows enabled features upfront (+ notes, joke, meme)
- **First run**: Uses realistic defaults based on actual hardware measurements
- **Subsequent runs**: Adjusts percentages based on your hardware's actual speed
- **Machine-specific**: Each machine gets its own performance profile
- **Continuous improvement**: Weighted averaging (30% new data) gradually refines estimates
- **Persistent storage**: Metrics saved to `~/.scribe/performance_{machine_id}.json`

The more you use Scribe, the more accurate your progress estimates become!

### Integration
- OBS Studio integration for direct recording
- Cross-platform: Windows, macOS, Linux
- Quick commands: `scribe <file>`, `scribe rec`
- Configurable via environment variables or CLI flags
- Comprehensive error handling with actionable messages

## System Requirements

### GPU Transcription (Optional - Auto-detected)

| Component | Requirement |
|-----------|-------------|
| GPU | NVIDIA GPU with CUDA support (RTX 4090 optimized for 12.6x speed) |
| VRAM | 8 GB minimum, 24 GB recommended |
| CUDA | 12.4 or newer |
| FFmpeg | Required for media conversion |

### OpenAI API Transcription (Automatic Fallback)

| Component | Requirement |
|-----------|-------------|
| Model | gpt-4o-transcribe or gpt-4o-transcribe-diarize |
| API Key | Required |
| Network | Stable internet connection |

### Common

| Component | Requirement |
|-----------|-------------|
| Python | 3.10 or newer |
| OS | Windows 10/11, macOS 12+, or Linux |
| Tools | FFmpeg, OBS Studio for recording features |

**Note**: Scribe automatically detects if you have an NVIDIA GPU with CUDA. If detected, it uses local GPU transcription (fast). If not, it falls back to OpenAI API (still accurate, just uses cloud).

## Installation

Choose one of the paths below. All examples assume a clean virtual environment.

### Path A: API-Only (no GPU)

```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
pip install -r requirements.txt
pip install -e .
```

### Path B: Full GPU Acceleration

```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
pip install -e .
```

### Optional: Dev Extras

```bash
pip install -e ".[dev]"
```

### Optional: Additional AI Providers

```bash
# For XAI/Grok support (recommended for cost savings)
pip install openai  # XAI uses OpenAI-compatible API

# For Anthropic Claude support
pip install anthropic

# For Google Gemini support (coming soon)
# pip install google-generativeai
```

### Configure Environment

```bash
cp .env.example .env
```

Then edit `.env`:

```env
# Required for API transcription
OPENAI_API_KEY=sk-proj-...

# Optional: XAI/Grok (47x cheaper for jokes/notes/memes)
XAI_API_KEY=xai-...

# Optional: Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-...

# Output directory for artifacts
SCRIBE_OUTPUT_FOLDER=/path/to/scribe/output

# Defaults
SCRIBE_DEFAULT_MODEL=large-v3
SCRIBE_DEFAULT_LANGUAGE=en

# OBS for recording
SCRIBE_OBS_HOST=localhost
SCRIBE_OBS_PORT=4455
SCRIBE_OBS_PASSWORD=your_websocket_password

# Optional: Meme QA and Humor
SCRIBE_MEME_QA_THRESHOLD=8.0
SCRIBE_MEME_QA_ATTEMPTS=3
SCRIBE_HUMOR_SPICE=5
```

**Notes**:
- All variables use the `SCRIBE_` prefix with the exception of `OPENAI_API_KEY`
- On Windows, use forward slashes or escape backslashes in paths
- Enable OBS WebSocket in OBS Studio under Tools → WebSocket Server Settings

### Upgrade

```bash
git pull
pip install -e .
```

### Uninstall

```bash
pip uninstall scribe
```

## Quick Start

```bash
# Fast path: transcribe a file
scribe meeting.mp4

# Record using OBS and auto-transcribe
scribe rec

# Force OpenAI API
scribe transcribe interview.mp3 --method openai

# Spanish transcription
scribe transcribe podcast.wav --language es

# Generate just a joke or meme from existing transcript
scribe joke transcript.txt
scribe meme transcript.txt

# Clean up recordings left running overnight (remove silence)
scribe clean long_recording.mp4
scribe clean recording.mp4 --analyze  # Just analyze, don't remove

# System status and GPU check
scribe info
```

### Progress & UX

Scribe provides clean, informative progress for all operations:

- **Full workflows** (`transcribe`, `record`): Unified progress bar shows overall completion across all phases (preparing, transcribing, finishing)
- **Individual operations** (`joke`, `meme`, `notes`): Clean spinners with status updates
- **Adaptive estimates**: Progress percentages improve over time as Scribe learns your machine's performance
- **No clutter**: Single progress indicator, no flickering or emoji spam

## End-to-End Workflow

### Recording
Optional OBS integration records to MP4. You can trigger and stop recording from the CLI. Files are placed in the configured output folder.

### Conversion
Input media is converted to 16 kHz mono WAV with professional dynamic audio normalization (dynaudnorm). This preprocessing step takes approximately 10% of the audio duration (e.g., 5.5 minutes for a 55-minute recording) but ensures maximum transcription accuracy. In API mode, the original file is used or converted to compressed MP3 if over 25 MB.

### Transcription
Local GPU uses Whisper large-v3 for maximum accuracy. This is the highest quality Whisper model available, optimized for RTX 4090 with 11x real-time speed. Audio is preprocessed with professional-grade dynamic normalization (dynaudnorm) which takes ~10x real-time but ensures optimal transcription quality. API mode uses gpt-4o-transcribe-diarize with automatic speaker separation and server-side chunking for long audio. The method is selected automatically unless overridden.

### Document Generation
Scribe produces a clean TXT transcript and a formatted DOCX. Meeting metadata such as date and duration is included.

### Meeting Notes
GPT-5 analyzes the transcript and writes narrative and structured sections: Current State, Drivers, Blockers, Future State, and Next Steps.

### Humor and Memes
GPT-5 generates meeting-aware jokes and meme prompts. A QA loop evaluates and refines memes before saving the PNG.

### Output and Cleanup
Intermediate files are removed. Final artifacts remain in the output directory.

## Output Layout

```
output/
├── meeting_YYYY-MM-DD_HHMMSS_transcription.txt
├── meeting_YYYY-MM-DD_HHMMSS_transcription.docx
├── meeting_YYYY-MM-DD_HHMMSS_transcription_notes.md
├── meeting_YYYY-MM-DD_HHMMSS_transcription_meme.png
└── meeting_YYYY-MM-DD_HHMMSS.mp4
```

Display order on completion:
1. Joke
2. Meme
3. Notes
4. DOCX
5. TXT

## CLI Reference

All commands return a nonzero exit code on failure.

### `scribe <file>` and `scribe transcribe`

Transcribe a single audio or video file.

```bash
scribe <file>
scribe transcribe <file> [OPTIONS]
```

**Options**:
- `--method, -m [auto|local|openai]` - Select method. Default is auto.
- `--model MODEL` - Whisper model for local GPU (large-v3 = best quality, large-v2 = faster, medium = fastest).
- `--language, -l LANG` - ISO language code, default en.
- `--output, -o PATH` - Output directory. Defaults to SCRIBE_OUTPUT_FOLDER.
- `--no-joke` - Skip joke generation.
- `--no-meme` - Skip meme generation.
- `--no-notes` - Skip meeting notes generation.
- `--no-docx` - Skip DOCX document generation.
- `--keep-all` - Preserve intermediate files for debugging.

**Examples**:

```bash
# Auto method selection
scribe meeting.mp4

# Force local GPU with best quality model (default)
scribe transcribe audio.wav --method local --model large-v3

# Use faster model if speed is more important than accuracy
scribe transcribe audio.wav --method local --model large-v2

# Force OpenAI API and Spanish
scribe transcribe podcast.mp3 --method openai --language es

# Custom output folder
scribe transcribe file.wav --output ./transcripts

# Skip humor generation
scribe transcribe meeting.mp4 --no-joke --no-meme
```

### `scribe rec` and `scribe record`

Record with OBS and optionally auto-transcribe.

```bash
scribe rec [NAME]
scribe record [--name NAME] [--auto-transcribe/--no-auto-transcribe]
```

**Options**:
- `--name, -n NAME` - Meeting name for the recording
- `--auto-transcribe/--no-auto-transcribe` - Auto-transcribe after recording (default: enabled)
- `--method, -m [auto|local|openai]` - Transcription method (if auto-transcribe enabled)
- `--no-joke` - Skip joke generation
- `--no-meme` - Skip meme generation

**Behavior**:
- If a name is not provided, Scribe prompts or defaults to "Meeting"
- Recording starts in OBS, then transcription runs automatically unless disabled

**Examples**:

```bash
# Prompted name
scribe rec

# Named recording
scribe rec "Team Standup"

# Record only
scribe record --name "Board Meeting" --no-auto-transcribe

# Record without humor
scribe record --no-joke --no-meme
```

### `scribe notes`

Generate structured notes from an existing transcript file.

```bash
scribe notes <transcript.txt> [OPTIONS]
```

**Options**:
- `--output, -o PATH` - Output path for the Markdown notes file. Default is alongside transcript.
- `--model NAME` - Override notes model. Defaults to SCRIBE_NOTES_MODEL or GPT-5.

**What it does**:
- Reads the transcript and runs multi-step reasoning
- Produces a narrative summary and a structured analysis with the sections: Current State, Drivers, Blockers, Future State, Next Steps
- Writes Markdown

**Examples**:

```bash
# Default output next to transcript
scribe notes transcript.txt

# Custom output location
scribe notes transcript.txt --output ./notes/meeting.md

# Explicit model override
scribe notes transcript.txt --model gpt-5
```

### `scribe joke`

Generate a context-aware joke from a transcript.

```bash
scribe joke <transcript.txt> [OPTIONS]
```

**Options**:
- `--spice INT` - Humor intensity 0-10 (overrides SCRIBE_HUMOR_SPICE).
- `--show-reasoning` - Shows GPT-5's analysis process.

**Behavior**:
- Uses GPT-5 to analyze tone, rhythm, and intent
- Selects one of eight archetypes and emits a short observation
- Optionally shows reasoning

**Examples**:

```bash
scribe joke transcript.txt
scribe joke transcript.txt --spice 8
scribe joke transcript.txt --show-reasoning
```

### `scribe meme`

Generate a meme image from a transcript with a QA loop.

```bash
scribe meme <transcript.txt> [OPTIONS]
```

**Options**:
- `--output, -o PATH` - Output path for the PNG file.
- `--qa-threshold FLOAT` - Overrides SCRIBE_MEME_QA_THRESHOLD.
- `--qa-attempts INT` - Overrides SCRIBE_MEME_QA_ATTEMPTS.
- `--spice INT` - Humor intensity 0-10 (overrides SCRIBE_HUMOR_SPICE).
- `--show-reasoning` - Prints intermediate evaluations and selected template.

**Behavior**:
- Reads the transcript
- Proposes a meme template and caption
- Renders an image and evaluates it for composition, readability, and accuracy
- Iterates until the threshold score is met or attempts are exhausted

**Examples**:

```bash
# Default output next to transcript
scribe meme transcript.txt

# Super spicy humor
scribe meme transcript.txt --spice 10

# Mild, office-safe humor
scribe meme transcript.txt --spice 3

# Custom output and stricter QA
scribe meme transcript.txt --output ./memes/board.png --qa-threshold 9.2 --qa-attempts 3 --show-reasoning
```

### `scribe doctor`

Run system diagnostics and health checks.

```bash
scribe doctor
```

**What it checks:**
- Python version (3.10+ required)
- FFmpeg and FFprobe availability
- CUDA and GPU detection
- OpenAI API key configuration
- Output folder permissions
- Disk space
- .env file presence

**Output:** Provides actionable suggestions for fixing any issues found.

### `scribe info`

Show environment, GPU, and configuration details.

```bash
scribe info
```

### `scribe version`

Print the current Scribe version.

```bash
scribe version
```

## Configuration Details

### Environment variables:

| Variable | Purpose | Default |
|----------|---------|---------|
| OPENAI_API_KEY | Required for API transcription, diarization, humor, memes | none |
| SCRIBE_OUTPUT_FOLDER | Base output directory | ./output |
| SCRIBE_DEFAULT_MODEL | Default local Whisper model | large-v3 |
| SCRIBE_DEFAULT_LANGUAGE | Default language code | en |
| SCRIBE_OBS_HOST | OBS WebSocket host | localhost |
| SCRIBE_OBS_PORT | OBS WebSocket port | 4455 |
| SCRIBE_OBS_PASSWORD | OBS WebSocket password | none |
| SCRIBE_MEME_QA_THRESHOLD | Meme acceptance score 0.0–10.0 | 8.0 |
| SCRIBE_MEME_QA_ATTEMPTS | Max meme iterations | 3 |
| SCRIBE_ENABLE_NOTES | Enable note generation in pipelines | true |
| SCRIBE_NOTES_MODEL | Model for notes generation | gpt-5 |
| SCRIBE_HUMOR_SPICE | Humor intensity level 0–10 (0=off, 5=default, 10=spicy) | 5 |

**Notes on diarization**:
- Speaker diarization is provided by OpenAI in API mode
- Local diarization with Whisper is not enabled by default

## Performance and Tuning

### Local GPU:
- RTX 4090 (24GB): Uses large-v3 with beam size 10 for maximum accuracy (~11x real-time)
- RTX 4080 (16GB): Uses large-v3 with beam size 8 for balanced performance (~8x real-time)
- RTX 3090 (24GB): Uses large-v3 with beam size 5 for stability (~6x real-time)
- Beam size settings affect quality and speed. Higher beam sizes improve accuracy but slow inference
- Audio preprocessing adds ~10% of recording duration (e.g., 5.5 min for 55 min recording)
- We prioritize transcription quality over speed - large-v3 + dynaudnorm provides best accuracy

### API mode:
- gpt-4o-transcribe handles long files with server-side chunking
- Typical cost around $0.006 per minute
- Files above provider size thresholds are compressed automatically when possible

### Audio recommendations:
- 16 kHz mono WAV input yields more stable results for local Whisper
- Normalize to −16 LUFS integrated loudness and −1.5 dB true peak

## Troubleshooting

### GPU not detected:

```bash
python -c "import torch; print(torch.cuda.is_available())"
```

If False, install CUDA-capable PyTorch:

```bash
conda install pytorch torchvision torchaudio pytorch-cuda=12.4 -c pytorch -c nvidia
```

### FFmpeg not found:

```bash
# Windows
winget install FFmpeg.FFmpeg

# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

### Poor transcription quality:
- Scribe uses `large-v3` by default for maximum accuracy
- Ensure clean audio input with minimal background noise
- Check that audio is properly normalized (automatic with Scribe)
- Verify microphone placement and recording quality

### API errors:
- Verify OPENAI_API_KEY or XAI_API_KEY with `scribe info`
- Check API quota and billing
- Ensure a stable network connection

### Garbled text output (Windows):
If joke or meme text shows weird characters (ô instead of quotes), set UTF-8 encoding:

```powershell
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

Or add to your PowerShell profile for permanent fix:
```powershell
notepad $PROFILE
# Add: [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
```

### Exit codes:
- 0: success
- 1: general failure
- 2: invalid arguments or missing input
- 3: external tool failure (FFmpeg, OBS, CUDA)
- 4: API error

### Logs:
- Structured logs are written to `./logs` with timestamps per run
- Increase verbosity with `--verbose` where supported

### Disk space:
- Scribe warns when low on disk space. Clean old outputs or set a larger SCRIBE_OUTPUT_FOLDER

## Testing

### Quick start:

```bash
pytest
```

### Selective:

```bash
pytest tests/unit/
pytest tests/integration/
pytest -m "not gpu"
```

### Coverage:

```bash
pytest --cov=scribe --cov-report=term-missing
pytest --cov=scribe --cov-report=html
```

### Coverage highlights:
- Overall 45% across 463 tests
- Exception handling 100%
- Run context 100%
- Logging 100%
- Config 95%
- Session 93%
- Diagnostics 91%
- DOCX converter 89%
- File operations 88%
- Safe writes 78%
- CLI commands 50%

## Project Structure

```
scribe/
├── src/scribe/
│   ├── cli/
│   │   ├── main.py
│   │   └── mobile.py
│   ├── core/
│   │   ├── converter.py
│   │   ├── transcriber.py
│   │   ├── local_whisper.py
│   │   ├── openai_api.py
│   │   └── recorder.py
│   ├── models/
│   │   ├── config.py
│   │   ├── session.py
│   │   └── gpu.py
│   ├── utils/
│   │   ├── audio.py
│   │   ├── files.py
│   │   ├── gpu.py
│   │   ├── gpu_manager.py
│   │   ├── resource_limits.py
│   │   ├── validation.py
│   │   ├── platform.py
│   │   ├── logging.py
│   │   ├── run_context.py
│   │   ├── safe_write.py
│   │   ├── progress.py
│   │   └── docx_converter.py
│   ├── __init__.py
│   ├── __main__.py
│   └── exceptions.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── conftest.py
├── archive/
├── input/
├── output/
├── logs/
├── .env.example
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── pytest.ini
└── README.md
```

## Architecture Overview

```
┌─────────────────────────────────────────┐
│               Scribe CLI                │
├─────────────────────────────────────────┤
│  Record Command        Transcribe Command
│         │                       │
│         ▼                       ▼
│           ┌───────────────────┐
│           │ Core Orchestration│
│           │  - method select  │
│           │  - workflow mgmt  │
│           │  - error handling │
│           └─────────┬─────────┘
│                     │
│      ┌──────────────┼──────────────┐
│      ▼              ▼              ▼
│   OBS Recorder   Converter     Transcriber
│                     │              │
│                     └──────┬───────┘
│                            │
│                  ┌─────────┴─────────┐
│                  ▼                   ▼
│              Local Whisper        OpenAI API
└─────────────────────────────────────────┘
```

## Security and Privacy

- Transcripts and generated artifacts are written locally to SCRIBE_OUTPUT_FOLDER
- When using API mode, audio or compressed audio segments are sent to the provider for processing and diarization
- Logs avoid storing raw transcript text where possible and focus on metadata and status
- For sensitive material, prefer local GPU mode and disable humor features

## License

MIT License. See LICENSE.

## Acknowledgments

- [OpenAI Whisper](https://github.com/openai/whisper)
- [faster-whisper](https://github.com/guillaumekln/faster-whisper)
- [Rich](https://github.com/Textualize/rich)
- [Typer](https://github.com/tiangolo/typer)

## Author

**Nick Seal**

GitHub: [@blisspixel](https://github.com/blisspixel)

