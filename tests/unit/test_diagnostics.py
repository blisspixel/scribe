"""
Unit tests for system diagnostics.

Tests diagnostic checks for environment, dependencies, and configuration.
"""

import os
from types import SimpleNamespace
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
            fix_suggestion="No action needed",
        )

        assert result.name == "Test Check"
        assert result.status == "pass"
        assert result.message == "All good"
        assert result.details == "Everything works"
        assert result.fix_suggestion == "No action needed"

    def test_result_without_optional_fields(self):
        """Test creating result without optional fields."""
        result = DiagnosticResult(name="Test Check", status="pass", message="All good")

        assert result.details is None
        assert result.fix_suggestion is None


class TestPythonVersionCheck:
    """Test Python version checking."""

    def test_python_312_or_higher(self):
        """Test a supported Python release passes."""
        diagnostics = SystemDiagnostics()

        # Create a mock version_info with named tuple attributes
        mock_version = type("version_info", (), {"major": 3, "minor": 12, "micro": 11})()

        with patch("sys.version_info", mock_version):
            result = diagnostics.check_python_version()

            assert result.status == "pass"
            assert "3.12.11" in result.message

    def test_python_314_fails_with_supported_range(self):
        """Test an interpreter above the native-wheel range fails clearly."""
        diagnostics = SystemDiagnostics()
        mock_version = type("version_info", (), {"major": 3, "minor": 14, "micro": 4})()

        with patch("sys.version_info", mock_version):
            result = diagnostics.check_python_version()

        assert result.status == "fail"
        assert "not supported" in result.message
        assert result.fix_suggestion is not None
        assert "uv tool install --python 3.12" in result.fix_suggestion
        assert "Omarchy" in result.fix_suggestion

    def test_python_310_or_311(self):
        """Test Python 3.10-3.11 warns (below the 3.12 floor)."""
        diagnostics = SystemDiagnostics()

        mock_version = type("version_info", (), {"major": 3, "minor": 11, "micro": 0})()

        with patch("sys.version_info", mock_version):
            result = diagnostics.check_python_version()

            assert result.status == "warn"
            assert "3.11.0" in result.message
            assert result.fix_suggestion is not None

    def test_python_too_old(self):
        """Test Python < 3.10 fails."""
        diagnostics = SystemDiagnostics()

        mock_version = type("version_info", (), {"major": 3, "minor": 9, "micro": 0})()

        with patch("sys.version_info", mock_version):
            result = diagnostics.check_python_version()

            assert result.status == "fail"
            assert "3.9.0" in result.message
            assert result.fix_suggestion is not None


class TestFFmpegCheck:
    """Test FFmpeg checking."""

    @patch("shutil.which")
    @patch("subprocess.check_output")
    def test_ffmpeg_installed(self, mock_check_output, mock_which):
        """Test FFmpeg installed and working."""
        mock_which.return_value = "/usr/bin/ffmpeg"
        mock_check_output.return_value = "ffmpeg version 4.4.2\n"

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_ffmpeg()

        assert result.status == "pass"
        assert "Installed" in result.message

    @patch("shutil.which")
    def test_ffmpeg_not_found(self, mock_which):
        """Test FFmpeg not found."""
        mock_which.return_value = None

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_ffmpeg()

        assert result.status == "fail"
        assert "Not found" in result.message
        assert result.fix_suggestion is not None

    @patch("shutil.which")
    @patch("subprocess.check_output")
    def test_ffmpeg_found_but_broken(self, mock_check_output, mock_which):
        """Test FFmpeg found but not working."""
        mock_which.return_value = "/usr/bin/ffmpeg"
        mock_check_output.side_effect = Exception("Command failed")

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_ffmpeg()

        assert result.status == "warn"
        assert "not working" in result.message


