#!/usr/bin/env python3
"""
Test runner for Scribe transcription system.
Runs all available tests and provides a comprehensive report.
"""

import os
import sys
import time
import argparse
import subprocess
from pathlib import Path
from colorama import Fore, Style, init

init(autoreset=True)

def print_banner():
    """Print the test runner banner."""
    print(f"{Fore.GREEN}{Style.BRIGHT}╔════════════════════════════════════════════════════════════╗")
    print(f"{Fore.GREEN}{Style.BRIGHT}║              SCRIBE SYSTEM TEST RUNNER                     ║")
    print(f"{Fore.GREEN}{Style.BRIGHT}║          Comprehensive Testing Framework                   ║")
    print(f"{Fore.GREEN}{Style.BRIGHT}╚════════════════════════════════════════════════════════════╝")
    print()

def run_test_module(module_path: Path, test_name: str) -> tuple[bool, str, float]:
    """
    Run a single test module and return results.
    
    Returns:
        tuple: (success, output, duration)
    """
    start_time = time.time()
    
    try:
        result = subprocess.run(
            [sys.executable, str(module_path)],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout per test
            cwd=module_path.parent.parent  # Run from project root
        )
        
        duration = time.time() - start_time
        success = result.returncode == 0
        output = result.stdout + result.stderr
        
        return success, output, duration
        
    except subprocess.TimeoutExpired:
        duration = time.time() - start_time
        return False, f"Test timed out after {duration:.1f} seconds", duration
        
    except Exception as e:
        duration = time.time() - start_time
        return False, f"Test execution failed: {str(e)}", duration

def print_test_result(test_name: str, success: bool, duration: float, details: str = ""):
    """Print formatted test result."""
    status = "PASS" if success else "FAIL"
    status_color = Fore.GREEN if success else Fore.RED
    
    print(f"{Fore.WHITE}{test_name:<25} {status_color}[{status}]{Fore.RESET} {Fore.CYAN}({duration:.2f}s)")
    
    if details and not success:
        # Show last few lines of error output
        lines = details.strip().split('\n')
        error_lines = [line for line in lines[-10:] if line.strip()]  # Last 10 non-empty lines
        for line in error_lines[:5]:  # Show up to 5 lines
            print(f"{Fore.YELLOW}  {line}")

def discover_tests(tests_dir: Path) -> list[tuple[Path, str]]:
    """Discover all test modules in the tests directory."""
    test_modules = []
    
    for test_file in tests_dir.glob("test_*.py"):
        test_name = test_file.stem.replace("test_", "").replace("_", " ").title()
        test_modules.append((test_file, test_name))
    
    return sorted(test_modules, key=lambda x: x[1])

def run_all_tests(tests_dir: Path, verbose: bool = False) -> dict:
    """Run all discovered tests."""
    test_modules = discover_tests(tests_dir)
    
    if not test_modules:
        print(f"{Fore.RED}No test modules found in {tests_dir}")
        return {}
    
    print(f"{Fore.CYAN}Discovered {len(test_modules)} test modules:")
    for _, name in test_modules:
        print(f"{Fore.WHITE}  • {name}")
    
    print(f"\n{Fore.BLUE}{'='*60}")
    print(f"{Fore.BLUE}RUNNING TESTS")
    print(f"{Fore.BLUE}{'='*60}")
    
    results = {}
    total_duration = 0
    
    for test_path, test_name in test_modules:
        print(f"\n{Fore.YELLOW}Running {test_name}...")
        
        success, output, duration = run_test_module(test_path, test_name)
        total_duration += duration
        
        results[test_name] = {
            'success': success,
            'duration': duration,
            'output': output
        }
        
        print_test_result(test_name, success, duration, output if not success else "")
        
        if verbose and success:
            # Show summary of successful test output
            lines = output.split('\n')
            summary_lines = [line for line in lines if 'PASS' in line or 'Results:' in line]
            for line in summary_lines[-3:]:  # Last 3 relevant lines
                if line.strip():
                    print(f"{Fore.GREEN}  {line.strip()}")
    
    return results

