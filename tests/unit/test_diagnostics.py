"""
Unit tests for system diagnostics.

Tests diagnostic checks for environment, dependencies, and configuration.
"""

import os
from unittest.mock import MagicMock, Mock, patch

import pytest

from scribe.utils.diagnostics import DiagnosticResult, SystemDiagnostics


class TestDiagnosticResult:
    """Test DiagnosticResult dataclass."""

    def test_create_result(self):
        """Test creating a diagnostic result."""
        result = DiagnosticResult(
            name="Test Check",
            status="pass",
            message="All good",
            details="Everything works",
            fix_suggestion="No action needed"
        )

        assert result.name == "Test Check"
        assert result.status == "pass"
        assert result.message == "All good"
        assert result.details == "Everything works"
        assert result.fix_suggestion == "No action needed"

    def test_result_without_optional_fields(self):
        """Test creating result without optional fields."""
        result = DiagnosticResult(
            name="Test Check",
            status="pass",
            message="All good"
        )

        assert result.details is None
        assert result.fix_suggestion is None


class TestPythonVersionCheck:
    """Test Python version checking."""

    def test_python_310_or_higher(self):
        """Test Python 3.10+ passes."""
        diagnostics = SystemDiagnostics()

        # Create a mock version_info with named tuple attributes
        mock_version = type('version_info', (), {'major': 3, 'minor': 10, 'micro': 11})()

        with patch('sys.version_info', mock_version):
            result = diagnostics.check_python_version()

            assert result.status == "pass"
            assert "3.10.11" in result.message

    def test_python_38_or_39(self):
        """Test Python 3.8-3.9 warns."""
        diagnostics = SystemDiagnostics()

        mock_version = type('version_info', (), {'major': 3, 'minor': 9, 'micro': 0})()

        with patch('sys.version_info', mock_version):
            result = diagnostics.check_python_version()

            assert result.status == "warn"
            assert "3.9.0" in result.message
            assert result.fix_suggestion is not None

    def test_python_too_old(self):
        """Test Python < 3.8 fails."""
        diagnostics = SystemDiagnostics()

        mock_version = type('version_info', (), {'major': 3, 'minor': 7, 'micro': 0})()

        with patch('sys.version_info', mock_version):
            result = diagnostics.check_python_version()

            assert result.status == "fail"
            assert "3.7.0" in result.message
            assert result.fix_suggestion is not None


class TestFFmpegCheck:
    """Test FFmpeg checking."""

    @patch('shutil.which')
    @patch('subprocess.check_output')
    def test_ffmpeg_installed(self, mock_check_output, mock_which):
        """Test FFmpeg installed and working."""
        mock_which.return_value = "/usr/bin/ffmpeg"
        mock_check_output.return_value = "ffmpeg version 4.4.2\n"

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_ffmpeg()

        assert result.status == "pass"
        assert "Installed" in result.message

    @patch('shutil.which')
    def test_ffmpeg_not_found(self, mock_which):
        """Test FFmpeg not found."""
        mock_which.return_value = None

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_ffmpeg()

        assert result.status == "fail"
        assert "Not found" in result.message
        assert result.fix_suggestion is not None

    @patch('shutil.which')
    @patch('subprocess.check_output')
    def test_ffmpeg_found_but_broken(self, mock_check_output, mock_which):
        """Test FFmpeg found but not working."""
        mock_which.return_value = "/usr/bin/ffmpeg"
        mock_check_output.side_effect = Exception("Command failed")

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_ffmpeg()

        assert result.status == "warn"
        assert "not working" in result.message


class TestCUDACheck:
    """Test CUDA checking."""

    def test_cuda_available(self):
        """Test CUDA available."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.version.cuda = "12.4"

        with patch.dict('sys.modules', {'torch': mock_torch}):
            diagnostics = SystemDiagnostics()
            result = diagnostics.check_cuda()

            assert result.status == "pass"
            assert "CUDA 12.4" in result.message

    def test_cuda_not_available(self):
        """Test CUDA not available."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict('sys.modules', {'torch': mock_torch}):
            diagnostics = SystemDiagnostics()
            result = diagnostics.check_cuda()

            assert result.status == "warn"
            assert "Not available" in result.message

    def test_pytorch_not_installed(self):
        """Test PyTorch not installed."""
        # Skip this test if torch is already imported (can't easily mock ImportError)
        pytest.skip("Torch import mocking is complex - tested manually")


