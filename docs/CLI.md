# CLI Guide

This guide covers Scribe's common user workflows. Run `scribe --help` or
`scribe COMMAND --help` for the complete, version-matched option set.

## Transcription

```bash
# One local file
scribe meeting.mp4
scribe transcribe meeting.mp4

# Language and vocabulary
scribe transcribe meeting.mp4 --language es --vocab tech
scribe transcribe meeting.mp4 --vocab path/to/terms.txt

# URL input
scribe url https://example.com/podcast.mp3
scribe url https://youtu.be/VIDEO_ID --cookies edge

# Explicit OpenRouter upload with a per-file reported-cost guard
scribe meeting.mp4 --method openrouter --max-spend 5

# Multiple inputs
scribe batch *.mp4
scribe batch first.wav second.wav
scribe batch *.mp4 -o ./archive --format json,md

# Music and lyrics
scribe music song.mp3
scribe music album/*.flac --method local
```

`--method auto` and `--method local` are local and do not silently select a cloud
API. Use `--method openai` or `--method openrouter` only when cloud transcription
is intentional. OpenRouter setup and partial-chunk recovery are in the
[Cloud Transcription Guide](CLOUD_TRANSCRIPTION.md).

Local speaker labels ("who said what") need one diarization extra. The
token-free `diarize-nemotron` extra runs NVIDIA Nemotron-3 Diarization, which
needs no Hugging Face token, handles up to eight speakers, and runs on CUDA or CPU.
The `diarize` extra runs pyannote and needs an `HF_TOKEN` with the pyannote model
terms accepted. Labels are experimental and off by default, including when an
extra is installed. Use `--diarize` or `--diarizer BACKEND` to opt in for a run;
`--no-diarize` overrides an enabled setting. Ordinary local transcription uses
full Whisper large-v3 unless a model or faster profile is explicitly selected.
The default `max` profile requires cached local acoustic review; `--quality
accurate` selects one pass. See [setup and review limits](ACOUSTIC_REVIEW.md).

```bash
scribe transcribe meeting.mp4 --diarize
scribe transcribe meeting.mp4 --diarizer pyannote   # more than eight speakers
scribe transcribe meeting.mp4 --no-diarize
```

`auto` prefers MLX on Apple Silicon, then Nemotron, then pyannote, skipping any
backend whose extra or token is missing. `scribe info` shows the backend that will
run and its device. The first run downloads the model from Hugging Face; later
runs are offline. Speaker labels never fail a transcription: if labeling fails,
the unlabeled transcript is kept and the reason is logged.

Labeled transcripts list the speakers at the top and group each speaker's
consecutive sentences into one paragraph. Short speaker flips inside a sentence,
which are usually diarization jitter at a turn edge, are folded into the
sentence's main speaker.

These heuristics can hide brief participants or merge similar voices. Do not
assume that the detected speaker count equals the number of people on a call.
To disable labels persistently, set this in the [user config file](STORAGE.md):

```toml
[diarization]
enabled = false
```

`SCRIBE_ENABLE_SPEAKER_DIARIZATION=false` also disables labels. Existing explicit
opt-ins in configuration remain effective after an upgrade.

### Speaker names

`--name-speakers` also enables local labeling unless `--no-diarize` or
`--diarizer none` is supplied. To enable naming persistently, set both
`enabled = true` and `name_speakers = true` under `[diarization]` in
the [user config file](STORAGE.md). Names are suggested from the conversation, such as
introductions and people addressing each other. A language model proposes the
names that are spoken; Scribe then assigns each name to a speaker by counting
evidence across every mention, and leaves a speaker unidentified when the
evidence is not clear. The header shows the best guess for easy correction:

```text
Speakers (best guess from the conversation; fix names here and in the text):
  Dana = SPEAKER_00
  Priya = SPEAKER_01 (possibly also: Sam)
  SPEAKER_02 = unidentified
```

"Possibly also" means one label collected two names, which often happens when
diarization merges two similar voices. Naming uses a local Ollama model by
default and unloads it when done. It sends the transcript to a cloud provider only
when you choose one:

```bash
scribe transcribe meeting.mp4 --name-speakers
SCRIBE_SPEAKERS_PROVIDER=openrouter scribe transcribe meeting.mp4 --name-speakers
```

Supported providers are `ollama`, `openai`, `openrouter`, `anthropic`, `gemini`,
and `xai`; `SCRIBE_SPEAKERS_MODEL` overrides the model. Local-only mode always
keeps naming local. If no local model is available, naming is skipped.

## Optional generated outputs

Notes, jokes, and memes are disabled by default. A positive flag enables the
feature for one run; a `--no-` flag overrides a configured default.

```bash
scribe meeting.mp4 --notes
scribe meeting.mp4 --notes --meme
scribe batch *.mp4 --no-notes --no-joke --no-meme

scribe notes transcript.md
scribe notes transcript.md --provider ollama
scribe notes transcript.md --compare openai,ollama:qwen2.5:14b --judge openai
scribe joke transcript.docx --spice 5
scribe joke transcript.docx --provider xai
scribe meme transcript.md --provider xai
```

The standalone intelligence commands accept TXT, Markdown, and DOCX transcript
inputs. Select a notes, joke, or meme concept provider with `--provider`.
Notes default to local Ollama when no provider is selected. An explicit
`--provider` wins over `SCRIBE_NOTES_PROVIDER`, then `[providers].notes_provider`
in `~/.scribe/config.toml`. Existing explicit choices stay in effect. A cloud
notes provider sends the transcript to that provider and can incur charges;
having an API key alone does not opt notes into cloud use. Local notes do not
fall back to cloud when Ollama is unavailable, including with optional provider
health checks enabled. Install and select a suitable local model before running
notes; `--model` overrides the existing installed-model selection policy.

