import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from click import unstyle
from typer.testing import CliRunner

from scribe.cli.main import _persist_failed_session, _persist_music_session, app
from scribe.exceptions import ProcessError
from scribe.models.session import TranscriptionSession
from scribe.utils.logging import setup_logging as real_setup_logging
from scribe.utils.support_bundle import get_run_history_summary


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


def test_url_post_save_output_failure_does_not_rewrite_success(tmp_path: Path) -> None:
    downloaded_file = tmp_path / "downloaded.mp3"
    downloaded_file.write_text("audio", encoding="utf-8")
    transcript_path = tmp_path / "downloaded_transcript.txt"
    transcript_path.write_text("transcript text", encoding="utf-8")
    progress = Mock(frame_delay=0.001)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []
    config = _make_config(tmp_path)

    def fail_output_heading(*args, **_kwargs):
        if args and "Output Files:" in str(args[0]):
            raise BrokenPipeError("closed terminal")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch(
            "scribe.utils.validation.validate_media_url",
            return_value="https://example.com/video",
        ),
        patch("scribe.core.downloader.URLDownloader") as downloader_class,
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.unified_progress.UnifiedProgress", return_value=progress),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.console.print", side_effect=fail_output_heading),
        patch("scribe.cli.main.logger.warning") as warning_log,
    ):
        downloader_class.return_value.download.return_value = SimpleNamespace(
            file_path=downloaded_file,
            title="Example Video",
            duration=120.0,
        )
        result = CliRunner().invoke(
            app,
            ["url", "https://example.com/video", "--no-joke", "--no-notes", "--no-meme"],
        )

    assert result.exit_code == 1
    summary = next(tmp_path.glob("*_session_summary.json"))
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["outcome"] == "success"
    assert data["success"] is True
    assert any("already saved" in str(call) for call in warning_log.call_args_list)


def test_transcribe_post_save_output_failure_does_not_rewrite_success(tmp_path: Path) -> None:
    audio_file = tmp_path / "meeting.mp3"
    audio_file.write_text("audio", encoding="utf-8")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript text", encoding="utf-8")
    progress = Mock(frame_delay=0.001)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []
    config = _make_config(tmp_path)

    def fail_output_heading(*args, **_kwargs):
        if args and "Output Files:" in str(args[0]):
            raise BrokenPipeError("closed terminal")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.validate_file_path", return_value=audio_file),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.unified_progress.UnifiedProgress", return_value=progress),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.console.print", side_effect=fail_output_heading),
        patch("scribe.cli.main.logger.warning") as warning_log,
    ):
        result = CliRunner().invoke(
            app,
            [
                "transcribe",
                str(audio_file),
                "--no-docx",
                "--no-joke",
                "--no-notes",
                "--no-meme",
            ],
        )

    assert result.exit_code == 1
    summary = next(tmp_path.glob("*_session_summary.json"))
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["outcome"] == "success"
    assert data["success"] is True
    assert any("already saved" in str(call) for call in warning_log.call_args_list)


def test_transcribe_persistent_output_failure_exits_without_recursive_error(tmp_path: Path) -> None:
    audio_file = tmp_path / "meeting.mp3"
    audio_file.write_text("audio", encoding="utf-8")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript text", encoding="utf-8")
    progress = Mock(frame_delay=0.001)
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []
    config = _make_config(tmp_path)
    output_failed = False

    def fail_from_output_heading(*args, **_kwargs):
        nonlocal output_failed
        if output_failed or (args and "Output Files:" in str(args[0])):
            output_failed = True
            raise BrokenPipeError("closed terminal")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.validate_file_path", return_value=audio_file),
        patch("scribe.cli.main.setup_logging", side_effect=real_setup_logging),
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.unified_progress.UnifiedProgress", return_value=progress),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.console.print", side_effect=fail_from_output_heading),
    ):
        result = CliRunner().invoke(
            app,
            [
                "transcribe",
                str(audio_file),
                "--no-docx",
                "--no-joke",
                "--no-notes",
                "--no-meme",
            ],
        )

    configured_logger = logging.getLogger("scribe")
    for handler in configured_logger.handlers[:]:
        handler.close()
        configured_logger.removeHandler(handler)

    assert result.exit_code == 1
    assert not isinstance(result.exception, BrokenPipeError)
    data = json.loads(next(tmp_path.glob("*_session_summary.json")).read_text(encoding="utf-8"))
    assert data["outcome"] == "success"
    assert data["success"] is True
    log_text = next(tmp_path.glob("scribe_meeting_*.log")).read_text(encoding="utf-8")
    assert "already saved before a later error" in log_text
    assert "Terminal output failed" in log_text
    assert "--- Logging error ---" not in result.stdout


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