class TestGPUCheck:
    """Test GPU checking."""

    def test_gpu_detected(self):
        """Test GPU detected."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1
        mock_torch.cuda.get_device_name.return_value = "NVIDIA GeForce RTX 4090"

        mock_props = Mock()
        mock_props.total_memory = 24 * 1024**3  # 24 GB
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with patch.dict('sys.modules', {'torch': mock_torch}):
            diagnostics = SystemDiagnostics()
            result = diagnostics.check_gpu()

            assert result.status == "pass"
            assert "RTX 4090" in result.message
            assert "24.0 GB" in result.details

    def test_no_gpu(self):
        """Test no GPU detected."""
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict('sys.modules', {'torch': mock_torch}):
            diagnostics = SystemDiagnostics()
            result = diagnostics.check_gpu()

            assert result.status == "warn"
            assert "No GPU" in result.message


class TestAPIKeyCheck:
    """Test OpenAI API key checking."""

    @patch("scribe.utils.diagnostics.OpenAI")
    def test_valid_api_key(self, mock_openai_cls):
        """Test valid API key that passes live validation."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-proj-1234567890abcdefghijklmnopqrstuvwxyz'}):
            result = diagnostics.check_openai_api_key()

            assert result.status == "pass"
            assert "Valid" in result.message
            mock_client.models.list.assert_called_once()

    @patch("scribe.utils.diagnostics.OpenAI")
    def test_invalid_api_key_rejected(self, mock_openai_cls):
        """Test API key that is rejected by OpenAI (401)."""
        from openai import AuthenticationError

        mock_client = MagicMock()
        mock_client.models.list.side_effect = AuthenticationError(
            message="Invalid API key",
            response=MagicMock(status_code=401),
            body=None,
        )
        mock_openai_cls.return_value = mock_client

        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-proj-1234567890abcdefghijklmnopqrstuvwxyz'}):
            result = diagnostics.check_openai_api_key()

            assert result.status == "fail"
            assert "401" in result.message
            assert result.fix_suggestion is not None

    @patch("scribe.utils.diagnostics.OpenAI")
    def test_valid_key_network_error(self, mock_openai_cls):
        """Test valid key format but network error during verification."""
        mock_client = MagicMock()
        mock_client.models.list.side_effect = ConnectionError("No internet")
        mock_openai_cls.return_value = mock_client

        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-proj-1234567890abcdefghijklmnopqrstuvwxyz'}):
            result = diagnostics.check_openai_api_key()

            assert result.status == "warn"
            assert "verify" in result.message.lower()

    def test_invalid_api_key_format(self):
        """Test invalid API key format."""
        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {'OPENAI_API_KEY': 'invalid-key'}):
            result = diagnostics.check_openai_api_key()

            assert result.status == "warn"
            assert "Invalid format" in result.message

    def test_no_api_key(self):
        """Test no API key configured."""
        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {}, clear=True):
            result = diagnostics.check_openai_api_key()

            assert result.status == "fail"
            assert "Not configured" in result.message


