"""
Unit tests for custom exception hierarchy.

Tests exception behavior, context preservation, and error formatting.
"""

import pytest
from scribe.exceptions import (
    ScribeError,
    ValidationError,
    ProcessError,
    TranscriptionError,
    FileOperationError,
    CircuitBreakerOpen,
    ConversionError,
    AudioFormatError,
    GPUError,
    APIError,
)


class TestScribeError:
    """Test base ScribeError exception."""
    
    def test_basic_error_message(self):
        """Test basic error message without context."""
        error = ScribeError("Test error")
        assert str(error) == "Test error"
        assert error.message == "Test error"
        assert error.context == {}
    
    def test_error_with_context(self):
        """Test error message with context."""
        error = ScribeError("Test error", context={"key": "value", "count": 42})
        error_str = str(error)
        
        assert "Test error" in error_str
        assert "key=value" in error_str
        assert "count=42" in error_str
    
    def test_error_context_attribute(self):
        """Test context is stored as attribute."""
        context = {"file": "test.mp4", "size": 1024}
        error = ScribeError("Test error", context=context)
        
        assert error.context == context
        assert error.context["file"] == "test.mp4"
        assert error.context["size"] == 1024
    
    def test_error_without_context_has_empty_dict(self):
        """Test error without context has empty dict, not None."""
        error = ScribeError("Test error")
        assert error.context == {}
        assert isinstance(error.context, dict)


class TestExceptionInheritance:
    """Test exception inheritance hierarchy."""
    
    def test_validation_error_inherits_from_scribe_error(self):
        """Test ValidationError inherits from ScribeError."""
        assert issubclass(ValidationError, ScribeError)
        assert issubclass(ValidationError, Exception)
    
    def test_process_error_inherits_from_scribe_error(self):
        """Test ProcessError inherits from ScribeError."""
        assert issubclass(ProcessError, ScribeError)
    
    def test_transcription_error_inherits_from_scribe_error(self):
        """Test TranscriptionError inherits from ScribeError."""
        assert issubclass(TranscriptionError, ScribeError)
    
    def test_file_operation_error_inherits_from_scribe_error(self):
        """Test FileOperationError inherits from ScribeError."""
        assert issubclass(FileOperationError, ScribeError)
    
    def test_circuit_breaker_open_inherits_from_scribe_error(self):
        """Test CircuitBreakerOpen inherits from ScribeError."""
        assert issubclass(CircuitBreakerOpen, ScribeError)
    
    def test_conversion_error_inherits_from_scribe_error(self):
        """Test ConversionError inherits from ScribeError."""
        assert issubclass(ConversionError, ScribeError)
    
    def test_audio_format_error_inherits_from_scribe_error(self):
        """Test AudioFormatError inherits from ScribeError."""
        assert issubclass(AudioFormatError, ScribeError)
    
    def test_gpu_error_inherits_from_scribe_error(self):
        """Test GPUError inherits from ScribeError."""
        assert issubclass(GPUError, ScribeError)
    
    def test_api_error_inherits_from_scribe_error(self):
        """Test APIError inherits from ScribeError."""
        assert issubclass(APIError, ScribeError)


class TestExceptionCatching:
    """Test exception catching behavior."""
    
    def test_catch_specific_exception(self):
        """Test catching specific exception type."""
        with pytest.raises(ValidationError):
            raise ValidationError("Test validation error")
    
    def test_catch_base_exception(self):
        """Test catching base ScribeError catches all subtypes."""
        with pytest.raises(ScribeError):
            raise ValidationError("Test error")
        
        with pytest.raises(ScribeError):
            raise ProcessError("Test error")
        
        with pytest.raises(ScribeError):
            raise TranscriptionError("Test error")
    
    def test_exception_message_accessible(self):
        """Test exception message is accessible after catching."""
        try:
            raise ValidationError("Test message", context={"key": "value"})
        except ScribeError as e:
            assert e.message == "Test message"
            assert e.context["key"] == "value"


class TestValidationError:
    """Test ValidationError specific behavior."""
    
    def test_validation_error_with_config_context(self):
        """Test ValidationError with configuration context."""
        error = ValidationError(
            "Invalid configuration",
            context={"config_key": "api_key", "reason": "missing"}
        )
        
        assert "Invalid configuration" in str(error)
        assert "config_key=api_key" in str(error)
    
    def test_validation_error_with_file_context(self):
        """Test ValidationError with file path context."""
        error = ValidationError(
            "File not found",
            context={"path": "/test/file.mp4", "exists": False}
        )
        
        assert error.context["path"] == "/test/file.mp4"
        assert error.context["exists"] is False


class TestProcessError:
    """Test ProcessError specific behavior."""
    
    def test_process_error_with_command_context(self):
        """Test ProcessError with command context."""
        error = ProcessError(
            "FFmpeg failed",
            context={"command": "ffmpeg -i input.mp4", "exit_code": 1}
        )
        
        assert "FFmpeg failed" in str(error)
        assert error.context["exit_code"] == 1
    
    def test_process_error_with_timeout_context(self):
        """Test ProcessError with timeout context."""
        error = ProcessError(
            "Process timeout",
            context={"timeout_seconds": 300, "elapsed": 305}
        )
        
        assert error.context["timeout_seconds"] == 300