Notes show Summary 1/3, Breakdown 2/3, and Polish 3/3 with elapsed time. A terminal
updates one line; redirected output records one line per phase transition.
Long transcripts identify each chunk before the merged polish phase. Elapsed
time is measured, not a completion estimate; CPU inference can take minutes.

Detailed Summary is prose. Business and technical sections appear only when
populated; undiscussed categories may be empty. The prompts distinguish a
meeting from an interview, lecture, or fictional reading and ask for explicit
source support. Transcript header dates may come from a filename or the day of
transcription, so notes omit them as event dates and exclude those headers from
model evidence. Spoken dates remain in the transcript evidence. These controls
reduce unsupported claims; they do not verify factual accuracy. Review notes
against the original transcript before relying on them. Notes retain the existing
minimum of 100 transcript words.

Configure meme quality with `SCRIBE_MEME_QA_THRESHOLD` and
`SCRIBE_MEME_QA_ATTEMPTS`. Memes use a separate configurable image provider and
can incur a separate image-generation charge.

## Recording

```bash
scribe rec "Team Meeting"
scribe record --name "Board Meeting"
scribe record --name "Cloud Meeting" --method openrouter --max-spend 5
scribe record --no-auto-transcribe
scribe rec --check
```

Quick Record launchers call the stable global `scribe` command:

```bash
scribe shortcut
scribe shortcut --desktop
scribe shortcut --remove
```

Read the [Recording Guide](RECORDING.md) before relying on OBS for an important
meeting. See [Troubleshooting](TROUBLESHOOTING.md) for symptom-specific recovery.

## Transcript search and vocabulary

```bash
scribe query "budget"
scribe query "action item" --speaker SPEAKER_01

scribe vocab
scribe vocab finance
```

Structured JSON transcripts are searchable. Glossaries bias recognition and can
rewrite known misrecognitions after transcription.

## Voice commands

```bash
scribe listen
scribe listen --mode hold
scribe listen --mode continuous
scribe listen --inject type

scribe say transcript.txt
scribe say --selection
scribe say --clipboard
scribe say notes.md --speed 1.2

scribe tray --setup
scribe tray --check
scribe tray
```

See the [Resident Voice Guide](VOICE.md) before enabling the always-running tray.

## Diagnostics

```bash
scribe doctor
scribe doctor --live
scribe health
scribe health --provider openai
scribe info
scribe version
scribe support-bundle
```

`doctor` is local by default. `doctor --live` and provider health checks can make
network calls when a provider key is configured.

## Common transcription flags

| Flag | Meaning |
|---|---|
| `--method auto\|local\|openai\|openrouter` | Local automatic, forced local, or an explicit cloud provider |
| `--max-spend USD` | Per-file OpenRouter reported-cost guard; default $5, with a provider key limit required for an absolute cap |
| `--model MODEL` | Whisper model selection |
| `--quality max\|accurate\|balanced\|fast` | Full-model review default, full-model one pass, or explicit faster model profiles |
| `--verification required\|best-effort\|off` | Override the profile review policy |
| `--verification-model MODEL` | Already cached local secondary checkpoint |
| `--language CODE` | ISO 639-1 language code |
| `--vocab NAME_OR_FILE` | Bundled glossary or custom TXT/JSON vocabulary |
| `--format json,vtt,srt,md` | Structured sidecars in addition to TXT |
| `--diarize` / `--no-diarize` | Force local speaker labels on or off for this run |
| `--diarizer auto\|nemotron\|pyannote\|mlx\|none` | Choose the local speaker-label backend |
| `--no-docx` | Skip DOCX output |
| `--notes` / `--no-notes` | Force notes on or off for this run |
| `--joke` / `--no-joke` | Force joke generation on or off |
| `--meme` / `--no-meme` | Force image generation on or off |
| `--cookies BROWSER` | Use browser cookies for a protected media URL |

## Batch and music behavior

Batch and music commands continue through later inputs by default. Use
`--stop-on-error` to stop at the first missing or failed item.

A complete run exits 0. Missing files, failed items, partial music segments, or
requested artifacts that could not be generated produce a final summary and exit
1. A confirmed instrumental track is a successful outcome. A planned partial
exit keeps the saved partial outcome and is not logged as a later session error.
An unexpected failure after that summary is saved is still logged and does not
rewrite the saved outcome.

## Exit codes and evidence

| Code | Meaning |
|---|---|
| 0 | All requested work completed |
| 1 | Runtime, validation, dependency, provider, or partial-artifact failure |
| 2 | Command-line usage or parsing error |

Every started file, URL, batch item, recording, and music track writes a unique
`*_session_summary.json`. The record distinguishes `success`, `partial`, `failed`,
and `instrumental`, and retains available artifact and log paths. An evidence-write
failure is reported separately without replacing the original workflow result.

`files_created` excludes original input references. `files_cleaned` records
disposed conversions/downloads, while `files_moved` records transcript archive
source and destination paths. File, URL, batch, and recording conversion cleanup
only removes files owned by that run. Recoverable partial transcripts survive
failure. File/URL `--keep-all` retains intermediate audio beside the input without
replacing an existing conversion; configuration also controls this for batch and
recording.

Terminal rendering is presentation-only. A closed pipe or unsupported output
encoding cannot turn completed work into a traceback or erase saved evidence.

`scribe support-bundle` produces a bounded redacted projection of recent summaries
plus opaque log metadata. It excludes transcript bodies, media, artifact paths,
log names, and log contents. Review its JSON before sharing it.

## Configuration

Precedence, highest first:

1. CLI flags.
2. Environment variables and `.env`.
3. The [user config file](STORAGE.md).

Run `scribe init` for the guided configuration flow. See the
[Deployment Guide](DEPLOYMENT.md) for supported installs and settings.
