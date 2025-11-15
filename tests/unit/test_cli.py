"""
Unit tests for CLI commands.

Tests command-line interface including argument parsing,
command execution, and error handling.
"""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call
from typer.testing import CliRunner
from scribe.cli.main import app
from scribe.exceptions import ScribeError, ValidationError


@pytest.fixture
def cli_runner():
    """Create CLI test runner."""
    return CliRunner()


@pytest.fixture
def mock_config():
    """Mock ScribeConfig."""
    config = Mock()
    config.output_folder = Path("/test/output")
    config.log_folder = Path("/test/logs")
    config.default_model = "large-v3"
    config.default_language = "en"
    config.default_method = "auto"
    config.openai_api_key = "sk-test-key"
    config.keep_intermediate_files = False
    return config


class TestCLIHelp:
    """Test CLI help and version commands."""
    
    def test_main_help(self, cli_runner):
        """Test main help command shows available commands."""
        result = cli_runner.invoke(app, ["--help"])
        
        assert result.exit_code == 0
        assert "transcribe" in result.stdout
        assert "record" in result.stdout
        assert "joke" in result.stdout
        assert "info" in result.stdout
        assert "version" in result.stdout
    
    def test_transcribe_help(self, cli_runner):
        """Test transcribe command help."""
        result = cli_runner.invoke(app, ["transcribe", "--help"])
        
        assert result.exit_code == 0
        assert "audio" in result.stdout.lower() or "video" in result.stdout.lower()
        assert "--method" in result.stdout
        assert "--model" in result.stdout
        assert "--language" in result.stdout
        assert "--no-joke" in result.stdout
    
    def test_record_help(self, cli_runner):
        """Test record command help."""
        result = cli_runner.invoke(app, ["record", "--help"])
        
        assert result.exit_code == 0
        assert "--name" in result.stdout
    
    def test_joke_help(self, cli_runner):
        """Test joke command help."""
        result = cli_runner.invoke(app, ["joke", "--help"])
        
        assert result.exit_code == 0
        assert "transcript" in result.stdout.lower()
    
    def test_info_help(self, cli_runner):
        """Test info command help."""
        result = cli_runner.invoke(app, ["info", "--help"])
        
        assert result.exit_code == 0
    
    def test_version_command(self, cli_runner):
        """Test version command shows version."""
        result = cli_runner.invoke(app, ["version"])
        
        assert result.exit_code == 0
        assert "Scribe" in result.stdout
        # Should show version number (format: X.Y.Z)