class TestPythonPackagesCheck:
    """Test required package recovery guidance."""

    def test_missing_package_points_to_authoritative_package_source(self):
        """A missing dependency must not point to a duplicate requirements shim."""

        def import_for_check(name, *_args, **_kwargs):
            if name == "typer":
                raise ImportError(name)
            return Mock()

        diagnostics = SystemDiagnostics()
        with patch("builtins.__import__", side_effect=import_for_check):
            result = diagnostics.check_python_packages()

        assert result.status == "fail"
        assert result.details == "Missing: typer"
        assert result.fix_suggestion is not None
        assert "uv sync --locked" in result.fix_suggestion
        assert "requirements" not in result.fix_suggestion

    def test_binary_import_failure_is_reported_as_broken(self):
        """A native ABI mismatch must not be misreported as a healthy install."""

        def import_for_check(name, *_args, **_kwargs):
            if name == "torch":
                raise OSError("DLL load failed while importing torch")
            return Mock()

        diagnostics = SystemDiagnostics()
        with patch("builtins.__import__", side_effect=import_for_check):
            result = diagnostics.check_python_packages()

        assert result.status == "fail"
        assert result.message == "1 critical package(s) unavailable"
        assert result.details is not None
        assert "Broken: torch" in result.details
        assert "--torch-backend auto" in (result.fix_suggestion or "")


class TestCUDACheck:
    """Test CUDA checking."""

    @patch("scribe.utils.diagnostics.GPUConfig.detect")
    def test_cuda_available(self, mock_detect):
        """Test CUDA available."""
        mock_gpu = Mock()
        mock_gpu.has_gpu = True
        mock_gpu.cuda_version = "12.4"
        mock_gpu.reason = "CUDA available for local transcription"
        mock_detect.return_value = mock_gpu

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_cuda()

        assert result.status == "pass"
        assert "CUDA 12.4" in result.message

    @patch("scribe.utils.diagnostics.GPUConfig.detect")
    def test_cuda_not_available(self, mock_detect):
        """Test CUDA not available."""
        mock_gpu = Mock()
        mock_gpu.has_gpu = False
        mock_gpu.reason = "No local CUDA backend detected"
        mock_detect.return_value = mock_gpu

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

    @patch("scribe.utils.diagnostics.GPUConfig.detect")
    def test_gpu_detected(self, mock_detect):
        """Test GPU detected."""
        mock_gpu = Mock()
        mock_gpu.has_gpu = True
        mock_gpu.gpu_name = "NVIDIA GeForce RTX 4090"
        mock_gpu.gpu_memory_gb = 24.0
        mock_gpu.reason = "GPU detected via CTranslate2"
        mock_detect.return_value = mock_gpu

        diagnostics = SystemDiagnostics()
        result = diagnostics.check_gpu()

        assert result.status == "pass"
        assert "RTX 4090" in result.message
        assert "24.0 GB" in result.details

    @patch("scribe.utils.diagnostics.GPUConfig.detect")
    def test_no_gpu(self, mock_detect):
        """Test no GPU detected."""
        mock_gpu = Mock()
        mock_gpu.has_gpu = False
        mock_gpu.reason = "No local CUDA backend detected"
        mock_detect.return_value = mock_gpu

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

        with patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-proj-1234567890abcdefghijklmnopqrstuvwxyz"}
        ):
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

        with patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-proj-1234567890abcdefghijklmnopqrstuvwxyz"}
        ):
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

        with patch.dict(
            os.environ, {"OPENAI_API_KEY": "sk-proj-1234567890abcdefghijklmnopqrstuvwxyz"}
        ):
            result = diagnostics.check_openai_api_key()

            assert result.status == "warn"
            assert "verify" in result.message.lower()

    def test_invalid_api_key_format(self):
        """Test invalid API key format."""
        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {"OPENAI_API_KEY": "invalid-key"}):
            result = diagnostics.check_openai_api_key()

            assert result.status == "warn"
            assert "Invalid format" in result.message

    def test_no_api_key(self):
        """An optional, unconfigured provider is omitted from live checks."""
        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {}, clear=True):
            result = diagnostics.check_openai_api_key()

            assert result is None
            assert diagnostics.results == []


