# Scribe Test Suite

Comprehensive testing framework for the Scribe transcription system.

## Overview

**Current Status**: 459 tests passing, 45% coverage

The Scribe test suite validates all system components:

- **Core Utilities**: Config, session, logging, file operations, validation
- **Audio Processing**: Duration detection, format handling, device management
- **Transcription**: Local GPU, OpenAI API, progress tracking
- **AI Features**: Joke generation, meme creation with QA loops
- **CLI**: Command parsing, workflow execution
- **Integration**: End-to-end workflows, error recovery

## Quick Start

### Run All Tests
```bash
# Run complete test suite with pytest
pytest

# Run with coverage report
pytest --cov=src/scribe --cov-report=term-missing

# Run with verbose output
pytest -v
```

### Run Specific Test Categories
```bash
# Unit tests only (fast)
pytest tests/unit/ -v

# Integration tests
pytest tests/integration/ -v

# End-to-end tests
pytest tests/e2e/ -v

# Specific module
pytest tests/unit/test_audio_duration.py -v
pytest tests/unit/test_progress_display.py -v
```

### Run by Test Markers
```bash
# Skip GPU tests
pytest -m "not gpu"

# Skip slow tests
pytest -m "not slow"

# Run only integration tests
pytest -m integration
```

## Test Organization

### Unit Tests (`tests/unit/`) - 412 tests

**Well-Tested Modules (>80% coverage)**:
- `test_exceptions.py` - Exception handling (100%, 34 tests)
- `test_logging.py` - Structured logging (100%, 24 tests)
- `test_config.py` - Configuration management (95%, 38 tests)
- `test_session.py` - Session tracking (93%, 30 tests)
- `test_files.py` - File operations (88%, 46 tests)
- `test_validation.py` - Input validation (83%, 40 tests)
- `test_joke_generator.py` - AI joke generation (77%, 45 tests)
- `test_meme_generator.py` - AI meme creation (75%, 38 tests)
- `test_audio_duration.py` - Duration detection (100%, 20 tests)
- `test_progress_display.py` - Progress bar UX (100%, 27 tests)
- `test_cli.py` - CLI commands (50%, 37 tests)

**Key Features**:
- Isolated unit tests with mocked dependencies
- Fast execution (<5 seconds total)
- Comprehensive edge case coverage
- Clear test names and documentation

### Integration Tests (`tests/integration/`) - 35 tests

**Modules**:
- `test_converter.py` - Audio/video conversion workflows
- `test_local_whisper.py` - GPU transcription integration
- `test_openai_api.py` - OpenAI API integration

**Key Features**:
- Tests component interactions
- Mocked external services (OpenAI, GPU)
- Validates error handling and recovery
- Tests real file operations

### End-to-End Tests (`tests/e2e/`) - 12 tests

**Workflows**:
- `test_full_workflow.py` - Complete transcription pipeline

**Key Features**:
- Tests entire user workflows
- Validates file cleanup
- Tests session management
- Checks output quality

### Legacy Tests (Root Level)

**Standalone Scripts**:
- `test_startup.py` - System health checks
- `test_audio.py` - Audio file handling
- `test_devices.py` - Audio device detection
- `test_platform.py` - Cross-platform compatibility

**Note**: These are being migrated to pytest format

## Test Results

Current test status:

```
============================================ test session starts ============================================
collected 459 items

tests/unit/test_audio_duration.py ......................                                              [ 4%]
tests/unit/test_progress_display.py ...........................                                       [ 10%]
tests/unit/test_exceptions.py ..................................                                      [ 17%]
tests/unit/test_logging.py ........................                                                   [ 22%]
tests/unit/test_config.py ......................................                                      [ 30%]
tests/unit/test_session.py ..............................                                             [ 37%]
tests/unit/test_files.py ..............................................                               [ 47%]
tests/unit/test_validation.py ........................................                                [ 56%]
tests/unit/test_joke_generator.py .............................................                       [ 66%]
tests/unit/test_meme_generator.py ......................................                              [ 74%]
tests/unit/test_cli.py .....................................                                          [ 82%]
tests/integration/ ...................................                                                [ 90%]
tests/e2e/ ............                                                                               [100%]

============================================ 459 passed in 45.2s ============================================

Coverage: 45%
```

## Recent Improvements (November 2025)

### New Test Coverage

**Audio Duration Detection** (20 tests):
- Multiple detection methods (WAV, torchaudio, ffprobe)
- Fallback mechanisms
- Corrupted file handling
- Duration validation and correction

**Progress Bar UX** (27 tests):
- GPU-based time estimation
- ETA calculation and formatting
- Duration correction logic
- UX improvements validation

### Bug Fixes Validated

1. [done] **Incorrect progress percentage** - Fixed calculation (1.5% → accurate)
2. [done] **Wrong duration detection** - Corrected WAV header parsing (2237 min → 53 min)
3. [done] **Confusing ETA** - Improved estimation (615m → accurate)
4. [done] **Information overload** - Simplified display (7 metrics → 2 metrics)
5. [done] **Technical jargon** - Removed from user-facing messages

## Integration with Main System

Tests are designed to integrate seamlessly with the main Scribe system:

- **Isolated Testing**: Tests run independently without affecting production files
- **Temporary Files**: Creates and cleans up test files automatically
- **Error Handling**: Comprehensive error catching and reporting
- **Performance Monitoring**: Times all operations for performance validation

## Requirements

The test suite requires the same dependencies as the main Scribe system:

- Python 3.8+
- torch (with CUDA support recommended)
- whisper
- torchaudio
- colorama
- dotenv
- numpy
- scipy

**Windows-specific (optional):**
- pycaw (for advanced audio device control)
- AudioDeviceCmdlets PowerShell module

## Troubleshooting

### Common Issues

**Import Errors:**
```bash
# Install missing packages
pip install torch torchaudio whisper-openai colorama python-dotenv numpy scipy
```

**Audio Device Tests Failing:**
```bash
# Install pycaw for Windows audio control
pip install pycaw

# Install AudioDeviceCmdlets for PowerShell integration
Install-Module -Name AudioDeviceCmdlets -Force
```

**Path Issues:**
- Ensure file paths don't contain unsupported characters
- Use absolute paths when possible
- Check file permissions for test directories

### Test Output Interpretation

- **PASS**: Test completed successfully
- **FAIL**: Test failed, check details for resolution
- **SKIP**: Test skipped (usually platform-specific)
- **WARN**: Test passed with warnings, may need attention
- **INFO**: Informational output, not a test result

## Contributing

When adding new tests:

1. Create test files with `test_` prefix in the `tests/` directory
2. Follow the established format with `print_test()` and `print_header()` functions
3. Include comprehensive error handling and cleanup
4. Document test purpose and expected behavior
5. Ensure tests can run independently and in any order

## Performance

The test suite is optimized for speed:

- Parallel test execution where safe
- Minimal file I/O operations
- Efficient GPU detection
- Quick timeout handling
- Smart test discovery

Typical execution times:
- Startup tests: ~5-10 seconds
- Audio tests: ~10-15 seconds
- Device tests: ~5-10 seconds
- **Total suite: ~20-35 seconds**
