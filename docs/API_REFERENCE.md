# Python API Reference

Scribe's supported product interface is the `scribe` command-line interface.
The Python modules documented here are useful for integrations and tests, but
they are internal interfaces in the 2.x series and can change without a separate
deprecation cycle. Prefer [CLI.md](CLI.md) for automation that needs a stable
contract.

All examples assume Scribe is installed from this repository and Python 3.12 or
3.13 is active.

## Transcription orchestration

`scribe.core.transcriber.Transcriber` selects a local or OpenAI transcription
path from `ScribeConfig` and writes a transcript artifact.

```python
from pathlib import Path

from scribe.core.transcriber import Transcriber
from scribe.models.config import ScribeConfig

config = ScribeConfig()
transcript = Transcriber(config).transcribe(
    Path("authorized-recording.mp4"),
    method="local",
)
print(transcript)
```

Current signature:

```python
Transcriber(config: ScribeConfig)
Transcriber.transcribe(
    audio_path: Path,
    method: Literal["auto", "local", "openai"] = "auto",
    session: TranscriptionSession | None = None,
    custom_vocabulary: CustomVocabulary | None = None,
    music_mode: bool = False,
) -> Path
```

`auto` is local-first and does not silently send a failed local job to a paid
cloud provider. Use `openai` explicitly when cloud transcription is intended.

## Local transcription

```python
from pathlib import Path

from scribe.core.local_whisper import LocalWhisperTranscriber

worker = LocalWhisperTranscriber(model_size="small", language="en")
transcript = worker.transcribe(Path("authorized-audio.wav"))
```

Current signature:

```python
LocalWhisperTranscriber(
    model_size: str = "large-v3",
    language: str | None = "en",
    gpu_config: GPUConfig | None = None,
)
LocalWhisperTranscriber.transcribe(
    audio_path: Path,
    output_path: Path | None = None,
    detect_silence: bool = True,
    initial_prompt: str | None = None,
    music_mode: bool = False,
    diarizer: SpeakerDiarizer | None = None,
) -> Path
```

Backend selection can use faster-whisper on CPU or supported GPUs, MLX on Apple
Silicon when installed, or whisper.cpp when configured. Availability depends on
the host and installed extras. Use `scribe doctor` before embedding a backend.

## OpenAI transcription

This interface uploads audio to OpenAI. Obtain recording permission and approval
to share the content with the provider before calling it.

```python
import os
from pathlib import Path

from scribe.core.openai_api import OpenAITranscriber

worker = OpenAITranscriber(api_key=os.environ["OPENAI_API_KEY"])
transcript = worker.transcribe(Path("authorized-audio.wav"))
```

Current signature:

```python
OpenAITranscriber(
    api_key: str,
    model: str = "gpt-4o-transcribe",
    use_server_chunking: bool = True,
)
OpenAITranscriber.transcribe(
    audio_path: Path,
    output_path: Path | None = None,
    prompt: str | None = None,
    cleanup_temp: bool = True,
    initial_prompt: str | None = None,
) -> Path
```

## Notes, jokes, and memes

These optional features can send transcript text to the selected provider. Meme
generation can also send a generated concept to a separate image provider.

```python
from pathlib import Path

from scribe.utils.notes_generator import NotesGenerator

generator = NotesGenerator(provider_name="ollama")
notes = generator.generate_notes(Path("transcript.txt"))
```

```python
NotesGenerator(
    api_key: str | None = None,
    model: str = "",
    max_retries: int = 3,
    provider_name: str | None = None,
)
NotesGenerator.generate_notes(
    transcript_path: Path,
    output_path: Path | None = None,
) -> Path
```

```python
from pathlib import Path

from scribe.utils.joke_generator import generate_transcript_joke
from scribe.utils.meme_generator import generate_meeting_meme

joke = generate_transcript_joke(Path("transcript.txt"), provider_name="xai")
if joke is not None:
    joke_text, style = joke

meme = generate_meeting_meme(Path("transcript.txt"), provider_name="xai")
if meme is not None:
    final_path = meme["final_path"]
```

`generate_transcript_joke` returns `(text, style)` or `None`.
`generate_meeting_meme` returns a result dictionary or `None`; its dictionary
contains `final_path`, an `attempts` list, and optional bake-off metadata.
An empty notes model uses the selected provider's current default.

## Resource and progress helpers

`GPUResourceManager` serializes ownership of a loaded GPU model within the
process. It does not expose hardware inventory properties.

```python
from scribe.utils.gpu_manager import GPUResourceManager

manager = GPUResourceManager()
with manager.acquire_gpu("large-v3", model_obj):
    run_inference(model_obj)

manager.get_current_model()  # str | None
manager.unload_current_model()
```

`ProgressTracker` tracks one in-memory operation. Durable performance history is
implemented separately in `scribe.utils.performance_tracker`.

```python
from scribe.utils.progress import ProgressTracker

progress = ProgressTracker(total_duration=3600.0, operation="Transcribing")
progress.start()
progress.update(900.0)
eta_seconds = progress.get_eta()
progress.complete()
```

## Diagnostics and file helpers

```python
from scribe.utils.diagnostics import SystemDiagnostics

results = SystemDiagnostics().run_all_checks(live=False)
```

`live=False` performs local checks only. `live=True` permits provider validation
requests. Each result contains `name`, `status`, `message`, and an optional
`fix_suggestion`.

Use `scribe.utils.files.safe_path(value)` to normalize a user path after
environment and home expansion. It returns a `Path`; it does not establish that
the caller is authorized to read or write that location.

## Errors and compatibility

Public CLI failures are normalized through the exception types in
`scribe.exceptions`. Python callers should expect internal exceptions to evolve
with implementation changes. Pin an exact Scribe commit and add integration tests
if an application imports these modules directly.

Last verified against Scribe 2.8.1 on 2026-08-11.
