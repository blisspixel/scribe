# Cloud Transcription

Scribe is local-first. Cloud transcription is available only when you select a
cloud method explicitly or save one as your default. `auto` never uploads audio.

## Choose the data boundary

| Method | Audio location | Key | Behavior |
|---|---|---|---|
| `auto` | Local | None | Selects a local backend on GPU or CPU |
| `local` | Local | None | Forces local processing |
| `openai` | OpenAI | `OPENAI_API_KEY` | Uses the configured OpenAI transcription model |
| `openrouter` | OpenRouter and its routed provider | `OPENROUTER_API_KEY` | Uses the configured OpenRouter STT model |

Use cloud transcription only when the recording is authorized for third-party
processing. Provider terms, routing, retention, regional processing, model
availability, and pricing can change independently of Scribe. OpenRouter can
route a request to the provider serving the selected model, so approval must
cover both OpenRouter and that provider.

`SCRIBE_LOCAL_ONLY=1` overrides every configured or requested cloud method and
keeps transcription local. It is the appropriate guard when no network
transmission is permitted.

## OpenRouter setup

Create an OpenRouter key, then put it in your user environment or an untracked
`.env` file. Do not put a key in `config.toml`, a command argument, source control,
an issue, or a support bundle.

PowerShell for the current terminal:

```powershell
$env:OPENROUTER_API_KEY = "your-key"
scribe meeting.mp4 --method openrouter
```

macOS or Linux for the current shell:

```bash
export OPENROUTER_API_KEY="your-key"
scribe meeting.mp4 --method openrouter
```

Optional settings:

```env
OPENROUTER_API_KEY=
SCRIBE_OPENROUTER_MODEL=openai/whisper-1
SCRIBE_OPENROUTER_TIMEOUT_SECONDS=90
SCRIBE_MAX_RETRIES=3
```

The model must be an OpenRouter speech-to-text model slug. Discover current
models with OpenRouter's transcription model filter rather than assuming an old
slug is still available. Scribe's default follows the provider's documented
`openai/whisper-1` example.

OpenRouter documents a dedicated
[`/api/v1/audio/transcriptions`](https://openrouter.ai/docs/guides/overview/multimodal/stt)
endpoint. It accepts raw base64 audio in JSON and returns text plus optional usage
and cost information. Scribe calls this dedicated endpoint directly instead of
using the conversational audio endpoint.

## Long-recording reliability

Scribe does not put a multi-hour recording into memory or a single OpenRouter
request. The OpenRouter path:

1. Uses streaming FFmpeg conversion in a unique system temporary directory to
   create mono, 16 kHz, 48 kbps MP3 audio without colliding with source files.
2. Splits that audio into no more than five-minute chunks with a small overlap.
3. Refuses any generated chunk larger than Scribe's 12 MiB upload ceiling.
4. Sends chunks sequentially with a bounded timeout and retry schedule.
5. Fails immediately on rejected credentials or insufficient credits.
6. Atomically refreshes a labeled `*_transcription.partial.txt` after every
   confirmed chunk.
7. Publishes the normal transcript only after every chunk succeeds.
8. Atomically archives existing complete or partial output with a `.previous`
   suffix before a rerun, so an old result cannot look like a successful new one.

If a cloud chunk still fails, the normal transcription orchestrator attempts the
local backend for the complete source. A successful local recovery becomes the
complete result. If local recovery also fails, the command exits nonzero and the
confirmed cloud partial remains available. Scribe never skips a failed middle
chunk and labels the remaining text complete.

A timeout, connection loss after upload, or server error can make completion
ambiguous. Scribe retries these failures to favor transcript recovery, but it
cannot prove that a failed attempt was not processed and billed. Set
`SCRIBE_MAX_RETRIES=1` when avoiding a possible duplicate billable request is
more important than automatic cloud recovery.

The unique temporary workspace and its normalized audio and chunks are removed
by default. Use `--keep-all` only when you intentionally need intermediate files
for diagnosis and have disk space for them; the retained directory is logged.

## Output differences

OpenRouter's dedicated STT response contract returns transcript text, not
speaker-labeled or word-timestamped segments. Scribe therefore records
OpenRouter provenance and chunk-level approximate timing in structured output.
Use local diarization or the supported OpenAI diarization model when speaker
labels are required.

When OpenRouter reports usage cost, Scribe records the aggregate in transcript
metadata and logs it without logging request audio or the API key. Actual billing
is controlled by OpenRouter and the routed provider.

## Diagnostics and safe testing

`scribe doctor` is offline with respect to cloud providers. `scribe doctor
--live` validates a configured OpenRouter key through OpenRouter's
[`GET /api/v1/key`](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-key)
endpoint. This checks authentication without submitting audio.

For an end-to-end test, use a short synthetic or non-sensitive audio file:

```bash
scribe synthetic-test.wav --method openrouter --language en
```

Review the terminal notice before upload, the TXT result, the JSON provenance,
and the session summary. Avoid using a real meeting merely to test credentials.

## Troubleshooting

- `--method openrouter needs an OpenRouter API key`: set
  `OPENROUTER_API_KEY` in the current environment or `.env`.
- Authentication failed: run `scribe doctor --live`, then rotate or replace the
  rejected key without printing it.
- Insufficient credits: review the OpenRouter account limit and current model
  pricing before retrying.
- Model not found: choose a current model whose output modality is
  `transcription`.
- Repeated timeout or 5xx response: keep the partial transcript, check provider
  status, and retry later or use `--method local`.
- A partial transcript exists: do not treat it as complete. Check the session
  summary and the reported failed chunk.

See [Responsible Use](RESPONSIBLE_USE.md) for consent and sensitive-data limits
and [Troubleshooting](TROUBLESHOOTING.md) for the rest of the local pipeline.