def test_failed_session_summary_write_failure_is_visible(tmp_path: Path) -> None:
    session = TranscriptionSession.create("Meeting")

    with (
        patch.object(session, "save_summary", side_effect=OSError("disk full")),
        patch("scribe.cli.main.console.print") as print_message,
    ):
        summary_path = _persist_failed_session(
            session,
            tmp_path,
            RuntimeError("backend failed"),
        )

    assert summary_path is None
    assert session.error_message == "backend failed"
    assert any(
        "Failure summary could not be saved: disk full" in str(call.args[0])
        for call in print_message.call_args_list
    )


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


def test_batch_all_missing_inputs_reach_one_aggregate_summary(tmp_path: Path) -> None:
    first = tmp_path / "missing_[bold].mp3"
    second = tmp_path / "missing_second.mp3"

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=_make_config(tmp_path)),
        patch("scribe.cli.main.setup_logging") as setup_log,
        patch("scribe.cli.main.Transcriber") as transcriber_class,
    ):
        result = CliRunner().invoke(
            app,
            [
                "batch",
                str(first),
                str(second),
                "--no-docx",
                "--no-joke",
                "--no-notes",
                "--no-meme",
            ],
        )

    assert result.exit_code == 1
    assert result.stdout.count("Batch Summary") == 1
    assert "Successful: 0" in result.stdout
    assert "Partial: 0" in result.stdout
    assert "Failed: 2" in result.stdout
    assert str(first) in result.stdout
    assert str(second) in result.stdout
    assert "No valid files to process" not in result.stdout
    assert "\u2500" not in result.stdout
    setup_log.assert_not_called()
    transcriber_class.assert_not_called()


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


def test_batch_missing_input_stop_is_not_reported_as_unexpected(tmp_path: Path) -> None:
    missing = tmp_path / "missing_[bold].mp3"

    with patch("scribe.cli.errors.logger.exception") as unexpected_log:
        result = CliRunner().invoke(
            app,
            [
                "batch",
                str(missing),
                "--stop-on-error",
                "--no-docx",
                "--no-joke",
                "--no-notes",
                "--no-meme",
            ],
        )

    assert result.exit_code == 1
    assert str(missing) in result.stdout
    assert "Unexpected error" not in result.stdout
    assert "scribe doctor" not in result.stdout
    unexpected_log.assert_not_called()


def test_batch_expected_validation_errors_render_literal_text(tmp_path: Path) -> None:
    audio_file = tmp_path / "meeting.mp3"
    audio_file.write_text("audio", encoding="utf-8")
    runner = CliRunner()

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=_make_config(tmp_path)),
        patch("scribe.cli.errors.logger.exception") as unexpected_log,
    ):
        language_result = runner.invoke(
            app,
            ["batch", str(audio_file), "--language", "[/]"],
        )

    assert language_result.exit_code == 1
    assert "Invalid language code: [/]" in language_result.stdout
    assert language_result.exception is not None
    assert type(language_result.exception).__name__ == "SystemExit"
    unexpected_log.assert_not_called()

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=_make_config(tmp_path)),
        patch(
            "scribe.utils.vocabulary.CustomVocabulary.load",
            side_effect=ValueError("invalid [/] glossary"),
        ),
        patch("scribe.cli.errors.logger.exception") as unexpected_log,
    ):
        vocabulary_result = runner.invoke(
            app,
            ["batch", str(audio_file), "--vocabulary", str(tmp_path / "terms.txt")],
        )

    assert vocabulary_result.exit_code == 1
    assert "Failed to load vocabulary: invalid [/] glossary" in vocabulary_result.stdout
    assert vocabulary_result.exception is not None
    assert type(vocabulary_result.exception).__name__ == "SystemExit"
    unexpected_log.assert_not_called()


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
        outcome="partial",
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
        outcome="partial",
    )


def test_batch_help_explains_cost_and_incomplete_exit_status() -> None:
    result = CliRunner().invoke(app, ["batch", "--help"])

    assert result.exit_code == 0
    assert "paid cloud" in result.stdout
    assert "nonzero" in result.stdout


def test_tray_help_explains_default_toggle_interaction() -> None:
    result = CliRunner().invoke(app, ["tray", "--help"])
    normalized_output = " ".join(unstyle(result.stdout).split())

    assert result.exit_code == 0
    assert "Tap the dictation hotkey" in normalized_output
    assert "tap it again to stop" in normalized_output
    assert "configurable hold mode remains available" in normalized_output
    assert "Hold the dictation hotkey" not in normalized_output


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


