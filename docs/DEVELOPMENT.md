# Development Guide

**Last Updated:** 2025-11-18

## Getting Started

### Prerequisites
- Python 3.10 or newer
- Git
- FFmpeg
- (Optional) NVIDIA GPU with CUDA 12.4+

### Clone and Setup
```bash
git clone https://github.com/blisspixel/scribe.git
cd scribe

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Install in editable mode
pip install -e .
```

### Configuration
```bash
cp .env.example .env
# Edit .env with your API keys
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
pytest --cov=scribe --cov-report=term-missing
pytest --cov=scribe --cov-report=html
pytest --cov=scribe --cov-report=term-missing --cov-fail-under=80
```

### Specific Tests
```bash
# Single file
pytest tests/unit/test_vocabulary.py

# Single test
pytest tests/unit/test_vocabulary.py::TestCustomVocabularyInit::test_init_empty

# By marker
pytest -m "not gpu"
```

### Test Status
- 589 tests passing (100% pass rate)
- Zero failures
- Execution time: ~72 seconds

## Code Quality Standards

### Documentation
- PhD-level docstrings for core modules
- Module-level architecture documentation
- Class and method documentation with examples
- Type hints throughout

### Logging
- Structured logging with context
- Appropriate log levels (DEBUG, INFO, WARNING, ERROR)
- No sensitive data in logs
- Consistent formatting

### Error Handling
- Use custom exception hierarchy
- Always include context in exceptions
- Graceful degradation
- Clear error messages

### Testing
- Unit tests for all new code
- Defensive tests for edge cases
- Mock external dependencies
- 100% pass rate required

See `docs/CODE_QUALITY_STANDARDS.md` for detailed guidelines.

## Development Workflow

### 1. Create Feature Branch
```bash
git checkout -b feature/your-feature-name
```

### 2. Make Changes
- Write code following standards
- Add tests
- Update documentation

### 3. Run Tests
```bash
pytest
```

### 4. Check Code Quality
```bash
# Run diagnostics
scribe doctor

# Check for issues
python -m py_compile src/scribe/**/*.py
```

### 5. Commit
```bash
git add .
git commit -m "feat: add your feature"
```

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
```bash
# Create docs/CHANGELOG_v2.4.0.md
```

### 3. Run Full Test Suite
```bash
pytest
```

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
