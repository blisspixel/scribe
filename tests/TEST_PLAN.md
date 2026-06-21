# Scribe Test Plan

## Current Status (November 2025)

**Test Results**: 459 passed, 0 failed (459 total)
**Coverage**: 45% overall

**Recent Additions**:
- [done] Audio duration detection tests (20 tests)
- [done] Progress bar UX tests (27 tests)
- [done] Joke generator tests (45 tests)
- [done] Meme generator tests (38 tests)
- [done] Session management tests (30 tests)
- [done] DOCX converter tests (23 tests)

## Test Coverage by Module

### Unit Tests (412 tests)

#### [done] Well Tested (>80% coverage)
- **Exception handling**: 100% (34 tests)
- **Logging utilities**: 100% (24 tests)
- **Configuration**: 95% (38 tests)
- **Session management**: 93% (30 tests)
- **DOCX converter**: 89% (23 tests)
- **File operations**: 88% (46 tests)
- **Input validation**: 83% (40 tests)
- **Joke generator**: 77% (45 tests)
- **Meme generator**: 75% (38 tests)
- **Audio duration**: 100% (20 tests)
- **Progress display**: 100% (27 tests)

#### Needs Improvement (30-70% coverage)
- **CLI commands**: 50% (37 tests) -> Target: 80%
- **Transcriber orchestration**: 39% (needs more) -> Target: 70%
- **Converter**: 44% (needs more) -> Target: 70%
- **Platform utilities**: 35% (needs more) -> Target: 70%
- **Audio utilities**: 28% (needs more) -> Target: 70%

#### Low Coverage (<30%)
- **OpenAI API client**: 21% -> Target: 70%
- **GPU utilities**: 18% -> Target: 60%
- **Local Whisper**: 12% -> Target: 60%

### Integration Tests (35 tests)

#### [done] Working
- **Converter integration**: Basic WAV/MP3 conversion
- **Local Whisper integration**: GPU transcription workflow
- **OpenAI API integration**: Server-side chunking

#### Needs More Coverage
- **Recorder integration**: OBS WebSocket workflow
- **Full transcription pipeline**: End-to-end with all features
- **Error recovery**: Network failures, GPU OOM, etc.

### End-to-End Tests (12 tests)

#### [done] Working
- **Basic workflow**: Audio -> Transcript -> DOCX
- **Cleanup behavior**: Intermediate file removal
- **Session tracking**: File management

#### [needs-work] Missing Tests
- **Complete workflow with AI features**
  - Record -> Convert -> Transcribe -> DOCX -> Joke -> Meme
- **CLI command workflows**
  - `scribe transcribe` full flow
  - `scribe rec` quick recording
  - `scribe joke` standalone
  - `scribe meme` with QA loop
- **Cross-platform scenarios**
  - GPU vs OpenAI fallback
  - Path handling (Windows/macOS/Linux)
  - Terminal link rendering

## Priority Test Implementation

### Phase 1: Core Utilities (Target: 60% coverage) - IN PROGRESS

**Status**: 45% -> 60% (75% complete)

[done] **Completed**:
- Session management tests (93% coverage)
- DOCX converter tests (89% coverage)
- Logging tests (100% coverage)
- File operations tests (88% coverage)
- Configuration tests (95% coverage)
- Audio duration tests (100% coverage)
- Progress display tests (100% coverage)

**In Progress**:
- Audio utilities (28% -> 70%, ~30 tests needed)
- Platform utilities (35% -> 70%, ~25 tests needed)
- GPU utilities (18% -> 60%, ~20 tests needed)

### Phase 2: Core Logic (Target: 75% coverage)

**Priority**:
1. **Transcriber orchestration** (39% -> 75%)
   - Method selection logic
   - Fallback behavior
   - Error handling

2. **Converter integration** (44% -> 75%)
   - WAV conversion edge cases
   - MP3 compression
   - Format detection

3. **OpenAI API client** (21% -> 70%)
   - Server-side chunking
   - Speaker diarization
   - Error recovery

4. **Local Whisper** (12% -> 60%)
   - GPU transcription
   - Progress tracking
   - Memory management

5. **CLI commands** (50% -> 80%)
   - Argument parsing
   - Workflow execution
   - Error messages

### Phase 3: Integration (Target: 85% coverage)

**Priority**:
1. **End-to-end workflows**
   - Full transcription pipeline
   - AI feature integration (jokes, memes)
   - Error recovery scenarios

2. **Recorder integration**
   - OBS WebSocket mocking
   - Recording workflow
   - File finalization

3. **Cross-platform testing**
   - Windows/macOS/Linux paths
   - GPU detection
   - Terminal rendering

### Phase 4: Advanced (Target: 90%+ coverage)

**Nice to Have**:
1. **Performance benchmarks**
   - GPU transcription speed
   - API latency
   - File size limits

2. **Stress testing**
   - Large files (>2 hours)
   - Concurrent operations
   - Memory limits

3. **Security testing**
   - API key handling
   - File permissions
   - Input sanitization

## Test Infrastructure

### [done] Implemented
- Fixtures for common test data (conftest.py)
- Mocks for external services (OpenAI API, GPU)
- Test markers (gpu, slow, integration, e2e)
- Coverage reporting (pytest-cov)
- Isolated test environments (tmp_path fixtures)

### Needs Improvement
- CI/CD integration (GitHub Actions)
- Performance benchmarking
- Test data management (sample audio files)
- Mock OBS WebSocket server
- Automated coverage tracking

## Success Criteria

### Phase 1 (Current Target)
- [done] All existing tests passing (459/459)
- 60%+ code coverage (currently ~45%)
- [done] Core utilities tested (>80% coverage)
- Audio/Platform/GPU utilities improved
- [done] Fast test execution (<5 seconds for unit tests)

### Phase 2 (Next Milestone)
- 75%+ code coverage
- All core logic tested (transcriber, converter, APIs)
- CLI commands fully tested
- Integration tests comprehensive

### Phase 3 (Production Ready)
- 85%+ code coverage
- End-to-end workflows tested
- Cross-platform validation
- Performance benchmarks
- No flaky tests

## Recent Improvements (November 2025)

### New Test Files
- `tests/unit/test_audio_duration.py` (20 tests)
- `tests/unit/test_progress_display.py` (27 tests)
- `tests/TEST_SUMMARY_PROGRESS_UX.md` (documentation)

### Bug Fixes Validated
1. [done] Incorrect progress percentage (1.5% -> accurate)
2. [done] Wrong duration detection (2237 min -> 53 min)
3. [done] Confusing ETA (615m -> accurate)
4. [done] Information overload (7 metrics -> 2 metrics)
5. [done] Technical jargon removed from UX

### Coverage Improvements
- Audio duration detection: 0% -> 100%
- Progress display logic: 0% -> 100%
- Overall coverage: 41% -> 45% (+4%)
