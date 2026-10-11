"""Conversion ownership and truthful terminal histories, without inference."""

import json
import math
import socket
import struct
import wave
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from rich.console import Console
from rich.progress import Progress
from typer.testing import CliRunner

from scribe.cli.audio_workspace import AudioWorkspace, preserve_download_outputs
from scribe.cli.main import app
from scribe.core.converter import Converter
from scribe.core.downloader import DownloadResult, URLDownloader
from scribe.core.transcriber import Transcriber
from scribe.exceptions import ProcessError, TranscriptionError
from scribe.models.config import ScribeConfig
from scribe.models.session import TranscriptionSession
from scribe.utils.diagnostics import SystemDiagnostics
from scribe.utils.unified_progress import UnifiedProgress


def test_keep_all_reserves_paths_before_conversion_starts(tmp_path: Path) -> None:
    source = tmp_path / "clip.wav"
    source.write_bytes(b"original synthetic recording")
    first = AudioWorkspace(keep=True)
    second = AudioWorkspace(keep=True)
    first_path = first.output_for(source, "_16k_mono.wav")
    second_path = second.output_for(source, "_16k_mono.wav")
    assert first_path != second_path
    assert first_path.is_file() and second_path.is_file()
    first_path.write_bytes(b"first owned conversion")
    second_path.write_bytes(b"second owned conversion")
    first.finish(None, None)
    second.finish(None, None)
    assert first_path.read_bytes() == b"first owned conversion"
    assert second_path.read_bytes() == b"second owned conversion"
    assert source.read_bytes() == b"original synthetic recording"


def test_download_cleanup_preserves_outputs_and_uninspectable_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    download = tmp_path / "owned" / "download.wav"
    download.parent.mkdir()
    download.write_bytes(b"synthetic source")
    session = TranscriptionSession.create("synthetic")
    session.add_file(download, "download")
    assert not preserve_download_outputs(session, download)
    unrelated = tmp_path / "archived.txt"
    unrelated.write_text("archived output")
    session.add_file(unrelated, "transcript")
    assert not preserve_download_outputs(session, download)
    partial = download.with_suffix(".txt")
    partial.write_text("recoverable partial transcript")
    session.add_file(partial, "transcript")
    assert preserve_download_outputs(session, download)

    original_is_file = Path.is_file

    def inspect(path: Path) -> bool:
        if path == partial:
            raise PermissionError("synthetic inspection failure")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", inspect)
    assert preserve_download_outputs(session, download)
    assert partial.read_text() == "recoverable partial transcript"
    assert not preserve_download_outputs(None, download)
    assert not preserve_download_outputs(session, None)