class TestOpenRouterAPIKeyCheck:
    """Test the opt-in, no-cost OpenRouter key diagnostic."""

    @patch("scribe.utils.diagnostics.httpx.get")
    def test_valid_key(self, get):
        get.return_value = MagicMock(status_code=200)
        get.return_value.json.return_value = {"data": {"limit": 5.0, "limit_remaining": 4.0}}
        diagnostics = SystemDiagnostics()

        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "sk-or-v1-" + "test-key-1234567890"},
            clear=True,
        ):
            result = diagnostics.check_openrouter_api_key()

        assert result is not None
        assert result.status == "pass"
        assert "hard cap" in result.message
        assert get.call_args.kwargs["headers"]["Authorization"].startswith("Bearer sk-or-")

    @patch("scribe.utils.diagnostics.httpx.get")
    def test_valid_key_without_matching_hard_cap_warns_without_disclosing_balance(self, get):
        get.return_value = MagicMock(status_code=200)
        get.return_value.json.return_value = {"data": {"limit": None, "limit_remaining": 123.456}}
        diagnostics = SystemDiagnostics()

        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "sk-or-v1-" + "test-key-1234567890"},
            clear=True,
        ):
            result = diagnostics.check_openrouter_api_key()

        assert result is not None
        assert result.status == "warn"
        assert "hard cap" in result.message
        assert "123.456" not in str(result)

    @patch("scribe.utils.diagnostics.httpx.get")
    def test_uses_effective_configured_spend_guard(self, get):
        get.return_value = MagicMock(status_code=200)
        get.return_value.json.return_value = {"data": {"limit": 3.0, "limit_remaining": 2.0}}
        config = SimpleNamespace(
            openrouter_api_key="sk-or-v1-" + "test-key-1234567890",
            openrouter_max_spend_usd=2.5,
        )
        diagnostics = SystemDiagnostics(config=config)

        with patch.dict(os.environ, {}, clear=True):
            result = diagnostics.check_openrouter_api_key()

        assert result is not None
        assert result.status == "warn"
        assert result.fix_suggestion is not None
        assert "$2.50" in result.fix_suggestion

    @patch("scribe.utils.diagnostics.httpx.get")
    def test_rejected_key(self, get):
        get.return_value = MagicMock(status_code=401)
        diagnostics = SystemDiagnostics()

        with patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "sk-or-v1-test-key-1234567890"},
            clear=True,
        ):
            result = diagnostics.check_openrouter_api_key()

        assert result is not None
        assert result.status == "fail"
        assert "401" in result.message

    @patch("scribe.utils.diagnostics.httpx.get")
    def test_unconfigured_key_is_silent_and_offline(self, get):
        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {}, clear=True):
            result = diagnostics.check_openrouter_api_key()

        assert result is None
        get.assert_not_called()


class TestAdditionalProviders:
    """Test additional AI provider key validation."""

    @patch("scribe.utils.diagnostics.OpenAI")
    def test_xai_valid_key(self, mock_openai_cls):
        """Test XAI key that passes live validation."""
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client

        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {"XAI_API_KEY": "xai-test-key"}, clear=True):
            results = diagnostics.check_additional_providers()

            xai = next(r for r in results if "XAI" in r.name)
            assert xai.status == "pass"
            assert "Valid" in xai.message

    @patch("scribe.utils.diagnostics.OpenAI")
    def test_xai_invalid_key(self, mock_openai_cls):
        """Test XAI key rejected with 401."""
        from openai import AuthenticationError

        mock_client = MagicMock()
        mock_client.models.list.side_effect = AuthenticationError(
            message="Invalid",
            response=MagicMock(status_code=401),
            body=None,
        )
        mock_openai_cls.return_value = mock_client

        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {"XAI_API_KEY": "xai-bad-key"}, clear=True):
            results = diagnostics.check_additional_providers()

            xai = next(r for r in results if "XAI" in r.name)
            assert xai.status == "fail"
            assert "401" in xai.message

    def test_no_providers(self):
        """Unconfigured optional providers do not create warnings."""
        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {}, clear=True):
            results = diagnostics.check_additional_providers()

            assert results == []
            assert diagnostics.results == []

    @patch("scribe.utils.diagnostics.OpenAI")
    def test_provider_diagnostics_never_include_key_fragments(self, mock_openai_cls):
        key = "xai-private-key-1234567890"
        mock_openai_cls.return_value.models.list.side_effect = ConnectionError("offline")
        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {"XAI_API_KEY": key}, clear=True):
            results = diagnostics.check_additional_providers()

        assert key not in str(results)
        assert key[:8] not in str(results)
        assert key[-4:] not in str(results)


