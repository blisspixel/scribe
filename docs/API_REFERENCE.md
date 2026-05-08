# API Reference

**Last Updated:** 2025-11-18

## Core Classes

### Transcriber

Main orchestration class for transcription operations.

```python
from scribe.core.transcriber import Transcriber

transcriber = Transcriber(
    method="auto",           # "auto", "local", or "openai"
    model="large-v3",        # Whisper model
    language="en",           # ISO 639-1 language code
    output_folder=Path("./output")
)

# Transcribe a file
transcript_path = transcriber.transcribe(
    audio_path=Path("meeting.mp4"),
    vocabulary=None,         # Optional custom vocabulary
    enable_notes=True,       # Generate meeting notes
    enable_joke=True,        # Generate joke
    enable_meme=True         # Generate meme
)
```

**Methods:**

`transcribe(audio_path, vocabulary=None, enable_notes=True, enable_joke=True, enable_meme=True) -> Path`
- Transcribes audio/video file
- Returns path to transcript file
- Raises `TranscriptionError` on failure

`batch_transcribe(files, **kwargs) -> List[Path]`
- Transcribes multiple files
- Returns list of transcript paths
- Continues on error by default


### LocalWhisperTranscriber

GPU-accelerated transcription using faster-whisper.

```python
from scribe.core.local_whisper import LocalWhisperTranscriber

transcriber = LocalWhisperTranscriber(
    model_size="large-v3",
    language="en",
    gpu_config=None  # Auto-detected if None
)

transcript_path = transcriber.transcribe(
    audio_path=Path("audio.wav"),
    output_path=None,        # Auto-generated if None
    detect_silence=True,     # Mark silence periods
    initial_prompt=None      # Custom vocabulary prompt
)
```

**Methods:**

`transcribe(audio_path, output_path=None, detect_silence=True, initial_prompt=None) -> Path`
- GPU-accelerated transcription
- Returns path to transcript
- Raises `TranscriptionError` on failure

### OpenAITranscriber

API-based transcription with speaker diarization.

```python
from scribe.core.openai_api import OpenAITranscriber

transcriber = OpenAITranscriber(
    api_key="sk-...",
    model="gpt-4o-transcribe-diarize",
    language="en"
)

transcript_path = transcriber.transcribe(
    audio_path=Path("meeting.mp4"),
    output_path=None,
    enable_diarization=True  # Speaker identification
)
```

**Methods:**

`transcribe(audio_path, output_path=None, enable_diarization=True) -> Path`
- API-based transcription
- Automatic chunking for large files
- Returns path to transcript

### Converter

Audio/video format conversion with progress tracking.

```python
from scribe.core.converter import Converter

converter = Converter()

# Convert to WAV for local transcription
wav_path = converter.convert_to_wav(
    input_file=Path("video.mp4"),
    output_file=None,        # Auto-generated
    sample_rate=16000,       # 16kHz for Whisper
    channels=1,              # Mono
    show_progress=True,
    progress_callback=None   # Optional callback
)

# Convert to MP3 for API transcription
mp3_path = converter.convert_to_mp3(
    input_file=Path("audio.wav"),
    output_file=None,
    bitrate=48               # kbps
)
```

**Methods:**

`convert_to_wav(input_file, output_file=None, sample_rate=16000, channels=1, show_progress=True, progress_callback=None) -> Path`
- Converts to optimized WAV
- Applies audio normalization
- Returns path to WAV file

`convert_to_mp3(input_file, output_file=None, bitrate=48) -> Path`
- Converts to compressed MP3
- Returns path to MP3 file

### CustomVocabulary

Custom vocabulary for improved transcription accuracy.

```python
from scribe.utils.vocabulary import CustomVocabulary

# From list
vocab = CustomVocabulary(words=["Kubernetes", "PostgreSQL"])

# From file
vocab = CustomVocabulary.from_file("terms.txt")

# Convert to Whisper format
prompt = vocab.to_whisper_format()
# Returns: "Kubernetes, PostgreSQL"

# Check if empty
if vocab:
    print(f"Loaded {len(vocab)} terms")
```

**Methods:**

`from_file(path) -> CustomVocabulary` (classmethod)
- Loads from TXT or JSON file
- Supports comments in TXT files
- Returns CustomVocabulary instance

`to_whisper_format() -> str`
- Converts to comma-separated string
- Preserves capitalization
- Returns formatted prompt

### NotesGenerator

GPT-5.5 meeting notes generation.

```python
from scribe.utils.notes_generator import NotesGenerator, NotesConfig

config = NotesConfig(
    api_key="sk-...",
    model="gpt-5.5",
    provider_name="openai"
)

generator = NotesGenerator(config)

notes_path = generator.generate_notes(
    transcript_path=Path("transcript.txt"),
    output_path=None  # Auto-generated
)
```

**Methods:**

