import os
import time
import tracemalloc
from pathlib import Path

import psutil
from pydub import AudioSegment
from pydub.silence import split_on_silence


def generate_test_audio(path: Path, duration_min: int = 60) -> None:
    print(f"Generating {duration_min}-minute test audio...")
    # Generate 1 minute of audio (alternating noise and silence)
    # Then multiply by duration_min to get the full audio
    sound = AudioSegment.silent(duration=5000)  # 5 seconds of silence
    noise = AudioSegment.silent(
        duration=55000
    )  # 55 seconds of "noise" (we use silence here for speed, but pydub split_on_silence processes it the same if we set thresholds right)

    # Actually, we need real noise so it doesn't just split everywhere.
    # Let's generate a 1 minute segment of white noise using ffmpeg
    if not path.parent.exists():
        path.parent.mkdir(parents=True)

    os.system(f'ffmpeg -f lavfi -i "anoisesrc=d=60:c=white:r=16000" -y {path} > NUL 2>&1')

    audio = AudioSegment.from_file(str(path))
    full_audio = audio * duration_min

    # inject silence every 5 minutes
    for i in range(1, duration_min, 5):
        pos = i * 60 * 1000
        full_audio = full_audio[:pos] + AudioSegment.silent(duration=2000) + full_audio[pos:]

    full_audio.export(str(path), format="wav")
    print(f"Test audio saved to {path} ({os.path.getsize(path) / (1024 * 1024):.1f} MB)")


def benchmark_pydub():
    audio_path = Path(".agent/test_benchmark_audio.wav")
    if not audio_path.exists():
        generate_test_audio(audio_path, duration_min=10)  # 10 mins to start, 60 might OOM in our CI

    process = psutil.Process(os.getpid())

    print("\nStarting benchmark...")
    mem_before = process.memory_info().rss / 1024 / 1024

    tracemalloc.start()
    start_time = time.time()

    # Load audio
    print(f"[Mem: {process.memory_info().rss / 1024 / 1024:.1f} MB] Loading AudioSegment...")
    audio = AudioSegment.from_file(str(audio_path))

    print(f"[Mem: {process.memory_info().rss / 1024 / 1024:.1f} MB] Splitting on silence...")
    chunks = split_on_silence(audio, min_silence_len=500, silence_thresh=-40, keep_silence=200)

    end_time = time.time()
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    mem_after = process.memory_info().rss / 1024 / 1024

    print("\n--- Results ---")
    print(f"Audio Duration: {len(audio) / 1000 / 60:.1f} minutes")
    print(f"Chunks generated: {len(chunks)}")
    print(f"Time taken: {end_time - start_time:.2f} seconds")
    print(f"Peak tracemalloc memory: {peak / 1024 / 1024:.1f} MB")
    print(f"Process memory diff: {mem_after - mem_before:.1f} MB")
    print(f"Final process memory: {mem_after:.1f} MB")


if __name__ == "__main__":
    benchmark_pydub()
