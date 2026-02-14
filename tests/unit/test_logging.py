"""
Unit tests for logging utilities.

Tests logging configuration, formatting, and system info logging.
"""

import logging
from unittest.mock import Mock, patch

from scribe.utils.logging import (
    get_logger,
    log_exception,
    log_system_info,
    set_log_level,
    setup_logging,
)


class TestLoggingSetup:
    """Test logging setup and configuration."""

    def test_setup_logging_basic(self, tmp_path):
        """Test basic logging setup."""
        log_dir = tmp_path / "logs"

        logger = setup_logging("test_session", log_dir)

        # Should create log directory
        assert log_dir.exists()

        # Should return logger
        assert isinstance(logger, logging.Logger)
        assert logger.name == "scribe"
        assert logger.level == logging.DEBUG

    def test_setup_logging_creates_log_file(self, tmp_path):
        """Test logging setup creates log file."""
        log_dir = tmp_path / "logs"

        logger = setup_logging("test_session", log_dir)

        # Should create log file
        log_files = list(log_dir.glob("scribe_test_session_*.log"))
        assert len(log_files) == 1
        assert log_files[0].exists()

    def test_setup_logging_with_custom_levels(self, tmp_path):
        """Test logging setup with custom levels."""
        log_dir = tmp_path / "logs"

        logger = setup_logging(
            "custom_session",
            log_dir,
            console_level=logging.ERROR,
            file_level=logging.INFO
        )

        # Should have handlers with correct levels
        assert len(logger.handlers) == 2

        # File handler should be INFO
        file_handler = logger.handlers[0]
        assert file_handler.level == logging.INFO

        # Console handler should be ERROR
        console_handler = logger.handlers[1]
        assert console_handler.level == logging.ERROR

    def test_setup_logging_clears_existing_handlers(self, tmp_path):
        """Test logging setup clears existing handlers."""
        log_dir = tmp_path / "logs"

        # Setup logging twice
        logger1 = setup_logging("session1", log_dir)
        initial_handler_count = len(logger1.handlers)

        logger2 = setup_logging("session2", log_dir)

        # Should have same number of handlers (old ones cleared)
        assert len(logger2.handlers) == initial_handler_count

    def test_setup_logging_creates_nested_directory(self, tmp_path):
        """Test logging setup creates nested directories."""
        log_dir = tmp_path / "nested" / "log" / "directory"

        logger = setup_logging("nested_session", log_dir)

        # Should create all parent directories
        assert log_dir.exists()
        assert (log_dir / f"scribe_nested_session_{logger.handlers[0].baseFilename.split('_')[-1].replace('.log', '')}.log").exists() or len(list(log_dir.glob("*.log"))) > 0


class TestGetLogger:
    """Test logger retrieval."""

    def test_get_logger_default(self):
        """Test getting default logger."""
        logger = get_logger()

        assert isinstance(logger, logging.Logger)
        assert logger.name == "scribe"

    def test_get_logger_with_name(self):
        """Test getting logger with custom name."""
        logger = get_logger("custom_module")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "custom_module"

    def test_get_logger_returns_same_instance(self):
        """Test logger instances are cached."""
        logger1 = get_logger("test_module")
        logger2 = get_logger("test_module")

        # Should return same instance
        assert logger1 is logger2


class TestLogSystemInfo:
    """Test system information logging."""

    @patch('scribe.utils.gpu.detect_gpu_capability')
    @patch('scribe.utils.platform.get_platform_info')
    def test_log_system_info_with_gpu(self, mock_platform, mock_gpu):
        """Test logging system info with GPU."""
        mock_logger = Mock()
        mock_gpu.return_value = {
            "has_gpu": True,
            "gpu_name": "NVIDIA RTX 3090",
            "gpu_memory_gb": 24.0,
            "cuda_version": "11.8"
        }

        log_system_info(mock_logger)

        # Should log system info
        assert mock_logger.debug.call_count >= 5

        # Check for GPU info in calls
        calls = [str(call) for call in mock_logger.debug.call_args_list]
        gpu_logged = any("GPU" in str(call) or "NVIDIA" in str(call) for call in calls)
        assert gpu_logged

    @patch('scribe.utils.gpu.detect_gpu_capability')
    @patch('scribe.utils.platform.get_platform_info')
    def test_log_system_info_without_gpu(self, mock_platform, mock_gpu):
        """Test logging system info without GPU."""
        mock_logger = Mock()
        mock_gpu.return_value = {"has_gpu": False}

        log_system_info(mock_logger)

        # Should log that GPU is not available
        calls = [str(call) for call in mock_logger.debug.call_args_list]
        no_gpu_logged = any("Not available" in str(call) for call in calls)
        assert no_gpu_logged

    @patch('scribe.utils.gpu.detect_gpu_capability')
    @patch('scribe.utils.platform.get_platform_info')
    def test_log_system_info_gpu_detection_fails(self, mock_platform, mock_gpu):
        """Test logging system info when GPU detection fails."""
        mock_logger = Mock()
        mock_gpu.side_effect = Exception("GPU detection error")

        log_system_info(mock_logger)

        # Should log detection failure
        calls = [str(call) for call in mock_logger.debug.call_args_list]
        error_logged = any("Detection failed" in str(call) for call in calls)
        assert error_logged


