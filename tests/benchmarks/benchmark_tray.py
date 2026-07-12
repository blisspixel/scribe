import subprocess
import time

import psutil


def benchmark_tray():
    print("Starting Scribe Tray in the background...")

    # Launch scribe tray daemon process
    process = subprocess.Popen(
        ["uv", "run", "scribe", "tray"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    try:
        # Give it a moment to boot
        time.sleep(3)

        # Get psutil process
        ps_proc = psutil.Process(process.pid)

        # In a real environment, pystray spawns children or uses threads.
        # Let's sum up memory for the whole process tree
        children = ps_proc.children(recursive=True)
        all_procs = [ps_proc] + children

        total_rss = sum(p.memory_info().rss for p in all_procs)

        print("\n--- Scribe Tray Memory Baseline ---")
        print(f"Total Resident Memory (RSS): {total_rss / 1024 / 1024:.1f} MB")
        print(f"Number of processes in tree: {len(all_procs)}")

    finally:
        print("Terminating daemon...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


if __name__ == "__main__":
    benchmark_tray()