def print_summary(results: dict, total_duration: float):
    """Print comprehensive test summary."""
    print(f"\n{Fore.BLUE}{'='*60}")
    print(f"{Fore.BLUE}TEST SUMMARY")
    print(f"{Fore.BLUE}{'='*60}")
    
    passed_tests = sum(1 for r in results.values() if r['success'])
    total_tests = len(results)
    
    print(f"\n{Fore.WHITE}Test Results:")
    for test_name, result in results.items():
        status = "PASS" if result['success'] else "FAIL"
        status_color = Fore.GREEN if result['success'] else Fore.RED
        duration = result['duration']
        
        print(f"{Fore.WHITE}  {test_name:<25} {status_color}[{status}]{Fore.RESET} {Fore.CYAN}({duration:.2f}s)")
    
    print(f"\n{Fore.CYAN}Overall Results:")
    print(f"{Fore.WHITE}  Tests passed: {Fore.GREEN}{passed_tests}")
    print(f"{Fore.WHITE}  Tests failed: {Fore.RED}{total_tests - passed_tests}")
    print(f"{Fore.WHITE}  Total tests:  {Fore.CYAN}{total_tests}")
    print(f"{Fore.WHITE}  Total time:   {Fore.CYAN}{total_duration:.2f} seconds")
    
    success_rate = (passed_tests / total_tests * 100) if total_tests > 0 else 0
    
    if success_rate == 100:
        print(f"\n{Fore.GREEN}{Style.BRIGHT}ALL TESTS PASSED! System is ready.")
    elif success_rate >= 80:
        print(f"\n{Fore.YELLOW}{Style.BRIGHT}Most tests passed ({success_rate:.0f}%). Check failed tests.")
    else:
        print(f"\n{Fore.RED}{Style.BRIGHT}Multiple test failures ({success_rate:.0f}%). System needs attention.")
    
    return success_rate == 100

def main():
    """Main test runner function."""
    parser = argparse.ArgumentParser(description="Run Scribe system tests")
    parser.add_argument("--verbose", "-v", action="store_true", 
                       help="Show detailed output for passed tests")
    parser.add_argument("--test", "-t", type=str, 
                       help="Run specific test (e.g., 'startup', 'audio')")
    parser.add_argument("--list", "-l", action="store_true",
                       help="List available tests and exit")
    
    args = parser.parse_args()
    
    # Find tests directory
    script_dir = Path(__file__).parent
    tests_dir = script_dir
    project_root = script_dir.parent
    
    if args.list:
        print_banner()
        print(f"{Fore.CYAN}Available tests:")
        test_modules = discover_tests(tests_dir)
        for _, test_name in test_modules:
            print(f"{Fore.WHITE}  • {test_name}")
        return 0
    
    print_banner()
    
    # Add project root to Python path
    sys.path.insert(0, str(project_root))
    
    if args.test:
        # Run specific test
        test_file = tests_dir / f"test_{args.test.lower()}.py"
        if not test_file.exists():
            print(f"{Fore.RED}Test not found: {test_file}")
            return 1
        
        print(f"{Fore.CYAN}Running specific test: {args.test}")
        success, output, duration = run_test_module(test_file, args.test.title())
        
        print_test_result(args.test.title(), success, duration)
        
        if args.verbose or not success:
            print(f"\n{Fore.CYAN}Test Output:")
            print(output)
        
        return 0 if success else 1
    
    else:
        # Run all tests
        start_time = time.time()
        results = run_all_tests(tests_dir, args.verbose)
        total_duration = time.time() - start_time
        
        if results:
            all_passed = print_summary(results, total_duration)
            return 0 if all_passed else 1
        else:
            print(f"{Fore.RED}No tests were executed.")
            return 1

if __name__ == "__main__":
    sys.exit(main())