#!/usr/bin/env python3
"""
Audio processing and device tests for Scribe transcription system.
"""

import contextlib
import os
import sys
import tempfile
import time
import wave
from pathlib import Path

from colorama import Fore, Style, init

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

init(autoreset=True)


def print_header(title: str):
    """Print a formatted test section header."""
    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"{Fore.CYAN}{title:^60}")
    print(f"{Fore.CYAN}{'='*60}")


def print_test(name: str, status: str, details: str = ""):
    """Print formatted test result."""
    status_color = Fore.GREEN if status == "PASS" else Fore.RED if status == "FAIL" else Fore.YELLOW
    print(f"{Fore.WHITE}{name:<40} {status_color}[{status}]{Fore.RESET}")
    if details:
        print(f"{Fore.CYAN}   Details: {details}")


def create_test_wav_file(duration_seconds: float = 1.0, sample_rate: int = 44100) -> str:
    """Create a test WAV file for testing."""
    import numpy as np

    # Generate a simple sine wave
    t = np.linspace(0, duration_seconds, int(sample_rate * duration_seconds))
    frequency = 440  # A4 note
    amplitude = 0.3
    audio_data = (amplitude * np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)

    # Create temporary WAV file
    temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_path = temp_file.name
    temp_file.close()

    # Write WAV file
    with wave.open(temp_path, "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(audio_data.tobytes())

    return temp_path


def test_audio_file_handling():
    """Test audio file reading and validation."""
    print_header("AUDIO FILE HANDLING TESTS")

    test_files = []
    all_passed = True

    try:
        # Create test files with different characteristics
        test_configs = [
            ("Short audio (1s)", 1.0, 44100),
            ("Standard audio (5s)", 5.0, 48000),
            ("Long audio (30s)", 30.0, 44100),
        ]

        for name, duration, sample_rate in test_configs:
            try:
                test_file = create_test_wav_file(duration, sample_rate)
                test_files.append(test_file)

                # Test file properties
                with wave.open(test_file, "rb") as wav:
                    channels = wav.getnchannels()
                    sample_width = wav.getsampwidth()
                    framerate = wav.getframerate()
                    frames = wav.getnframes()
                    duration_actual = frames / framerate

                details = (
                    f"{channels}ch, {sample_width*8}bit, {framerate}Hz, {duration_actual:.1f}s"
                )
                print_test(f"Create {name}", "PASS", details)

            except Exception as e:
                print_test(f"Create {name}", "FAIL", str(e))
                all_passed = False

        return all_passed

    finally:
        # Cleanup test files
        for test_file in test_files:
            with contextlib.suppress(BaseException):
                os.unlink(test_file)


def test_audio_device_detection():
    """Test audio device detection and configuration."""
    print_header("AUDIO DEVICE TESTS")

    try:
        # Test Windows audio device detection
        if os.name == "nt":
            try:
                import subprocess

                result = subprocess.run(
                    [
                        "powershell",
                        "-Command",
                        "Get-AudioDevice -PlaybackCommunication | Select-Object Name, Default",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result.returncode == 0 and result.stdout:
                    lines = result.stdout.strip().split("\n")
                    devices_found = len(
                        [line for line in lines if line.strip() and "Name" not in line]
                    )
                    print_test(
                        "Audio device detection", "PASS", f"{devices_found} playback devices found"
                    )

                    # Check for expected device
                    expected_device = os.getenv("EXPECTED_AUDIO_OUTPUT", "")
                    if expected_device:
                        if expected_device in result.stdout:
                            print_test("Expected audio device", "PASS", f"Found: {expected_device}")
                        else:
                            print_test(
                                "Expected audio device", "WARN", f"Not found: {expected_device}"
                            )
                else:
                    print_test("Audio device detection", "FAIL", "PowerShell command failed")

            except Exception as e:
                print_test("Audio device detection", "FAIL", str(e))

        else:
            print_test("Audio device detection", "SKIP", "Non-Windows platform")

        return True

    except Exception as e:
        print_test("Audio device detection", "FAIL", str(e))
        return False


def test_path_normalization():
    """Test path normalization with various input formats."""
    print_header("PATH NORMALIZATION TESTS")

    # Create a test file
    temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_path = temp_file.name
    temp_file.close()

    try:
        # Test various path formats
        test_cases = [
            ("Normal path", temp_path),
            ("Double quoted", f'"{temp_path}"'),
            ("Single quoted", f"'{temp_path}'"),
            ("Spaces around quotes", f' "{temp_path}" '),
            ("Mixed quotes", f"'{temp_path}\""),  # Edge case
            ("Forward slashes", temp_path.replace("\\", "/")),
            ("Extra spaces", f"  {temp_path}  "),
        ]

        all_passed = True

        for test_name, input_path in test_cases:
            try:
                # Apply the same normalization logic as voicetotext.py
                normalized = input_path.strip().strip('"').strip("'").strip()
                normalized = os.path.normpath(os.path.abspath(normalized))

                if os.path.exists(normalized) and os.path.samefile(normalized, temp_path):
                    print_test(f"Normalize {test_name}", "PASS")
                else:
                    print_test(f"Normalize {test_name}", "FAIL", f"Expected: {temp_path}")
                    all_passed = False

            except Exception as e:
                print_test(f"Normalize {test_name}", "FAIL", str(e))
                all_passed = False

        return all_passed

    finally:
        with contextlib.suppress(BaseException):
            os.unlink(temp_path)


def test_audio_format_validation():
    """Test audio format validation and error handling."""
    print_header("AUDIO FORMAT VALIDATION TESTS")

    try:
        # Test valid WAV file
        valid_wav = create_test_wav_file(2.0)

        try:
            with wave.open(valid_wav, "rb"):
                print_test("Valid WAV file", "PASS", "Opened successfully")
        except Exception as e:
            print_test("Valid WAV file", "FAIL", str(e))
            return False
        finally:
            os.unlink(valid_wav)

        # Test invalid file (create empty file)
        invalid_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        invalid_path = invalid_file.name
        invalid_file.write(b"not a wav file")
        invalid_file.close()

        try:
            try:
                with wave.open(invalid_path, "rb"):
                    print_test("Invalid WAV handling", "FAIL", "Should have failed")
                    return False
            except wave.Error:
                print_test("Invalid WAV handling", "PASS", "Correctly rejected invalid file")
            except Exception as e:
                print_test("Invalid WAV handling", "PASS", f"Correctly failed: {type(e).__name__}")
        finally:
            os.unlink(invalid_path)

        # Test non-existent file
        non_existent = "this_file_does_not_exist.wav"
        try:
            with wave.open(non_existent, "rb"):
                print_test("Non-existent file handling", "FAIL", "Should have failed")
                return False
        except FileNotFoundError:
            print_test("Non-existent file handling", "PASS", "Correctly handled missing file")
        except Exception as e:
            print_test(
                "Non-existent file handling", "PASS", f"Correctly failed: {type(e).__name__}"
            )

        return True

    except Exception as e:
        print_test("Audio format validation", "FAIL", str(e))
        return False


def test_file_size_handling():
    """Test handling of various file sizes."""
    print_header("FILE SIZE HANDLING TESTS")

    try:
        # Test different file sizes
        size_tests = [
            ("Tiny file", 0.1),  # 100ms
            ("Small file", 1.0),  # 1 second
            ("Medium file", 10.0),  # 10 seconds
            ("Large file", 60.0),  # 1 minute
        ]

        all_passed = True

        for test_name, duration in size_tests:
            try:
                test_file = create_test_wav_file(duration)

                # Check file size
                file_size = os.path.getsize(test_file)
                size_mb = file_size / (1024 * 1024)

                # Validate with wave module
                with wave.open(test_file, "rb") as wav:
                    actual_duration = wav.getnframes() / wav.getframerate()

                if abs(actual_duration - duration) < 0.1:  # Within 100ms
                    print_test(test_name, "PASS", f"{size_mb:.2f} MB, {actual_duration:.1f}s")
                else:
                    print_test(
                        test_name,
                        "FAIL",
                        f"Duration mismatch: {actual_duration:.1f}s vs {duration:.1f}s",
                    )
                    all_passed = False

                os.unlink(test_file)

            except Exception as e:
                print_test(test_name, "FAIL", str(e))
                all_passed = False

        return all_passed

    except Exception as e:
        print_test("File size handling", "FAIL", str(e))
        return False


def main():
    """Run all audio tests."""
    print(f"{Fore.GREEN}{Style.BRIGHT}Scribe Audio System Tests")
    print(f"{Fore.WHITE}Testing audio processing and device capabilities...\n")

    start_time = time.time()

    # Run all test suites
    test_results = {
        "Audio File Handling": test_audio_file_handling(),
        "Audio Device Detection": test_audio_device_detection(),
        "Path Normalization": test_path_normalization(),
        "Format Validation": test_audio_format_validation(),
        "File Size Handling": test_file_size_handling(),
    }

    # Summary
    print_header("TEST SUMMARY")

    passed_tests = sum(1 for result in test_results.values() if result)
    total_tests = len(test_results)

    for test_name, result in test_results.items():
        status = "PASS" if result else "FAIL"
        print_test(test_name, status)

    elapsed = time.time() - start_time

    print(f"\n{Fore.CYAN}Results: {passed_tests}/{total_tests} test suites passed")
    print(f"{Fore.CYAN}Time: {elapsed:.2f} seconds")

    if passed_tests == total_tests:
        print(f"\n{Fore.GREEN}{Style.BRIGHT}Audio system tests passed!")
        return 0
    else:
        print(f"\n{Fore.RED}{Style.BRIGHT}Some audio tests failed.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