@pytest.mark.parametrize("command", ["transcribe", "batch"])
@pytest.mark.parametrize("failure", [None, "conversion", "transcription", "archive", "summary"])
def test_cli_owned_audio_is_cleaned_on_success_and_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, failure: str | None
) -> None:
    source = tmp_path / "clip.wav"
    source.write_bytes(b"original synthetic recording")
    foreign = tmp_path / "neighbor_converted.mp3"
    foreign.write_bytes(b"an unrelated recording must survive")
    archive = tmp_path / "archive"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCRIBE_OUTPUT_FOLDER", str(archive))
    monkeypatch.setenv("SCRIBE_LOG_FOLDER", str(tmp_path / "logs"))
    monkeypatch.setenv("SCRIBE_ENABLE_NOTES", "false")
    monkeypatch.setenv("SCRIBE_ENABLE_JOKE", "false")
    monkeypatch.setenv("SCRIBE_ENABLE_MEME", "false")
    monkeypatch.setenv("SCRIBE_KEEP_INTERMEDIATE_FILES", "false")
    monkeypatch.setattr("scribe.config_file.CONFIG_PATH", tmp_path / "missing.toml")
    monkeypatch.setitem(ScribeConfig.model_config, "env_file", None)
    monkeypatch.setattr("scribe.cli.init.maybe_prompt_first_run", Mock())
    monkeypatch.setattr("scribe.utils.audio.get_audio_duration", lambda *_args: 0.1)
    monkeypatch.setattr("scribe.cli.main.setup_logging", Mock())
    monkeypatch.setattr("scribe.cli.main._show_command_banner", Mock())
    progress = Mock(frame_delay=0.001)
    monkeypatch.setattr(
        "scribe.utils.unified_progress.UnifiedProgress", Mock(return_value=progress)
    )
    conversions: list[Path] = []
    transcripts: list[Path] = []

    def reject_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Cleanup tests cannot contact a network")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket, "getaddrinfo", reject_network)

    class SyntheticConverter:
        def convert_to_wav(self, _source: Path, *, output_file: Path, **_kwargs: object) -> Path:
            assert output_file.parent != source.parent
            output_file.write_bytes(b"owned converted audio")
            conversions.append(output_file)
            if failure == "conversion":
                raise ProcessError("Synthetic conversion failure")
            return output_file

    class SyntheticTranscriber:
        last_transcript = None
        converter = SimpleNamespace(output_path_factory=None)

        def choose_method(self, _method: str) -> str:
            return "local"

        def transcribe(
            self, audio: Path, *, session: TranscriptionSession, **_kwargs: object
        ) -> Path:
            session.add_file(audio, "audio")
            if failure == "transcription":
                raise TranscriptionError("Synthetic transcription failure")
            transcript = audio.with_name("clip_transcription.txt")
            transcript.write_text("Confirmed synthetic transcript, preserved for review.\n")
            transcripts.append(transcript)
            session.add_file(transcript, "transcript")
            return transcript

    monkeypatch.setattr("scribe.core.converter.Converter", SyntheticConverter)
    monkeypatch.setattr("scribe.cli.main.Transcriber", lambda _config: SyntheticTranscriber())
    if failure == "archive":

        def fail_copy(*_args: object, **_kwargs: object) -> None:
            raise OSError("Synthetic archive failure")

        monkeypatch.setattr("scribe.utils.safe_write.safe_copy", fail_copy)
    if failure == "summary":
        monkeypatch.setattr(
            TranscriptionSession,
            "save_summary",
            Mock(side_effect=OSError("Synthetic summary failure")),
        )
    result = CliRunner().invoke(
        app, [command, str(source), "--method", "local", "--no-docx", "--format", ""]
    )
    assert result.exit_code == (0 if failure is None else 1), result.output
    assert len(conversions) == 1
    converted = conversions[0]
    assert not converted.exists()
    assert source.read_bytes() == b"original synthetic recording"
    assert foreign.read_bytes() == b"an unrelated recording must survive"
    if failure == "summary":
        assert not list(archive.glob("*_session_summary.json"))
        assert (archive / "clip_transcription.txt").read_text().startswith("Confirmed synthetic")
        if command == "transcribe":
            progress.complete.assert_not_called()
            progress.fail.assert_called_once()
        return
    summary = json.loads(next(archive.glob("*_session_summary.json")).read_text())
    assert str(source) not in summary["files_created"]
    assert str(source) not in summary["files_cleaned"]
    assert str(converted) in summary["files_created"]
    assert str(converted) in summary["files_cleaned"]
    if failure == "archive":
        assert transcripts[0].read_text().startswith("Confirmed synthetic transcript")
        assert "Retained recoverable" in result.output
        transcripts[0].unlink()
        converted.parent.rmdir()
    else:
        assert not converted.parent.exists()
    if failure is None:
        archived = archive / "clip_transcription.txt"
        assert archived.read_text().startswith("Confirmed synthetic transcript")
        assert summary["files_moved"] == [
            {"source": str(transcripts[0]), "destination": str(archived)}
        ]
        assert str(transcripts[0]) not in summary["files_cleaned"]


