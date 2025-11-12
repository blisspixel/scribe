# Scribe Roadmap

## Focus Areas

**Reliability, User Experience, and Install Simplicity**

---

## Installer and Bootstrap

**One-command install on Windows, macOS, and Linux**. Auto-detect FFmpeg and provide guided setup prompts. Goal: A new user can complete setup and produce their first transcript in under five minutes.

- Detect Python, FFmpeg, CUDA availability
- Guided `.env` setup with validation
- Platform-specific install scripts
- Auto-download FFmpeg if missing (optional)

---

## Observability (Complete)

**Structured logs with run IDs, timestamps, GPU model, and configuration summary**. Single "support bundle" command that collects logs, environment info, and last-run metadata.

- [DONE] Run ID tracking across all operations
- [DONE] AsyncIO-compatible context management with contextvars
- [DONE] Structured metadata collection
- [DONE] Run history with automatic tracking
- [DONE] Nested operation support
- [DONE] Thread-safe and async-safe context propagation
- [TODO] GPU model and CUDA version in logs
- [TODO] Configuration snapshot per run
- [TODO] `scribe support-bundle` command for troubleshooting

---

## Safe Writes and Recovery (Complete)

**Use temp files and atomic renames to prevent corruption on failure**. Resume interrupted transcriptions automatically when possible. Include quota and backoff handling for API mode.

- [DONE] Atomic file writes (write to `.tmp`, rename on success)
- [DONE] Platform-specific atomic rename (Windows and POSIX)
- [DONE] Safe copy operations with atomic rename
- [DONE] Backup file creation before modifications
- [DONE] Context manager for safe file writing
- [DONE] Automatic cleanup on failure
- [TODO] Resume from checkpoint for long transcriptions
- [TODO] Exponential backoff for API rate limits
- [TODO] Graceful degradation on quota exhaustion

---

## Clear Diagnostics (Complete)

**Config doctor that validates environment, CUDA, FFmpeg, and API key status**. Human-readable error messages with suggested fixes.

- [DONE] `scribe doctor` command validates full environment
- [DONE] Check CUDA, FFmpeg, API key, disk space
- [DONE] Actionable error messages with fix suggestions
- [DONE] Platform-specific guidance (Windows vs macOS vs Linux)

---

## Performance and Adaptivity

### GPU Detection and Auto-Tuning (Complete)

**Detect available GPU and apply model, beam, and precision settings automatically**. Default to "large-v3 fast" for 24 GB VRAM (4090) and scale down for smaller GPUs without user intervention. Include manual override flags for advanced users.

- [DONE] Auto-detect VRAM and select optimal model
- [DONE] RTX 4090 (24GB): large-v3, beam 10, fp16
- [DONE] RTX 4080 (16GB): large-v3, beam 8, fp16
- [DONE] RTX 4070 (12GB): large-v2, beam 5, fp16
- [DONE] GPU Resource Manager prevents OOM and concurrent access
- [DONE] Automatic model switching with cleanup
- [DONE] Manual overrides: `--model`, `--method`

### Resource Management (Complete)

**Prevent OOM and runaway processes with configurable limits**. Validate file size and duration before processing.

- [DONE] Configurable file size limits (default: 25GB)
- [DONE] Configurable duration limits (default: 12 hours)
- [DONE] Early validation with clear error messages
- [DONE] GPU memory management with singleton pattern
- [DONE] Thread-safe model loading and unloading
- [DONE] Automatic GPU cache clearing

### Mid-Range GPU Optimization (Complete)

**Mixed-precision inference and tuned beam sizes for 12 GB–16 GB cards**. Aim for consistent accuracy at lower memory and compute cost.

- [DONE] FP16 inference by default
- [DONE] Dynamic beam size based on VRAM
- [DONE] Memory-efficient batching
- [DONE] Fallback to API if GPU OOM
- [DONE] Resource limits prevent crashes

---

## Usability and Interface

### CLI Ergonomics (Partial)

**Consistent flags across commands**. Descriptive help text with grouped sections. Shell completion for Bash, Zsh, and PowerShell.

- [DONE] Standardize flag names (`--output`, `--model`, `--method`)
- [DONE] `--no-joke` and `--no-meme` flags for disabling humor
- [DONE] Consistent exit codes and error handling
- [TODO] Group help text by category (Input, Output, Performance, AI)
- [TODO] Shell completion scripts in `completions/`

### Export and Sharing

**Markdown outputs include front-matter metadata for downstream tools**. DOCX templates follow clean Word styles for business use. Provide an optional JSON schema for programmatic consumption of transcripts and notes.

- YAML front-matter in Markdown notes
- Clean DOCX styles (Heading 1, Heading 2, Body Text)
- JSON export: `scribe transcribe --format json`
- Schema documentation for API consumers

---

## Intelligence and Analysis

### Meeting Notes

**Streamline GPT-5 note generation for clarity and consistent structure**. Allow user-defined templates and redaction rules for sensitive data.

- User-defined note templates (YAML config)
- Redaction patterns for PII, emails, phone numbers
- Consistent section structure
- Confidence scoring and quality metrics

### Advanced Diarization

**Speaker profile hints and optional correction pass to improve attribution accuracy**. Support a local diarization path for offline workflows.

- Speaker name hints (config file)
- Post-processing correction pass
- Local diarization with pyannote (optional)
- Offline-first workflows

### QA and Humor Controls

**Keep meme QA loop configurable and optional**. Default to safe, concise humor modes suitable for professional settings.

- Configurable QA threshold and attempts
- Disable humor: `--no-joke --no-meme`
- Professional mode (conservative humor)
- Humor style presets (professional, casual, creative)

---

## Humor and Meme System

### Goals

