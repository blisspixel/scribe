import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from typer.testing import CliRunner

from scribe.cli.main import _persist_failed_session, app
from scribe.models.session import TranscriptionSession


def _make_config(tmp_path: Path, *, api_key: str | None = None) -> Mock:
    config = Mock()
    config.output_folder = tmp_path
    config.log_folder = tmp_path
    config.default_model = "large-v3"
    config.default_language = "en"
    config.default_method = "auto"
    config.openai_api_key = api_key
    config.notes_model = "gpt-5"
    config.enable_notes = False
    config.enable_joke = False
    config.enable_meme = False
    config.keep_intermediate_files = False
    config.keep_downloads = False
    config.download_folder = None
    config.download_audio_only = True
    config.download_timeout = 60
    config.max_file_size_gb = 5.0
    config.cookies_from_browser = None
    config.max_recording_hours = 2.0
    config.recording_warning_fraction = 0.9
    return config


def test_url_command_success(tmp_path: Path) -> None:
    runner = CliRunner()
    downloaded_file = tmp_path / "downloaded.mp3"
    downloaded_file.write_text("audio")
    transcript_path = tmp_path / "downloaded_transcript.txt"
    transcript_path.write_text("transcript text")
    docx_path = tmp_path / "downloaded_transcript.docx"
    progress = Mock(frame_delay=0.001)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []
    config = _make_config(tmp_path)

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch(
            "scribe.utils.validation.validate_media_url", return_value="https://example.com/video"
        ),
        patch("scribe.core.downloader.URLDownloader") as mock_downloader_class,
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.unified_progress.UnifiedProgress", return_value=progress),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.txt_to_docx", return_value=docx_path),
    ):
        mock_downloader = Mock()
        mock_downloader.download.return_value = SimpleNamespace(
            file_path=downloaded_file,
            title="Example Video",
            duration=120.0,
        )
        mock_downloader_class.return_value = mock_downloader
        result = runner.invoke(
            app, ["url", "https://example.com/video", "--no-joke", "--no-notes", "--no-meme"]
        )

    assert result.exit_code == 0
    assert "Transcription Complete" in result.stdout
    transcriber.transcribe.assert_called_once()


def test_transcribe_failure_persists_unique_session_summary(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_file = tmp_path / "meeting.mp3"
    audio_file.write_text("audio")
    config = _make_config(tmp_path)
    progress = Mock(frame_delay=0.001)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.side_effect = RuntimeError("backend unavailable")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.validate_file_path", return_value=audio_file),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.unified_progress.UnifiedProgress", return_value=progress),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
    ):
        result = runner.invoke(
            app,
            ["transcribe", str(audio_file), "--no-docx", "--no-joke", "--no-notes", "--no-meme"],
        )

    assert result.exit_code == 1
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["success"] is False
    assert data["error_message"] == "backend unavailable"
    assert "Failure summary:" in result.stdout


def test_transcribe_no_output_persists_precise_failure_stage(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_file = tmp_path / "meeting.mp3"
    audio_file.write_text("audio")
    config = _make_config(tmp_path)
    progress = Mock(frame_delay=0.001)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = None

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.validate_file_path", return_value=audio_file),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.unified_progress.UnifiedProgress", return_value=progress),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
    ):
        result = runner.invoke(
            app,
            ["transcribe", str(audio_file), "--no-docx", "--no-joke", "--no-notes", "--no-meme"],
        )

    assert result.exit_code == 1
    assert "Transcription produced no output file" in result.stdout
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["error_message"] == "Transcription produced no output file"


def test_failure_summary_notification_cannot_mask_original_failure(tmp_path: Path) -> None:
    session = TranscriptionSession.create("Meeting")
    session.add_file(tmp_path / "meeting.wav", "source")

    with patch("scribe.cli.main.console.print", side_effect=BrokenPipeError("closed terminal")):
        summary_path = _persist_failed_session(session, tmp_path, RuntimeError("backend failed"))

    assert summary_path is not None
    data = json.loads(summary_path.read_text(encoding="utf-8"))
    assert data["success"] is False
    assert data["error_message"] == "backend failed"