def test_keep_all_preserves_existing_conversion_and_tracks_new_copy(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp3"
    source.write_bytes(b"source")
    previous = tmp_path / "clip_16k_mono.wav"
    previous.write_bytes(b"previous conversion")
    workspace = AudioWorkspace(keep=True)
    converted = workspace.output_for(source, "_16k_mono.wav")
    converted.write_bytes(b"new conversion")
    session = TranscriptionSession.create("synthetic")
    session.add_file(source, "source")
    workspace.finish(session, None)
    assert previous.read_bytes() == b"previous conversion"
    assert converted.parent == source.parent
    assert converted != previous
    assert converted.read_bytes() == b"new conversion"
    assert session.files_created == [converted]
    assert session.files_cleaned == []


def test_keep_all_refreshes_failure_summary_with_retained_conversion(tmp_path: Path) -> None:
    source = tmp_path / "clip.mp3"
    source.write_bytes(b"source")
    workspace = AudioWorkspace(keep=True)
    converted = workspace.output_for(source, "_16k_mono.wav")
    converted.write_bytes(b"retained incomplete conversion")
    session = TranscriptionSession.create("synthetic")
    session.add_file(source, "source")
    session.complete(success=False, error_message="Synthetic conversion failure")
    summary_path = session.save_summary(tmp_path)
    assert str(converted) not in json.loads(summary_path.read_text())["files_created"]
    workspace.finish(session, tmp_path)
    summary = json.loads(summary_path.read_text())
    assert summary["outcome"] == "failed"
    assert str(converted) in summary["files_created"]
    assert str(converted) not in summary["files_cleaned"]
    assert converted.read_bytes() == b"retained incomplete conversion"


def test_cleanup_inspection_failure_preserves_primary_error_and_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = AudioWorkspace()
    converted = workspace.output_for(tmp_path / "source.wav", "_16k_mono.wav")
    converted.write_bytes(b"owned audio")
    original_exists = Path.exists

    def cannot_inspect(path: Path) -> bool:
        if path == converted:
            raise PermissionError("Synthetic inaccessible owned conversion")
        return original_exists(path)

    session = TranscriptionSession.create("synthetic")
    with monkeypatch.context() as isolated:
        isolated.setattr(Path, "exists", cannot_inspect)
        with pytest.raises(RuntimeError, match="Primary transcription error"):
            try:
                raise RuntimeError("Primary transcription error")
            finally:
                workspace.finish(session, None)
    assert converted.read_bytes() == b"owned audio"
    workspace.finish(session, None)
    assert not converted.exists()
    assert converted in session.files_created
    assert converted in session.files_cleaned


def test_url_failure_preserves_recorded_partial_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "archive"
    monkeypatch.setattr("scribe.config_file.CONFIG_PATH", tmp_path / "absent.toml")
    monkeypatch.setitem(ScribeConfig.model_config, "env_file", None)
    monkeypatch.setenv("SCRIBE_OUTPUT_FOLDER", str(archive))
    monkeypatch.setenv("SCRIBE_LOG_FOLDER", str(tmp_path / "logs"))
    monkeypatch.setenv("SCRIBE_KEEP_DOWNLOADS", "false")
    paths: dict[str, Path] = {}

    def download(owner: URLDownloader, url: str) -> DownloadResult:
        media = owner.output_dir / "clip.wav"
        media.write_bytes(b"synthetic downloaded media")
        paths["media"] = media
        return DownloadResult(media, "Synthetic partial fixture", 0.1, url)

    class PartialTranscriber:
        def choose_method(self, _method: str) -> str:
            return "openrouter"

        def transcribe(
            self, audio: Path, *, session: TranscriptionSession, **_kwargs: object
        ) -> Path:
            partial = audio.with_name("clip_transcription.partial.txt")
            partial.write_text("Confirmed synthetic words from the completed first chunk.\n")
            paths["partial"] = partial
            session.add_file(partial, "partial_transcript")
            raise TranscriptionError("Synthetic later chunk failure; partial transcript retained")

    monkeypatch.setattr(URLDownloader, "download", download)
    monkeypatch.setattr("scribe.cli.main.Transcriber", lambda _config: PartialTranscriber())
    monkeypatch.setattr("scribe.utils.audio.get_audio_duration", lambda *_args: 0.1)
    monkeypatch.setattr("scribe.utils.validation.validate_media_url", lambda value: value)
    monkeypatch.setattr("scribe.cli.main.setup_logging", Mock())
    monkeypatch.setattr(
        "scribe.utils.unified_progress.UnifiedProgress", Mock(return_value=Mock(frame_delay=0.001))
    )
    result = CliRunner().invoke(
        app, ["url", "https://8.8.8.8/synthetic.wav", "--method", "openrouter", "--no-docx"]
    )
    assert result.exit_code == 1
    assert paths["media"].read_bytes() == b"synthetic downloaded media"
    assert paths["partial"].read_text().startswith("Confirmed synthetic words")
    summary = json.loads(next(archive.glob("*_session_summary.json")).read_text())
    assert summary["outcome"] == "failed"
    assert str(paths["partial"]) in summary["files_created"]
    assert str(paths["partial"]) not in summary["files_cleaned"]
    assert "recoverable transcription outputs were retained" in result.output
    paths["partial"].unlink()
    paths["media"].unlink()
    paths["media"].parent.rmdir()


def test_failed_progress_has_terminal_state_without_unfinished_percentage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = StringIO()
    printer = Console(file=stream, force_terminal=False)
    monkeypatch.setattr("scribe.utils.unified_progress.console", printer)
    unified = UnifiedProgress()
    progress = Progress(console=printer, auto_refresh=False)
    unified.progress = progress
    unified.task = progress.add_task("Transcribing", total=100, completed=99)
    unified.fail()
    assert "Failed" in stream.getvalue()
    assert "99%" not in stream.getvalue()
    assert unified.progress is None


def test_installed_tool_audit_is_not_applicable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "scribe.utils.diagnostics.__file__",
        str(tmp_path / "site-packages/scribe/utils/diagnostics.py"),
    )
    finder = Mock(side_effect=AssertionError("An installed tool must not inspect pip-audit"))
    monkeypatch.setattr("importlib.util.find_spec", finder)
    result = SystemDiagnostics().check_dependency_security()
    assert result.status == "pass"
    assert result.message == "Not applicable to an installed tool"
    assert result.fix_suggestion is None


