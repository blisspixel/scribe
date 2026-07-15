import os
import time
import tracemalloc
from pathlib import Path

import psutil

try:
    import scribe_audio_core
except ImportError:
    print("scribe_audio_core not installed. Run `maturin develop` in crates/scribe-audio-core.")
    exit(1)


def benchmark_rust():
    audio_path = Path(".agent/test_benchmark_audio.wav")
    if not audio_path.exists():
        print("Please run benchmark_pydub.py first to generate the test audio.")
        return

    process = psutil.Process(os.getpid())

    print("\nStarting Rust audio processing benchmark...")
    mem_before = process.memory_info().rss / 1024 / 1024

    tracemalloc.start()
    start_time = time.time()

    print(
        f"[Mem: {process.memory_info().rss / 1024 / 1024:.1f} MB] Finding split points in Rust..."
    )
    split_points = scribe_audio_core.get_split_timestamps(
        str(audio_path),
        min_silence_ms=500,
        silence_thresh_db=-40.0,
        max_duration_ms=600000,
    )

    print(f"[Mem: {process.memory_info().rss / 1024 / 1024:.1f} MB] Done finding split points.")

    # Python would then split it using ffmpeg
    chunks_count = len(split_points)

    end_time = time.time()
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    mem_after = process.memory_info().rss / 1024 / 1024

    print("\n--- Results ---")
    print(f"Split points found: {chunks_count}")
    print(f"Time taken: {end_time - start_time:.2f} seconds")
    print(f"Peak tracemalloc memory: {peak / 1024 / 1024:.1f} MB")
    print(f"Process memory diff: {mem_after - mem_before:.1f} MB")
    print(f"Final process memory: {mem_after:.1f} MB")


if __name__ == "__main__":
    benchmark_rust()