def test_url_failure_persists_session_before_download_cleanup(tmp_path: Path) -> None:
    runner = CliRunner()
    downloaded_file = tmp_path / "downloaded.mp3"
    downloaded_file.write_text("audio")
    config = _make_config(tmp_path)
    progress = Mock(frame_delay=0.001)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.side_effect = RuntimeError("remote media failed")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch(
            "scribe.utils.validation.validate_media_url", return_value="https://example.com/video"
        ),
        patch("scribe.core.downloader.URLDownloader") as mock_downloader_class,
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.unified_progress.UnifiedProgress", return_value=progress),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
    ):
        mock_downloader_class.return_value.download.return_value = SimpleNamespace(
            file_path=downloaded_file,
            title="Example Video",
            duration=120.0,
        )
        result = runner.invoke(
            app,
            [
                "url",
                "https://example.com/video",
                "--no-docx",
                "--no-joke",
                "--no-notes",
                "--no-meme",
            ],
        )

    assert result.exit_code == 1
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["success"] is False
    assert data["error_message"] == "remote media failed"
    assert str(downloaded_file) in data["files_cleaned"]
    assert not downloaded_file.exists()


def test_batch_transcribe_reports_success_and_failure(tmp_path: Path) -> None:
    runner = CliRunner()
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    missing = tmp_path / "missing.mp3"
    first.write_text("audio1")
    second.write_text("audio2")
    transcript_path = tmp_path / "first_transcript.txt"
    transcript_path.write_text("transcript text")
    config = _make_config(tmp_path)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.side_effect = [transcript_path, RuntimeError("boom")]
    transcriber.cleanup_intermediate_files.return_value = []

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.validate_file_path", side_effect=lambda value: Path(value)),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.txt_to_docx", return_value=tmp_path / "first.docx"),
    ):
        result = runner.invoke(
            app,
            [
                "batch",
                str(first),
                str(second),
                str(missing),
                "--no-joke",
                "--no-notes",
                "--no-meme",
            ],
        )

    assert result.exit_code == 1
    assert "Batch Summary" in result.stdout
    assert "Successful: 1" in result.stdout
    assert "Failed: 2" in result.stdout
    assert "missing.mp3" in result.stdout
    assert transcriber.transcribe.call_count == 2
    summaries = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in tmp_path.glob("*_session_summary.json")
    ]
    assert any(
        summary["success"] is False and summary["error_message"] == "boom" for summary in summaries
    )


def test_batch_transcribe_complete_run_exits_zero(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_file = tmp_path / "meeting.mp3"
    audio_file.write_text("audio")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript text")
    config = _make_config(tmp_path)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.validate_file_path", return_value=audio_file),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.txt_to_docx", return_value=tmp_path / "meeting.docx"),
    ):
        result = runner.invoke(
            app,
            ["batch", str(audio_file), "--no-joke", "--no-notes", "--no-meme"],
        )

    assert result.exit_code == 0
    assert "Successful: 1" in result.stdout
    assert "Partial: 0" in result.stdout
    assert "Failed: 0" in result.stdout


def test_batch_stop_on_error_does_not_attempt_later_files(tmp_path: Path) -> None:
    runner = CliRunner()
    first = tmp_path / "first.mp3"
    second = tmp_path / "second.mp3"
    first.write_text("audio1")
    second.write_text("audio2")
    config = _make_config(tmp_path)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.side_effect = RuntimeError("backend unavailable")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.validate_file_path", side_effect=lambda value: Path(value)),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
    ):
        result = runner.invoke(
            app,
            [
                "batch",
                str(first),
                str(second),
                "--stop-on-error",
                "--no-docx",
                "--no-joke",
                "--no-notes",
                "--no-meme",
            ],
        )

    assert result.exit_code == 1
    assert transcriber.transcribe.call_count == 1
    assert "Failed: 1" in result.stdout


def test_batch_transcribe_marks_artifact_failure_partial(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_file = tmp_path / "meeting.mp3"
    audio_file.write_text("audio")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript text")
    config = _make_config(tmp_path)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []
    session = Mock()

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.validate_file_path", return_value=audio_file),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.TranscriptionSession.create", return_value=session),
        patch("scribe.cli.main.txt_to_docx", side_effect=RuntimeError("conversion boom")),
    ):
        result = runner.invoke(
            app,
            ["batch", str(audio_file), "--no-joke", "--no-notes", "--no-meme"],
        )

    assert result.exit_code == 1
    assert "Partial: 1" in result.stdout
    assert "DOCX generation failed: conversion boom" in result.stdout
    session.complete.assert_called_once_with(
        success=False,
        error_message="DOCX generation failed: conversion boom",
    )
    session.save_summary.assert_called_once_with(tmp_path)