def test_record_only_persists_session_with_log_correlation(tmp_path: Path) -> None:
    runner = CliRunner()
    recording_path = tmp_path / "meeting.mp4"
    recording_path.write_text("video")
    log_path = tmp_path / "scribe_weekly.log"
    log_path.write_text("log")
    config = _make_config(tmp_path)
    recorder = Mock()
    recorder.record.return_value = recording_path

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.get_current_log_file", return_value=log_path),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
    ):
        result = runner.invoke(
            app,
            ["record", "--name", "Weekly Sync", "--no-auto-transcribe"],
        )

    assert result.exit_code == 0
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["success"] is True
    assert data["source_file"] == str(recording_path)
    assert data["log_file"] == str(log_path)
    assert f"Session summary: {summaries[0]}" in result.stdout


def test_record_summary_notification_failure_preserves_saved_success(tmp_path: Path) -> None:
    recording_path = tmp_path / "meeting.mp4"
    recording_path.write_text("video")
    config = _make_config(tmp_path)
    recorder = Mock(record=Mock(return_value=recording_path))

    def fail_summary_notification(*args, **_kwargs):
        if args and str(args[0]).startswith("Session summary:"):
            raise BrokenPipeError("closed terminal")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
        patch("scribe.cli.main.console.print", side_effect=fail_summary_notification),
        patch("scribe.cli.main.logger.warning") as warning_log,
    ):
        result = CliRunner().invoke(
            app,
            ["record", "--name", "Weekly Sync", "--no-auto-transcribe"],
        )

    assert result.exit_code == 0
    summary = next(tmp_path.glob("*_session_summary.json"))
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["outcome"] == "success"
    assert data["success"] is True
    assert warning_log.call_count == 1


def test_record_post_save_output_failure_does_not_rewrite_success(tmp_path: Path) -> None:
    recording_path = tmp_path / "meeting.mp4"
    recording_path.write_text("video")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript")
    config = _make_config(tmp_path)
    recorder = Mock(record=Mock(return_value=recording_path))
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []

    def fail_output_heading(*args, **_kwargs):
        if args and "Output:" in str(args[0]):
            raise BrokenPipeError("closed terminal")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.txt_to_docx", return_value=tmp_path / "meeting.docx"),
        patch("scribe.cli.main.console.print", side_effect=fail_output_heading),
        patch("scribe.cli.main.logger.warning") as warning_log,
    ):
        result = CliRunner().invoke(
            app,
            ["record", "--name", "Weekly Sync", "--no-joke", "--no-meme"],
        )

    assert result.exit_code == 1
    summary = next(tmp_path.glob("*_session_summary.json"))
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["outcome"] == "success"
    assert data["success"] is True
    assert any("already saved" in str(call) for call in warning_log.call_args_list)


def test_record_failure_before_media_persists_started_session(tmp_path: Path) -> None:
    runner = CliRunner()
    config = _make_config(tmp_path)
    recorder = Mock()
    recorder.record.side_effect = RuntimeError("OBS connection dropped")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
    ):
        result = runner.invoke(app, ["record", "--name", "Weekly Sync"])

    assert result.exit_code == 1
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["success"] is False
    assert data["error_message"] == "OBS connection dropped"
    assert data["source_file"] is None
    assert "Failure summary:" in result.stdout


def test_record_transcription_failure_retains_recording_evidence(tmp_path: Path) -> None:
    runner = CliRunner()
    recording_path = tmp_path / "meeting.mp4"
    recording_path.write_text("video")
    config = _make_config(tmp_path)
    recorder = Mock(record=Mock(return_value=recording_path))
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.side_effect = RuntimeError("transcription backend stopped")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
    ):
        result = runner.invoke(app, ["record", "--name", "Weekly Sync"])

    assert result.exit_code == 1
    summary = next(tmp_path.glob("*_session_summary.json"))
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["success"] is False
    assert data["error_message"] == "transcription backend stopped"
    assert data["source_file"] == str(recording_path)
    assert data["transcript_file"] is None
    assert f"Failure summary: {summary}" in result.stdout


