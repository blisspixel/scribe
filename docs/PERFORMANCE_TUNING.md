# Performance Tuning Guide

**Last Updated:** 2025-11-18

## Overview

This guide covers performance optimization for Scribe, including GPU tuning, audio processing optimization, and system configuration for maximum throughput.

## GPU Performance

### Hardware Benchmarks

Real-world performance on different GPUs with Whisper large-v3:

| GPU | VRAM | Beam Size | Speed | Notes |
|-----|------|-----------|-------|-------|
| RTX 4090 | 24GB | 10 | 11-12x | Optimal configuration |
| RTX 4080 | 16GB | 8 | 8-9x | Excellent performance |
| RTX 4070 Ti | 12GB | 6 | 6-7x | Good performance |
| RTX 3090 | 24GB | 5 | 5-6x | Older architecture |
| RTX 3080 | 10GB | 4 | 4-5x | Memory limited |

**Speed Ratio:** How many times faster than real-time (e.g., 11x = 60 min audio in 5.5 min)

### GPU Configuration

Scribe automatically detects and configures optimal settings per GPU. Manual tuning available for advanced users.

**Automatic Configuration:**
```python
from scribe.models.gpu import GPUConfig

# Auto-detect optimal settings
gpu_config = GPUConfig.detect()
print(f"GPU: {gpu_config.gpu_name}")
print(f"Beam size: {gpu_config.beam_size}")
print(f"FP16: {gpu_config.use_fp16}")
```

**Manual Override (Advanced):**
```python
gpu_config = GPUConfig(
    has_gpu=True,
    gpu_name="RTX 4090",
    gpu_memory_gb=24.0,
    beam_size=12,          # Higher = better quality, slower
    use_fp16=True,         # Half precision for speed
    enable_tensor_cores=True
)
```

### Beam Size Tuning

Beam size affects quality vs speed tradeoff:

| Beam Size | Quality | Speed | Memory | Use Case |
|-----------|---------|-------|--------|----------|
| 1 | Lowest | Fastest | Minimal | Quick drafts |
| 5 | Good | Fast | Low | General use |
| 8 | Better | Moderate | Medium | Balanced |
| 10 | Best | Slower | High | Maximum quality |
| 12+ | Marginal gain | Much slower | Very high | Diminishing returns |

**Recommendation:** Use default (10 for RTX 4090, 8 for RTX 4080, 5 for others)

### Memory Optimization

**Prevent OOM Errors:**

1. **Close other GPU applications:**
```bash
# Check GPU usage
nvidia-smi

# Kill other processes if needed
kill <PID>
```

2. **Use smaller model if needed:**
```bash
# large-v2 uses less memory
scribe transcribe audio.mp4 --model large-v2

# medium uses even less
scribe transcribe audio.mp4 --model medium
```

3. **Monitor memory during transcription:**
```bash
watch -n 1 nvidia-smi
```

4. **Clear GPU cache between runs:**
```python
from scribe.utils.gpu import clear_gpu_cache
clear_gpu_cache()
```

### GPU Utilization

**Maximize GPU Usage:**

1. **Ensure GPU is actually being used:**
```bash
# Should show high GPU utilization during transcription
nvidia-smi dmon -s u
```

2. **Check for thermal throttling:**
```bash
# Monitor temperature
nvidia-smi dmon -s t

# Should stay below 85°C
```

3. **Verify CUDA is working:**
```python
import torch
print(torch.cuda.is_available())  # Should be True
print(torch.cuda.get_device_name(0))
```

## Audio Processing Optimization

### Preprocessing Performance

Audio preprocessing (conversion + normalization) takes approximately:
- 10% of audio duration for standard quality
- Example: 60 min audio = 6 min preprocessing

**Why preprocessing matters:**
- Ensures optimal audio quality for transcription
- Normalizes volume levels
- Converts to optimal format (16kHz mono WAV)
- Results in better transcription accuracy

**Preprocessing stages:**
1. Format conversion (FFmpeg)
2. Audio normalization (dynaudnorm)
3. Resampling to 16kHz
4. Conversion to mono

### FFmpeg Optimization

**Hardware Acceleration:**

Enable hardware-accelerated encoding/decoding:

```bash
# Check available encoders
ffmpeg -encoders | grep nvenc

# Use NVIDIA hardware acceleration
ffmpeg -hwaccel cuda -i input.mp4 -c:a pcm_s16le output.wav
```

**Parallel Processing:**

For batch processing, process multiple files in parallel:

