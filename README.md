License: pending owner confirmation.
Historical project metadata is inconsistent: earlier README copy referenced Apache 2.0 + Commons Clause, while `pyproject.toml` currently declares MIT and no LICENSE file is present. Treat licensing as unresolved until the owner chooses the canonical license and aligns README, `pyproject.toml`, and LICENSE.

# Scribe

**Speech Transcription and Summarization CLI**

Scribe converts spoken content into transcripts, notes, and optional humor outputs. It is **$0-first**: transcription runs locally on any machine (GPU or CPU) with no API key, and paid cloud APIs are an explicit opt-in.

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

> **Costs default to off.** To avoid surprise charges, the paid AI extras - meeting **notes**, **jokes**, and **memes** (memes call a paid *image* API) - are **disabled by default**. A plain `scribe meeting.mp4` only transcribes. Turn one on **just for this run** with the matching flag (`scribe meeting.mp4 --notes --meme`), turn it on **persistently** with `scribe init` or `SCRIBE_ENABLE_NOTES/JOKE/MEME=true`, or generate one on demand from an existing transcript: `scribe notes transcript.md`, `scribe joke transcript.md`, `scribe meme transcript.md`. The `--notes/--no-notes`, `--joke/--no-joke`, and `--meme/--no-meme` flags are paired toggles: the bare flag forces the feature on for that run, the `--no-` form forces it off, and omitting both uses your config default. Transcription is **$0-first**: `--method auto` always runs locally (GPU when present, CPU otherwise), so it never silently spends on an API - the paid OpenAI API is an explicit opt-in via `--method openai`. Want everything local? Set **`SCRIBE_LOCAL_ONLY=1`** to force local transcription and route notes/jokes to local [Ollama](https://ollama.com), never touching a paid API. Run **`scribe doctor`** (or `scribe info`) for a plain "$0 LOCAL" verdict of what runs free on your machine and how to enable anything that's missing. Use **`scribe doctor --live`** only when you intentionally want provider API-key validation.

> **Cloud-synced home folder (OneDrive, Dropbox)?** If the install errors with a hardlink failure (Windows `os error 396`), add `--link-mode=copy` to the install command.
>
> **Want to hack on Scribe instead?** Clone the repo and use the project-local dev workflow (`uv sync`, then `uv run scribe ...`), or do an editable global install: `uv tool install --editable . --python 3.12`. See [Installation](#installation).

---

## What's New in v2.8.1 (in development)

- **Safer setup defaults**: `scribe init` keeps transcription on `auto` for
  both GPU and CPU machines. It asks about provider keys only when a paid or
  provider-backed feature is selected.
- **Truthful diagnostics**: `scribe health --provider NAME` fails when that
  provider is unknown or has no configured key instead of reporting an empty
  check as healthy. `scribe tray --check` turns missing optional parent packages
  into actionable dependency output instead of a traceback.
- **Durable terminal evidence**: started file, URL, batch-item, recording, and
  music-track runs save a unique session summary. Exact outcomes distinguish
  success, partial completion, failure, and confirmed instrumentals; incomplete
  output prints the summary location. Repeating a meeting name no longer
  overwrites an earlier record.
- **Private support bundles**: bundles read a bounded set of durable session
  summaries across processes, recursively redact known home-identifier and
  credential patterns, and include opaque recent-log metadata without filenames
  or log contents. Review the generated JSON before sharing it.
- **Reproducible quality gates**: CI uses the committed lockfile, includes the
  toolchain check in the aggregate result, enforces formatting, lint, strict
  typing, dependency audit policy, and at least 80 percent meaningful coverage.
- **Portable release artifact**: the root wheel no longer requires an unpublished
  workspace-only Rust package. Required CI now builds and inspects the wheel,
  installs it without workspace packages, and smokes the installed command.
- **Bounded long-audio fallback**: client-side OpenAI chunking uses native silence
  analysis when available and a visible portable fallback otherwise. Both paths
  enforce the configured duration cap before exporting chunks.

## v2.8.0 Highlights

- **$0-first, runs anywhere**: `--method auto` always transcribes locally (GPU when present, CPU otherwise) and never auto-selects the paid API. The paid OpenAI API is an explicit opt-in via `--method openai`.
- **Cost safety by default**: the paid AI extras (notes, jokes, memes) are off by default. Turn them on per run with `--notes`/`--joke`/`--meme`, persistently via `scribe init` or `SCRIBE_ENABLE_*`, or on demand with `scribe notes|joke|meme`.
- **Local-only mode**: `SCRIBE_LOCAL_ONLY=1` forces everything to $0: local transcription (no paid fallback) plus notes/jokes routed to local Ollama.
- **$0 readiness in doctor/info**: `scribe doctor` and `scribe info` now lead with a plain verdict of what runs free on your machine, and tell you exactly how to enable anything missing.
- **Cross-machine nudges**: on Apple or AMD/Intel machines that fall back to CPU, Scribe points you at the faster local engine (`scribe[mlx]` or `scribe[whispercpp]`).

See [CHANGELOG.md](CHANGELOG.md) for the full list and [ROADMAP](ROADMAP.md) for direction.

## Recent Changes

All historical changes and the full version history live in [CHANGELOG.md](CHANGELOG.md) (Keep a Changelog format).

The current workspace is executing the **Engineering Excellence Roadmap** (see [ROADMAP.md](ROADMAP.md)):
- Step 1 complete: reproducible uv foundation, `.python-version` pin, consolidated `pyproject.toml`, pre-commit, and production-grade GitHub Actions CI (uv-native, matrix 3.12/3.13, ruff, mypy --strict, 80%+ cov gate, pip-audit security, aggregator job).
- Step 2 complete: full-tree ruff format + check enforced locally via pre-commit and as a hard CI gate.
- Step 3 in progress: mypy --strict clean; `deal` contracts on pure modules (`costs`, transcript model, validation helpers); Hypothesis property tests expanding.
- Step 4 operational with tracked debt: pip-audit is blocking in CI, SBOM generation is documented, `scribe doctor` reports CUDA driver age and dependency-audit results, and accepted Torch advisories are explicit in ADR-004 while compatible CPU/CUDA upgrade validation remains open.

---

## What Scribe Does

**Core Value:**
- Record or import audio/video files
- Get accurate transcripts with speaker identification (cloud diarization in API mode, or local diarization with `--diarize`)
- Receive structured meeting notes with decisions and action items (via a cloud or local AI provider)
- Optional context-aware humor (jokes and memes)
- Output in TXT, DOCX, Markdown, and PNG formats

**Key Features:**
- GPU-accelerated local processing (11x real-time on RTX 4090)
- Quality-first auto model selection based on detected VRAM
- $0-first: transcribes locally on any machine (GPU or CPU); the paid OpenAI API is opt-in only
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

# Notes/jokes/memes are OFF by default (cost safety). Opt in per run:
scribe meeting.mp4 --notes              # add meeting notes this run (paid text API)
scribe meeting.mp4 --notes --meme       # notes + meme (meme uses a paid image API)
scribe batch *.mp4 --notes              # apply to every file in the batch

# Transcript only is already the default; --no-* still force a feature off
# even when your config turns it on:
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

Batch and music commands continue through remaining inputs by default. A fully
complete run, including a confirmed instrumental track, exits 0. Missing inputs,
failed files, partial music segments, or requested artifacts that could not be
generated are listed in the summary and make the command exit 1 after processing.
Use `--stop-on-error` when later inputs should not be attempted.

### Recording
```bash
# Record and auto-transcribe
scribe rec "Team Meeting"
scribe record --name "Board Meeting"

# Record only (no transcription)
scribe record --no-auto-transcribe

# Install native Quick Record launchers (Start Menu + optional Desktop).
# Runs `scribe rec`. See "Quick Record launcher" section for details + taskbar tips.
scribe shortcut
scribe shortcut --desktop   # also drop one on the Desktop
scribe shortcut --remove    # remove it
```

Every started recording saves a session summary, including record-only success
and failures before transcription. If transcription succeeds but a requested
DOCX, notes, joke, meme, or cleanup step fails, the surviving artifacts are kept,
the outcome is `partial`, and the command exits 1 instead of claiming complete
success.

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
# Needs: pip install "scribe[voice]" for listen/say
# Needs: pip install "scribe[tray]" for the resident tray utility
# Optional: pip install "scribe[kokoro]" for a high-quality neural read-aloud voice

# One-time setup: pre-download the dictation model + pick a read-aloud voice
# (so the first use is instant instead of triggering a surprise download)
scribe tray --setup

# Dictate (tap-to-toggle by default): tap F9, speak, tap F9 again to insert at the cursor
scribe listen
scribe listen --mode hold                # push-to-talk: hold F9, release to insert
scribe listen --mode continuous          # always listening, F9 pauses
scribe listen --inject type              # type keystrokes instead of paste
scribe listen --model small --language en

# Read aloud with a local offline voice (Kokoro if set up, else the system voice)
scribe say meeting_transcription.txt     # a file
scribe say --selection                   # the currently selected text
scribe say --clipboard                   # the clipboard contents
scribe say notes.md --speed 1.2          # 1.2x speed (0.5-2.0); Esc stops playback

# Resident voice tray utility
scribe tray --check                      # validate deps, backend, hotkeys, and read-aloud
scribe tray                              # tray icon: tap F9 to dictate, tap F8 to read selection
scribe tray --activation hold            # prefer push-to-talk over tap-to-toggle
scribe tray --speed 1.2                  # default read-aloud speed
scribe tray --no-tray                    # terminal fallback with the same hotkeys
scribe tray --profile accurate           # large-v3-turbo (model is warmed at startup by default)
scribe tray --no-preload                 # don't warm the model at startup (load on first use)
scribe tray --startup install            # run the tray automatically at login (remove | status)
```
Dictation and read-aloud both default to **tap-to-toggle**: tap the hotkey to start,
tap again to stop (matching Windows Voice Access and macOS dictation/Speak Selection).
The default **Python tray menu** shows the current hotkeys and lets you remap them
(F6-F12), pick a read-aloud speed, pause hotkeys, and toggle "Start at login" - all
live. The Go tray remains an explicit source prototype with a smaller Dictate,
Read, and Quit menu and no desktop-notification parity. It is selected only through
a deliberate `SCRIBE_TRAY_NATIVE_BIN` path, never from a checked-in or merely
packaged build artifact. Its current protocol supports toggle activation and simple
F6-F12 keys. It must authenticate, register both keys, and signal readiness before
Scribe reports it as active; daemon startup failure or a nonzero daemon exit visibly
returns to the Python tray.
This is a deliberate real-time mode that sits outside the batch pipeline (see ADR-008).
The complete Python tray is live-validated on **Windows**. macOS and Linux support
is implemented but still needs the platform matrix recorded in the roadmap before
it is described as validated. Run `scribe tray --check` first on every platform to
see missing dependencies, selected backend and provenance, the resolved read-aloud
backend, and macOS Input Monitoring or Linux Wayland permission caveats.
See the [Resident Voice Tray Utility Plan](docs/features/VOICE_TRAY_UTILITY_PLAN.md) and [macOS/Linux Validation Plan](docs/features/VOICE_TRAY_MAC_LINUX_VALIDATION.md).

High-quality neural read-aloud uses **Kokoro** (82M, ONNX, CPU-capable, Apache-2.0)
when installed (`scribe[kokoro]`) and set up; otherwise it falls back to the OS voice.
The model is cached and warmed at startup, and synthesis is pipelined so multi-paragraph
reads play without gaps.

### Utilities
```bash
# First-run setup wizard (auto-prompts on first run; rerun anytime)
scribe init
scribe init --force                # Overwrite existing ~/.scribe/config.toml

# Install Quick Record launchers (see dedicated section + taskbar icon tips)
scribe shortcut
scribe shortcut --remove
scribe rec --check              # read-only OBS preflight before a meeting

# Search across your structured (.json) transcripts
scribe query "budget"
scribe query "action item" --speaker SPEAKER_01

# Domain glossaries (bias terms + fix known misrecognitions)
scribe vocab                 # list available glossaries
scribe vocab finance         # show a glossary's terms

# System diagnostics
scribe doctor

# Provider health check (fails if no provider can actually be checked)
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
- `--notes` / `--no-notes` - Force meeting notes on / off for this run (paid text API; default off)
- `--joke` / `--no-joke` - Force joke generation on / off for this run (paid text API; default off)
- `--meme` / `--no-meme` - Force meme generation on / off for this run (paid **image** API; default off)

**Tip:** Transcript-only is the default now that the paid extras ship off. The `--no-*` flags are only needed to override a config/env setting that turned a feature on.

---

## Installation

### Requirements

**For GPU Transcription (Optional):**
- NVIDIA GPU with CUDA support (RTX 4090 optimized)
- 8GB VRAM minimum, 24GB recommended
- NVIDIA driver with CUDA support for your card
- `faster-whisper` / CTranslate2 must be able to see the GPU

**For API Transcription (optional, explicit opt-in via `--method openai`):**
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

1. **CLI flags** (`--no-joke`, `--method local`, etc.) - per-run override
2. **Env vars / `.env` file** (`SCRIBE_*`, `OPENAI_API_KEY`, etc.) - per-machine secrets and overrides
3. **`~/.scribe/config.toml`** - written by the first-run wizard (`scribe init`)

**First-run wizard:**

```bash
scribe init   # auto-prompts on first run; rerun anytime
```

The wizard is interactive and defensive:
- Smart defaults (local `auto` transcription on GPU or CPU, existing config / env / OBS settings).
- Provider keys are requested only when you choose API transcription or a provider-backed extra.
- Review step with confirmation before writing.
- Post-save verification (including real OBS preflight if you supplied a password).
- Offers to create a Quick Record launcher immediately.
- Resolves conflicting `SCRIBE_ENABLE_*` env vars.

It writes `~/.scribe/config.toml`. Env vars and CLI flags still override. Re-run `scribe init` (or `--force`) anytime.

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

# Output directory. Overrides ~/.scribe/config.toml.
SCRIBE_OUTPUT_FOLDER=/path/to/scribe/output

# Defaults
SCRIBE_DEFAULT_MODEL=large-v3
SCRIBE_DEFAULT_LANGUAGE=en

# $0 local-only mode: force local transcription (never the paid API) and route
# notes/jokes to local Ollama. Unset/false keeps the default (auto is still
# $0-first; the paid API is opt-in via --method openai).
SCRIBE_LOCAL_ONLY=false

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

Windows one-session examples:

```bat
set SCRIBE_OBS_PASSWORD=your_password
```

```powershell
$env:SCRIBE_OBS_PASSWORD = 'your_password'
```

OBS settings can also live in `~/.scribe/config.toml`:

```toml
[obs]
host = "localhost"
port = 4455
password = "your OBS WebSocket password"
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
- **Local (default, $0):** Whisper via faster-whisper (GPU) or CPU int8 - `auto` always runs locally
- **API Mode (opt-in):** gpt-4o-transcribe-diarize (speaker separation, server-side chunking) via `--method openai`
- `auto` picks the best local backend for your hardware; it never auto-selects the paid API

**3. Document Generation**
- Clean TXT transcript with metadata
- Formatted DOCX document
- Structured session summaries

### Music Transcription

Music transcription uses a separation-first architecture to improve lyrics capture quality.

**Key Features:**
- Segment-based transcription with VAD timestamps
- Explicit complete, partial, failed, and instrumental outcomes
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

If VAD is unavailable, music mode reports the fallback and transcribes the full
audio instead of calling the track instrumental. If some vocal segments fail, the
usable lyrics are preserved as a partial result. If every segment fails, the track
is failed and no instrumental marker is written. Every started track writes a
session summary. Lyrics and instrumental markers are replaced atomically, and
cleanup is limited to temporary artifacts created by the current track run.

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
- **Google Gemini:** Gemini 3 Pro, Gemini 3 Flash, Imagen 4 - optional, not part of fallback chain by default
- **Ollama (local):** any installed model - free, fully offline notes; runs on Linux/macOS/Windows. The model is auto-selected to fit your GPU/VRAM (override with `SCRIBE_OLLAMA_MODEL`).

### Local, Free Notes with Ollama

Generate meeting notes entirely on your machine - no API key, no cost, nothing leaves your device. Requires a running [Ollama](https://ollama.com) server with at least one model pulled.

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

One short command runs the same transcript through several providers and prints a cost / latency / quality scorecard plus a plain-English verdict. Quality is scored objectively (structured-fidelity, free and offline) plus an optional LLM-judge rubric - and the judge is chosen automatically.

```bash
scribe compare meeting.md            # smart: your cloud default vs the best local model, auto-judged
scribe compare meeting.md local      # every installed local model - free and offline
scribe compare meeting.md all        # everything you have keys/models for
scribe compare meeting.md openai,ollama:gemma4:26b --judge openai   # explicit
```

```
model                                    cost     time   struct  judge
-----------------------------------------------------------------------
openai:gpt-5.5                          $0.0120    4.2s   100.0%    9.1
ollama:qwen2.5:14b                       $0.00    18.7s    94.0%    7.8

→ Local qwen2.5:14b is worth it - comparable quality to gpt-5.5 (~$0.0120/run) at $0.00.
```

(`scribe notes meeting.md --compare ...` does the same thing if you prefer a flag.)

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
- GPT-Image-1: ~$0.04-$0.07 medium quality, ~$0.17-$0.25 high quality

**Per-meme cost (default config, up to 3 QA attempts):**
- gpt-image-1 medium: typically $0.05-$0.20
- grok-imagine-image: typically $0.05-$0.15 (note: watermarked)

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
OS application menu that runs `scribe rec` (you do not need to open a terminal first).
It is defensive and adaptive: it prefers whatever `scribe` is on your PATH at runtime
(e.g. a stable `uv tool install`), falls back gracefully, keeps the console window open
with pauses and clear messages, and stages a custom icon.

- **Windows**: Start Menu + optional Desktop `.lnk`. The `.lnk` targets `cmd.exe` (with env
  and title for reliable taskbar pinning and console behavior) + a companion adaptive
  `.cmd` wrapper is created in `~/.scribe` for advanced use/editing. Custom icon is set
  on the `.lnk`.
- **macOS**: `~/Applications/Scribe Quick Record.command` (and optional Desktop copy).
- **Linux**: XDG `.desktop` (and optional Desktop copy), plus adaptive wrapper script.

```bash
scribe shortcut            # install to the app menu (offers a Desktop copy)
scribe shortcut --desktop  # also place one on the Desktop
scribe shortcut --remove   # remove installed launchers
```

After installation, drag the Desktop `.lnk` to your taskbar to pin. If the icon appears
generic on the pinned taskbar item, right-click it → Properties → Change Icon and select
`~/.scribe/scribe.ico`.

The shortcut is the cross-platform replacement for hand-made launchers and survives
updates when you use a stable global `scribe` on PATH.

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

# CI-safe unit matrix
uv run pytest tests/unit -m "not gpu and not slow and not e2e and not requires_openai and not requires_ffmpeg and not requires_whisperx and not requires_pillow" -q

# Meaningful coverage gate
uv run pytest --cov=scribe --cov-report=term-missing --cov-fail-under=80 -m "not gpu and not slow and not requires_openai and not requires_whisperx and not requires_pillow" -q

# Quick check
uv run pytest tests/unit -m "not gpu and not slow and not e2e" --tb=no -q

# Skip slow / external / GPU tests
uv run pytest -q -m "not e2e and not gpu and not slow"
```

**Test Status:**
- Latest CI-safe unit matrix: 1512 passed, 2 skipped, 37 deselected
- Latest broader CI-equivalent coverage gate: 1612 passed, 12 skipped, 27 deselected, 83.07% line coverage
- Current collection: 1651 assertion-based tests
- Full suite includes unit, integration, e2e, optional-provider, hardware, and live-I/O tests guarded by markers
- Excellent coverage of error paths (especially OBS recorder)
- Platform-specific skips and markers are used responsibly
- End-to-end tests may require a valid `OPENAI_API_KEY`
- Ruff, mypy --strict, and coverage gates enforced on safe subsets

See the Engineering Excellence section of [ROADMAP.md](ROADMAP.md) for the ordered plan to raise gates (uv foundation, ruff, strict types, property testing, coverage, and hygiene).

### Code Quality

**Standards:**
- Structured dual-output logging (Rich console for users + detailed files for debugging)
- Comprehensive, typed exception hierarchy with context for every failure domain
- Defensive design with automatic fallbacks and self-healing (see OBS recorder)
- Type hints on public APIs and core logic

**Primary Tools:**
- **uv** - sole package + project manager (uv sync, uv run, uv.lock for reproducibility)
- **ruff** - universal linter + formatter (replaced Black + isort)
- **mypy --strict** on src/ (enforced in CI)
- **pre-commit** - local gates before every commit (ruff + mypy + basic checks)
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
2. Run `scribe rec --check` for a read-only connection test
3. Check `SCRIBE_OBS_PASSWORD` or `[obs].password` in `~/.scribe/config.toml`
4. Scribe can launch OBS only when no OBS process is already running; it will not kill or restart a running OBS instance

**"No recording file detected" error:**

1. Check OBS Settings → Output → Recording Path matches your `SCRIBE_OUTPUT_FOLDER`
2. Scribe searches the OBS recording directory for 15 seconds after stop
3. If OBS records to a different folder, Scribe will tell you where it looked

**OBS keeps asking about safe mode:**

Scribe cleans crash sentinel files before launching OBS with `--disable-shutdown-check`, but it does not kill a running OBS process. If you still see the safe mode dialog, close OBS manually and delete `%APPDATA%/obs-studio/global.ini`.

**To configure OBS WebSocket:**
1. Open OBS Studio
2. Go to Tools > WebSocket Server Settings
3. Enable WebSocket server on port 4455
4. Run `scribe init --force` and configure OBS, or set `SCRIBE_OBS_PASSWORD`
5. Run `scribe rec --check` or `scribe doctor` to verify

### Exit Codes
- 0: All requested work completed, including confirmed instrumental results
- 1: Failure or partial completion, including missing inputs or requested artifacts
- 2: Invalid arguments
- 3: External tool failure (FFmpeg, OBS, CUDA)
- 4: API error

`--continue-on-error` controls whether later batch or music inputs are attempted.
It does not hide an incomplete final result: any partial or failed item still makes
the command exit 1 after printing the complete summary.

### Failure Evidence

After a file, URL, batch-item, recording, or music-track session starts, Scribe
writes a uniquely named `*_session_summary.json` record for its terminal outcome.
The record distinguishes `success`, `partial`, `failed`, and `instrumental` rather
than reducing every usable-but-incomplete result to success or failure. Incomplete
output prints the exact local summary path. The summary retains the active
timestamped log path when one is available, plus local artifact paths, so you can
recover a surviving recording, transcript, or lyrics file and inspect the precise
failed stage. If the summary itself cannot be written, Scribe reports that
evidence gap without hiding the original command failure.

`scribe support-bundle` discovers a bounded newest-first set of those summaries in
the configured output folder and recent logs in the configured log folder. The
shareable bundle contains only a redacted session projection and opaque log
metadata. Structured session filenames, meeting names, artifact paths, log
filenames, and log contents are excluded. Redacted error and diagnostic text is
retained because it is needed for troubleshooting, so review the JSON before
sharing it.

See [Troubleshooting Guide](docs/TROUBLESHOOTING.md) for more solutions.

---

## Documentation

### Core Documentation
- [Architecture Guide](docs/ARCHITECTURE.md) - System architecture and design patterns
- [Agentic Balance](docs/AGENTIC_BALANCE.md) - Where Scribe uses deterministic rules versus model judgment
- [API Reference](docs/API_REFERENCE.md) - Complete API documentation
- [Development Guide](docs/DEVELOPMENT.md) - Development setup and workflows
- [Troubleshooting Guide](docs/TROUBLESHOOTING.md) - Common issues and solutions
- [Performance Tuning](docs/PERFORMANCE_TUNING.md) - Optimization and benchmarking
- [Deployment Guide](docs/DEPLOYMENT.md) - Local install, self-managed operation, and backup guidance

### Feature Documentation
- [Music Mode Architecture](docs/features/MUSIC_MODE_ARCHITECTURE.md) - Music transcription technical details
- [Polyglot Architecture Plan](docs/features/POLYGLOT_ARCHITECTURE_PLAN.md) - Architectural decoupling of audio pipelines (Rust) and background daemons (Go) for zero-latency, sub-10MB idle footprint
- [Resident Voice Tray Utility Plan](docs/features/VOICE_TRAY_UTILITY_PLAN.md) - Initial resident dictation and read-aloud prototype, validation plan, and follow-on work

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

License terms are pending owner confirmation. Current repository evidence is inconsistent: earlier README copy referenced Apache 2.0 + Commons Clause, `pyproject.toml` declares MIT, and no LICENSE file is present.

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

**Workspace Version:** 2.8.1 in development (latest release tag: v2.8.0)
**Build Status:** Refer to local CI/test runs
**Focus:** Reliability and maintainability - see [ROADMAP](ROADMAP.md)
**Last Updated:** 2026-07-15