def test_record_conversion_failure_retains_source_log_and_cause(tmp_path: Path) -> None:
    runner = CliRunner()
    recording_path = tmp_path / "meeting.mp4"
    recording_path.write_text("video")
    log_path = tmp_path / "record.log"
    log_path.write_text("log")
    config = _make_config(tmp_path)
    recorder = Mock(record=Mock(return_value=recording_path))
    transcriber = Mock()
    transcriber.choose_method.return_value = "local"
    converter = Mock()
    converter.convert_to_wav.side_effect = ProcessError("ffmpeg stopped")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.get_current_log_file", return_value=log_path),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.core.converter.Converter", return_value=converter),
    ):
        result = runner.invoke(app, ["record", "--name", "Weekly Sync"])

    assert result.exit_code == 1
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["outcome"] == "failed"
    assert data["error_message"] == "Recording conversion failed: ffmpeg stopped"
    assert data["source_file"] == str(recording_path)
    assert data["log_file"] == str(log_path)


def test_record_requested_docx_failure_is_partial(tmp_path: Path) -> None:
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
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.txt_to_docx", side_effect=RuntimeError("document unavailable")),
    ):
        result = runner.invoke(
            app,
            [
                "record",
                "--name",
                "Weekly Sync",
                "--no-notes",
                "--no-joke",
                "--no-meme",
            ],
        )

    assert result.exit_code == 1
    assert "Recording & Transcription Partial" in result.stdout
    assert "DOCX generation failed: document unavailable" in result.stdout
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["success"] is False
    assert data["error_message"] == "DOCX generation failed: document unavailable"
    assert data["transcript_file"] == str(transcript_path)


def test_record_saves_final_meme_state_atomically(tmp_path: Path) -> None:
    runner = CliRunner()
    recording_path = tmp_path / "meeting.mp4"
    recording_path.write_text("video")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript text")
    docx_path = tmp_path / "meeting.docx"
    docx_path.write_text("document")
    meme_path = tmp_path / "meeting_meme.png"
    meme_path.write_text("image")
    config = _make_config(tmp_path, api_key="configured-key")
    recorder = Mock(record=Mock(return_value=recording_path))
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.txt_to_docx", return_value=docx_path),
        patch(
            "scribe.utils.meme_generator.generate_meeting_meme",
            return_value={"final_path": meme_path},
        ),
    ):
        result = runner.invoke(
            app,
            [
                "record",
                "--name",
                "Weekly Sync",
                "--no-notes",
                "--no-joke",
                "--meme",
            ],
        )

    assert result.exit_code == 0
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["success"] is True
    assert data["meme_file"] == str(meme_path)


def test_record_does_not_double_count_transcriber_registered_transcript(tmp_path: Path) -> None:
    runner = CliRunner()
    recording_path = tmp_path / "meeting.mp4"
    recording_path.write_text("video")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript text")
    config = _make_config(tmp_path)
    session = TranscriptionSession.create("Weekly Sync")
    recorder = Mock(record=Mock(return_value=recording_path))
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.cleanup_intermediate_files.return_value = []

    def transcribe_with_session(*_args: object, **kwargs: object) -> Path:
        active_session = kwargs["session"]
        assert isinstance(active_session, TranscriptionSession)
        active_session.add_file(transcript_path, "transcript")
        return transcript_path

    transcriber.transcribe.side_effect = transcribe_with_session

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.TranscriptionSession.create", return_value=session),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.txt_to_docx", return_value=tmp_path / "meeting.docx"),
    ):
        result = runner.invoke(
            app,
            [
                "record",
                "--name",
                "Weekly Sync",
                "--no-notes",
                "--no-joke",
                "--no-meme",
            ],
        )

    assert result.exit_code == 0
    summary = next(tmp_path.glob("*_session_summary.json"))
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["files_created"].count(str(transcript_path)) == 1


def test_record_requested_notes_without_key_is_partial(tmp_path: Path) -> None:
    runner = CliRunner()
    recording_path = tmp_path / "meeting.mp4"
    recording_path.write_text("video")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript text")
    config = _make_config(tmp_path)
    recorder = Mock(record=Mock(return_value=recording_path))
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.txt_to_docx", return_value=tmp_path / "meeting.docx"),
    ):
        result = runner.invoke(
            app,
            [
                "record",
                "--name",
                "Weekly Sync",
                "--notes",
                "--no-joke",
                "--no-meme",
            ],
        )

    assert result.exit_code == 1
    assert "Notes requested but OPENAI_API_KEY is not configured" in result.stdout
    summary = next(tmp_path.glob("*_session_summary.json"))
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["success"] is False
    assert data["error_message"] == "Notes requested but OPENAI_API_KEY is not configured"