class TestTranscribeCommand:
    """Test transcribe command functionality."""
    
    def test_transcribe_missing_file(self, cli_runner):
        """Test transcribe with nonexistent file fails."""
        result = cli_runner.invoke(app, ["transcribe", "nonexistent.mp4"])
        
        assert result.exit_code != 0
    
    @patch('scribe.utils.audio.get_audio_duration')
    @patch('scribe.utils.unified_progress.UnifiedProgress')
    @patch('scribe.cli.main.txt_to_docx')
    @patch('scribe.cli.main.ScribeConfig')
    @patch('scribe.cli.main.Transcriber')
    @patch('scribe.cli.main.validate_file_path')
    @patch('scribe.cli.main.TranscriptionSession')
    @patch('scribe.cli.main.setup_logging')
    def test_transcribe_basic_flow(
        self, mock_logging, mock_session, mock_validate, 
        mock_transcriber_class, mock_config_class, mock_docx, mock_progress, mock_duration, cli_runner, tmp_path
    ):
        """Test basic transcribe command flow."""
        # Setup mocks
        test_file = tmp_path / "test.mp4"
        test_file.write_text("fake audio")
        
        mock_config = Mock()
        mock_config.output_folder = tmp_path
        mock_config.log_folder = tmp_path
        mock_config.openai_api_key = None  # Disable joke/meme/notes generation
        mock_config.keep_intermediate_files = False
        mock_config.enable_notes = False  # Disable notes
        mock_config_class.return_value = mock_config
        
        mock_validate.return_value = test_file
        
        mock_session_inst = Mock()
        mock_session_inst.add_file = Mock()
        mock_session_inst.complete = Mock()
        mock_session_inst.save_summary = Mock(return_value=None)
        mock_session_inst.docx_file = None
        mock_session_inst.meme_file = None
        mock_session_inst.joke_data = None
        mock_session_inst.__getitem__ = Mock(side_effect=KeyError)  # Make it not subscriptable
        mock_session.create.return_value = mock_session_inst
        
        transcript_path = tmp_path / "transcript.txt"
        transcript_path.write_text("Test transcript")
        
        mock_transcriber = Mock()
        mock_transcriber.choose_method.return_value = "openai"
        mock_transcriber.transcribe.return_value = transcript_path
        mock_transcriber.cleanup_intermediate_files.return_value = []
        mock_transcriber_class.return_value = mock_transcriber
        
        mock_duration.return_value = 600.0  # 10 minutes
        
        docx_path = tmp_path / "transcript.docx"
        mock_docx.return_value = docx_path
        
        # Mock unified progress
        mock_progress_inst = Mock()
        mock_progress.return_value = mock_progress_inst
        
        # Run command with flags to disable optional features
        result = cli_runner.invoke(app, ["transcribe", str(test_file), "--no-joke", "--no-notes", "--no-meme"])
        
        # Verify
        if result.exit_code != 0:
            print(f"STDOUT: {result.stdout}")
            print(f"STDERR: {result.stderr}")
            if result.exception:
                print(f"EXCEPTION: {result.exception}")
        assert result.exit_code == 0
        mock_transcriber.transcribe.assert_called_once()
    
    @patch('scribe.cli.main.ScribeConfig')
    def test_transcribe_with_method_option(self, mock_config_class, cli_runner, tmp_path):
        """Test transcribe with --method option."""
        test_file = tmp_path / "test.wav"
        test_file.write_text("fake audio")
        
        mock_config = Mock()
        mock_config.output_folder = tmp_path
        mock_config_class.return_value = mock_config
        
        result = cli_runner.invoke(app, ["transcribe", str(test_file), "--method", "local"])
        
        # Command should parse successfully (may fail on execution, that's OK)
        assert "--method" in str(result) or result.exit_code in [0, 1]
    
    @patch('scribe.cli.main.ScribeConfig')
    def test_transcribe_with_model_option(self, mock_config_class, cli_runner, tmp_path):
        """Test transcribe with --model option."""
        test_file = tmp_path / "test.wav"
        test_file.write_text("fake audio")
        
        result = cli_runner.invoke(app, ["transcribe", str(test_file), "--model", "medium"])
        
        # Command should parse successfully
        assert "--model" in str(result) or result.exit_code in [0, 1]
    
    @patch('scribe.cli.main.ScribeConfig')
    def test_transcribe_with_language_option(self, mock_config_class, cli_runner, tmp_path):
        """Test transcribe with --language option."""
        test_file = tmp_path / "test.wav"
        test_file.write_text("fake audio")
        
        result = cli_runner.invoke(app, ["transcribe", str(test_file), "--language", "es"])
        
        # Command should parse successfully
        assert "--language" in str(result) or result.exit_code in [0, 1]
    
    @patch('scribe.cli.main.ScribeConfig')
    def test_transcribe_with_no_joke_flag(self, mock_config_class, cli_runner, tmp_path):
        """Test transcribe with --no-joke flag."""
        test_file = tmp_path / "test.wav"
        test_file.write_text("fake audio")
        
        result = cli_runner.invoke(app, ["transcribe", str(test_file), "--no-joke"])
        
        # Command should parse successfully
        assert "--no-joke" in str(result) or result.exit_code in [0, 1]
    
    @patch('scribe.cli.main.ScribeConfig')
    def test_transcribe_with_keep_all_flag(self, mock_config_class, cli_runner, tmp_path):
        """Test transcribe with --keep-all flag."""
        test_file = tmp_path / "test.wav"
        test_file.write_text("fake audio")
        
        result = cli_runner.invoke(app, ["transcribe", str(test_file), "--keep-all"])
        
        # Command should parse successfully
        assert "--keep-all" in str(result) or result.exit_code in [0, 1]


class TestRecordCommand:
    """Test record command functionality."""
    
    def test_record_help_shows_options(self, cli_runner):
        """Test record command help shows all options."""
        result = cli_runner.invoke(app, ["record", "--help"])
        
        assert result.exit_code == 0
        assert "--name" in result.stdout
    
    @patch('scribe.cli.main.ScribeConfig')
    @patch('scribe.cli.main.OBSRecorder')
    def test_record_command_structure(self, mock_recorder_class, mock_config_class, cli_runner):
        """Test record command basic structure."""
        mock_config = Mock()
        mock_config.output_folder = Path("/test")
        mock_config_class.return_value = mock_config
        
        mock_recorder = Mock()
        mock_recorder_class.return_value = mock_recorder
        
        # Just test that command is recognized
        result = cli_runner.invoke(app, ["record", "--help"])
        assert result.exit_code == 0


