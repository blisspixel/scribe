# Scribe Polyglot Architecture Plan (Phase 3 & 4)

## Overview
As Scribe matures into a robust, local-first intelligence application, our pure-Python foundation is bumping against the limitations of the Python interpreter in two specific areas:
1. **Always-on background daemon memory footprint** (`scribe tray`).
2. **CPU-bound, memory-heavy audio preprocessing** (`pydub.silence.split_on_silence`).

Following the "Harden first, measure second, extract third" philosophy, we will selectively adopt **Go** and **Rust** to optimize these exact boundaries while keeping the core intelligence and orchestration logic in Python.

This document outlines the extraction plan for these two components.

---

## Seam 1: Resident Tray Daemon
**Language Choice:** Go
**Component Name:** `scribe-tray-daemon` (Standalone binary)

### The Problem
Currently, `scribe tray` uses `pystray` and runs in a full Python interpreter. This consumes ~100-200MB of RAM just to sit idly in the system tray. Furthermore, Python's OS-level global keyboard hooks (`keyboard` library) can be fragile, requiring our current watchdog threads to keep them alive.

### The Solution
Extract the system tray icon and global hotkey listener into a lightweight Go binary using [fyne-io/systray](https://github.com/fyne-io/systray) and [hookz](https://github.com/robotn/gohook).
- **Memory Footprint:** Expected to drop to ~10-15MB.
- **Cold Start:** Near instant.
- **Communication:** The Go daemon will communicate with the Scribe Python core via a lightweight localhost gRPC or Unix Domain Socket (UDS) / TCP socket on Windows. When the user taps `F9`, Go catches the interrupt natively and fires a signal to the Python intelligence backend to begin transcription.

### Boundary Interface (IPC)
The Go daemon will own the OS boundary (tray, context menus, raw keystrokes).
The Python backend will own the domain logic (loading models, transcribing, TTS, config parsing).

---

## Seam 2: Audio Chunking & VAD (Voice Activity Detection)
**Language Choice:** Rust
**Component Name:** `scribe-audio-core` (Native Python Extension via PyO3)

### The Problem
To bypass OpenAI's 25MB limits, `scribe.core.openai_api.py` uses `pydub.silence.split_on_silence` (line 433). This requires loading the *entire* audio file into memory as a Pydub AudioSegment. For a 2-hour meeting, this spikes memory usage drastically and introduces significant CPU-bound latency due to Python's GIL.

### The Solution
Replace the `pydub` chunking pipeline with a native Rust extension built using [PyO3](https://pyo3.rs/) and [Maturin](https://github.com/PyO3/maturin).
- **Streaming Execution:** Rust can stream the audio bytes directly from disk using `symphonia` or `hound`, detecting silence thresholds in a single, zero-allocation pass.
- **Speed:** Expected 50x-100x speedup for audio chunking compared to Python.
- **Memory:** Flat line (O(1) memory complexity during streaming chunking).

### Boundary Interface (FFI)
We will expose a clean, Pythonic API from Rust:
```python
# Before (pydub)
from pydub.silence import split_on_silence
chunks = split_on_silence(audio_segment, min_silence_len=500, silence_thresh=-40)

# After (scribe-audio-core Rust extension)
from scribe_audio_core import split_audio_on_silence
# Rust handles reading the file and chunking it natively, returning a list of paths
chunk_paths = split_audio_on_silence(file_path="meeting.wav", max_duration_sec=600)
```

---

## Execution Plan

### Phase A: Profile & Baseline (COMPLETED)
1. [x] Write benchmarking scripts in `tests/benchmarks/` to measure peak memory and latency of `pydub.silence.split_on_silence` on a 60-minute audio file.
2. [x] Measure the resident memory footprint of `scribe tray` on Windows, macOS, and Linux over a 24-hour period.

### Phase B: Rust Audio Core (COMPLETED)
1. [x] Initialize a Rust crate `crates/scribe-audio-core`.
2. [x] Configure `pyproject.toml` to build the extension via Maturin.
3. [x] Write the streaming chunking logic in Rust and expose the PyO3 bindings.
4. [x] Replace the `pydub` call in `openai_api.py` and measure the delta against the baseline.

### Phase C: Go Tray Daemon (COMPLETED)
1. [x] Create `cmd/scribe-tray/main.go`.
2. [x] Implement the static sys-tray icon, menu states, and global hotkeys.
3. [x] Implement the IPC boundary (a lightweight Python socket server inside `scribe.voice.service`).
4. [x] Package the compiled Go binary into the Python wheel or build distribution pipeline (via importlib.resources).