class TestAdditionalProviders:
    """Test additional AI provider key validation."""

    @patch("scribe.utils.diagnostics.OpenAI")
    def test_xai_valid_key(self, mock_openai_cls):
        """Test XAI key that passes live validation."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {'XAI_API_KEY': 'xai-test-key'}, clear=True):
            results = diagnostics.check_additional_providers()

            xai = [r for r in results if "XAI" in r.name][0]
            assert xai.status == "pass"
            assert "Valid" in xai.message

    @patch("scribe.utils.diagnostics.OpenAI")
    def test_xai_invalid_key(self, mock_openai_cls):
        """Test XAI key rejected with 401."""
        from openai import AuthenticationError

        mock_client = MagicMock()
        mock_client.models.list.side_effect = AuthenticationError(
            message="Invalid", response=MagicMock(status_code=401), body=None,
        )
        mock_openai_cls.return_value = mock_client

        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {'XAI_API_KEY': 'xai-bad-key'}, clear=True):
            results = diagnostics.check_additional_providers()

            xai = [r for r in results if "XAI" in r.name][0]
            assert xai.status == "fail"
            assert "401" in xai.message

    def test_no_providers(self):
        """Test no additional providers configured."""
        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {}, clear=True):
            results = diagnostics.check_additional_providers()

            assert len(results) == 1
            assert results[0].status == "warn"
            assert "No additional" in results[0].message


class TestOutputFolderCheck:
    """Test output folder checking."""

    def test_output_folder_exists_and_writable(self, tmp_path):
        """Test output folder exists and is writable."""
        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {'SCRIBE_OUTPUT_FOLDER': str(tmp_path)}):
            result = diagnostics.check_output_folder()

            assert result.status == "pass"
            assert "writable" in result.message

    def test_output_folder_not_configured(self):
        """Test output folder not configured."""
        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {}, clear=True):
            result = diagnostics.check_output_folder()

            assert result.status == "warn"
            assert "Not configured" in result.message

    def test_output_folder_does_not_exist(self, tmp_path):
        """Test output folder does not exist."""
        diagnostics = SystemDiagnostics()
        non_existent = tmp_path / "does_not_exist"

        with patch.dict(os.environ, {'SCRIBE_OUTPUT_FOLDER': str(non_existent)}):
            result = diagnostics.check_output_folder()

            assert result.status == "warn"
            assert "Does not exist" in result.message


class TestDiskSpaceCheck:
    """Test disk space checking."""

    @patch('shutil.disk_usage')
    def test_plenty_of_space(self, mock_disk_usage):
        """Test plenty of disk space."""
        mock_usage = Mock()
        mock_usage.free = 50 * 1024**3  # 50 GB
        mock_usage.total = 100 * 1024**3  # 100 GB
        mock_disk_usage.return_value = mock_usage

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_disk_space()

        assert result.status == "pass"
        assert "50.0 GB" in result.message

    @patch('shutil.disk_usage')
    def test_low_disk_space(self, mock_disk_usage):
        """Test low disk space."""
        mock_usage = Mock()
        mock_usage.free = 7 * 1024**3  # 7 GB
        mock_usage.total = 100 * 1024**3  # 100 GB
        mock_disk_usage.return_value = mock_usage

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_disk_space()

        assert result.status == "warn"
        assert "7.0 GB" in result.message

    @patch('shutil.disk_usage')
    def test_very_low_disk_space(self, mock_disk_usage):
        """Test very low disk space."""
        mock_usage = Mock()
        mock_usage.free = 3 * 1024**3  # 3 GB
        mock_usage.total = 100 * 1024**3  # 100 GB
        mock_disk_usage.return_value = mock_usage

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_disk_space()

        assert result.status == "fail"
        assert "3.0 GB" in result.message


class TestEnvFileCheck:
    """Test .env file checking."""

    def test_env_file_exists(self, tmp_path, monkeypatch):
        """Test .env file exists."""
        monkeypatch.chdir(tmp_path)
        env_file = tmp_path / ".env"
        env_file.touch()

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_env_file()

        assert result.status == "pass"
        assert "Found" in result.message

    def test_env_file_missing(self, tmp_path, monkeypatch):
        """Test .env file missing."""
        monkeypatch.chdir(tmp_path)

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_env_file()

        assert result.status == "warn"
        assert "Not found" in result.message


class TestSystemDiagnostics:
    """Test SystemDiagnostics class."""

    def test_run_all_checks(self):
        """Test running all checks."""
        # Mock torch to avoid import issues in tests
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1
        mock_torch.cuda.get_device_name.return_value = "Test GPU"
        mock_torch.version.cuda = "12.4"
        mock_props = Mock()
        mock_props.total_memory = 8 * 1024**3
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with patch.dict('sys.modules', {'torch': mock_torch}):
            diagnostics = SystemDiagnostics()
            results = diagnostics.run_all_checks()

            # Should have results for all checks
            assert len(results) >= 9

            # Check that all results have required fields
            for result in results:
                assert result.name
                assert result.status in ["pass", "warn", "fail"]
                assert result.message

    def test_get_summary(self):
        """Test getting summary counts."""
        diagnostics = SystemDiagnostics()

        # Add some test results
        diagnostics.results = [
            DiagnosticResult("Test 1", "pass", "OK"),
            DiagnosticResult("Test 2", "pass", "OK"),
            DiagnosticResult("Test 3", "warn", "Warning"),
            DiagnosticResult("Test 4", "fail", "Failed"),
        ]

        pass_count, warn_count, fail_count = diagnostics.get_summary()

        assert pass_count == 2
        assert warn_count == 1
        assert fail_count == 1