def test_record_configured_joke_no_result_and_meme_error_are_partial(tmp_path: Path) -> None:
    runner = CliRunner()
    recording_path = tmp_path / "meeting.mp4"
    recording_path.write_text("video")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript text")
    config = _make_config(tmp_path, api_key="configured-key")
    config.enable_joke = True
    recorder = Mock(record=Mock(return_value=recording_path))
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.return_value = []

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.txt_to_docx", return_value=tmp_path / "meeting.docx"),
        patch("scribe.cli.main.generate_transcript_joke", return_value=None),
        patch(
            "scribe.utils.meme_generator.generate_meeting_meme",
            side_effect=RuntimeError("renderer unavailable"),
        ),
    ):
        result = runner.invoke(
            app,
            [
                "record",
                "--name",
                "Weekly Sync",
                "--no-notes",
                "--meme",
            ],
        )

    assert result.exit_code == 1
    assert "Joke generation returned no result" in result.stdout
    assert "Meme generation failed: renderer unavailable" in result.stdout
    summary = next(tmp_path.glob("*_session_summary.json"))
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["outcome"] == "partial"
    assert data["error_message"] == (
        "Joke generation returned no result; Meme generation failed: renderer unavailable"
    )


def test_record_cleanup_failure_preserves_outputs_and_is_partial(tmp_path: Path) -> None:
    runner = CliRunner()
    recording_path = tmp_path / "meeting.mp4"
    recording_path.write_text("video")
    transcript_path = tmp_path / "meeting_transcript.txt"
    transcript_path.write_text("transcript text")
    config = _make_config(tmp_path)
    recorder = Mock(record=Mock(return_value=recording_path))
    transcriber = Mock()
    transcriber.choose_method.return_value = "openai"
    transcriber.transcribe.return_value = transcript_path
    transcriber.cleanup_intermediate_files.side_effect = OSError("locked intermediate")

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.consent.ensure_recording_consent", return_value=True),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.OBSRecorder", return_value=recorder),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.cli.main.txt_to_docx", return_value=tmp_path / "meeting.docx"),
    ):
        result = runner.invoke(
            app,
            [
                "record",
                "--name",
                "Weekly Sync",
                "--no-notes",
                "--no-joke",
                "--no-meme",
            ],
        )

    assert result.exit_code == 1
    assert "Intermediate cleanup failed: locked intermediate" in result.stdout
    summary = next(tmp_path.glob("*_session_summary.json"))
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["success"] is False
    assert data["error_message"] == "Intermediate cleanup failed: locked intermediate"
    assert data["source_file"] == str(recording_path)
    assert data["transcript_file"] == str(transcript_path)


def test_music_instrumental_persists_terminal_session(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_path = tmp_path / "instrumental.mp3"
    audio_path.write_text("audio")
    vocals_path = tmp_path / "instrumental_vocals.wav"
    vocals_path.write_text("vocals")
    log_path = tmp_path / "scribe_instrumental.log"
    log_path.write_text("log")
    config = _make_config(tmp_path)
    detector = Mock()
    detector.analyze_music.return_value = {
        "is_music": True,
        "metadata": {"tempo": 90, "key": "C"},
    }

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.get_current_log_file", return_value=log_path),
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.music_detection.MusicDetector", return_value=detector),
        patch("scribe.utils.source_separation.separate_vocals", return_value=vocals_path),
        patch("scribe.utils.vad.detect_vocal_segments", return_value=[]),
    ):
        result = runner.invoke(app, ["music", str(audio_path)])

    assert result.exit_code == 0
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["success"] is True
    assert data["source_file"] == str(audio_path)
    assert data["log_file"] == str(log_path)
    assert data["transcript_file"] == str(tmp_path / "instrumental_lyrics.txt")
    assert f"Evidence: {summaries[0]}" in result.stdout
    history = get_run_history_summary(output_dir=tmp_path)
    assert history["total_runs"] == 1
    assert history["recent_runs"][0]["artifact_types"] == ["source", "transcript"]
    assert history["recent_runs"][0]["outcome"] == "instrumental"


