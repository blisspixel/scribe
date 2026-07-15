# Development Guide

**Last Updated:** 2026-07-15 (locked setup and current local validation gates)

## Getting Started

### Prerequisites
- Python 3.12 or newer (3.12+ strongly recommended)
- Git
- FFmpeg
- (Optional) NVIDIA GPU with CUDA 12.4+
- **uv** (recommended for development - https://docs.astral.sh/uv/)

### Clone and Setup (Recommended - uv)

```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
uv sync --locked --group dev
uv run scribe init          # polished interactive first-run (review + verification + optional launcher)
uv run scribe doctor        # diagnostics + offers to re-run init on failures
```

**Classic pip path** (still supported but not recommended for development):

```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
pip install -e .
```

> **Note:** The requirements*.txt files are now legacy. The single source of truth is `pyproject.toml` + `uv.lock`. The legacy files may drift.

See [ROADMAP.md](ROADMAP.md) Step 1 (Reproducible Environment Foundation - now complete) for the rationale and current state.

### Configuration
```bash
cp .env.example .env
# Edit .env with your API keys (or let `scribe init` guide you)
```

## Project Structure

```
scribe/
├── src/scribe/           # Source code
│   ├── cli/              # Command-line interface
│   ├── core/             # Core transcription logic
│   ├── models/           # Data models and config
│   ├── providers/        # AI provider integrations
│   ├── utils/            # Utilities and helpers
│   └── exceptions.py     # Exception hierarchy
├── tests/                # Test suite
│   ├── unit/             # Unit tests
│   ├── integration/      # Integration tests
│   └── conftest.py       # Pytest configuration
├── docs/                 # Documentation
├── examples/             # Example files
└── output/               # Default output directory
```

## Running Tests

### Quick Test
```bash
pytest tests/unit/ --tb=no -q
```

### Full Test Suite
```bash
pytest
```

### With Coverage
```bash
# Recommended
uv run pytest tests/unit -m "not gpu and not slow and not e2e" --cov=src/scribe --cov-report=term-missing --cov-fail-under=80
uv run pytest tests/unit -m "not gpu and not slow and not e2e" --cov=src/scribe --cov-report=html
```

### Specific Tests
```bash
# Single file
pytest tests/unit/test_vocabulary.py

# Single test
pytest tests/unit/test_vocabulary.py::TestCustomVocabularyInit::test_init_empty

# By marker
uv run pytest -m "not gpu and not slow and not e2e"
```

### Test Status
- CI-safe unit coverage subset: `uv run pytest tests/unit -m "not gpu and not slow and not e2e" --cov=src/scribe --cov-report=term-missing --cov-fail-under=80`
- Latest CI-safe unit matrix: 1520 passed, 2 skipped, 37 deselected
- Latest broader CI-equivalent validation: 1620 passed, 12 skipped, 27 deselected, 82.57% line coverage
- Current collection: 1659 assertion-based tests
- Coverage gate: 80% minimum enforced (`fail_under = 80` in pyproject.toml)
- Very high pass rate on CI-safe subsets; comprehensive error-path coverage (especially recorder)
- Use markers to keep runs fast during development: `-m "not gpu and not slow and not e2e"`
- Full ruff + mypy --strict gates must pass before commit (see ROADMAP Step 2)

## Code Quality & Engineering Standards

We are actively elevating the codebase toward 2026-grade verifiable Python practices. See the Engineering Excellence section of [ROADMAP.md](../ROADMAP.md) for the ordered forward plan, definitions of done, and explicit non-goals.

### Current Expectations (following the ordered plan in ROADMAP.md)
- Prefer `uv run` for all development commands once uv is adopted
- New code must have type annotations on public symbols
- Run `ruff check` and `ruff format` before committing (enforced locally via pre-commit and in CI)
- Add or update tests for any changed behavior; use existing markers
- Follow the established defensive patterns: Pydantic validators, `ScribeError` subclasses with context, structured logging via `get_logger`
- No new bare `print()` in user-facing or library paths (debug/bake-off paths are the exception)

### Documentation
- Clear module and public API docstrings
- Architecture notes in long modules (see transcriber.py, recorder.py for examples)
- Type hints on all new public functions/classes

### Logging & Errors
- Dual-output logging (Rich console for humans, detailed files for post-mortems)
- Always use the custom exception hierarchy with structured `context`
- Graceful degradation and actionable messages are non-negotiable

### Testing
- Unit tests for new logic
- Exercise error paths and edge cases
- 100% pass rate on the CI-safe subset

## Development Workflow

### 1. Create Feature Branch
```bash
git checkout -b feature/your-feature-name
```

### 2. Make Changes
- Write code following the standards above and the ordered Engineering Excellence plan in ROADMAP.md
- Add tests
- Update documentation

### 3. Run Quality Gates (local)
```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy --strict src/scribe
uv run pytest tests/unit -m "not gpu and not slow and not e2e" -q
uv build --package scribe --out-dir .agent/build
uv run python scripts/check_release_artifact.py .agent/build
```

### 4. Full Local Verification
```bash
uv run pytest tests/unit -m "not gpu and not slow and not e2e" --cov=src/scribe --cov-report=term-missing --cov-fail-under=80
```

Optional live provider validation:

```bash
uv run scribe doctor --live
```

### 5. Commit
```bash
git add .
git commit -m "feat: add your feature"
```

**Local gates:** `pre-commit install --install-hooks` (enforces ruff + mypy + yaml/toml checks on every commit). The same gates run in CI via [.github/workflows/ci.yml](https://github.com/blisspixel/scribe/blob/main/.github/workflows/ci.yml).

See [ROADMAP.md](../ROADMAP.md) Step 1 for the reproducible environment foundation that is now in place.

### 6. Push and PR
```bash
git push origin feature/your-feature-name
# Create pull request on GitHub
```

## Adding New Features

### Adding a New Provider

1. **Create provider file**
```python
# src/scribe/providers/newprovider_provider.py
from scribe.providers.base import AIProvider, ProviderConfig

class NewProvider(AIProvider):
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        # Initialize client

    def chat_completion(self, messages, **kwargs):
        # Implement
        pass

    def generate_image(self, prompt, **kwargs):
        # Implement or raise NotImplementedError
        pass
```

2. **Register in factory**
```python
# src/scribe/providers/factory.py
def get_provider(feature, provider_name):
    if provider_name == "newprovider":
        return NewProvider(config)
```

3. **Add tests**
```python
# tests/unit/providers/test_newprovider_provider.py
def test_chat_completion():
    provider = NewProvider(config)
    result = provider.chat_completion(messages)
    assert result is not None
```

4. **Update documentation**
- Add to README.md provider list
- Document capabilities
- Add configuration examples

### Adding a New Command

1. **Create command function**
```python
# src/scribe/cli/main.py
@app.command()
def newcommand(
    input_file: Path,
    option: str = "default"
):
    """
    Description of new command.
    """
    try:
        # Implementation
        console.print("[green]Success!")
    except Exception as e:
        console.print(f"[red]Error: {e}")
        raise typer.Exit(1)
```

2. **Add tests**
```python
# tests/unit/test_cli.py
def test_newcommand():
    result = runner.invoke(app, ["newcommand", "test.txt"])
    assert result.exit_code == 0
```

3. **Update documentation**
- Add to README CLI section
- Add examples
- Document options

## Debugging

### Enable Debug Logging
```bash
export SCRIBE_LOG_LEVEL=DEBUG
scribe transcribe file.mp4
```

### Check GPU Status
```bash
python -c "import torch; print(torch.cuda.is_available())"
python -c "import torch; print(torch.cuda.get_device_name(0))"
```

### Inspect Session Data
```bash
# Session files stored in output directory
cat output/session_*.json
```

### Test Provider Connectivity
```bash
scribe health --provider openai
scribe health --provider xai
```

## Performance Profiling

### Profile Transcription
```python
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

# Run transcription
transcriber.transcribe(audio_path)

profiler.disable()
stats = pstats.Stats(profiler)
stats.sort_stats('cumulative')
stats.print_stats(20)
```

### Memory Profiling
```python
from memory_profiler import profile

@profile
def transcribe_with_profiling():
    transcriber.transcribe(audio_path)
```

### GPU Memory Monitoring
```bash
# Watch GPU memory usage
watch -n 1 nvidia-smi
```

## Common Development Tasks

### Update Dependencies
```bash
pip install --upgrade -r requirements.txt
pip install --upgrade -r requirements-dev.txt
```

### Clean Build Artifacts
```bash
# Remove Python cache
find . -type d -name __pycache__ -exec rm -rf {} +
find . -type f -name "*.pyc" -delete

# Remove test artifacts
rm -rf .pytest_cache
rm -rf htmlcov
rm .coverage
```

### Regenerate Requirements
```bash
pip freeze > requirements.txt
```

## Troubleshooting Development Issues

### Import Errors
```bash
# Reinstall in editable mode
pip install -e .
```

### Test Failures
```bash
# Run with verbose output
pytest -vv

# Run with full traceback
pytest --tb=long

# Run single failing test
pytest tests/unit/test_file.py::test_name -vv
```

### GPU Issues
```bash
# Check CUDA installation
nvcc --version

# Check PyTorch CUDA
python -c "import torch; print(torch.version.cuda)"

# Reinstall PyTorch with CUDA
pip uninstall torch torchvision torchaudio
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

## Release Process

### 1. Update Version
```python
# src/scribe/__init__.py
__version__ = "2.4.0"
```

### 2. Update Changelog
Add a new section at the top of the root `CHANGELOG.md` following the existing format (Unreleased section becomes the new versioned release).

### 3. Run Full Test Suite And Artifact Contract
```bash
uv run pytest
uv build --package scribe --out-dir .agent/build
uv run python scripts/check_release_artifact.py .agent/build
```

The root wheel is the portable product artifact. `scribe-audio-core` is an
optional workspace acceleration and must not appear as a mandatory root-wheel
requirement until matching platform wheels are published and clean-install tested.

### 4. Update Documentation
- README.md
- ROADMAP.md
- Any affected docs

### 5. Tag Release
```bash
git tag -a v2.4.0 -m "Release v2.4.0"
git push origin v2.4.0
```

## Contributing Guidelines

### Code Style
- Follow PEP 8
- Use type hints
- Write docstrings
- Keep functions focused (single responsibility)
- Avoid deep nesting (max 3 levels)

### Commit Messages
```
feat: add new feature
fix: fix bug
docs: update documentation
test: add tests
refactor: refactor code
perf: improve performance
chore: maintenance tasks
```

### Pull Request Process
1. Create feature branch
2. Make changes with tests
3. Ensure all tests pass
4. Update documentation
5. Submit PR with clear description
6. Address review feedback

### Review Checklist
- [ ] Tests pass (100% pass rate)
- [ ] Documentation updated
- [ ] Code follows standards
- [ ] No breaking changes (or documented)
- [ ] Performance impact considered
- [ ] Security implications reviewed

## Resources

- [Python Type Hints](https://docs.python.org/3/library/typing.html)
- [Pytest Documentation](https://docs.pytest.org/)
- [Rich Documentation](https://rich.readthedocs.io/)
- [Typer Documentation](https://typer.tiangolo.com/)
- [faster-whisper](https://github.com/guillaumekln/faster-whisper)

## Getting Help

- Check existing documentation
- Search GitHub issues
- Run `scribe doctor` for diagnostics
- Check logs in `./logs` directory
- Create GitHub issue with details