```python
from concurrent.futures import ThreadPoolExecutor

def process_file(file_path):
    return transcriber.transcribe(file_path)

with ThreadPoolExecutor(max_workers=2) as executor:
    results = executor.map(process_file, file_list)
```

**Note:** Limit workers to avoid GPU memory issues (max 2 concurrent for most GPUs)

### Audio Format Recommendations

**Best Performance:**
- Input: 16kHz mono WAV (no conversion needed)
- Preprocessing: Skipped or minimal
- Result: Fastest transcription

**Good Performance:**
- Input: MP3, M4A, FLAC (common formats)
- Preprocessing: Standard conversion
- Result: Normal speed

**Slower Performance:**
- Input: High-resolution audio (96kHz, 192kHz)
- Preprocessing: Heavy resampling
- Result: Longer preprocessing time

**Recommendation:** Record at 16kHz mono if possible to skip preprocessing

## API Mode Optimization

### Cost Optimization

**Use XAI/Grok for intelligence features:**
```bash
# 47x cheaper than GPT-5
export SCRIBE_JOKE_PROVIDER=xai
export SCRIBE_MEME_PROVIDER=xai
export SCRIBE_NOTES_PROVIDER=xai
```

**Cost comparison (per 1M tokens):**
- Grok 4.3: $1.25 input / $2.50 output
- GPT-5: $3.00 input / $15.00 output
- Verify current provider pricing before high-volume runs
- Scribe records exact xAI request cost when the API returns `cost_in_usd_ticks`; otherwise it uses local estimates for known xAI defaults

**Image generation:**
- Grok Imagine Image: priced per image by xAI
- GPT-Image-1: $0.40 per image
- Verify current provider pricing before high-volume runs

### Network Optimization

**Reduce API calls:**

1. **Batch processing:**
```bash
# Process multiple files in one session
scribe batch *.mp4
```

2. **Disable optional features:**
```bash
# Skip humor if not needed
scribe transcribe audio.mp4 --no-joke --no-meme
```

3. **Use local GPU when available:**
```bash
# Force local processing
scribe transcribe audio.mp4 --method local
```

### Rate Limiting

Scribe automatically handles rate limits with exponential backoff. For high-volume processing:

1. **Use multiple API keys (if allowed by provider)**
2. **Spread processing across time**
3. **Consider local GPU for transcription**

## System Configuration

### CPU Optimization

**FFmpeg threads:**
```bash
# Set FFmpeg thread count (default: auto)
export SCRIBE_FFMPEG_THREADS=8
```

**Python threads:**
```python
# For batch processing
import os
os.environ['OMP_NUM_THREADS'] = '8'
```

### Memory Management

**Monitor memory usage:**
```bash
# Linux/macOS
top
htop

# Windows
taskmgr
```

**Optimize Python memory:**
```python
import gc

# Force garbage collection between files
gc.collect()
```

### Disk I/O

**Use SSD for output:**
- Faster file writes
- Better for large files
- Reduces bottlenecks

**Temporary files:**
```bash
# Use fast storage for temp files
export TMPDIR=/path/to/fast/storage
```

**Clean up old files:**
```bash
# Remove old outputs periodically
find output/ -mtime +30 -delete
```

## Batch Processing Optimization

### Sequential vs Parallel

**Sequential (default):**
- One file at a time
- Predictable memory usage
- Safer for GPU

**Parallel (advanced):**
```python
from concurrent.futures import ProcessPoolExecutor

# Process 2 files at once (if GPU memory allows)
with ProcessPoolExecutor(max_workers=2) as executor:
    results = executor.map(transcribe_file, files)
```

**Recommendation:** Use sequential for GPU, parallel for API mode

### Large File Handling

**For files > 1 hour:**

1. **Use API mode with chunking:**
```bash
scribe transcribe long_file.mp4 --method openai
```

2. **Or split file first:**
```bash
# Split into 30-minute chunks
ffmpeg -i long_file.mp4 -f segment -segment_time 1800 -c copy chunk_%03d.mp4
```

3. **Process chunks separately:**
```bash
scribe batch chunk_*.mp4
```

## Progress Tracking Optimization

### Adaptive Progress

Scribe learns your machine's performance over time:

**First run:**
- Uses default estimates
- May be inaccurate

**Subsequent runs:**
- Uses actual performance data
- Improves accuracy
- Stored in `~/.scribe/performance_{machine_id}.json`

**Reset performance data:**
```bash
rm ~/.scribe/performance_*.json
```

### Progress Callbacks

For programmatic usage, use callbacks for real-time updates:

```python
def progress_callback(progress: float):
    print(f"Progress: {progress * 100:.1f}%")

transcriber.transcribe(
    audio_path,
    progress_callback=progress_callback
)
```