def test_music_lyrics_atomic_write_does_not_follow_symlink(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_path = tmp_path / "song.mp3"
    audio_path.write_text("audio")
    protected = tmp_path / "protected.txt"
    protected.write_text("do not overwrite")
    lyrics_path = tmp_path / "song_lyrics.txt"
    try:
        lyrics_path.symlink_to(protected)
    except OSError as error:
        pytest.skip(f"Symlinks are unavailable: {error}")

    vocals_path = tmp_path / "song_vocals.wav"
    vocals_path.write_text("vocals")
    config = _make_config(tmp_path)
    detector = Mock()
    detector.analyze_music.return_value = {
        "is_music": True,
        "metadata": {"tempo": 90, "key": "C"},
    }

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.music_detection.MusicDetector", return_value=detector),
        patch("scribe.utils.source_separation.separate_vocals", return_value=vocals_path),
        patch("scribe.utils.vad.detect_vocal_segments", return_value=[]),
    ):
        result = runner.invoke(app, ["music", str(audio_path)])

    assert result.exit_code == 0
    assert protected.read_text() == "do not overwrite"
    assert not lyrics_path.is_symlink()
    assert "[Instrumental - No Speech Detected]" in lyrics_path.read_text()


def test_music_stop_on_error_continues_after_instrumental(tmp_path: Path) -> None:
    runner = CliRunner()
    tracks = [tmp_path / "first.mp3", tmp_path / "second.mp3"]
    for track in tracks:
        track.write_text("audio")
    config = _make_config(tmp_path)
    detector = Mock()
    detector.analyze_music.return_value = {
        "is_music": True,
        "metadata": {"tempo": 90, "key": "C"},
    }

    def separated(audio_path: Path) -> Path:
        vocals_path = audio_path.with_name(f"{audio_path.stem}_vocals.wav")
        vocals_path.write_text("vocals")
        return vocals_path

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0) as duration,
        patch("scribe.utils.music_detection.MusicDetector", return_value=detector),
        patch("scribe.utils.source_separation.separate_vocals", side_effect=separated),
        patch("scribe.utils.vad.detect_vocal_segments", return_value=[]),
    ):
        result = runner.invoke(
            app,
            ["music", *(str(track) for track in tracks), "--stop-on-error"],
        )

    assert result.exit_code == 0
    assert duration.call_count == 2
    assert "Instrumental: 2" in result.stdout
    assert len(list(tmp_path.glob("*_session_summary.json"))) == 2


def test_music_non_music_reason_is_durable(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_path = tmp_path / "podcast.mp3"
    audio_path.write_text("audio")
    config = _make_config(tmp_path)
    detector = Mock()
    detector.analyze_music.return_value = {
        "is_music": False,
        "reason": "speech-only podcast",
        "metadata": {},
    }

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.music_detection.MusicDetector", return_value=detector),
    ):
        result = runner.invoke(app, ["music", str(audio_path)])

    assert result.exit_code == 1
    summary = next(tmp_path.glob("*_session_summary.json"))
    data = json.loads(summary.read_text(encoding="utf-8"))
    assert data["outcome"] == "failed"
    assert data["error_message"] == "Not music: speech-only podcast"


def test_music_full_audio_no_output_preserves_precise_failure(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_path = tmp_path / "song.mp3"
    audio_path.write_text("audio")
    vocals_path = tmp_path / "song_vocals.wav"
    vocals_path.write_text("vocals")
    config = _make_config(tmp_path)
    detector = Mock()
    detector.analyze_music.return_value = {
        "is_music": True,
        "metadata": {"tempo": 90, "key": "C"},
    }
    transcriber = Mock()
    transcriber.transcribe.return_value = None

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.music_detection.MusicDetector", return_value=detector),
        patch("scribe.utils.source_separation.separate_vocals", return_value=vocals_path),
        patch(
            "scribe.utils.vad.detect_vocal_segments",
            side_effect=RuntimeError("VAD unavailable"),
        ),
    ):
        result = runner.invoke(app, ["music", str(audio_path)])

    assert result.exit_code == 1
    assert "Full-track transcription produced no transcript output" in result.stdout
    assert "NoneType" not in result.stdout
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["outcome"] == "failed"
    assert data["error_message"] == "Full-track transcription produced no transcript output"


def test_music_segment_no_output_cannot_mask_terminal_summary(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_path = tmp_path / "song.mp3"
    audio_path.write_text("audio")
    vocals_path = tmp_path / "song_vocals.wav"
    vocals_path.write_text("vocals")
    slice_dir = tmp_path / "vocal_slices"
    slice_dir.mkdir()
    slice_path = slice_dir / "slice.wav"
    slice_path.write_text("slice")
    config = _make_config(tmp_path)
    detector = Mock()
    detector.analyze_music.return_value = {
        "is_music": True,
        "metadata": {"tempo": 90, "key": "C"},
    }
    transcriber = Mock()
    transcriber.transcribe.return_value = None

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.music_detection.MusicDetector", return_value=detector),
        patch("scribe.utils.source_separation.separate_vocals", return_value=vocals_path),
        patch("scribe.utils.vad.detect_vocal_segments", return_value=[(0.0, 10.0)]),
        patch("tempfile.mkdtemp", return_value=str(slice_dir)),
        patch("scribe.utils.audio_slicer.slice_audio_by_segments", return_value=[slice_path]),
    ):
        result = runner.invoke(app, ["music", str(audio_path)])

    assert result.exit_code == 1
    assert "Transcription failed for all 1 vocal segments" in result.stdout
    assert "NoneType" not in result.stdout
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["outcome"] == "failed"
    assert data["error_message"] == "Transcription failed for all 1 vocal segments"


