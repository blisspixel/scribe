"""
Manual test to measure actual timing for each phase.
Run this to get real performance data for your machine.

Usage: python tests/manual/test_actual_timing.py

NOTE: This is a manual test that requires a specific test file.
It will be skipped during normal pytest runs.
"""

import time
from pathlib import Path

from scribe.core.converter import Converter
from scribe.core.transcriber import Transcriber
from scribe.models.config import ScribeConfig
from scribe.utils.audio import get_audio_duration
from scribe.utils.docx_converter import txt_to_docx
from scribe.utils.joke_generator import generate_transcript_joke
from scribe.utils.meme_generator import generate_meeting_meme
from scribe.utils.notes_generator import NotesGenerator


def main():
    """Run the timing test"""
    # Test file
    test_file = Path("C:/Users/nicks/OneDrive/scribe/output/Rawlings_AI_Literacy_Internal_2025-11-13_14-31-14.mp4")

    if not test_file.exists():
        print(f"Test file not found: {test_file}")
        return

    print(f"Testing with: {test_file.name}")
    print("=" * 60)

    # Get audio duration
    audio_duration = get_audio_duration(test_file)
    duration_mins = audio_duration / 60 if audio_duration else 0
    print(f"Audio duration: {duration_mins:.1f} minutes ({audio_duration:.0f} seconds)")
    print()

    config = ScribeConfig()
    converter = Converter()
    transcriber = Transcriber(config)

    # Phase 1: Analysis + Conversion
    print("Phase 1: Preparing Audio")
    print("-" * 60)
    start = time.time()
    wav_file = converter.convert_to_wav(test_file, show_progress=True)
    preparing_time = time.time() - start
    print(f"✓ Completed in {preparing_time:.1f}s ({preparing_time/60:.2f} minutes)")
    print(f"  Speed: {audio_duration/preparing_time:.1f}x real-time")
    print()

    # Phase 2: Transcription
    print("Phase 2: Transcription")
    print("-" * 60)
    start = time.time()

    # Show progress during transcription
    import sys
    import threading

    transcription_done = threading.Event()

    def show_transcription_progress():
        """Show elapsed time during transcription"""
        while not transcription_done.is_set():
            elapsed = time.time() - start
            sys.stdout.write(f"\r⠹ Transcribing with Whisper... {elapsed:.0f}s elapsed")
            sys.stdout.flush()
            time.sleep(1.0)

    progress_thread = threading.Thread(target=show_transcription_progress, daemon=True)
    progress_thread.start()

    transcript_path = transcriber.transcribe(wav_file, method="local", session=None)

    transcription_done.set()
    progress_thread.join(timeout=2.0)

    transcription_time = time.time() - start
    print(f"\r✓ Completed in {transcription_time:.1f}s ({transcription_time/60:.2f} minutes)")
    print(f"  Speed: {audio_duration/transcription_time:.1f}x real-time")
    print()

    # Phase 3: Post-processing
    print("Phase 3: Post-processing")
    print("-" * 60)

    # DOCX
    start = time.time()
    txt_to_docx(transcript_path)
    docx_time = time.time() - start
    print(f"✓ DOCX: {docx_time:.1f}s")

    # Notes
    if config.openai_api_key and config.enable_notes:
        start = time.time()
        notes_gen = NotesGenerator(api_key=config.openai_api_key)
        notes_gen.generate_notes(transcript_path)
        notes_time = time.time() - start
        print(f"✓ Notes: {notes_time:.1f}s")
    else:
        notes_time = 0
        print("⊘ Notes: skipped (no API key)")

    # Joke
    if config.openai_api_key:
        start = time.time()
        generate_transcript_joke(transcript_path, config.openai_api_key)
        joke_time = time.time() - start
        print(f"✓ Joke: {joke_time:.1f}s")
    else:
        joke_time = 0
        print("⊘ Joke: skipped (no API key)")

    # Meme
    if config.openai_api_key:
        start = time.time()
        generate_meeting_meme(transcript_path, api_key=config.openai_api_key)
        meme_time = time.time() - start
        print(f"✓ Meme: {meme_time:.1f}s")
    else:
        meme_time = 0
        print("⊘ Meme: skipped (no API key)")

    post_time = docx_time + notes_time + joke_time + meme_time
    print(f"Total post-processing: {post_time:.1f}s ({post_time/60:.2f} minutes)")
    print()

    # Summary
    print("=" * 60)
    print("TIMING SUMMARY")
    print("=" * 60)
    total_time = preparing_time + transcription_time + post_time

    print(f"Audio duration: {duration_mins:.1f} min ({audio_duration:.0f}s)")
    print(f"Total processing: {total_time/60:.2f} min ({total_time:.0f}s)")
    print()
    print(f"Preparing:     {preparing_time:6.1f}s ({preparing_time/total_time*100:5.1f}%)")
    print(f"Transcribing:  {transcription_time:6.1f}s ({transcription_time/total_time*100:5.1f}%)")
    print(f"Post-process:  {post_time:6.1f}s ({post_time/total_time*100:5.1f}%)")
    print()
    print("Time multipliers (for unified_progress.py):")
    print(f"  preparing: {preparing_time/audio_duration:.4f}")
    print(f"  transcribing: {transcription_time/audio_duration:.4f}")
    print(f"  finishing: {post_time/audio_duration:.4f}")


if __name__ == "__main__":
    main()
