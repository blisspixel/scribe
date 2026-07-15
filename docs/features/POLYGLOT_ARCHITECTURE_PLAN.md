# Scribe Polyglot Architecture Plan

## Overview
As Scribe matures into a robust, local-first intelligence application, our pure-Python foundation is bumping against the limitations of the Python interpreter in two specific areas:
1. **Always-on background daemon memory footprint** (`scribe tray`).
2. **CPU-bound, memory-heavy audio preprocessing** (`pydub.silence.split_on_silence`).

Following the "Harden first, measure second, extract third" philosophy, we will selectively adopt **Go** and **Rust** to optimize these exact boundaries while keeping the core intelligence and orchestration logic in Python.

This document outlines the extraction plan for these two components.

---

## Seam 1: Resident Tray Daemon
**Language Choice:** Go
**Component Name:** `scribe-tray` (standalone binary)

### The Problem
Currently, `scribe tray` uses `pystray` and runs in a full Python interpreter. This consumes ~100-200MB of RAM just to sit idly in the system tray. Furthermore, Python's OS-level global keyboard hooks (`keyboard` library) can be fragile, requiring our current watchdog threads to keep them alive.

### The Solution
The source prototype uses [fyne-io/systray](https://github.com/fyne-io/systray) and
`golang.design/x/hotkey`. It communicates with the Python service over a loopback
TCP socket. Memory and startup improvements must be benchmarked on release
artifacts before a numeric claim is published.

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
- **Speed:** Benchmark locally against representative media before making a release claim.
- **Memory:** Flat line (O(1) memory complexity during streaming chunking).

### Boundary Interface (FFI)
We will expose a clean, Pythonic API from Rust:
```python
# Before (pydub)
from pydub.silence import split_on_silence
chunks = split_on_silence(audio_segment, min_silence_len=500, silence_thresh=-40)

# After (optional scribe-audio-core Rust extension)
from scribe_audio_core import get_audio_dbfs, get_split_timestamps

level = get_audio_dbfs("meeting.wav")
endpoints = get_split_timestamps(
    "meeting.wav",
    min_silence_ms=500,
    silence_thresh_db=level - 30,
    max_duration_ms=600_000,
)
```

---

## Execution Plan

### Phase A: Profile & Baseline (PARTIAL)
1. [x] Write benchmarking scripts in `tests/benchmarks/` to measure peak memory and latency of `pydub.silence.split_on_silence` on a 60-minute audio file.
2. [ ] Record reproducible 24-hour resident-memory baselines for supported Windows, macOS, and Linux environments.

### Phase B: Rust Audio Core (SOURCE IMPLEMENTED, DISTRIBUTION PARTIAL)
1. [x] Initialize a Rust crate `crates/scribe-audio-core`.
2. [x] Configure `pyproject.toml` to build the extension via Maturin.
3. [x] Write the streaming chunking logic in Rust and expose the PyO3 bindings.
4. [x] Use the native analyzer opportunistically from `openai_api.py`, with a bounded portable fallback when it is absent or fails.
5. [ ] Build, publish, and clean-install a supported platform wheel matrix before presenting native acceleration as part of the root distribution.

### Phase C: Go Tray Daemon (SOURCE PROTOTYPE, DELIVERY PARTIAL)
1. [x] Create `cmd/scribe-tray/main.go`.
2. [x] Use the canonical platform icon, honor simple configured F6-F12 keys, reject collisions, and fail startup when either key cannot register.
3. [x] Implement the IPC boundary (a lightweight Python socket server inside `scribe.voice.service`).
4. [x] Require a process-scoped capability and authenticated READY signal, close IPC resources explicitly, report backend provenance, and recover visibly from daemon launch, readiness, and exit failures.
5. [ ] Reproducibly build and package platform-specific Go binaries with integrity checks.
6. [ ] Reach Python menu, desktop-notification, activation-mode, and user-facing error parity before any packaged daemon can be selected automatically.
