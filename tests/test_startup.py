#!/usr/bin/env python3
"""
Improved startup and system health tests for Scribe transcription system.
"""

import contextlib
import os
import subprocess
import sys
import tempfile
import time
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

def test_imports():
    """Test all critical imports."""
    print_header("IMPORT TESTS")

    imports_to_test = [
        ("os", "os"),
        ("colorama", "colorama"),
        ("torch", "torch"),
        ("whisper", "whisper"),
        ("torchaudio", "torchaudio"),
        ("dotenv", "dotenv"),
        ("numpy", "numpy"),
        ("scipy", "scipy"),
    ]

    results = []
    for name, module in imports_to_test:
        try:
            __import__(module)
            print_test(f"Import {name}", "PASS")
            results.append(True)
        except ImportError as e:
            print_test(f"Import {name}", "FAIL", str(e))
            results.append(False)

    return all(results)

def test_path_handling():
    """Test path handling with various quote combinations."""
    print_header("PATH HANDLING TESTS")

    # Create a temporary test file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
        tmp_path = tmp_file.name
        tmp_file.write(b"dummy wav data for testing")

    try:
        # Test different path formats
        test_paths = [
            tmp_path,  # Normal path
            f'"{tmp_path}"',  # Double quotes
            f"'{tmp_path}'",  # Single quotes
            f' "{tmp_path}" ',  # Double quotes with spaces
            f" '{tmp_path}' ",  # Single quotes with spaces
        ]

        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from scribe.utils.validation import validate_file_path

        all_passed = True
        for i, test_path in enumerate(test_paths):
            try:
                # Test the path validation logic from scribe
                cleaned_path = validate_file_path(str(test_path), must_exist=False)
                cleaned_path = str(cleaned_path)

                if os.path.exists(cleaned_path):
                    print_test(f"Path format {i+1}: {test_path[:30]}...", "PASS")
                else:
                    print_test(f"Path format {i+1}: {test_path[:30]}...", "FAIL", "Cleaned path not found")
                    all_passed = False

            except Exception as e:
                print_test(f"Path format {i+1}: {test_path[:30]}...", "FAIL", str(e))
                all_passed = False

        return all_passed

    finally:
        # Clean up temp file
        with contextlib.suppress(BaseException):
            os.unlink(tmp_path)

def test_script_syntax():
    """Test that all main scripts have valid syntax."""
    print_header("SYNTAX TESTS")

    scripts_to_test = [
        "scribe.py",
        "record.py",
        "converter.py",
        "voicetotext.py",
        "openaitranscribe.py",
        "wavtomp3.py",
        "txt_to_docx.py"
    ]

    base_dir = Path(__file__).parent.parent
    all_passed = True

    for script in scripts_to_test:
        script_path = base_dir / script
        if script_path.exists():
            try:
                # Check syntax by compiling
                with open(script_path, encoding='utf-8') as f:
                    code = f.read()
                compile(code, script_path, 'exec')
                print_test(f"Syntax check {script}", "PASS")
            except SyntaxError as e:
                print_test(f"Syntax check {script}", "FAIL", f"Line {e.lineno}: {e.msg}")
                all_passed = False
            except Exception as e:
                print_test(f"Syntax check {script}", "FAIL", str(e))
                all_passed = False
        else:
            print_test(f"Syntax check {script}", "SKIP", "File not found")

    return all_passed

def test_gpu_detection():
    """Test GPU detection capability."""
    print_header("GPU DETECTION TESTS")

    try:
        import torch

        # Test CUDA availability
        cuda_available = torch.cuda.is_available()
        print_test("CUDA availability", "PASS" if cuda_available else "INFO",
                  f"CUDA available: {cuda_available}")

        if cuda_available:
            gpu_count = torch.cuda.device_count()
            current_device = torch.cuda.current_device()
            gpu_name = torch.cuda.get_device_name(current_device)

            print_test("GPU detection", "PASS", f"{gpu_count} GPU(s) found")
            print_test("Current GPU", "INFO", f"Device {current_device}: {gpu_name}")

            # Test memory info
            if hasattr(torch.cuda, 'get_device_properties'):
                props = torch.cuda.get_device_properties(current_device)
                memory_gb = props.total_memory / (1024**3)
                print_test("GPU memory", "INFO", f"{memory_gb:.1f} GB")

        return True

    except Exception as e:
        print_test("GPU detection", "FAIL", str(e))
        return False

def test_environment():
    """Test environment configuration."""
    print_header("ENVIRONMENT TESTS")

    # Check for .env file
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        print_test("Environment file", "PASS", ".env file found")
    else:
        print_test("Environment file", "WARN", "No .env file found (optional)")

    # Check environment variables
    env_vars = [
        "DEFAULT_OUTPUT_FOLDER",
        "EXPECTED_AUDIO_OUTPUT",
        "OPENAI_API_KEY"
    ]

    for var in env_vars:
        value = os.getenv(var)
        if value:
            print_test(f"Environment var {var}", "PASS", f"Set (length: {len(value)})")
        else:
            print_test(f"Environment var {var}", "INFO", "Not set")

    return True

def test_file_operations():
    """Test file operations and permissions."""
    print_header("FILE OPERATION TESTS")

    # Test creating output directory
    try:
        output_dir = Path(os.getenv("DEFAULT_OUTPUT_FOLDER",
                                   os.path.expanduser("~/Videos/OBS_Recordings")))
        output_dir.mkdir(parents=True, exist_ok=True)
        print_test("Output directory creation", "PASS", str(output_dir))

        # Test write permissions
        test_file = output_dir / "write_test.tmp"
        try:
            test_file.write_text("test")
            test_file.unlink()
            print_test("Write permissions", "PASS")
        except Exception as e:
            print_test("Write permissions", "FAIL", str(e))
            return False

    except Exception as e:
        print_test("Output directory creation", "FAIL", str(e))
        return False

    return True

def test_external_tools():
    """Test availability of external tools."""
    print_header("EXTERNAL TOOLS TESTS")

    tools_to_test = [
        ("ffmpeg", "ffmpeg -version"),
        ("python", "python --version"),
    ]

    all_found = True
    for tool_name, test_cmd in tools_to_test:
        try:
            result = subprocess.run(test_cmd.split(),
                                  capture_output=True,
                                  text=True,
                                  timeout=10)
            if result.returncode == 0:
                version = result.stdout.split('\n')[0] if result.stdout else "Unknown version"
                print_test(f"Tool {tool_name}", "PASS", version)
            else:
                print_test(f"Tool {tool_name}", "FAIL", "Command failed")
                all_found = False
        except FileNotFoundError:
            print_test(f"Tool {tool_name}", "FAIL", "Not found in PATH")
            all_found = False
        except Exception as e:
            print_test(f"Tool {tool_name}", "FAIL", str(e))
            all_found = False

    return all_found

def main():
    """Run all tests."""
    print(f"{Fore.GREEN}{Style.BRIGHT}Scribe System Health Check")
    print(f"{Fore.WHITE}Testing system components and configuration...\n")

    start_time = time.time()

    # Run all test suites
    test_results = {
        "Imports": test_imports(),
        "Path Handling": test_path_handling(),
        "Script Syntax": test_script_syntax(),
        "GPU Detection": test_gpu_detection(),
        "Environment": test_environment(),
        "File Operations": test_file_operations(),
        "External Tools": test_external_tools(),
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
        print(f"\n{Fore.GREEN}{Style.BRIGHT}All systems operational!")
        return 0
    else:
        print(f"\n{Fore.RED}{Style.BRIGHT}Some tests failed. Check configuration.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
