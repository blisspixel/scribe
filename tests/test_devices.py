#!/usr/bin/env python3
"""
Improved audio device testing for Scribe transcription system.
Tests audio device detection, configuration, and compatibility.
"""

import os
import sys
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

def test_pycaw_import():
    """Test if pycaw is available for Windows audio control."""
    print_header("AUDIO LIBRARY TESTS")
    
    try:
        if os.name != 'nt':
            print_test("pycaw import", "SKIP", "Not Windows platform")
            return True
            
        from comtypes import CLSCTX_ALL, CoCreateInstance
        from pycaw.constants import EDataFlow, ERole  
        from pycaw.pycaw import IMMDeviceEnumerator
        
        print_test("pycaw import", "PASS", "Audio control library available")
        return True
        
    except ImportError as e:
        print_test("pycaw import", "FAIL", f"Install with: pip install pycaw")
        return False
    except Exception as e:
        print_test("pycaw import", "FAIL", str(e))
        return False

def get_audio_devices():
    """Get list of audio devices using different methods."""
    devices = []
    
    # Method 1: pycaw (Windows only)
    if os.name == 'nt':
        try:
            from comtypes import CLSCTX_ALL, CoCreateInstance
            from pycaw.constants import EDataFlow, ERole
            from pycaw.pycaw import IMMDeviceEnumerator
            
            device_enumerator = CoCreateInstance(
                IMMDeviceEnumerator._iid_,
                IMMDeviceEnumerator,
                CLSCTX_ALL
            )
            
            # Get default device
            default_device = device_enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender, ERole.eMultimedia)
            if default_device:
                devices.append({
                    'name': default_device.FriendlyName,
                    'default': True,
                    'method': 'pycaw'
                })
                
        except Exception as e:
            pass
    
    # Method 2: PowerShell (Windows only)
    if os.name == 'nt':
        try:
            import subprocess
            result = subprocess.run(
                ['powershell', '-Command', 
                 'Get-AudioDevice -PlaybackCommunication | Select-Object Name, Default'],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0 and result.stdout:
                lines = result.stdout.strip().split('\n')[2:]  # Skip header
                for line in lines:
                    if line.strip():
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            name = ' '.join(parts[:-1])
                            is_default = parts[-1].lower() == 'true'
                            devices.append({
                                'name': name,
                                'default': is_default,
                                'method': 'powershell'
                            })
                            
        except Exception:
            pass
    
    return devices

def test_audio_device_detection():
    """Test audio device detection capabilities."""
    print_header("AUDIO DEVICE DETECTION TESTS")
    
    devices = get_audio_devices()
    
    if not devices:
        print_test("Device detection", "FAIL", "No audio devices found")
        return False
    
    print_test("Device detection", "PASS", f"Found {len(devices)} devices")
    
    # Show detected devices
    default_devices = [d for d in devices if d.get('default', False)]
    
    for i, device in enumerate(devices[:5]):  # Show up to 5 devices
        is_default = device.get('default', False)
        method = device.get('method', 'unknown')
        status = "DEFAULT" if is_default else "AVAILABLE"
        
        print_test(f"Device {i+1}", status, f"{device['name']} ({method})")
    
    if len(devices) > 5:
        print_test("Additional devices", "INFO", f"{len(devices)-5} more devices found")
    
    return True

def test_expected_device_configuration():
    """Test if expected audio device is configured correctly."""
    print_header("EXPECTED DEVICE CONFIGURATION TESTS")
    
    # Load expected device from environment
    from dotenv import load_dotenv
    load_dotenv()
    
    expected_device = os.getenv("EXPECTED_AUDIO_OUTPUT", "").strip()
    
    if not expected_device:
        print_test("Expected device config", "SKIP", "EXPECTED_AUDIO_OUTPUT not set in .env")
        return True
    
    print_test("Expected device setting", "PASS", f"Expecting: {expected_device}")
    
    # Get current devices
    devices = get_audio_devices()
    default_devices = [d for d in devices if d.get('default', False)]
    
    if not default_devices:
        print_test("Default device check", "FAIL", "No default device found")
        return False
    
    # Check if expected device is the default
    current_default = default_devices[0]['name']
    
    if expected_device.lower() in current_default.lower():
        print_test("Device match", "PASS", f"Current default matches expected")
        return True
    else:
        print_test("Device match", "WARN", f"Current: {current_default}")
        print_test("Device mismatch details", "INFO", f"Expected: {expected_device}")
        return False

def test_audio_device_switching():
    """Test audio device switching capabilities (informational)."""
    print_header("AUDIO DEVICE SWITCHING TESTS")
    
    if os.name != 'nt':
        print_test("Device switching", "SKIP", "Not Windows platform")
        return True
    
    try:
        # Test if AudioDeviceCmdlets is available
        import subprocess
        result = subprocess.run(
            ['powershell', '-Command', 'Get-Module -ListAvailable AudioDeviceCmdlets'],
            capture_output=True, text=True, timeout=10
        )
        
        if 'AudioDeviceCmdlets' in result.stdout:
            print_test("AudioDeviceCmdlets", "PASS", "Device switching module available")
            
            # Test Get-AudioDevice command
            result = subprocess.run(
                ['powershell', '-Command', 'Get-AudioDevice -List | Select-Object -First 3'],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                print_test("Device listing", "PASS", "Can enumerate audio devices")
            else:
                print_test("Device listing", "FAIL", "Cannot list devices")
                
        else:
            print_test("AudioDeviceCmdlets", "WARN", "Module not installed (optional)")
            print_test("Install info", "INFO", "Install-Module -Name AudioDeviceCmdlets")
        
        return True
        
    except Exception as e:
        print_test("Device switching test", "FAIL", str(e))
        return False

def test_audio_system_health():
    """Test overall audio system health."""
    print_header("AUDIO SYSTEM HEALTH TESTS")
    
    try:
        devices = get_audio_devices()
        
        # Check for multiple detection methods
        methods = set(d.get('method', 'unknown') for d in devices)
        print_test("Detection methods", "INFO", f"Available: {', '.join(methods)}")
        
        # Check for default device
        default_count = len([d for d in devices if d.get('default', False)])
        if default_count == 1:
            print_test("Default device count", "PASS", "Exactly one default device")
        elif default_count == 0:
            print_test("Default device count", "FAIL", "No default device found")
            return False
        else:
            print_test("Default device count", "WARN", f"Multiple default devices: {default_count}")
        
        # Check for device availability
        total_devices = len(devices)
        if total_devices >= 1:
            print_test("Device availability", "PASS", f"{total_devices} devices available")
        else:
            print_test("Device availability", "FAIL", "No audio devices found")
            return False
        
        return True
        
    except Exception as e:
        print_test("Audio system health", "FAIL", str(e))
        return False

def main():
    """Run all audio device tests."""
    print(f"{Fore.GREEN}{Style.BRIGHT}Scribe Audio Device Tests")
    print(f"{Fore.WHITE}Testing audio device detection and configuration...\n")
    
    start_time = time.time() if 'time' in globals() else 0
    
    # Import time here to avoid issues
    import time
    start_time = time.time()
    
    # Run all test suites
    test_results = {
        "Audio Libraries": test_pycaw_import(),
        "Device Detection": test_audio_device_detection(), 
        "Expected Configuration": test_expected_device_configuration(),
        "Device Switching": test_audio_device_switching(),
        "System Health": test_audio_system_health(),
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
        print(f"\n{Fore.GREEN}{Style.BRIGHT}Audio device tests passed!")
        return 0
    else:
        print(f"\n{Fore.RED}{Style.BRIGHT}Some audio device tests failed.")
        return 1

if __name__ == "__main__":
    sys.exit(main())