def test_source_audio_reference_is_not_created_but_download_is(tmp_path: Path) -> None:
    source = tmp_path / "clip.wav"
    session = TranscriptionSession.create("synthetic")
    session.add_file(source, "source")
    session.add_file(source, "audio")
    assert session.source_file == session.audio_file == source
    assert session.files_created == []
    session.add_file(source, "download")
    assert session.files_created == [source]


@pytest.mark.requires_ffmpeg
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("format_name", ["wav", "mp3"])
def test_real_converter_uses_owner_and_preserves_explicit_output_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, explicit: bool, format_name: str
) -> None:
    source = tmp_path / "original.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(
            struct.pack(
                "<16000h",
                *(int(4000 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(16000)),
            )
        )
    original = source.read_bytes()
    workspace = AudioWorkspace()
    factory = Mock(side_effect=workspace.output_for)
    converter = Converter(output_path_factory=factory)
    monkeypatch.setattr(
        converter,
        "_analyze_audio_loudness",
        lambda *_args: {
            "measured_i": "-16",
            "measured_tp": "-1.5",
            "measured_lra": "11",
            "measured_thresh": "-27",
        },
    )
    output = tmp_path / f"explicit.{format_name}" if explicit else None
    if format_name == "wav":
        result = converter.convert_to_wav(source, output_file=output, show_progress=False)
    else:
        result = converter.convert_to_mp3(source, output_file=output)
    assert result.stat().st_size > 0
    assert source.read_bytes() == original
    if explicit:
        assert result == output
        factory.assert_not_called()
    else:
        assert result.parent != source.parent
        factory.assert_called_once()
        workspace.finish(None, None)
        assert not result.exists()


@pytest.mark.requires_ffmpeg
def test_real_cloud_to_local_fallback_conversion_obeys_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "original.wav"
    with wave.open(str(source), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(
            struct.pack(
                "<16000h",
                *(int(4000 * math.sin(2 * math.pi * 440 * i / 16000)) for i in range(16000)),
            )
        )
    original = source.read_bytes()
    transcriber = Transcriber.__new__(Transcriber)
    transcriber.converter = Converter()
    workspace = AudioWorkspace()
    workspace.bind(transcriber)
    session = TranscriptionSession.create("synthetic")
    session.add_file(source, "source")

    def decode(audio: Path, *_args: object) -> Path:
        assert audio.parent != source.parent
        transcript = audio.with_suffix(".txt")
        transcript.write_text("Confirmed synthetic fallback transcript.\n")
        return transcript

    monkeypatch.setattr(transcriber, "_transcribe_local", decode)
    transcript = transcriber._attempt_fallback_transcription(
        source, "openai", session, None, False, RuntimeError("Synthetic API failure")
    )
    workspace.finish(session, None)
    assert source.read_bytes() == original
    assert transcript.read_text() == "Confirmed synthetic fallback transcript.\n"
    assert session.files_cleaned
    assert all(not path.exists() for path in session.files_cleaned)
    assert not (source.parent / "original_16k_mono.wav").exists()
    transcript.unlink()
    transcript.parent.rmdir()
