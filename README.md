# Scribe

**GPU-Accelerated Speech Intelligence for Teams, Creators, and Engineers**

Scribe is a complete system for transforming spoken content into structured understanding. It combines the raw speed of local GPU-accelerated speech recognition with the analytical depth of large-scale language models to deliver accurate transcription, intelligent summaries, and creative humor automatically. It is built for professionals who deal with large volumes of meetings, interviews, or recordings and want more than a simple transcript.

At its core, Scribe is optimized for NVIDIA RTX hardware, reaching up to twelve times real-time speed on an RTX 4090. When GPU resources are not available, it automatically falls back to the OpenAI API, ensuring consistent accuracy and reliability on any machine. Every part of the workflow, from recording to final report generation, is designed to be both automated and customizable. Users can record directly through OBS Studio, transcribe locally or via the cloud, and immediately receive clear, human-readable documents with speaker identification and metadata.

Scribe does more than produce transcripts. It interprets the conversation, identifies the structure and intent of discussions, and turns unstructured speech into organized information. With the GPT-5 meeting analysis module, it can extract decisions, next steps, blockers, and opportunities and present them in a consistent format that fits both technical and business contexts. Output can be generated in text, Markdown, and Word documents.

For lighter moments, Scribe can analyze tone and intent to produce context-aware jokes and visual memes that are grounded in the meeting content. The humor pipeline uses explicit criteria and a short QA loop to keep output relevant and professional.

Scribe integrates Whisper for speech recognition, GPT-4o and GPT-5 for analysis, PyTorch for GPU inference, and OBS Studio for capture. The result is a tool that merges speed, comprehension, and polish. It helps convert hours of recordings into useful insight within minutes.

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

## Feature Summary

### Transcription
- GPU-accelerated Whisper transcription (up to 12.6x real-time on RTX 4090)
- Automatic fallback to OpenAI API when GPU unavailable
- High-accuracy models: Whisper large-v3 and gpt-4o-transcribe-diarize
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

### Output
- TXT, DOCX, Markdown notes, PNG memes
- Live progress bars with speed and ETA calculations
- Structured metadata and session summaries
- Clean formatting with meeting metadata

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

### Configure Environment

```bash
cp .env.example .env
```

Then edit `.env`:

```env
# Required for API transcription and humor
OPENAI_API_KEY=sk-proj-...

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

# System status and GPU check
scribe info
```

## End-to-End Workflow

### Recording
Optional OBS integration records to MP4. You can trigger and stop recording from the CLI. Files are placed in the configured output folder.

### Conversion
Input media is converted to 16 kHz mono WAV for Whisper. In API mode, the original file is used or converted to compressed MP3 if over 25 MB.

### Transcription
Local GPU uses Whisper large-v3. API mode uses gpt-4o-transcribe with automatic diarization. The method is selected automatically unless overridden.

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
- `--model MODEL` - Whisper model for local GPU (for example large-v3, large-v2).
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

# Force local GPU and model
scribe transcribe audio.wav --method local --model large-v3

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
- Prefer large-v3 on 24 GB VRAM
- On 12–16 GB, use large-v3 with reduced beam size or switch to large-v2
- Beam size settings affect quality and speed. Higher beam sizes improve accuracy but slow inference

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
- Use `--model large-v3`
- Ensure clean audio and correct sample rate
- Reduce background noise and microphone distance

### API errors:
- Verify OPENAI_API_KEY with `scribe info`
- Check API quota and billing
- Ensure a stable network connection

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
