"""Configured archives stay consistent across CLI producers and consumers."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from scribe.cli.main import app
from scribe.models.gpu import GPUConfig
from scribe.models.transcript import Transcript, TranscriptSegment


@pytest.mark.parametrize("command", ["implicit", "transcribe", "url", "batch"])
@pytest.mark.parametrize("destination", ["config", "env", "flag"])
def test_cli_archives_all_outputs_and_query_finds_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, destination: str
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    source = source_dir / "clip.wav"
    source.write_bytes(b"synthetic media fixture")
    configured = tmp_path / "configured"
    environment = tmp_path / "environment"
    override = tmp_path / "override"
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        f"[output]\nfolder = {json.dumps(str(configured))}\n"
        '[transcription]\nmodel = "tiny"\nmethod = "local"\n'
        "[features]\ngenerate_notes = true\ngenerate_joke = false\ngenerate_meme = false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("scribe.config_file.CONFIG_PATH", config_file)
    monkeypatch.setenv("SCRIBE_LOG_FOLDER", str(tmp_path / "logs"))
    monkeypatch.delenv("SCRIBE_OUTPUT_FOLDER", raising=False)
    monkeypatch.chdir(tmp_path)
    expected = configured
    if destination == "env":
        monkeypatch.setenv("SCRIBE_OUTPUT_FOLDER", str(environment))
        expected = environment
    elif destination == "flag":
        expected = override

    transcriber = Mock()
    transcriber.gpu_config = GPUConfig(has_gpu=False)
    transcriber.choose_method.return_value = "local"
    transcriber.cleanup_intermediate_files.return_value = []
    transcriber.last_transcript = Transcript(
        segments=[TranscriptSegment(0, 3, "ExampleCo schedules repair appointments.")],
        language="en",
        backend="synthetic",
        model="synthetic",
    )

    def transcribe(*_args: object, **kwargs: object) -> Path:
        path = source_dir / "clip_transcription.txt"
        path.write_text("ExampleCo schedules repair appointments.\n", encoding="utf-8")
        session = kwargs["session"]
        session.add_file(path, "transcript")
        session.transcription_method = "local"
        session.model_used = "synthetic"
        return path

    transcriber.transcribe.side_effect = transcribe
    notes_generator = Mock()

    def generate_notes(transcript_path: Path, **_kwargs: object) -> Path:
        notes_path = transcript_path.with_name(f"{transcript_path.stem}_notes.md")
        notes_path.write_text("Synthetic notes fixture.\n", encoding="utf-8")
        return notes_path

    notes_generator.generate_notes.side_effect = generate_notes
    monkeypatch.setattr(
        "scribe.utils.notes_generator.NotesGenerator", lambda **_kwargs: notes_generator
    )
    monkeypatch.setattr("scribe.cli.main.Transcriber", lambda *_args, **_kwargs: transcriber)
    monkeypatch.setattr("scribe.cli.main.setup_logging", Mock())
    monkeypatch.setattr("scribe.cli.main._show_command_banner", Mock())
    monkeypatch.setattr("scribe.cli.init.maybe_prompt_first_run", Mock())
    monkeypatch.setattr("scribe.utils.audio.get_audio_duration", lambda *_args: 3.0)
    monkeypatch.setattr(
        "scribe.utils.unified_progress.UnifiedProgress", Mock(return_value=Mock(frame_delay=0.001))
    )
    converter = Mock()
    converter.convert_to_wav.return_value = source
    monkeypatch.setattr("scribe.core.converter.Converter", lambda: converter)
    downloader = Mock()
    downloader.download.return_value = SimpleNamespace(
        file_path=source, title="Synthetic clip", duration=3.0
    )
    monkeypatch.setattr(
        "scribe.core.downloader.URLDownloader", lambda *_args, **_kwargs: downloader
    )
    monkeypatch.setattr("scribe.utils.validation.validate_media_url", lambda value: value)

    if command == "url":
        args = ["url", "https://example.com/synthetic.wav", "--keep-download"]
    elif command == "implicit":
        args = [str(source)]
    else:
        args = [command, str(source)]
    args += ["--method", "local", "--format", "json,md"]
    if destination == "flag":
        args += ["-o", str(override)]
    runner = CliRunner()
    if command == "implicit":
        from scribe.cli import main as cli_main

        real_app = cli_main.app
        captured = []
        monkeypatch.setattr("sys.argv", ["scribe", *args])
        monkeypatch.setattr(
            cli_main,
            "app",
            Mock(side_effect=lambda: captured.append(runner.invoke(real_app, sys.argv[1:]))),
        )
        cli_main.app.registered_commands = real_app.registered_commands
        cli_main.app.registered_groups = real_app.registered_groups
        cli_main.main()
        result = captured[0]
    else:
        result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    for suffix in ("txt", "json", "md", "docx"):
        assert (expected / f"clip_transcription.{suffix}").is_file()
        assert not (source_dir / f"clip_transcription.{suffix}").exists()
    assert (expected / "clip_transcription_notes.md").is_file()
    assert not (source_dir / "clip_transcription_notes.md").exists()
    notes_generator.generate_notes.assert_called_once()
    summaries = list(expected.glob("*_session_summary.json"))
    assert len(summaries) == 1
    summary = json.loads(summaries[0].read_text(encoding="utf-8"))
    assert summary["outcome"] == "success"
    assert str(expected / "clip_transcription.txt") in summary["files_created"]
    assert source.read_bytes() == b"synthetic media fixture"
    query_args = ["query", "ExampleCo"]
    if destination == "flag":
        query_args += ["--folder", str(override)]
    query = runner.invoke(app, query_args)
    assert query.exit_code == 0, query.output
    assert "ExampleCo schedules repair appointments" in query.output