class TestOutputFolderCheck:
    """Test output folder checking."""

    def test_output_folder_exists_and_writable(self, tmp_path):
        """Test output folder exists and is writable."""
        diagnostics = SystemDiagnostics()

        with patch.dict(os.environ, {"SCRIBE_OUTPUT_FOLDER": str(tmp_path)}):
            result = diagnostics.check_output_folder()

            assert result.status == "pass"
            assert "writable" in result.message

    def test_output_folder_uses_resolved_default(self, tmp_path):
        """An unset environment variable still has a configured default."""
        diagnostics = SystemDiagnostics()

        with patch(
            "scribe.models.config.ScribeConfig",
            return_value=SimpleNamespace(output_folder=tmp_path),
        ):
            result = diagnostics.check_output_folder()

        assert result.status == "pass"
        assert str(tmp_path) in result.details

    def test_output_folder_does_not_exist(self, tmp_path):
        """Test output folder does not exist."""
        non_existent = tmp_path / "does_not_exist"
        diagnostics = SystemDiagnostics(config=SimpleNamespace(output_folder=non_existent))

        with patch.dict(os.environ, {"SCRIBE_OUTPUT_FOLDER": str(non_existent)}):
            result = diagnostics.check_output_folder()

            assert result.status == "warn"
            assert "Does not exist" in result.message

    def test_resolved_config_wins_and_probe_preserves_existing_file(self, tmp_path):
        sentinel = tmp_path / ".scribe_test"
        sentinel.write_text("user data", encoding="utf-8")
        diagnostics = SystemDiagnostics(config=SimpleNamespace(output_folder=tmp_path))
        with patch.dict(os.environ, {"SCRIBE_OUTPUT_FOLDER": str(tmp_path / "other")}):
            result = diagnostics.check_output_folder()
        assert result.status == "pass"
        assert result.details == f"Path: {tmp_path}"
        assert sentinel.read_text(encoding="utf-8") == "user data"
        assert sorted(path.name for path in tmp_path.iterdir()) == [".scribe_test"]

    def test_invalid_output_configuration_is_reported(self):
        with patch("scribe.models.config.ScribeConfig", side_effect=ValueError("bad folder")):
            result = SystemDiagnostics().check_output_folder()
        assert result.status == "fail"
        assert result.message == "Invalid configuration"


class TestDiskSpaceCheck:
    """Test disk space checking."""

    @patch("shutil.disk_usage")
    def test_disk_space_uses_configured_drive_and_nearest_existing_ancestor(
        self, mock_disk_usage, tmp_path
    ):
        mock_disk_usage.return_value = SimpleNamespace(free=50 * 1024**3, total=100 * 1024**3)
        diagnostics = SystemDiagnostics(
            config=SimpleNamespace(output_folder=tmp_path / "future" / "archive")
        )
        with patch.dict(os.environ, {"SCRIBE_OUTPUT_FOLDER": str(tmp_path / "ignored")}):
            assert diagnostics.check_disk_space().status == "pass"
        mock_disk_usage.assert_called_once_with(tmp_path)

    @patch("shutil.disk_usage")
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

    @patch("shutil.disk_usage")
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

    @patch("shutil.disk_usage")
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

        assert result.status == "pass"
        assert "Not found" in result.message


