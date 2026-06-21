# Test Suite Status

## Summary

- **Total Tests**: 1565 collected (unit + integration + e2e)
- **Pass Rate**: Very high on CI-safe subsets (markers exclude gpu/slow/requires_*)
- **Quality Gates**: Ruff check + format, mypy --strict, 80% coverage on filtered subset all enforced
- **Note**: Full suite is intentionally large; developers use markers for fast feedback

## Test Breakdown

### Current Reality (as of 2026-06-21)
- 1565 tests collected via pytest.
- Meme generator defensive tests now pass (previous mock image data issues resolved through code evolution).
- Strong coverage of error paths, recorder, CLI, providers, voice tray, vocabulary.
- Property-based tests (Hypothesis) present for core pure logic (costs, backend selection, diarizer, transcript model, validation, vocabulary, recording policy RecordingPhaseMachine, voice tray HotkeyStateMachine).

## Known Issues
None blocking. Old meme defensive failures noted in prior revisions of this file have been cleared. Stale counts in other docs were corrected as part of quality loop.

## Recent Quality Work
- Ruff RUF059 violations eliminated in recorder tests so full `ruff check` passes on src + tests (ROADMAP Step 2).
- Documentation accuracy refreshed across README, ROADMAP, DEVELOPMENT, this file.

## Test Categories

### Unit Tests
- Configuration and validation
- CLI commands
- Audio processing
- Provider abstraction
- Joke generation
- Meme generation
- Notes generation
- File operations
- Session management
- Logging and diagnostics
- **Custom vocabulary** (NEW)

### Integration Tests
- Audio converter
- Local Whisper transcription
- OpenAI API transcription

### E2E Tests
- Full workflow tests

### Manual Tests
- Actual timing tests
- Provider-specific tests

## Running Tests

### All Unit Tests
```bash
python -m pytest tests/unit -v
```

### Specific Feature
```bash
python -m pytest tests/unit/test_vocabulary.py -v
```

### With Coverage
```bash
python -m pytest tests/unit --cov=scribe --cov-report=html
```

### Skip Slow Tests
```bash
python -m pytest tests/unit -m "not slow"
```

### Skip Manual Tests
```bash
python -m pytest tests/ --ignore=tests/manual --ignore=tests/e2e
```

## Test Quality

### Coverage
- Current coverage maintained at ~42%
- New vocabulary module has 100% test coverage
- All critical paths tested

### Test Types
- Unit tests: Fast, isolated, mocked dependencies
- Integration tests: Real components, no external APIs
- E2E tests: Full workflow, may require API keys
- Manual tests: Performance and timing validation

## Recent Updates (v2.3.0)

### Added
- 27 new tests for custom vocabulary feature
- Tests for txt and json file formats
- Tests for comment handling in txt files
- Tests for Whisper prompt format conversion
- Tests for edge cases and error conditions

### Fixed
- Updated provider default model test for XAI meme generation

### Maintained
- All existing tests continue to pass
- No regressions introduced by new features
- Test suite runs in ~70 seconds

## Next Steps

### To Fix
1. Update meme generator defensive tests with valid mock image data
2. Add integration tests for batch processing
3. Add integration tests for vocabulary in transcription pipeline

### To Add
- Batch processing CLI tests
- Vocabulary integration with transcriber tests
- Performance tests for batch operations

## Notes

- Manual tests in `tests/manual/` require actual API keys and are not run in CI
- E2E tests may be slow and are typically run separately
- The test suite is designed to run quickly for development workflow
- All new features should include unit tests before merging