class TestRecShortcut:
    """Test 'rec' shortcut command."""
    
    def test_rec_help(self, cli_runner):
        """Test rec shortcut help."""
        result = cli_runner.invoke(app, ["rec", "--help"])
        
        assert result.exit_code == 0
        assert "rec" in result.stdout.lower() or "record" in result.stdout.lower()
    
    def test_rec_without_name(self, cli_runner):
        """Test rec command without name argument."""
        # Should prompt or use default
        result = cli_runner.invoke(app, ["rec", "--help"])
        assert result.exit_code == 0
    
    def test_rec_with_name(self, cli_runner):
        """Test rec command with name argument."""
        result = cli_runner.invoke(app, ["rec", "Test Meeting", "--help"])
        assert result.exit_code == 0


class TestJokeCommand:
    """Test joke command functionality."""
    
    def test_joke_missing_file(self, cli_runner):
        """Test joke command with nonexistent file."""
        result = cli_runner.invoke(app, ["joke", "nonexistent.txt"])
        
        assert result.exit_code != 0
    
    def test_joke_invalid_file_type(self, cli_runner, tmp_path):
        """Test joke command with non-text file."""
        test_file = tmp_path / "test.mp4"
        test_file.write_text("fake content")
        
        result = cli_runner.invoke(app, ["joke", str(test_file)])
        
        assert result.exit_code != 0
        assert "text file" in result.stdout.lower()
    
    @patch('scribe.cli.main.ScribeConfig')
    @patch('scribe.cli.main.generate_transcript_joke')
    def test_joke_success(self, mock_generate, mock_config_class, cli_runner, tmp_path):
        """Test successful joke generation."""
        # Create test transcript
        test_file = tmp_path / "transcript.txt"
        test_file.write_text("Meeting transcript content")
        
        # Mock config
        mock_config = Mock()
        mock_config.openai_api_key = "sk-test-key"
        mock_config_class.return_value = mock_config
        
        # Mock joke generation
        mock_generate.return_value = ("Test joke", "trickster")
        
        result = cli_runner.invoke(app, ["joke", str(test_file)])
        
        assert result.exit_code == 0
        assert "Test joke" in result.stdout
        assert "Joke:" in result.stdout
    
    @patch('scribe.cli.main.ScribeConfig')
    def test_joke_no_api_key(self, mock_config_class, cli_runner, tmp_path):
        """Test joke command without API key."""
        test_file = tmp_path / "transcript.txt"
        test_file.write_text("Meeting transcript")
        
        mock_config = Mock()
        mock_config.openai_api_key = None
        mock_config_class.return_value = mock_config
        
        result = cli_runner.invoke(app, ["joke", str(test_file)])
        
        assert result.exit_code != 0
        assert "API key" in result.stdout
    
    @patch('scribe.cli.main.ScribeConfig')
    @patch('scribe.cli.main.generate_transcript_joke')
    def test_joke_generation_failure(self, mock_generate, mock_config_class, cli_runner, tmp_path):
        """Test joke command when generation fails."""
        test_file = tmp_path / "transcript.txt"
        test_file.write_text("Meeting transcript")
        
        mock_config = Mock()
        mock_config.openai_api_key = "sk-test-key"
        mock_config_class.return_value = mock_config
        
        # Mock generation failure
        mock_generate.return_value = None
        
        result = cli_runner.invoke(app, ["joke", str(test_file)])
        
        assert result.exit_code != 0
        assert "Failed" in result.stdout or "failed" in result.stdout