class TestTranscriptionError:
    """Test TranscriptionError specific behavior."""
    
    def test_transcription_error_with_gpu_context(self):
        """Test TranscriptionError with GPU context."""
        error = TranscriptionError(
            "GPU out of memory",
            context={"vram_used_gb": 22.5, "vram_total_gb": 24.0, "model": "large-v3"}
        )
        
        assert "GPU out of memory" in str(error)
        assert error.context["model"] == "large-v3"
    
    def test_transcription_error_with_api_context(self):
        """Test TranscriptionError with API context."""
        error = TranscriptionError(
            "API call failed",
            context={"status_code": 500, "retry_count": 3}
        )
        
        assert error.context["status_code"] == 500


class TestFileOperationError:
    """Test FileOperationError specific behavior."""
    
    def test_file_operation_error_with_permission_context(self):
        """Test FileOperationError with permission context."""
        error = FileOperationError(
            "Permission denied",
            context={"path": "/protected/file.txt", "operation": "write"}
        )
        
        assert "Permission denied" in str(error)
        assert error.context["operation"] == "write"
    
    def test_file_operation_error_with_disk_space_context(self):
        """Test FileOperationError with disk space context."""
        error = FileOperationError(
            "Disk full",
            context={"required_mb": 1024, "available_mb": 100}
        )
        
        assert error.context["required_mb"] == 1024


class TestCircuitBreakerOpen:
    """Test CircuitBreakerOpen specific behavior."""
    
    def test_circuit_breaker_with_failure_context(self):
        """Test CircuitBreakerOpen with failure context."""
        error = CircuitBreakerOpen(
            "Too many failures",
            context={"failure_count": 5, "timeout_seconds": 60}
        )
        
        assert "Too many failures" in str(error)
        assert error.context["failure_count"] == 5
        assert error.context["timeout_seconds"] == 60


class TestConversionError:
    """Test ConversionError specific behavior."""
    
    def test_conversion_error_with_format_context(self):
        """Test ConversionError with format context."""
        error = ConversionError(
            "Conversion failed",
            context={"input_format": "mp4", "output_format": "wav", "error": "Invalid codec"}
        )
        
        assert error.context["input_format"] == "mp4"
        assert error.context["output_format"] == "wav"


class TestAudioFormatError:
    """Test AudioFormatError specific behavior."""
    
    def test_audio_format_error_with_format_context(self):
        """Test AudioFormatError with format context."""
        error = AudioFormatError(
            "Unsupported format",
            context={"file": "audio.xyz", "format": "unknown"}
        )
        
        assert "Unsupported format" in str(error)
        assert error.context["format"] == "unknown"


class TestGPUError:
    """Test GPUError specific behavior."""
    
    def test_gpu_error_with_memory_context(self):
        """Test GPUError with memory context."""
        error = GPUError(
            "CUDA out of memory",
            context={"requested_gb": 12, "available_gb": 8}
        )
        
        assert "CUDA out of memory" in str(error)
        assert error.context["requested_gb"] == 12
    
    def test_gpu_error_with_driver_context(self):
        """Test GPUError with driver context."""
        error = GPUError(
            "CUDA driver mismatch",
            context={"required_version": "12.4", "installed_version": "11.8"}
        )
        
        assert error.context["required_version"] == "12.4"


class TestAPIError:
    """Test APIError specific behavior."""
    
    def test_api_error_with_rate_limit_context(self):
        """Test APIError with rate limit context."""
        error = APIError(
            "Rate limit exceeded",
            context={"status_code": 429, "retry_after": 60}
        )
        
        assert "Rate limit exceeded" in str(error)
        assert error.context["status_code"] == 429
    
    def test_api_error_with_auth_context(self):
        """Test APIError with authentication context."""
        error = APIError(
            "Authentication failed",
            context={"status_code": 401, "reason": "Invalid API key"}
        )
        
        assert error.context["status_code"] == 401


class TestExceptionFormatting:
    """Test exception string formatting."""
    
    def test_error_with_multiple_context_items(self):
        """Test error formatting with multiple context items."""
        error = ScribeError(
            "Complex error",
            context={"a": 1, "b": "test", "c": True, "d": 3.14}
        )
        
        error_str = str(error)
        assert "Complex error" in error_str
        assert "a=1" in error_str
        assert "b=test" in error_str
        assert "c=True" in error_str
        assert "d=3.14" in error_str
    
    def test_error_with_empty_context(self):
        """Test error formatting with empty context dict."""
        error = ScribeError("Simple error", context={})
        assert str(error) == "Simple error"
    
    def test_error_repr(self):
        """Test error repr includes class name."""
        error = ValidationError("Test error")
        assert "ValidationError" in repr(error)