Scribe's humor system exists to say what everyone in the meeting was thinking but didn't dare say out loud. It should sting just enough to be funny, but not enough to ruin your career. The goal is to create jokes that feel alive, brutally honest, and perfectly timed — the kind people read twice, grin at, and then forward with "this is too real."

### Tone Philosophy

- Humor should expose the absurdity of modern collaboration — endless alignment sessions, PowerPoint optimism, leadership doublespeak, and the quiet collective acceptance of chaos
- Slightly offensive is acceptable if it punches up — at processes, bureaucracy, or shared delusion — never at individuals or vulnerable groups
- The jokes should feel earned: they emerge from observation and insight, not random quips
- The best humor isn't "nice," it's accurate

### Structure and Style

- Allow longer, context-aware jokes — one to three paragraphs if needed. Brevity is good, but depth lands harder
- Write with a human narrative voice, as if from the perspective of the only sane person trapped in a meeting that won't end
- Capture the emotional arc: optimism → confusion → despair → ironic acceptance
- Encourage dark humor and quiet sarcasm. A good line should make readers laugh and question their life choices

**Example flavor**:
- "By minute 42, the team had achieved synergy — everyone agreed that someone else should do it."
- "The AI system detected 17 uses of the phrase 'circle back,' none of which resulted in actual movement."

### Implementation Priorities

**Introduce a spice index** via `SCRIBE_HUMOR_SPICE=0–10` (environment) or `--spice` (CLI flag):

| Level | Description | Behavior |
|-------|-------------|----------|
| **0** | Off | No jokes or memes generated |
| **1–3** | Mild | Office-safe irony, gentle observations |
| **4–6** | Honest | Witty, occasionally dark, shareable |
| **7–8** | Cutting | Slightly uncomfortable, still shareable |
| **9–10** | Spicy | "I can't believe this app said that" funny — default off unless explicitly enabled |

**Default**: Level 5 (honest, witty, safe for most contexts)

**Usage**:
```bash
# Environment variable (persistent)
SCRIBE_HUMOR_SPICE=8

# CLI flag (per-command override)
scribe meme transcript.txt --spice 10
scribe joke transcript.txt --spice 3
scribe transcribe meeting.mp4 --spice 7
```

**Additional controls**:
- Keep QA loop configurable, bias toward humor quality over safety
- Favor language that sounds human — weary, clever, grounded in reality
- Use context from transcript: recurring topics, contradictions, overused phrases, awkward silences
- Allow strong language in moderation when it improves timing or authenticity

### Cultural Boundaries

- Never attack personal identity or private individuals
- Punch upward — mock dysfunction, process, corporate absurdity, or misplaced confidence
- Allow strong language in moderation when it sounds natural and not hateful
- Profanity is acceptable in higher spice levels if it improves authenticity

### Output Behavior

- Text jokes appear before file links as a narrative quip
- Meme captions can include full-sentence context or quick one-liners; format flexibly
- Humor can appear in text-only transcripts for stealth comedy mode
- Memes prioritize what's funny, not polished composition — raw beats pretty

### Success Criteria

| Metric | Definition | Target |
|--------|------------|--------|
| **Laugh Rate** | People who react with genuine laughter | ≥85% |
| **Flinch Rate** | Jokes that cross into discomfort but not offense | ~10% (healthy tension) |
| **Safety Violations** | Explicitly inappropriate jokes | <1% |
| **Re-Enable Rate** | Users who turn humor back on after disabling | ≥95% |

---

## Privacy and Local-Only Operation

**Add a Local-Only Switch to disable all outbound API calls**. Ensure all local inference paths remain fully functional and transparent. Explicitly label runs that use remote models in logs and output metadata.

- `--local-only` flag disables all API calls
- Validate local-only mode (GPU required, no notes/jokes/memes)
- Log all API calls with model and token count
- Output metadata includes "local" or "api" source

---

## Metrics to Target

| Metric | Definition | Target |
|--------|------------|--------|
| **Accuracy** | Word error rate on internal evaluation set | Maintain or improve current baseline |
| **Stability** | Successful job completion rate and mean time to recover | 99.5% success, recovery under 30s |
| **Edit Burden** | Percentage of generated notes requiring manual edits | Under 10% after pilot feedback |

---

## Contribution Priorities

1. Improve install and bootstrap flow on non-Windows platforms
2. Expand GPU auto-detection and presets beyond RTX 4090
3. Enhance notes formatting, diarization, and JSON schema exports
4. Simplify CLI help, error output, and configuration validation
5. Maintain focus on stability and predictability over new features

---

## Current Status

**Version**: 2.0  
**Test Coverage**: 45% (463 tests passing)  
**Platform Support**: Windows (primary), macOS (tested), Linux (tested)

**Recent Additions** (November 2025):
- GPU Resource Manager with singleton pattern and thread-safe locking
- Resource limits validation (file size and duration)
- AsyncIO support with contextvars for async/await compatibility
- Meeting notes generator (GPT-5 multi-step reasoning)
- Meme generation with QA loop (multiple attempts, scoring)
- Configurable QA thresholds via environment variables
- Consistent progress spinners across all commands
- Humor spice levels (0-10) for jokes and memes
- New comedy archetypes: Based Observer and Gen Z Commentator
- System diagnostics command (`scribe doctor`)
- Humor control flags (`--no-joke`, `--no-meme`)
- Atomic file writes with platform-specific handling
- Run context tracking with unique IDs and metadata
- Cross-platform atomic writes (Windows and POSIX)

---

## Not Planned

- Enterprise features (team collaboration, access controls)
- Real-time translation
- Distributed processing
- Over-complicated integrations
- Chasing 100% test coverage

---

**Last Updated**: November 2025