class TestInfoCommand:
    """Test info command functionality."""
    
    @patch('scribe.cli.main.ScribeConfig')
    @patch('scribe.cli.main.GPUConfig')
    def test_info_shows_system_information(self, mock_gpu_class, mock_config_class, cli_runner):
        """Test info command displays system information."""
        # Mock config
        mock_config = Mock()
        mock_config.output_folder = Path("/test/output")
        mock_config.default_model = "large-v3"
        mock_config.default_language = "en"
        mock_config.openai_api_key = "sk-test"
        mock_config.hf_token = None
        mock_config_class.return_value = mock_config
        
        # Mock GPU
        mock_gpu = Mock()
        mock_gpu.has_gpu = True
        mock_gpu.gpu_name = "NVIDIA RTX 4090"
        mock_gpu.gpu_memory_gb = 24.0
        mock_gpu.cuda_available = True
        mock_gpu.cuda_version = "12.4"
        mock_gpu.model_size = "large-v3"
        mock_gpu.beam_size = 10
        mock_gpu.use_fp16 = True
        mock_gpu.recommendation = "local"
        mock_gpu.reason = "RTX 4090 detected"
        mock_gpu.get_expected_speed = Mock(return_value="12.6x real-time")
        mock_gpu_class.detect.return_value = mock_gpu
        
        result = cli_runner.invoke(app, ["info"])
        
        assert result.exit_code == 0
        # Should show some system info
        assert len(result.stdout) > 100
    
    @patch('scribe.cli.main.ScribeConfig')
    @patch('scribe.cli.main.GPUConfig')
    def test_info_shows_gpu_status(self, mock_gpu_class, mock_config_class, cli_runner):
        """Test info command shows GPU status."""
        mock_config = Mock()
        mock_config.output_folder = Path("/test")
        mock_config.default_model = "large-v3"
        mock_config.default_language = "en"
        mock_config.openai_api_key = None
        mock_config.hf_token = None
        mock_config_class.return_value = mock_config
        
        mock_gpu = Mock()
        mock_gpu.has_gpu = True
        mock_gpu.gpu_name = "NVIDIA RTX 4090"
        mock_gpu.gpu_memory_gb = 24.0
        mock_gpu.cuda_available = True
        mock_gpu.cuda_version = "12.4"
        mock_gpu.model_size = "large-v3"
        mock_gpu.beam_size = 10
        mock_gpu.use_fp16 = True
        mock_gpu.recommendation = "local"
        mock_gpu.reason = "GPU detected"
        mock_gpu.get_expected_speed = Mock(return_value="12x real-time")
        mock_gpu_class.detect.return_value = mock_gpu
        
        result = cli_runner.invoke(app, ["info"])
        
        assert result.exit_code == 0
        # Should mention GPU or CUDA
        assert "gpu" in result.stdout.lower() or "cuda" in result.stdout.lower() or "nvidia" in result.stdout.lower()
    
    @patch('scribe.cli.main.ScribeConfig')
    @patch('scribe.cli.main.GPUConfig')
    def test_info_shows_config_status(self, mock_gpu_class, mock_config_class, cli_runner):
        """Test info command shows configuration status."""
        mock_config = Mock()
        mock_config.output_folder = Path("/test/output")
        mock_config.default_model = "large-v3"
        mock_config.default_language = "en"
        mock_config.openai_api_key = "sk-test"
        mock_config.hf_token = None
        mock_config_class.return_value = mock_config
        
        mock_gpu = Mock()
        mock_gpu.has_gpu = False
        mock_gpu.reason = "No GPU detected"
        mock_gpu.recommendation = "openai"
        mock_gpu_class.detect.return_value = mock_gpu
        
        result = cli_runner.invoke(app, ["info"])
        
        assert result.exit_code == 0
        # Should show config info
        assert "output" in result.stdout.lower() or "config" in result.stdout.lower()


class TestVersionCommand:
    """Test version command."""
    
    def test_version_shows_version_number(self, cli_runner):
        """Test version command shows version."""
        result = cli_runner.invoke(app, ["version"])
        
        assert result.exit_code == 0
        assert "Scribe" in result.stdout
        # Should contain version-like pattern (numbers and dots)
        assert any(char.isdigit() for char in result.stdout)


class TestErrorHandling:
    """Test CLI error handling."""
    
    @patch('scribe.cli.main.ScribeConfig')
    def test_scribe_error_handling(self, mock_config_class, cli_runner, tmp_path):
        """Test ScribeError is caught and displayed properly."""
        test_file = tmp_path / "test.wav"
        test_file.write_text("fake")
        
        mock_config = Mock()
        mock_config_class.return_value = mock_config
        mock_config_class.side_effect = ScribeError("Test error", context={"key": "value"})
        
        result = cli_runner.invoke(app, ["transcribe", str(test_file)])
        
        assert result.exit_code != 0
        assert "Error" in result.stdout or "error" in result.stdout
    
    def test_invalid_command(self, cli_runner):
        """Test invalid command shows error."""
        result = cli_runner.invoke(app, ["invalid-command"])
        
        assert result.exit_code != 0
    
    def test_missing_required_argument(self, cli_runner):
        """Test missing required argument shows error."""
        result = cli_runner.invoke(app, ["transcribe"])
        
        assert result.exit_code != 0
        # Typer may output to stderr, just verify it failed
        assert result.exit_code == 2  # Typer uses exit code 2 for usage errors