## Benchmarking

### Measure Your Performance

**Transcription speed:**
```bash
time scribe transcribe test_60min.mp4
```

**Calculate speed ratio:**
```
Speed Ratio = Audio Duration / Processing Time
Example: 60 min / 5.5 min = 10.9x
```

**Compare models:**
```bash
# Test large-v3
time scribe transcribe audio.mp4 --model large-v3

# Test large-v2
time scribe transcribe audio.mp4 --model large-v2

# Test medium
time scribe transcribe audio.mp4 --model medium
```

### Performance Profiling

**Profile Python code:**
```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Run transcription
transcriber.transcribe(audio_path)

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)
```

**Profile GPU usage:**
```bash
# Monitor during transcription
nvidia-smi dmon -s pucvmet -c 100
```

## Optimization Checklist

### For Maximum Speed

- [ ] Use RTX 4090 or 4080
- [ ] Use large-v3 model (best quality/speed balance)
- [ ] Close other GPU applications
- [ ] Use 16kHz mono WAV input (skip preprocessing)
- [ ] Ensure good cooling (prevent thermal throttling)
- [ ] Use SSD for output
- [ ] Enable FP16 precision
- [ ] Use optimal beam size for GPU

### For Maximum Quality

- [ ] Use large-v3 model
- [ ] Use beam size 10+
- [ ] Enable audio normalization (default)
- [ ] Use custom vocabulary for technical terms
- [ ] Ensure clean audio input
- [ ] Use speaker diarization (API mode)

### For Minimum Cost

- [ ] Use local GPU for transcription
- [ ] Use XAI/Grok for intelligence features
- [ ] Disable optional features if not needed
- [ ] Batch process to reduce overhead
- [ ] Use custom vocabulary to improve accuracy (fewer retries)

## Troubleshooting Performance Issues

### Slow Transcription

**Check GPU utilization:**
```bash
nvidia-smi dmon -s u
# Should show high GPU usage
```

**Check thermal throttling:**
```bash
nvidia-smi dmon -s t
# Temperature should be < 85°C
```

**Check model being used:**
```bash
scribe info
# Verify model is large-v3
```

### High Memory Usage

**Monitor memory:**
```bash
nvidia-smi dmon -s m
```

**Reduce memory usage:**
- Use smaller model
- Lower beam size
- Close other applications
- Process smaller files

### Slow Preprocessing

**Check FFmpeg:**
```bash
ffmpeg -version
# Ensure recent version
```

**Use hardware acceleration:**
```bash
ffmpeg -hwaccel cuda -i input.mp4 output.wav
```

## Advanced Tuning

### Custom GPU Settings

For expert users, modify GPU configuration:

```python
from scribe.models.gpu import GPUConfig

# Custom configuration
config = GPUConfig(
    has_gpu=True,
    gpu_name="Custom",
    gpu_memory_gb=24.0,
    beam_size=15,           # Higher than default
    use_fp16=True,
    enable_tensor_cores=True,
    batch_size=16           # Experimental
)
```

### Model Caching

Keep model loaded between transcriptions:

```python
from scribe.core.local_whisper import LocalWhisperTranscriber

# Initialize once
transcriber = LocalWhisperTranscriber(model_size="large-v3")

# Transcribe multiple files (model stays loaded)
for file in files:
    transcriber.transcribe(file)
```

### Custom Audio Pipeline

For specialized audio processing:

```python
from scribe.core.converter import Converter

converter = Converter()

# Custom conversion settings
wav_path = converter.convert_to_wav(
    input_file,
    sample_rate=16000,
    channels=1,
    show_progress=False  # Disable for speed
)
```

## Performance Targets

### Expected Performance

**RTX 4090 + large-v3:**
- Speed: 11-12x real-time
- 60 min audio: ~5.5 min total (including preprocessing)
- Quality: Maximum

**RTX 4080 + large-v3:**
- Speed: 8-9x real-time
- 60 min audio: ~7.5 min total
- Quality: Maximum

**API Mode:**
- Speed: Varies by network and API load
- 60 min audio: ~10-15 min typical
- Quality: Excellent with diarization

## Summary

Key performance factors:
1. **GPU hardware** - Biggest impact on speed
2. **Model selection** - Balance quality vs speed
3. **Audio preprocessing** - ~10% overhead for quality
4. **System configuration** - Proper cooling, SSD, etc.
5. **Batch processing** - Amortize overhead across files

For maximum performance: RTX 4090 + large-v3 + 16kHz mono WAV input = 11-12x real-time
