"""
Profile the pydub audio chunking pipeline to establish a baseline for the Rust native extension rewrite.

Usage:
    uv run scripts/profile_audio_chunking.py <path_to_audio_file>
"""

import sys
import time
import tracemalloc
from pathlib import Path

from pydub import AudioSegment
from pydub.silence import split_on_silence


def profile_chunking(audio_path: str):
    print(f"Profiling audio chunking for: {audio_path}")

    if not Path(audio_path).exists():
        print("File does not exist!")
        return

    # Start memory tracing
    tracemalloc.start()

    start_time = time.monotonic()

    print("Loading audio file into memory...")
    try:
        audio = AudioSegment.from_file(audio_path)
    except Exception as e:
        print(f"Failed to load audio: {e}")
        return

    load_time = time.monotonic() - start_time
    print(f"Load time: {load_time:.2f}s")

    current_mem, peak_mem = tracemalloc.get_traced_memory()
    print(
        f"Memory after loading: Current={current_mem / 1024 / 1024:.2f}MB, Peak={peak_mem / 1024 / 1024:.2f}MB"
    )

    print("Chunking audio using pydub.silence.split_on_silence...")
    chunk_start = time.monotonic()

    # These match the settings in scribe.core.openai_api
    chunks = split_on_silence(
        audio,
        min_silence_len=500,
        silence_thresh=audio.dBFS - 14,
        keep_silence=250,
    )

    chunk_time = time.monotonic() - chunk_start
    total_time = time.monotonic() - start_time

    current_mem, peak_mem = tracemalloc.get_traced_memory()

    print("\n--- RESULTS ---")
    print(f"Total Chunks Generated: {len(chunks)}")
    print(f"Chunking Time: {chunk_time:.2f}s")
    print(f"Total Time: {total_time:.2f}s")
    print(f"Peak Memory Usage: {peak_mem / 1024 / 1024:.2f} MB")
    print("-----------------\n")

    tracemalloc.stop()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Please provide an audio file path.")
        sys.exit(1)

    profile_chunking(sys.argv[1])