class TestLogException:
    """Test exception logging."""

    def test_log_exception_basic(self):
        """Test logging basic exception."""
        mock_logger = Mock()
        exc = ValueError("Test error")

        log_exception(mock_logger, exc)

        # Should log error
        mock_logger.error.assert_called()
        error_call = str(mock_logger.error.call_args_list[0])
        assert "ValueError" in error_call
        assert "Test error" in error_call

    def test_log_exception_with_context(self):
        """Test logging exception with context."""
        mock_logger = Mock()
        exc = RuntimeError("Runtime error")
        context = {"session_id": "test-123", "file": "test.txt"}

        log_exception(mock_logger, exc, context)

        # Should log error and context
        assert mock_logger.error.call_count >= 2

        # Check context was logged
        calls = [str(call) for call in mock_logger.error.call_args_list]
        context_logged = any("Context" in str(call) for call in calls)
        assert context_logged

    def test_log_exception_with_traceback(self):
        """Test logging exception includes traceback."""
        mock_logger = Mock()
        exc = Exception("Test exception")

        log_exception(mock_logger, exc)

        # Should call debug with exc_info
        mock_logger.debug.assert_called()
        debug_call = mock_logger.debug.call_args
        assert debug_call[1].get("exc_info") is True


class TestSetLogLevel:
    """Test log level setting."""

    def test_set_log_level_basic(self, tmp_path):
        """Test setting log level."""
        log_dir = tmp_path / "logs"
        logger = setup_logging("test_session", log_dir)

        set_log_level(logger, logging.ERROR)

        # Logger level should be updated
        assert logger.level == logging.ERROR

    def test_set_log_level_updates_handlers(self, tmp_path):
        """Test setting log level updates Rich handlers."""
        log_dir = tmp_path / "logs"
        logger = setup_logging("test_session", log_dir)

        set_log_level(logger, logging.WARNING)

        # Rich handler should be updated
        from rich.logging import RichHandler
        rich_handlers = [h for h in logger.handlers if isinstance(h, RichHandler)]

        if rich_handlers:
            assert rich_handlers[0].level == logging.WARNING


class TestLoggingIntegration:
    """Test logging integration scenarios."""

    def test_full_logging_workflow(self, tmp_path):
        """Test complete logging workflow."""
        log_dir = tmp_path / "logs"

        # Setup logging
        logger = setup_logging("workflow_test", log_dir, console_level=logging.DEBUG)

        # Log various levels
        logger.debug("Debug message")
        logger.info("Info message")
        logger.warning("Warning message")
        logger.error("Error message")

        # Verify log file was created and contains messages
        log_files = list(log_dir.glob("*.log"))
        assert len(log_files) == 1

        log_content = log_files[0].read_text(encoding="utf-8")
        assert "Debug message" in log_content
        assert "Info message" in log_content
        assert "Warning message" in log_content
        assert "Error message" in log_content

    def test_logging_with_unicode(self, tmp_path):
        """Test logging with Unicode characters."""
        log_dir = tmp_path / "logs"
        logger = setup_logging("unicode_test", log_dir)

        # Log Unicode content
        logger.info("Testing Unicode: 中文 测试 café naïve")
        logger.info("Emoji test: 🎉 ✅ 🚀")

        # Verify log file contains Unicode
        log_files = list(log_dir.glob("*.log"))
        log_content = log_files[0].read_text(encoding="utf-8")

        assert "中文" in log_content
        assert "café" in log_content

    @patch('scribe.utils.gpu.detect_gpu_capability')
    def test_logging_with_system_info(self, mock_gpu, tmp_path):
        """Test logging with system information."""
        log_dir = tmp_path / "logs"
        logger = setup_logging("sysinfo_test", log_dir)

        mock_gpu.return_value = {"has_gpu": True, "gpu_name": "Test GPU"}

        # Log system info
        log_system_info(logger)

        # Verify system info was logged
        log_files = list(log_dir.glob("*.log"))
        log_content = log_files[0].read_text(encoding="utf-8")

        assert "System Information" in log_content
        assert "Platform" in log_content

    def test_logging_exception_workflow(self, tmp_path):
        """Test exception logging workflow."""
        log_dir = tmp_path / "logs"
        logger = setup_logging("exception_test", log_dir)

        try:
            # Trigger an exception
            result = 1 / 0
        except ZeroDivisionError as e:
            log_exception(logger, e, {"operation": "division", "values": [1, 0]})

        # Verify exception was logged
        log_files = list(log_dir.glob("*.log"))
        log_content = log_files[0].read_text(encoding="utf-8")

        assert "ZeroDivisionError" in log_content
        assert "Context" in log_content


class TestLoggingEdgeCases:
    """Test edge cases and error handling."""

    def test_setup_logging_existing_directory(self, tmp_path):
        """Test logging setup with existing directory."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        # Should not fail
        logger = setup_logging("existing_dir_test", log_dir)
        assert logger is not None

    def test_multiple_loggers_same_session(self, tmp_path):
        """Test multiple logger instances for same session."""
        log_dir = tmp_path / "logs"

        logger1 = setup_logging("multi_test", log_dir)
        logger2 = get_logger("scribe")

        # Should be same logger
        assert logger1 is logger2

    def test_log_exception_with_none_context(self):
        """Test logging exception with None context."""
        mock_logger = Mock()
        exc = ValueError("Test")

        # Should not crash
        log_exception(mock_logger, exc, None)

        mock_logger.error.assert_called()

    def test_set_log_level_no_handlers(self):
        """Test setting log level on logger with no handlers."""
        logger = logging.getLogger("test_no_handlers")
        logger.handlers = []

        # Should not crash
        set_log_level(logger, logging.INFO)
        assert logger.level == logging.INFO