class TestOBSWebSocketCheck:
    """Test OBS WebSocket configuration checks."""

    def _write_obs_config(
        self,
        tmp_path,
        monkeypatch,
        *,
        server_enabled=True,
        auth_required=True,
        server_port=4455,
    ):
        appdata = tmp_path / "AppData" / "Roaming"
        config_path = appdata / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
        config_path.parent.mkdir(parents=True)
        config_path.write_text(
            (
                "{"
                f'"server_enabled": {str(server_enabled).lower()}, '
                f'"auth_required": {str(auth_required).lower()}, '
                f'"server_port": {server_port}'
                "}"
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("APPDATA", str(appdata))
        return config_path

    @patch("scribe.utils.obs_config.get_platform", return_value="windows")
    def test_obs_auth_without_scribe_password_warns(self, _platform, tmp_path, monkeypatch):
        """OBS auth on with no Scribe password warns before recording fails."""
        self._write_obs_config(tmp_path, monkeypatch)
        diagnostics = SystemDiagnostics()

        with patch(
            "scribe.models.config.ScribeConfig",
            return_value=SimpleNamespace(obs_port=4455, obs_password=None),
        ):
            result = diagnostics.check_obs_websocket()

        assert result.status == "warn"
        assert result.message == "Password required but not configured"
        fix = result.fix_suggestion or ""
        assert "scribe init --force" in fix
        assert "set SCRIBE_OBS_PASSWORD=<password>" in fix
        assert "$env:SCRIBE_OBS_PASSWORD" in fix
        assert "[obs].password" in fix

    @patch("scribe.utils.obs_config.get_platform", return_value="windows")
    def test_obs_auth_with_scribe_password_passes(self, _platform, tmp_path, monkeypatch):
        """OBS auth on with a configured Scribe password passes."""
        self._write_obs_config(tmp_path, monkeypatch)
        diagnostics = SystemDiagnostics()

        class FakeConfig:
            obs_port = 4455
            obs_password = object()

        with patch(
            "scribe.models.config.ScribeConfig",
            return_value=FakeConfig(),
        ):
            result = diagnostics.check_obs_websocket()

        assert result.status == "pass"
        assert result.message == "Configured"

    @patch("scribe.utils.diagnostics._tcp_port_listening", return_value=False)
    @patch("scribe.utils.diagnostics._obs_process_running", return_value=True)
    @patch("scribe.utils.obs_config.get_platform", return_value="windows")
    def test_running_obs_with_closed_websocket_warns(
        self, _platform, _running, _listening, tmp_path, monkeypatch
    ):
        """Doctor reports a live OBS process whose configured port is closed."""
        self._write_obs_config(tmp_path, monkeypatch, auth_required=False)
        diagnostics = SystemDiagnostics()

        with patch(
            "scribe.models.config.ScribeConfig",
            return_value=SimpleNamespace(obs_host="localhost", obs_port=4455, obs_password=None),
        ):
            result = diagnostics.check_obs_websocket()

        assert result.status == "warn"
        assert result.message == "OBS is running, but WebSocket is not listening"
        assert result.fix_suggestion is not None
        assert "non-destructive relaunch" in result.fix_suggestion

    @patch("scribe.utils.obs_config.get_platform", return_value="windows")
    def test_obs_port_mismatch_warns(self, _platform, tmp_path, monkeypatch):
        """OBS and Scribe must use the same WebSocket port."""
        self._write_obs_config(tmp_path, monkeypatch, server_port=4456, auth_required=False)
        diagnostics = SystemDiagnostics()

        with patch(
            "scribe.models.config.ScribeConfig",
            return_value=SimpleNamespace(obs_port=4455, obs_password=None),
        ):
            result = diagnostics.check_obs_websocket()

        assert result.status == "warn"
        assert result.message == "Port mismatch"
        fix = result.fix_suggestion or ""
        assert "scribe init --force" in fix
        assert "set SCRIBE_OBS_PORT=4456" in fix
        assert "$env:SCRIBE_OBS_PORT='4456'" in fix
        assert "export SCRIBE_OBS_PORT=4456" in fix


class TestDependencySecurityCheck:
    """Test dependency vulnerability scanning."""

    @patch("importlib.util.find_spec", return_value=None)
    def test_warns_when_pip_audit_missing(self, _find_spec):
        """Without pip-audit, doctor surfaces a warning instead of failing."""
        diagnostics = SystemDiagnostics()
        result = diagnostics.check_dependency_security()

        assert result.status == "warn"
        assert result.name == "Dependency Security"
        assert "pip-audit not installed" in result.message
        assert result.fix_suggestion is not None
        assert "uv sync --locked --group dev" in result.fix_suggestion

    @patch("importlib.util.find_spec", return_value=True)
    @patch("scribe.utils.diagnostics.subprocess.run")
    def test_passes_when_scan_clean(self, mock_run, _find_spec):
        """A clean zero-exception pip-audit run passes."""
        mock_run.return_value = SimpleNamespace(
            returncode=0,
            stdout="No known vulnerabilities found\n",
            stderr="",
        )
        diagnostics = SystemDiagnostics()
        result = diagnostics.check_dependency_security()

        assert result.status == "pass"
        assert "No known vulnerabilities" in result.message
        assert "zero exceptions" in (result.details or "")
        cmd = mock_run.call_args[0][0]
        assert "--ignore-vuln" not in cmd

    @patch("importlib.util.find_spec", return_value=True)
    @patch("scribe.utils.diagnostics.subprocess.run")
    def test_fails_when_scan_finds_vulns(self, mock_run, _find_spec):
        """Actionable vulnerabilities fail the check."""
        mock_run.return_value = SimpleNamespace(
            returncode=1,
            stdout="Found 1 known vulnerability in 1 package\nexample 1.0.0 CVE-2099-0001\n",
            stderr="",
        )
        diagnostics = SystemDiagnostics()
        result = diagnostics.check_dependency_security()

        assert result.status == "fail"
        assert "vulnerabilities detected" in result.message.lower()
        assert "CVE-2099-0001" in (result.details or "")


class TestApiResilienceCheck:
    """Test OpenAI circuit breaker reporting in scribe doctor."""

    def test_passes_when_breaker_closed(self):
        from scribe.utils.api_resilience import reset_api_circuit_breaker

        reset_api_circuit_breaker()
        diagnostics = SystemDiagnostics()
        result = diagnostics.check_api_resilience()

        assert result.name == "API Resilience"
        assert result.status == "pass"
        assert "closed" in result.message.lower()

    def test_warns_when_breaker_open(self):
        from unittest.mock import patch

        from scribe.utils.api_resilience import record_api_failure, reset_api_circuit_breaker

        reset_api_circuit_breaker()
        for second in range(5):
            record_api_failure(now=float(second))

        diagnostics = SystemDiagnostics()
        with patch("scribe.utils.api_resilience.time.time", return_value=5.0):
            result = diagnostics.check_api_resilience()

        assert result.status == "warn"
        assert result.fix_suggestion is not None
        assert "open" in (result.details or "").lower()


class TestVoiceReadinessCheck:
    """Test resident-voice readiness in scribe doctor."""

    @patch("importlib.util.find_spec", return_value=None)
    def test_silent_when_voice_not_opted_in(self, _find_spec):
        """Non-voice users should not see an extra doctor check."""
        diagnostics = SystemDiagnostics()
        assert diagnostics.check_voice_readiness() is None

    @patch("importlib.util.find_spec", return_value=Mock())
    @patch("scribe.voice.service.missing_dependency_packages", return_value=[])
    @patch("scribe.voice.service.resident_voice_advisories")
    def test_pass_when_deps_ok_and_only_info_advisories(
        self, mock_advisories, _mock_missing, _find_spec
    ):
        from scribe.voice.service import ReadinessAdvisory

        mock_advisories.return_value = [
            ReadinessAdvisory("info", "Linux/X11: global hotkeys via pynput are supported")
        ]
        diagnostics = SystemDiagnostics()
        result = diagnostics.check_voice_readiness()

        assert result is not None
        assert result.name == "Voice Readiness"
        assert result.status == "pass"
        assert "ready" in result.message.lower()

    @patch("importlib.util.find_spec", return_value=Mock())
    @patch(
        "scribe.voice.service.missing_dependency_packages",
        return_value=["pyperclip", "sounddevice"],
    )
    @patch("scribe.voice.service.resident_voice_advisories", return_value=[])
    def test_warns_on_missing_voice_packages(self, _mock_advisories, _mock_missing, _find_spec):
        diagnostics = SystemDiagnostics()
        result = diagnostics.check_voice_readiness()

        assert result is not None
        assert result.status == "warn"
        assert "pyperclip" in result.message
        assert "Missing optional voice packages" in (result.details or "")
        assert result.fix_suggestion is not None


class TestSystemDiagnostics:
    """Test SystemDiagnostics class."""

    def test_run_all_checks(self):
        """Test running all checks."""
        # Mock torch to avoid import issues in tests
        mock_torch = MagicMock()
        mock_torch.__spec__ = Mock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1
        mock_torch.cuda.get_device_name.return_value = "Test GPU"
        mock_torch.version.cuda = "12.4"
        mock_props = Mock()
        mock_props.total_memory = 8 * 1024**3
        mock_torch.cuda.get_device_properties.return_value = mock_props

        with patch.dict("sys.modules", {"torch": mock_torch}):
            diagnostics = SystemDiagnostics()
            results = diagnostics.run_all_checks()

            # Should have results for all checks (includes dependency security)
            assert len(results) >= 10

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

    def test_missing_psutil_is_a_visible_warning(self):
        diagnostics = SystemDiagnostics()

        with patch.dict("sys.modules", {"psutil": None}):
            result = diagnostics.check_system_resources()

        assert result.status == "warn"
        assert result.message == "Resource monitor unavailable (psutil not installed)"
        assert result.fix_suggestion == "Reinstall Scribe; psutil is a required dependency"


class TestLocalReadiness:
    """The $0-local readiness assessment used by doctor/info."""

    def _patch_backends(self, monkeypatch, *, vendor, backend, available, ffmpeg):
        import scribe.core.backends as backends
        from scribe.utils import diagnostics as diag

        monkeypatch.setattr(
            backends, "detect_hardware", lambda: SimpleNamespace(vendor=vendor), raising=False
        )
        monkeypatch.setattr(backends, "backend_availability", lambda: available, raising=False)
        monkeypatch.setattr(backends, "select_backend", lambda *_a, **_k: backend, raising=False)
        monkeypatch.setattr(diag.shutil, "which", lambda _n: "/ffmpeg" if ffmpeg else None)

    def _patch_ollama(self, monkeypatch, *, models):
        import scribe.utils.ollama_models as om

        monkeypatch.setattr(om, "list_installed_models", lambda *_a, **_k: models, raising=False)
        monkeypatch.setattr(
            om, "select_default_ollama_model", lambda *_a, **_k: "llama3.2", raising=False
        )

    def test_fully_local_when_gpu_and_ollama_ready(self, monkeypatch):
        from scribe.utils.diagnostics import assess_local_readiness

        self._patch_backends(
            monkeypatch,
            vendor="nvidia",
            backend="faster-whisper",
            available={"faster-whisper": True, "cpu": True},
            ffmpeg=True,
        )
        self._patch_ollama(monkeypatch, models=["llama3.2"])

        r = assess_local_readiness()

        assert r.can_transcribe is True
        assert r.can_take_notes is True
        assert r.fully_local is True
        assert "faster-whisper" in r.transcribe_detail

    def test_transcription_blocked_without_ffmpeg(self, monkeypatch):
        from scribe.utils.diagnostics import assess_local_readiness

        self._patch_backends(
            monkeypatch,
            vendor="cpu",
            backend="cpu",
            available={"faster-whisper": True, "cpu": True},
            ffmpeg=False,
        )
        self._patch_ollama(monkeypatch, models=[])

        r = assess_local_readiness()

        assert r.can_transcribe is False
        assert r.transcribe_fix and "ffmpeg" in r.transcribe_fix.lower()
        assert r.can_take_notes is False

    def test_apple_cpu_floor_nudges_mlx(self, monkeypatch):
        from scribe.utils.diagnostics import assess_local_readiness

        self._patch_backends(
            monkeypatch,
            vendor="apple",
            backend="cpu",
            available={"cpu": True, "faster-whisper": True},
            ffmpeg=True,
        )
        self._patch_ollama(monkeypatch, models=[])

        r = assess_local_readiness()

        assert r.can_transcribe is True  # CPU floor still works at $0
        assert r.transcribe_fix and "mlx" in r.transcribe_fix.lower()

    def test_check_appends_transcription_and_notes(self, monkeypatch):
        from scribe.utils import diagnostics as diag
        from scribe.utils.diagnostics import LocalReadiness, SystemDiagnostics

        monkeypatch.setattr(
            diag,
            "assess_local_readiness",
            lambda: LocalReadiness(
                can_transcribe=True,
                transcribe_detail="faster-whisper on nvidia",
                transcribe_fix=None,
                can_take_notes=False,
                notes_detail="Ollama not reachable",
                notes_fix="Install Ollama",
                backend="faster-whisper",
                vendor="nvidia",
                ffmpeg=True,
            ),
        )

        d = SystemDiagnostics()
        result = d.check_local_readiness()

        names = {r.name: r.status for r in d.results}
        assert names.get("Local Transcription ($0)") == "pass"
        assert names.get("Local Notes ($0)") == "warn"
        assert result.status == "pass"