`generate_notes(transcript_path, output_path=None) -> Path`
- Analyzes transcript with GPT-5.5 (or `grok-4.3` when `provider_name="xai"`)
- Generates structured notes
- Returns path to Markdown file

### JokeGenerator

Context-aware joke generation.

```python
from scribe.utils.joke_generator import generate_joke

joke = generate_joke(
    transcript_path=Path("transcript.txt"),
    provider=None,           # Uses default provider
    spice_level=5,           # 0-10 intensity
    show_reasoning=False     # Show AI reasoning
)

print(joke)
```

**Functions:**

`generate_joke(transcript_path, provider=None, spice_level=5, show_reasoning=False) -> str`
- Generates context-aware joke
- Returns joke text
- Raises `JokeGenerationError` on failure

### MemeGenerator

Meme generation with QA loop.

```python
from scribe.utils.meme_generator import generate_meeting_meme, MemeConfig

config = MemeConfig(
    model="gpt-5.5",
    image_model="gpt-image-1",
    size="1024x1024",
    quality="hd",
    qa_threshold=8.0,
    qa_max_attempts=3,
    spice_level=5
)

meme_path = generate_meeting_meme(
    transcript_path=Path("transcript.txt"),
    output_dir=None,
    config=config,
    show_reasoning=False
)
```

**Functions:**

`generate_meeting_meme(transcript_path, output_dir=None, config=None, show_reasoning=False) -> Path`
- Generates meme with QA loop
- Returns path to PNG file
- Returns "SAFETY_BLOCKED" if rejected by safety filter

## Provider Classes

### AIProvider (Base)

Abstract base class for all AI providers.

```python
from scribe.providers.base import AIProvider, ProviderConfig

class CustomProvider(AIProvider):
    def chat_completion(self, messages, **kwargs):
        # Implement
        pass
    
    def generate_image(self, prompt, **kwargs):
        # Implement or raise NotImplementedError
        pass
    
    def transcribe_audio(self, audio_path, **kwargs):
        # Implement or raise NotImplementedError
        pass
```

**Required Methods:**

`chat_completion(messages, max_tokens=4000, temperature=0.7, **kwargs) -> dict`
- Returns: `{"content": str, "usage": dict}`

`generate_image(prompt, size="1024x1024", model=None, quality="standard", **kwargs) -> bytes`
- Returns: Image bytes

`transcribe_audio(audio_path, language="en", **kwargs) -> dict`
- Returns: `{"text": str, "segments": list}`

### OpenAIProvider

```python
from scribe.providers.openai_provider import OpenAIProvider
from scribe.providers.base import ProviderConfig

config = ProviderConfig(
    provider_name="openai",
    api_key="sk-...",
    model="gpt-5.5"
)

provider = OpenAIProvider(config)

# Chat completion
response = provider.chat_completion(
    messages=[
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello!"}
    ],
    max_tokens=1000
)

# Image generation
image_bytes = provider.generate_image(
    prompt="A cat wearing a hat",
    size="1024x1024",
    model="gpt-image-1",
    quality="hd"
)
```

### XAIProvider

```python
from scribe.providers.xai_provider import XAIProvider

config = ProviderConfig(
    provider_name="xai",
    api_key="xai-...",
    model="grok-4.3"
)

provider = XAIProvider(config)

# Same interface as OpenAIProvider
response = provider.chat_completion(messages)
image_bytes = provider.generate_image(prompt)
```

### AnthropicProvider

```python
from scribe.providers.anthropic_provider import AnthropicProvider

config = ProviderConfig(
    provider_name="anthropic",
    api_key="sk-ant-...",
    model="claude-3-5-sonnet-20241022"
)

provider = AnthropicProvider(config)

# Chat completion only (no images)
response = provider.chat_completion(messages)
```

### GeminiProvider

```python
from scribe.providers.gemini_provider import GeminiProvider

config = ProviderConfig(
    provider_name="gemini",
    api_key="...",
    model="gemini-2.5-flash"
)

provider = GeminiProvider(config)

# Chat and image generation
response = provider.chat_completion(messages)
image_bytes = provider.generate_image(prompt, size="1024x1024")
```

## Utility Classes

### GPUResourceManager

Singleton for GPU resource management.

```python
from scribe.utils.gpu_manager import get_gpu_manager

manager = get_gpu_manager()

# Check if GPU available
if manager.has_gpu():
    print(f"GPU: {manager.gpu_name}")
    print(f"VRAM: {manager.gpu_memory_gb}GB")

# Get current model
current = manager.get_current_model()

# Unload model
manager.unload_current_model()
```

**Methods:**

`has_gpu() -> bool`
- Returns True if GPU available

`get_current_model() -> Optional[str]`
- Returns current loaded model ID

`unload_current_model()`
- Unloads current model from GPU

### ProgressTracker

Adaptive progress tracking with Kalman filter.