def test_music_failure_persists_precise_terminal_session(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_path = tmp_path / "broken.mp3"
    audio_path.write_text("audio")
    preexisting_intermediate = tmp_path / "broken_16k_mono.wav"
    preexisting_intermediate.write_text("keep me")
    config = _make_config(tmp_path)

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.utils.audio.get_audio_duration", return_value=0.0),
    ):
        result = runner.invoke(app, ["music", str(audio_path)])

    assert result.exit_code == 1
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["success"] is False
    assert data["error_message"] == (
        "Could not read audio duration (invalid or unsupported audio file)"
    )
    assert "Failure summary:" in result.stdout
    assert preexisting_intermediate.read_text() == "keep me"


def test_music_stop_on_error_persists_only_started_track(tmp_path: Path) -> None:
    runner = CliRunner()
    first = tmp_path / "broken.mp3"
    second = tmp_path / "unstarted.mp3"
    first.write_text("audio")
    second.write_text("audio")
    config = _make_config(tmp_path)

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.utils.audio.get_audio_duration", return_value=0.0) as duration,
    ):
        result = runner.invoke(
            app,
            ["music", str(first), str(second), "--stop-on-error"],
        )

    assert result.exit_code == 1
    assert duration.call_count == 1
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["source_file"] == str(first)
    assert str(second) not in summaries[0].read_text(encoding="utf-8")


