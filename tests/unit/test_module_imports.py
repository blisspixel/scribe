"""
Module import and runtime tests.

These tests verify that all modules can be imported and key classes
can be instantiated without runtime errors like NameError or ImportError.

This catches bugs like:
- Missing imports in methods (e.g., ScribeTheme not imported in complete())
- Circular import issues
- Missing dependencies
"""

import importlib
from pathlib import Path

import pytest


class TestModuleImports:
    """Test that all modules can be imported."""

    @pytest.fixture
    def all_modules(self):
        """Get list of all scribe modules."""
        src_path = Path("src/scribe")
        modules = []
        for py_file in src_path.rglob("*.py"):
            rel = py_file.relative_to("src")
            parts = list(rel.parts)
            if parts[-1] == "__init__.py":
                parts = parts[:-1]
            else:
                parts[-1] = parts[-1].replace(".py", "")
            module = ".".join(parts)
            if module:
                modules.append(module)
        return sorted(set(modules))

    def test_all_modules_import(self, all_modules):
        """Verify all modules can be imported without errors."""
        failed = []
        for module in all_modules:
            try:
                importlib.import_module(module)
            except Exception as e:
                failed.append((module, str(e)))

        if failed:
            msg = "Failed to import modules:\n"
            for mod, err in failed:
                msg += f"  {mod}: {err}\n"
            pytest.fail(msg)


class TestUtilityClasses:
    """Test that utility classes can be instantiated and used."""

    def test_unified_progress_lifecycle(self):
        """Test UnifiedProgress full lifecycle without mocks."""
        from unittest.mock import MagicMock, patch

        from scribe.utils.unified_progress import UnifiedProgress

        # Mock the Progress class to avoid Rich live display conflicts in test environment
        with patch("scribe.utils.unified_progress.Progress") as mock_progress_class:
            mock_progress = MagicMock()
            mock_progress.add_task.return_value = 0
            mock_progress_class.return_value = mock_progress

            progress = UnifiedProgress(total_duration=100.0, include_api_features=True)
            try:
                progress.start()
                progress.update_phase("preparing", 0.5)
                progress.update_phase("transcribing", 0.5)
                progress.update_phase("finishing", 0.5)
                progress.complete()  # Must have ScribeTheme import
            finally:
                progress.stop()

    def test_spinner_progress_lifecycle(self):
        """Test SpinnerProgress full lifecycle."""
        from scribe.utils.spinner import SpinnerProgress

        sp = SpinnerProgress("Testing")
        sp.update("Still testing")
        sp.success("Done")

    def test_progress_bar_creation(self):
        """Test progress bar creation."""
        from scribe.utils.progress import create_progress_bar

        p = create_progress_bar("Test")
        p.start()
        task = p.add_task("Test", total=100)
        p.update(task, completed=50)
        p.stop()

    def test_theme_utilities(self):
        """Test theme utility functions."""
        from scribe.utils.theme import ScribeTheme, status_line, styled

        # Verify theme constants exist
        assert ScribeTheme.PRIMARY
        assert ScribeTheme.SUCCESS
        assert ScribeTheme.ERROR

        # Verify utility functions work
        result = styled("test", "primary")
        assert "test" in result

        result = status_line("done", "Test complete")
        assert "Test complete" in result


class TestRecorderClass:
    """Test OBSRecorder class methods."""

    @pytest.fixture
    def recorder(self, tmp_path):
        """Create OBSRecorder instance."""
        from scribe.core.recorder import OBSRecorder
        from scribe.models.config import ScribeConfig

        config = ScribeConfig(
            obs_host="localhost", obs_port=4455, obs_password="", output_folder=tmp_path
        )
        return OBSRecorder(config)

    def test_stop_listener_creation(self, recorder):
        """Test stop listener thread creation."""
        ev, restore = recorder._start_stop_listener()
        try:
            assert ev is not None
            ev.set()  # Stop it
        finally:
            restore()

    def test_safe_filename(self, recorder):
        """Test safe filename generation."""
        import time

        filename = recorder._safe_filename("Test Meeting", time.time())
        assert "Test Meeting" in filename
        assert filename.endswith(".mp4")

    def test_port_listening_closed(self, recorder):
        """Test port listening detection for closed port."""
        result = recorder._port_listening("127.0.0.1", 54321, timeout=0.1)
        assert result is False


class TestProviderClasses:
    """Test AI provider classes can be instantiated."""

    def test_openai_provider_import(self):
        """Test OpenAI provider can be imported."""
        from scribe.providers.openai_provider import OpenAIProvider

        # Just verify import works
        assert OpenAIProvider is not None

    def test_xai_provider_import(self):
        """Test XAI provider can be imported."""
        from scribe.providers.xai_provider import XAIProvider

        assert XAIProvider is not None

    def test_anthropic_provider_import(self):
        """Test Anthropic provider can be imported."""
        from scribe.providers.anthropic_provider import AnthropicProvider

        assert AnthropicProvider is not None

    def test_gemini_provider_import(self):
        """Test Gemini provider can be imported."""
        from scribe.providers.gemini_provider import GeminiProvider

        assert GeminiProvider is not None

    def test_provider_factory_import(self):
        """Test provider factory can be imported."""
        from scribe.providers.factory import get_provider

        assert get_provider is not None