def test_batch_transcribe_reports_unavailable_requested_feature(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_file = tmp_path / "meeting.mp3"
    audio_file.write_text("audio")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript text")
    config = _make_config(tmp_path, api_key=None)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []
    session = Mock()

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.validate_file_path", return_value=audio_file),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.TranscriptionSession.create", return_value=session),
    ):
        result = runner.invoke(
            app,
            [
                "batch",
                str(audio_file),
                "--notes",
                "--no-docx",
                "--no-joke",
                "--no-meme",
            ],
        )

    assert result.exit_code == 1
    assert "Partial: 1" in result.stdout
    assert "OPENAI_API_KEY is not configured" in result.stdout
    transcriber.transcribe.assert_called_once()
    session.complete.assert_called_once_with(
        success=False,
        error_message="Notes not generated: OPENAI_API_KEY is not configured",
    )


def test_batch_help_explains_cost_and_incomplete_exit_status() -> None:
    result = CliRunner().invoke(app, ["batch", "--help"])

    assert result.exit_code == 0
    assert "paid cloud" in result.stdout
    assert "nonzero" in result.stdout


def test_record_command_auto_transcribes(tmp_path: Path) -> None:
    runner = CliRunner()
    recording_path = tmp_path / "meeting.mp4"
    recording_path.write_text("video")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript text")
    config = _make_config(tmp_path)
    recorder = Mock()
    recorder.record.return_value = recording_path
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.txt_to_docx", return_value=tmp_path / "meeting.docx"),
    ):
        result = runner.invoke(app, ["record", "--name", "Weekly Sync", "--no-joke", "--no-meme"])

    assert result.exit_code == 0
    assert "Recording & Transcription Complete" in result.stdout


def test_meme_command_success_with_custom_output(tmp_path: Path) -> None:
    runner = CliRunner()
    transcript = tmp_path / "meeting.txt"
    transcript.write_text("meeting transcript")
    raw_output = tmp_path / "raw.png"
    raw_output.write_text("image")
    desired_output = tmp_path / "custom.png"
    config = _make_config(tmp_path, api_key="sk-test")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.utils.meme_generator.MemeConfig.from_env") as mock_from_env,
        patch("scribe.utils.meme_generator.generate_meeting_meme") as mock_generate,
        patch("shutil.move") as mock_move,
    ):
        mock_from_env.return_value = SimpleNamespace(spice_level=5)
        mock_generate.return_value = {
            "final_path": raw_output,
            "attempts": [{"attempt": 1, "score": 8.5, "path": raw_output}],
        }
        result = runner.invoke(app, ["meme", str(transcript), "--output", str(desired_output)])

    assert result.exit_code == 0
    assert "Meme:" in result.stdout
    mock_move.assert_called_once()


def test_notes_command_success(tmp_path: Path) -> None:
    runner = CliRunner()
    transcript = tmp_path / "meeting.txt"
    transcript.write_text("meeting transcript")
    notes_path = tmp_path / "meeting_notes.md"
    notes_path.write_text("notes")
    config = _make_config(tmp_path, api_key="sk-test")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.utils.notes_generator.NotesGenerator") as mock_generator_class,
    ):
        mock_generator = Mock()
        mock_generator.generate_notes.return_value = notes_path
        mock_generator_class.return_value = mock_generator
        result = runner.invoke(app, ["notes", str(transcript)])

    assert result.exit_code == 0
    assert "Notes:" in result.stdout


def test_doctor_command_reports_failures() -> None:
    runner = CliRunner()
    diagnostics = Mock()
    diagnostics.run_all_checks.return_value = [
        SimpleNamespace(name="GPU", status="pass", message="ok", fix_suggestion=None),
        SimpleNamespace(
            name="OBS", status="warn", message="not running", fix_suggestion="Start OBS"
        ),
        SimpleNamespace(name="API", status="fail", message="missing", fix_suggestion="Set key"),
    ]
    diagnostics.get_summary.return_value = (1, 1, 1)

    with patch("scribe.utils.diagnostics.SystemDiagnostics", return_value=diagnostics):
        result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 1
    assert "FAILED" in result.stdout
    assert "WARNINGS" in result.stdout
    diagnostics.run_all_checks.assert_called_once_with(live=False)


def test_doctor_command_live_enables_provider_checks() -> None:
    runner = CliRunner()
    diagnostics = Mock()
    diagnostics.run_all_checks.return_value = [
        SimpleNamespace(name="Python Version", status="pass", message="ok", fix_suggestion=None),
    ]
    diagnostics.get_summary.return_value = (1, 0, 0)

    with patch("scribe.utils.diagnostics.SystemDiagnostics", return_value=diagnostics):
        result = runner.invoke(app, ["doctor", "--live"])

    assert result.exit_code == 0
    assert "Live provider checks enabled" in result.stdout
    diagnostics.run_all_checks.assert_called_once_with(live=True)