```python
from scribe.utils.progress import ProgressTracker

tracker = ProgressTracker(
    total_duration=3600.0,  # seconds
    machine_id="unique_id"
)

# Update progress
tracker.update(progress=0.5)  # 50% complete

# Get estimates
eta = tracker.get_eta()
speed_ratio = tracker.get_speed_ratio()

# Save metrics for future runs
tracker.save_metrics()
```

**Methods:**

`update(progress: float)`
- Updates progress (0.0 to 1.0)

`get_eta() -> Optional[float]`
- Returns estimated seconds remaining

`get_speed_ratio() -> Optional[float]`
- Returns speed ratio (e.g., 11.5x)

### SystemDiagnostics

System health checks and diagnostics.

```python
from scribe.utils.diagnostics import SystemDiagnostics

diagnostics = SystemDiagnostics()

# Run all checks
results = diagnostics.run_all_checks()

# Print results
diagnostics.print_results(results)

# Get recommendations
recommendations = diagnostics.get_recommendations(results)
```

**Methods:**

`run_all_checks() -> List[DiagnosticResult]`
- Runs 15 comprehensive checks
- Returns list of results

`print_results(results)`
- Prints formatted results to console

`get_recommendations(results) -> List[str]`
- Returns prioritized action items

## Exception Classes

### ScribeError (Base)

```python
from scribe.exceptions import ScribeError

try:
    # Operation
    pass
except ScribeError as e:
    print(f"Error: {e}")
    print(f"Context: {e.context}")
```

### Specific Exceptions

```python
from scribe.exceptions import (
    ValidationError,      # Configuration/validation
    ProcessError,         # Subprocess execution
    TranscriptionError,   # Transcription failure
    FileOperationError,   # File I/O
    ConversionError,      # Audio conversion
    AudioFormatError,     # Invalid audio format
    GPUError,             # GPU-related
    APIError              # External API
)
```

All exceptions include:
- Descriptive message
- Context dictionary
- Original exception (if applicable)

## Configuration

### ScribeConfig

System-wide configuration with environment variable loading.

```python
from scribe.models.config import ScribeConfig

config = ScribeConfig()

# Access settings
print(config.output_folder)
print(config.default_model)
print(config.default_language)

# Validate configuration
config.validate()
```

### GPUConfig

GPU-specific configuration with auto-detection.

```python
from scribe.models.gpu import GPUConfig

# Auto-detect
gpu_config = GPUConfig.detect()

print(f"GPU: {gpu_config.gpu_name}")
print(f"VRAM: {gpu_config.gpu_memory_gb}GB")
print(f"Beam size: {gpu_config.beam_size}")
print(f"FP16: {gpu_config.use_fp16}")
```

## Helper Functions

### Audio Utilities

```python
from scribe.utils.audio import (
    get_audio_duration,
    detect_silence_periods,
    validate_audio_file,
    format_timestamp,
    get_audio_info
)

# Get duration
duration = get_audio_duration(Path("audio.wav"))

# Detect silence
silence = detect_silence_periods(
    audio_path=Path("audio.wav"),
    silence_threshold=-45.0,
    min_silence_duration=60.0
)

# Validate file
validate_audio_file(Path("audio.wav"))

# Format timestamp
timestamp = format_timestamp(3661.5)  # "01:01:01"

# Get comprehensive info
info = get_audio_info(Path("audio.wav"))
```

### File Utilities

```python
from scribe.utils.files import (
    safe_filename,
    extract_date_from_filename,
    format_date,
    verify_file_content
)

# Sanitize filename
safe_name = safe_filename("Meeting: 2024-01-15")

# Extract date
date_str = extract_date_from_filename("meeting_2024-01-15.mp4")

# Format date
formatted = format_date("2024-01-15")

# Verify file
verify_file_content(Path("file.txt"), min_size=100)
```

## Type Hints

Common type aliases used throughout the codebase:

```python
from pathlib import Path
from typing import Optional, List, Dict, Callable, Union

# Path types
FilePath = Union[str, Path]

# Provider types
ProviderName = Literal["openai", "xai", "anthropic", "gemini"]

# Method types
TranscriptionMethod = Literal["auto", "local", "openai"]

# Callback types
ProgressCallback = Callable[[float], None]
```

## Constants

```python
# Model names
WHISPER_MODELS = ["large-v3", "large-v2", "medium", "small", "base"]

# Language codes (ISO 639-1)
SUPPORTED_LANGUAGES = ["en", "es", "fr", "de", "zh", "ja", ...]

# Provider names
PROVIDERS = ["openai", "xai", "anthropic", "gemini"]

# Image sizes
IMAGE_SIZES = ["1024x1024", "1024x1536", "1536x1024", "auto"]
```

## Examples

See `examples/` directory for complete working examples:
- `basic_transcription.py` - Simple transcription
- `batch_processing.py` - Batch transcription
- `custom_vocabulary.py` - Using custom vocabulary
- `provider_switching.py` - Switching between providers
- `programmatic_usage.py` - Full programmatic control