class TestCommandAliases:
    """Test command aliases and shortcuts."""
    
    def test_rec_is_alias_for_record(self, cli_runner):
        """Test 'rec' command exists as shortcut."""
        result = cli_runner.invoke(app, ["rec", "--help"])
        
        assert result.exit_code == 0
        # Should show help for recording
        assert "record" in result.stdout.lower() or "rec" in result.stdout.lower()


class TestArgumentValidation:
    """Test argument validation."""
    
    def test_invalid_method_value(self, cli_runner, tmp_path):
        """Test invalid --method value."""
        test_file = tmp_path / "test.wav"
        test_file.write_text("fake")
        
        result = cli_runner.invoke(app, ["transcribe", str(test_file), "--method", "invalid"])
        
        assert result.exit_code != 0
    
    def test_invalid_model_value(self, cli_runner, tmp_path):
        """Test invalid --model value."""
        test_file = tmp_path / "test.wav"
        test_file.write_text("fake")
        
        result = cli_runner.invoke(app, ["transcribe", str(test_file), "--model", "invalid"])
        
        assert result.exit_code != 0


class TestOutputFormatting:
    """Test CLI output formatting."""
    
    @patch('scribe.cli.main.ScribeConfig')
    @patch('scribe.cli.main.GPUConfig')
    def test_info_output_is_formatted(self, mock_gpu_class, mock_config_class, cli_runner):
        """Test info command output is well-formatted."""
        mock_config = Mock()
        mock_config.output_folder = Path("/test")
        mock_config.default_model = "large-v3"
        mock_config.default_language = "en"
        mock_config.openai_api_key = None
        mock_config.hf_token = None
        mock_config_class.return_value = mock_config
        
        mock_gpu = Mock()
        mock_gpu.has_gpu = True
        mock_gpu.gpu_name = "Test GPU"
        mock_gpu.gpu_memory_gb = 8.0
        mock_gpu.cuda_available = True
        mock_gpu.cuda_version = "12.0"
        mock_gpu.model_size = "medium"
        mock_gpu.beam_size = 5
        mock_gpu.use_fp16 = True
        mock_gpu.recommendation = "local"
        mock_gpu.reason = "GPU available"
        mock_gpu.get_expected_speed = Mock(return_value="6x real-time")
        mock_gpu_class.detect.return_value = mock_gpu
        
        result = cli_runner.invoke(app, ["info"])
        
        assert result.exit_code == 0
        # Should have some structure (tables, panels, etc.)
        assert len(result.stdout) > 50
    
    def test_version_output_is_clean(self, cli_runner):
        """Test version output is clean and simple."""
        result = cli_runner.invoke(app, ["version"])
        
        assert result.exit_code == 0
        # Should be concise
        assert len(result.stdout) < 500


class TestIntegrationScenarios:
    """Test realistic usage scenarios."""
    
    @patch('scribe.cli.main.ScribeConfig')
    def test_transcribe_with_multiple_options(self, mock_config_class, cli_runner, tmp_path):
        """Test transcribe with multiple options combined."""
        test_file = tmp_path / "test.wav"
        test_file.write_text("fake")
        
        result = cli_runner.invoke(app, [
            "transcribe", str(test_file),
            "--method", "openai",
            "--language", "es",
            "--no-joke",
            "--keep-all"
        ])
        
        # Should parse all options successfully
        assert result.exit_code in [0, 1]  # May fail on execution, but should parse
    
    def test_help_for_all_commands(self, cli_runner):
        """Test help works for all commands."""
        commands = ["transcribe", "record", "rec", "joke", "info", "version"]
        
        for cmd in commands:
            result = cli_runner.invoke(app, [cmd, "--help"])
            assert result.exit_code == 0, f"Help failed for {cmd}"
            assert len(result.stdout) > 20, f"Help too short for {cmd}"