def test_music_cleanup_failure_is_visible_and_partial(tmp_path: Path) -> None:
    runner = CliRunner()
    audio_path = tmp_path / "song.mp3"
    audio_path.write_text("audio")
    vocals_path = tmp_path / "song_vocals.wav"
    vocals_path.write_text("vocals")
    slice_dir = tmp_path / "vocal_slices"
    slice_dir.mkdir()
    slice_path = slice_dir / "slice.wav"
    slice_path.write_text("slice")
    segment_transcript = tmp_path / "segment.txt"
    segment_transcript.write_text("These are durable lyrics")
    config = _make_config(tmp_path)
    detector = Mock()
    detector.analyze_music.return_value = {
        "is_music": True,
        "metadata": {"tempo": 120, "key": "D"},
    }
    transcriber = Mock()
    transcriber.transcribe.return_value = segment_transcript

    with (
        patch("scribe.cli.main.ScribeConfig", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.Transcriber", return_value=transcriber),
        patch("scribe.utils.audio.get_audio_duration", return_value=120.0),
        patch("scribe.utils.music_detection.MusicDetector", return_value=detector),
        patch("scribe.utils.source_separation.separate_vocals", return_value=vocals_path),
        patch("scribe.utils.vad.detect_vocal_segments", return_value=[(0.0, 10.0)]),
        patch("tempfile.mkdtemp", return_value=str(slice_dir)),
        patch("scribe.utils.audio_slicer.slice_audio_by_segments", return_value=[slice_path]),
        patch("shutil.rmtree", side_effect=OSError("directory busy")),
    ):
        result = runner.invoke(app, ["music", str(audio_path)])

    assert result.exit_code == 1
    assert "Cleanup failed: directory busy" in result.stdout
    summaries = list(tmp_path.glob("*_session_summary.json"))
    assert len(summaries) == 1
    data = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert data["success"] is False
    assert data["error_message"] == "Cleanup failed: directory busy"
    assert (tmp_path / "song_lyrics.txt").exists()


def test_music_summary_write_failure_marks_complete_result_partial(tmp_path: Path) -> None:
    session = TranscriptionSession.create("Song")
    session.add_file(tmp_path / "song.mp3", "source")
    result = {
        "file": "song.mp3",
        "status": "instrumental",
        "lyrics": tmp_path / "song_lyrics.txt",
    }

    with patch.object(session, "save_summary", side_effect=OSError("disk full")):
        summary_path = _persist_music_session(session, result, tmp_path)

    assert summary_path is None
    assert result["status"] == "partial"
    assert result["error"] == "Session summary could not be saved: disk full"
    assert session.success is False
    assert session.error_message == "Session summary could not be saved: disk full"


def test_music_evidence_notification_cannot_mask_saved_outcome(tmp_path: Path) -> None:
    session = TranscriptionSession.create("Song")
    lyrics_path = tmp_path / "song_lyrics.txt"
    lyrics_path.write_text("lyrics")
    result = {
        "file": "song.mp3",
        "status": "success",
        "lyrics": lyrics_path,
    }

    with patch("scribe.cli.main.console.print", side_effect=BrokenPipeError("closed terminal")):
        summary_path = _persist_music_session(session, result, tmp_path)

    assert summary_path is not None
    assert summary_path.exists()
    assert session.success is True
    assert session.outcome == "success"


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


def test_doctor_renders_complete_literal_diagnostic_text() -> None:
    diagnostics = Mock()
    diagnostics.run_all_checks.return_value = [
        SimpleNamespace(
            name="Probe [name]",
            status="pass",
            message="[red]literal[/red] C:\\Audio[/] decisive-tail-after-forty-characters",
            fix_suggestion=None,
        )
    ]
    diagnostics.get_summary.return_value = (1, 0, 0)

    with patch("scribe.utils.diagnostics.SystemDiagnostics", return_value=diagnostics):
        result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Probe [name]" in result.stdout
    assert "[red]literal[/red]" in result.stdout
    assert "C:\\Audio[/]" in result.stdout
    assert "characters" in result.stdout
    assert "1 check)" in result.stdout
    assert "1 checks" not in result.stdout


def test_doctor_warning_and_failure_text_cannot_inject_markup() -> None:
    diagnostics = Mock()
    diagnostics.run_all_checks.return_value = [
        SimpleNamespace(
            name="Warning [path]",
            status="warn",
            message="C:\\Audio[/] warning",
            fix_suggestion="Use [literal] path",
        ),
        SimpleNamespace(
            name="Failure [path]",
            status="fail",
            message="C:\\Output[/] failure",
            fix_suggestion="Fix [literal] path",
        ),
    ]
    diagnostics.get_summary.return_value = (0, 1, 1)

    with patch("scribe.utils.diagnostics.SystemDiagnostics", return_value=diagnostics):
        result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 1
    for literal in (
        "Warning [path]",
        "C:\\Audio[/] warning",
        "Use [literal] path",
        "Failure [path]",
        "C:\\Output[/] failure",
        "Fix [literal] path",
    ):
        assert literal in result.stdout


def test_transcription_method_help_is_local_first_and_cost_explicit() -> None:
    runner = CliRunner()

    for command in ("transcribe", "url", "record", "batch", "music"):
        result = runner.invoke(app, [command, "--help"])
        linear_output = result.stdout.replace("│", " ").replace("|", " ")
        normalized_output = " ".join(linear_output.split())
        assert result.exit_code == 0
        assert "auto/local" in normalized_output
        assert "$0 local" in normalized_output
        assert "GPU or CPU" in normalized_output
        assert "paid cloud" in normalized_output
        assert "local (GPU)" not in result.stdout


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


def test_support_bundle_command_renders_literal_location(tmp_path: Path) -> None:
    bundle_path = tmp_path / "support_[bold red]literal[/bold red].json"

    with patch(
        "scribe.utils.support_bundle.generate_support_bundle_cli",
        return_value=bundle_path,
    ):
        result = CliRunner().invoke(app, ["support-bundle", "--output", str(tmp_path)])

    assert result.exit_code == 0
    assert str(bundle_path) in result.stdout


def test_support_bundle_failure_has_context_aware_recovery(tmp_path: Path) -> None:
    with (
        patch(
            "scribe.utils.support_bundle.generate_support_bundle_cli",
            side_effect=OSError("disk [/] full"),
        ),
        patch("scribe.cli.errors.get_current_log_file", return_value=None),
    ):
        result = CliRunner().invoke(app, ["support-bundle", "--output", str(tmp_path)])

    assert result.exit_code == 1
    assert result.stdout.count("Unexpected error:") == 1
    assert "disk [/] full" in result.stdout
    assert "Check the error above and output-directory permissions" in result.stdout
    assert "If a log path is shown, inspect it" in result.stdout
    assert "Log file:" not in result.stdout
    assert "Failed to create support bundle" not in result.stdout
    assert "Use `scribe support-bundle`" not in result.stdout


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