def test_doctor_command_warning_summary_is_clear() -> None:
    runner = CliRunner()
    diagnostics = Mock()
    diagnostics.run_all_checks.return_value = [
        SimpleNamespace(name="Python Version", status="pass", message="ok", fix_suggestion=None),
        SimpleNamespace(
            name="Local Notes ($0)",
            status="warn",
            message="Ollama has no models installed",
            fix_suggestion="Install Ollama",
        ),
    ]
    diagnostics.get_summary.return_value = (1, 1, 0)

    with patch("scribe.utils.diagnostics.SystemDiagnostics", return_value=diagnostics):
        result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Ready with warnings" in result.stdout
    assert "Ready with notes" not in result.stdout


def test_health_check_success() -> None:
    runner = CliRunner()
    status = SimpleNamespace(is_healthy=True, response_time_ms=123.0, error_message=None)
    monitor = Mock()
    monitor.check_provider_health.return_value = status

    with (
        patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=True),
        patch("scribe.providers.health.get_health_monitor", return_value=monitor),
    ):
        result = runner.invoke(app, ["health", "--provider", "openai"])

    assert result.exit_code == 0
    assert "all providers healthy" in result.stdout


def test_health_check_fails_when_requested_provider_has_no_key() -> None:
    runner = CliRunner()
    monitor = Mock()

    with (
        patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=True),
        patch("scribe.providers.health.get_health_monitor", return_value=monitor),
    ):
        result = runner.invoke(app, ["health", "--provider", "xai"])

    assert result.exit_code == 1
    assert "XAI_API_KEY is not configured" in result.stdout
    assert "all providers healthy" not in result.stdout
    monitor.check_provider_health.assert_not_called()


def test_health_check_rejects_unknown_provider() -> None:
    runner = CliRunner()
    monitor = Mock()

    with (
        patch.dict("os.environ", {"OPENAI_API_KEY": "sk-test"}, clear=True),
        patch("scribe.providers.health.get_health_monitor", return_value=monitor),
    ):
        result = runner.invoke(app, ["health", "--provider", "unknown"])

    assert result.exit_code == 1
    assert "Unknown provider: unknown" in result.stdout
    assert "openai, xai, anthropic, gemini" in result.stdout
    monitor.check_provider_health.assert_not_called()


def test_support_bundle_command_success(tmp_path: Path) -> None:
    runner = CliRunner()
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text("{}")

    with patch("scribe.utils.support_bundle.generate_support_bundle_cli", return_value=bundle_path):
        result = runner.invoke(app, ["support-bundle", "--output", str(tmp_path)])

    assert result.exit_code == 0
    assert "Support bundle created successfully" in result.stdout
    assert "Redacted recent session summaries" in result.stdout
    assert "Recent log metadata" in result.stdout
    assert "Log contents are not included" in result.stdout
    assert "Review the file before sharing" in result.stdout


def test_clean_command_analyze_mode(tmp_path: Path) -> None:
    runner = CliRunner()
    input_file = tmp_path / "meeting.mp4"
    input_file.write_text("video")

    with (
        patch("scribe.utils.audio.get_audio_duration", return_value=600.0),
        patch(
            "scribe.utils.silence_remover.analyze_silence",
            return_value={
                "total_silence_minutes": 3.0,
                "total_silence_seconds": 180.0,
                "silence_periods": 2,
                "periods": [{"start": 60.0, "duration": 30.0}],
            },
        ),
    ):
        result = runner.invoke(app, ["clean", str(input_file), "--analyze"])

    assert result.exit_code == 0
    assert "Silence Analysis" in result.stdout


def test_clean_command_trim_mode(tmp_path: Path) -> None:
    runner = CliRunner()
    input_file = tmp_path / "meeting.mp4"
    input_file.write_text("video")
    trimmed = tmp_path / "meeting_trimmed.mp4"
    trimmed.write_text("trimmed")

    with (
        patch("scribe.utils.audio.get_audio_duration", side_effect=[7200.0, 3600.0]),
        patch("scribe.utils.silence_remover.trim_file", return_value=trimmed),
    ):
        result = runner.invoke(app, ["clean", str(input_file), "--trim", "01:00:00"])

    assert result.exit_code == 0
    assert "Success!" in result.stdout
