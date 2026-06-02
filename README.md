# Scribe

**Speech Transcription and Summarization CLI**

Scribe converts spoken content into transcripts, notes, and optional humor outputs. It supports local GPU transcription and API-based transcription with fallback behavior.

---

## Quickstart

Install Scribe as a real `scribe` command, the same steps on **Windows, macOS, and Linux**. (Needs [uv](https://docs.astral.sh/uv/); install that first if you don't have it.)

```bash
# 1. Install scribe globally (no clone needed)
uv tool install --python 3.12 git+https://github.com/blisspixel/scribe.git
uv tool update-shell      # one-time PATH setup, then open a NEW terminal

# 2. First-run setup + verify (these now work from ANY folder)
scribe init               # interactive wizard; writes ~/.scribe/config.toml
scribe info               # shows GPU detection and configured providers

# 3. Use it from anywhere
scribe meeting.mp4
scribe transcribe meeting.mp4 --method local
scribe doctor
```

That's it. `scribe` is on your PATH and runs from any terminal, Start Menu or taskbar shortcut, or scheduled job. Transcript-only local GPU use needs no API key; notes/jokes/memes and API transcription do, so set `OPENAI_API_KEY` (and friends) in your environment or a `.env` file, or let `scribe init` walk you through it.

> **Cloud-synced home folder (OneDrive, Dropbox)?** If the install errors with a hardlink failure (Windows `os error 396`), add `--link-mode=copy` to the install command.
>
> **Want to hack on Scribe instead?** Clone the repo and use the project-local dev workflow (`uv sync`, then `uv run scribe ...`), or do an editable global install: `uv tool install --editable . --python 3.12`. See [Installation](#installation).

---

## What's New in v2.6.0

- **Structured, queryable output**: every transcription writes a machine-readable JSON transcript next to the `.txt` (optional WebVTT, SRT, and Markdown via `--format`), and `scribe query` does keyword and speaker search across them to find a moment from past meetings.
- **Hardware-adaptive local backends**: local transcription picks the engine for your machine instead of being CUDA-only, NVIDIA and CPU on faster-whisper, Apple Silicon on mlx-whisper (`scribe[mlx]`), AMD/Intel/Apple on whisper.cpp (`scribe[whispercpp]`), always with a working CPU fallback.
- **Local speaker diarization**: label "who said what" fully offline with `--diarize` (`scribe[diarize]` + `HF_TOKEN`), filling the same speaker field in every output that the cloud path uses.
- **Voice I/O mode**: `scribe listen` dictates speech into the focused window and `scribe say` reads a file aloud with a local offline voice, a deliberate opt-in mode behind `scribe[voice]`.
- **Engineering**: a shared `Transcript` domain model underpins all of the above, a dependency-preference policy keeps the base install lean (heavy/platform deps are extras), and an advisory mutation-testing CI job guards the pure core.

See [CHANGELOG.md](CHANGELOG.md) for the full list and [ROADMAP](ROADMAP.md) for direction.

## Recent Changes

All historical changes and the full version history live in [CHANGELOG.md](CHANGELOG.md) (Keep a Changelog format).

The current workspace is executing the **Engineering Excellence Roadmap** (see [ROADMAP.md](ROADMAP.md)):
- Step 1 complete: reproducible uv foundation, .python-version pin, consolidated pyproject.toml, pre-commit, and production-grade GitHub Actions CI (uv-native, matrix 3.12/3.13, ruff, mypy --strict, 80%+ cov gate, pip-audit security, aggregator job).

---

## What Scribe Does

**Core Value:**
- Record or import audio/video files
- Get accurate transcripts with speaker identification (cloud diarization in API mode, or local diarization with `--diarize`)
- Receive structured meeting notes with decisions and action items (currently via a cloud AI provider)
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

# Local speaker labels ("who said what"), fully offline
#   needs: pip install "scribe[diarize]"  and  HF_TOKEN set
scribe transcribe meeting.mp4 --diarize
```

### Recording
```bash
# Record and auto-transcribe
scribe rec "Team Meeting"
scribe record --name "Board Meeting"

# Record only (no transcription)
scribe record --no-auto-transcribe

# Install a double-clickable "Quick Record" launcher in your OS app menu
# (Windows Start Menu, macOS ~/Applications, Linux app menu); runs `scribe rec`
scribe shortcut
scribe shortcut --desktop   # also drop one on the Desktop
scribe shortcut --remove    # remove it
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

### Voice (opt-in mode)
```bash
# Needs: pip install "scribe[voice]"
# Dictate: speak and have your words typed into the focused window
#   F9 toggles listening, Esc quits
scribe listen
scribe listen --model small --language en

# Read a transcript or notes file aloud with a local offline voice
scribe say meeting_transcription.txt
scribe say notes.md --rate 180
```
This is a deliberate real-time mode that sits outside the batch pipeline (see ADR-008).

### Utilities
```bash
# First-run setup wizard (auto-prompts on first run; rerun anytime)
scribe init
scribe init --force                # Overwrite existing ~/.scribe/config.toml

# Install a cross-platform "Quick Record" launcher (Windows/macOS/Linux)
scribe shortcut
scribe shortcut --remove

# Search across your structured (.json) transcripts
scribe query "budget"
scribe query "action item" --speaker SPEAKER_01

# Domain glossaries (bias terms + fix known misrecognitions)
scribe vocab                 # list available glossaries
scribe vocab finance         # show a glossary's terms

# System diagnostics
scribe doctor

# Provider health check
scribe health
scribe health --provider xai

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
- `--vocab NAME|FILE` - Domain glossary (a name like `finance`/`tech`, or a `.txt`/`.json` path)
- `--format json,vtt,srt,md` - Structured outputs written alongside the .txt (default: json)
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
- Python 3.12 or newer (3.12+ strongly recommended for full toolchain and dependency compatibility)
- FFmpeg for media conversion
- OBS Studio (optional, for recording)

### Install Steps

**Recommended (2026+): install `scribe` as a global command (uv)**

This puts a `scribe` command on your PATH that works from any directory, identically on **Windows, macOS, and Linux**. It uses [uv](https://docs.astral.sh/uv/) (install that first), which builds one isolated environment for the tool, separate from any project `.venv` (uv's equivalent of `pipx`).

```bash
# Straight from GitHub, no clone needed (for anyone who just wants to use Scribe)
uv tool install --python 3.12 git+https://github.com/blisspixel/scribe.git

# ...or from a cloned repo, tracking your local source (for machines where you edit Scribe)
#   git clone https://github.com/blisspixel/scribe.git && cd scribe
#   uv tool install --editable . --python 3.12

# One-time: ensure uv's tool-bin dir is on PATH, then open a NEW terminal
uv tool update-shell

# Verify (works from any folder now)
scribe init
scribe info
```

Now `scribe rec`, `scribe doctor`, etc. work from anywhere, and OS shortcuts that call a bare `scribe` work too.

- **Cloud-synced home folder (OneDrive, Dropbox, iCloud):** if the install fails with a hardlink error (Windows `os error 396`), add `--link-mode=copy`. uv's tool directory lives under your synced profile and cannot always be hardlinked.
- **Updating:** an `--editable` install picks up source changes automatically; a git install updates with `uv tool upgrade scribe`.
- **Uninstall:** `uv tool uninstall scribe`.

**For development / contributing: project-local with uv**
```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
uv sync
uv run scribe init
uv run scribe info
```

`uv sync` keeps everything project-local: you invoke it with `uv run scribe ...` from inside the repo. This is the right setup for hacking on Scribe, but note it creates **no global `scribe` command**: a bare `scribe` in another folder or a shortcut will fail with `'scribe' is not recognized` / `command not found`. Use the global install above for daily use.

**Option A: pip (widely compatible, classic)**
```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
pip install -r requirements.txt
pip install -e .
```

**Option B: Local GPU Transcription (pip path)**
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
# XAI/Grok (Grok 4.3 default for jokes/notes/memes)
pip install openai

# Anthropic Claude
pip install anthropic

# Google Gemini
pip install google-genai Pillow
```

### Configuration

Scribe reads from three layers, highest precedence first:

1. **CLI flags** (`--no-joke`, `--method local`, etc.) — per-run override
2. **Env vars / `.env` file** (`SCRIBE_*`, `OPENAI_API_KEY`, etc.) — per-machine secrets and overrides
3. **`~/.scribe/config.toml`** — written by the first-run wizard (`scribe init`)

**First-run wizard:**

```bash
scribe init   # auto-prompts on first run; rerun anytime
```

The wizard asks for output folder, transcription method (auto/local/openai), which features to enable by default (notes/joke/meme), and your AI vendor preference. It also detects conflicting `SCRIBE_ENABLE_*` lines in your `.env` and offers to comment them out so the wizard's choices actually take effect.

**`.env` setup:**

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

GPT-5.5 analyzes transcripts and generates structured notes:
- **Current State:** What's happening now
- **Drivers:** What's pushing things forward
- **Blockers:** What's in the way
- **Future State:** Where things are headed
- **Next Steps:** Concrete action items

### Humor Pipeline

**Jokes:**
- GPT-5.5 analyzes tone, rhythm, and intent
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
- **OpenAI:** GPT-5.5 (default), GPT-5.4, GPT-5, GPT-Image-1, Whisper
- **XAI/Grok:** Grok 4.3 (default for joke/meme/notes), Grok Imagine Image
- **Anthropic:** Claude 3.5 Sonnet (text only)
- **Google Gemini:** Gemini 3 Pro, Gemini 3 Flash, Imagen 4 — optional, not part of fallback chain by default
- **Ollama (local):** any installed model — free, fully offline notes; runs on Linux/macOS/Windows. The model is auto-selected to fit your GPU/VRAM (override with `SCRIBE_OLLAMA_MODEL`).

### Local, Free Notes with Ollama

Generate meeting notes entirely on your machine — no API key, no cost, nothing leaves your device. Requires a running [Ollama](https://ollama.com) server with at least one model pulled.

```bash
# Use your best installed local model (auto-selected for your VRAM)
scribe notes meeting.md --provider ollama

# Or pin a specific model
scribe notes meeting.md --provider ollama --model qwen2.5:14b
```

Scribe probes the Ollama server for installed models and picks the largest general-purpose model that fits your detected memory budget (mirroring how it auto-selects the Whisper model). `scribe info` shows the auto-selected local model.

**GPU-aware, no CPU spill.** Scribe talks to Ollama's native API and sizes the context window (`num_ctx`) to the actual transcript, then caps it. Some models ship a huge default context (e.g. 262K tokens ≈ 28GB of KV cache) that would push half the model onto the CPU and crawl; capping it keeps the whole model on the GPU. Selection also reserves headroom so weights + KV cache fit in VRAM. Structured notes use Ollama's constrained decoding (the JSON schema is passed to `format`), which guarantees valid JSON even from thinking models like Gemma 4 and Qwen3 (whose output would otherwise land in the reasoning channel).

Tuning knobs (all optional):

| Env var | Default | Purpose |
|---|---|---|
| `SCRIBE_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `SCRIBE_OLLAMA_MODEL` | auto | Pin a specific model (skips auto-select) |
| `SCRIBE_OLLAMA_MAX_CTX` | `16384` | Upper bound on the context window |
| `SCRIBE_OLLAMA_NUM_CTX` | auto | Pin an exact context window |
| `SCRIBE_OLLAMA_NUM_GPU` | auto | Force N layers onto the GPU (e.g. `999` = all) |
| `SCRIBE_OLLAMA_TIMEOUT` | `600` | Request timeout (s) for slow local inference |

### Comparing Providers ("is local worth it?")

One short command runs the same transcript through several providers and prints a cost / latency / quality scorecard plus a plain-English verdict. Quality is scored objectively (structured-fidelity, free and offline) plus an optional LLM-judge rubric — and the judge is chosen automatically.

```bash
scribe compare meeting.md            # smart: your cloud default vs the best local model, auto-judged
scribe compare meeting.md local      # every installed local model — free and offline
scribe compare meeting.md all        # everything you have keys/models for
scribe compare meeting.md openai,ollama:gemma4:26b --judge openai   # explicit
```

```
model                                    cost     time   struct  judge
-----------------------------------------------------------------------
openai:gpt-5.5                          $0.0120    4.2s   100.0%    9.1
ollama:qwen2.5:14b                       $0.00    18.7s    94.0%    7.8

→ Local qwen2.5:14b is worth it — comparable quality to gpt-5.5 (~$0.0120/run) at $0.00.
```

(`scribe notes meeting.md --compare …` does the same thing if you prefer a flag.)

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

**Cost Comparison (per 1M tokens, May 2026):**
- Grok 4.3: $1.25 input / $2.50 output
- GPT-5.5: see [OpenAI pricing](https://openai.com/api/pricing) (varies by tier)
- GPT-5.4: $1.25 input
- Claude 3.5 Sonnet: $3.00 input / $15.00 output

**Images:**
- Grok Imagine Image: priced per image by xAI; cost returned via `cost_in_usd_ticks`
- GPT-Image-1: ~$0.04–$0.07 medium quality, ~$0.17–$0.25 high quality

**Per-meme cost (default config, up to 3 QA attempts):**
- gpt-image-1 medium: typically $0.05–$0.20
- grok-imagine-image: typically $0.05–$0.15 (note: watermarked)

**xAI lifecycle note:** Scribe defaults to `grok-4.3` for joke/meme/notes. Older IDs retired by xAI on 2026-05-15 (`grok-4-fast`, `grok-4-1-fast`, `grok-4`, `grok-4.20-non-reasoning`, `grok-imagine-image-pro`) are no longer used. When xAI returns exact `cost_in_usd_ticks`, Scribe records the converted request cost in AI metrics.

### Domain Glossaries (custom vocabulary)

Improve accuracy for domain-specific terms, proper nouns, and technical jargon. A
glossary does two things: it **biases** recognition toward your terms (via Whisper's
prompt), and it **normalizes** known misrecognitions to the canonical form *after*
transcription (deterministic, offline find-and-replace). Biasing nudges the model;
normalization guarantees the final text.

**Use a named glossary or a file:**
```bash
# Bundled presets: finance, tech
scribe transcribe earnings.mp4 --vocab finance
scribe batch standups/*.mp4 --vocab tech

# Or a path to your own .txt/.json
scribe transcribe meeting.mp4 --vocab ./company-terms.txt

# List and inspect glossaries
scribe vocab                 # list bundled + ~/.scribe/vocab glossaries
scribe vocab tech            # show a glossary's terms and aliases
```

**Glossary format (`~/.scribe/vocab/<name>.txt`):**
```
# One term per line biases recognition.
Kubernetes
Acme Corporation

# "Canonical = variants" also rewrites known misrecognitions after transcription:
PostgreSQL = post gray sequel, postgres sql
OAuth = oh auth, o auth
```
JSON is also supported: `["term1", "term2"]`, or `{"terms": [...], "aliases": {"PostgreSQL": ["post gray sequel"]}}`.

Oversized glossaries are trimmed to fit Whisper's prompt budget (with a warning)
rather than being silently truncated. Glossaries should match the spoken language
(set with `--language`).

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
- Cross-platform support (OBS config/launch handled per-OS on Windows, macOS, Linux)

### Quick Record launcher

`scribe shortcut` installs a native, double-clickable "Quick Record" launcher in your
OS application menu that runs `scribe rec` with no terminal required:

- **Windows**: a Start Menu shortcut (`--desktop` also adds a Desktop one)
- **macOS**: `~/Applications/Scribe Quick Record.command` (shows in Finder/Launchpad)
- **Linux**: an XDG `.desktop` entry in your applications menu

```bash
scribe shortcut            # install to the app menu (offers a Desktop copy)
scribe shortcut --desktop  # also place one on the Desktop
scribe shortcut --remove   # remove installed launchers
```

The launcher calls whatever `scribe` resolves to at install time (preferring a `scribe`
on your PATH, e.g. from `uv tool install`), falling back to `python -m scribe`. This is
the cross-platform replacement for any hand-made `.bat`/shell shortcut.

---

## Performance

### Local GPU Performance

| GPU | VRAM | Model | Beam Size | Speed |
|-----|------|-------|-----------|-------|
| RTX 4090 | 24GB | large-v3 | 10 | 11x real-time |
| RTX 4080 | 16GB | large-v3 | 8 | 8x real-time |
| RTX 3090 | 24GB | large-v3 | 5 | 6x real-time |

**Note:** Audio preprocessing adds ~10% of recording duration. We prioritize quality over speed.

### Local Backends (hardware-adaptive)

Local transcription picks the engine that fits your machine. The base install
covers NVIDIA and CPU; Apple Silicon and AMD/Intel get faster local paths through
optional extras.

| Vendor | Engine used | Install |
|--------|-------------|---------|
| NVIDIA | faster-whisper (CUDA) | included |
| CPU (any) | faster-whisper (int8) | included |
| Apple Silicon | mlx-whisper (Metal) | `pip install "scribe[mlx]"` |
| AMD / Intel / Apple | whisper.cpp (Metal/Vulkan/ROCm) | `pip install "scribe[whispercpp]"` |

Selection is automatic by detected vendor and always falls back to a working CPU
path. Override it with `SCRIBE_LOCAL_BACKEND=mlx|whispercpp|faster-whisper|cpu` or
`local_backend` in `~/.scribe/config.toml`. `scribe info` shows the detected vendor,
the selected backend, and which optional engines are installed.

On an Apple Silicon Mac, the fast path is:

```bash
uv tool install --editable ".[mlx]" --python 3.12   # or: pip install "scribe[mlx]"
scribe info                                          # local backend: selected mlx, vendor apple
scribe transcribe meeting.m4a --method local         # runs on the Metal GPU via MLX
```

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
│(GPT-5.5) │   │ (Jokes/  │
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
- `notes_generator.py` - GPT-5.5 meeting analysis
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
# Recommended with uv
uv run pytest

# Or classic
pytest

# Unit tests only
pytest tests/unit/

# With coverage (gate is enforced in CI at 80%+)
uv run pytest --cov=scribe --cov-report=term-missing --cov-fail-under=80

# Quick check
pytest tests/unit/ --tb=no -q

# Skip slow / external / GPU tests
pytest -q -m "not e2e and not gpu and not slow"
```

**Test Status:**
- 1,143 tests collected (large, high-quality suite with unit + integration + e2e)
- Excellent coverage of error paths (especially OBS recorder)
- Platform-specific skips and markers are used responsibly
- End-to-end tests may require a valid `OPENAI_API_KEY`

See the Engineering Excellence section of [ROADMAP.md](ROADMAP.md) for the ordered plan to raise gates (uv foundation, ruff, strict types, property testing, coverage, and hygiene).

### Code Quality

**Standards:**
- Structured dual-output logging (Rich console for users + detailed files for debugging)
- Comprehensive, typed exception hierarchy with context for every failure domain
- Defensive design with automatic fallbacks and self-healing (see OBS recorder)
- Type hints on public APIs and core logic

**Primary Tools:**
- **uv** — sole package + project manager (uv sync, uv run, uv.lock for reproducibility)
- **ruff** — universal linter + formatter (replaced Black + isort)
- **mypy --strict** on src/ (enforced in CI)
- **pre-commit** — local gates before every commit (ruff + mypy + basic checks)
- pytest + pytest-cov (80%+ gate enforced in CI)

See the Engineering Excellence section of [ROADMAP.md](ROADMAP.md) and [.github/workflows/ci.yml](.github/workflows/ci.yml) for the ordered plan and current gates.

### Contributing

Priority areas:
1. Following the ordered Engineering Excellence plan (foundation, gates, types, testing, hygiene)
2. Test coverage and property-based tests for core invariants
3. Performance / UX polish on existing features
4. Documentation and error message clarity

See [Development Guide](docs/DEVELOPMENT.md) and the Engineering Excellence section of [ROADMAP.md](ROADMAP.md) for current standards and the ordered forward plan.

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

## Responsible Use and Legal

This section is for general awareness only and is not legal advice. See
[DISCLAIMER.md](DISCLAIMER.md) for the full notice.

### Recording consent
Scribe can record conversations and calls. Recording laws vary by jurisdiction.
Some US states and many countries require all-party (two-party) consent, where
everyone must agree before recording. Examples of all-party-consent US states
include California, Florida, Illinois, Pennsylvania, Massachusetts, and
Washington, among others; this list is not complete or guaranteed current. You
are responsible for obtaining any required consent and complying with local law.
The first time you record, Scribe shows a one-time notice and asks you to confirm.

### Regulated and sensitive data
Scribe is general-purpose and is not designed or certified for regulated data such
as protected health information (HIPAA/PHI), payment card data, or
government-classified material. Do not use it for such data unless you have
independently ensured compliance and put appropriate safeguards in place.

### Cloud data sharing
Local transcription stays on your device. When you use cloud transcription
(OpenAI) or cloud-based notes (OpenAI, xAI, Anthropic, Google), your audio and/or
transcript is sent to that provider and is subject to its terms and privacy
policy. The provider may retain that data. Review those terms first.

### No warranty
Scribe is provided "as is", without warranty of any kind. The authors are not
liable for any claim, damages, or other liability arising from its use. You are
solely responsible for how you use Scribe and for complying with applicable laws.

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

**Current Version:** 2.5.0 (cross-platform Quick Record launcher and app icon, macOS/Linux recording, plus correctness fixes)
**Build Status:** Refer to local CI/test runs
**Focus:** Reliability and maintainability - see [ROADMAP](ROADMAP.md)
**Last Updated:** 2026-06-01


