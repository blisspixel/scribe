"""Max review retains original audio and truthful evidence through CLI archives."""

import json
import os
import shutil
import socket
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from scribe.cli.main import app
from scribe.core.downloader import DownloadResult, URLDownloader
from scribe.models.config import ScribeConfig
from scribe.models.gpu import GPUConfig
from scribe.models.session import TranscriptionSession
from scribe.utils.review_audio import source_hash
from tests.unit.test_transcription_review import acoustic, audio_file


@pytest.mark.parametrize("command", ["record", "url"])
@pytest.mark.parametrize(
    "scenario,policy",
    [
        ("agreement", "required"),
        ("disagreement", "required"),
        ("verifier_missing", "required"),
        ("verifier_missing", "best-effort"),
        ("report_failure", "required"),
        ("report_failure", "best-effort"),
        ("archive_failure", "required"),
    ],
)
def test_max_review_original_source_archive_and_terminal_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, scenario: str, policy: str
) -> None:
    for name in list(os.environ):
        if name.startswith("SCRIBE_"):
            monkeypatch.delenv(name)
    monkeypatch.setattr("scribe.config_file.load_config_file", lambda: {})
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    seed = audio_file(tmp_path / "seed.wav")
    original: list[Path] = []
    conversions: list[Path] = []
    converter_instances = []
    sessions: list[TranscriptionSession] = []
    phase_calls: list[str] = []
    archive = tmp_path / "archive"
    archive.mkdir()
    existing = archive / "capture_transcription.txt"
    existing.write_text("Previously archived synthetic transcript must survive")
    config = ScribeConfig(
        _env_file=None,
        output_folder=archive,
        log_folder=tmp_path / "logs",
        local_backend="cpu",
        local_only=True,
        enable_speaker_diarization=False,
        transcription_verification=policy,
        enable_notes=False,
        enable_joke=False,
        enable_meme=False,
        keep_intermediate_files=False,
        keep_downloads=False,
    )
    assert config.transcription_quality == "max"
    monkeypatch.setattr("scribe.cli.main._load_transcription_config", lambda _spend: config)
    monkeypatch.setattr("scribe.cli.main._show_command_banner", Mock())
    monkeypatch.setattr("scribe.cli.main.setup_logging", Mock(return_value=Mock()))
    monkeypatch.setattr("scribe.cli.main.get_current_log_file", lambda: None)
    monkeypatch.setattr("scribe.cli.consent.ensure_recording_consent", lambda _console: True)
    monkeypatch.setattr("scribe.utils.audio.get_audio_duration", lambda _source: 3)
    monkeypatch.setattr("scribe.core.transcriber.validate_audio_file", lambda *_a, **_kw: None)
    monkeypatch.setattr(GPUConfig, "detect", lambda **_kw: GPUConfig(has_gpu=False))
    monkeypatch.setattr("scribe.core.backends.registry.backend_availability", lambda: {"cpu": True})
    progress = Mock(frame_delay=0.001)
    monkeypatch.setattr(
        "scribe.utils.unified_progress.UnifiedProgress", lambda *_a, **_kw: progress
    )

    def reject_network(*_args, **_kwargs):
        pytest.fail("Max archive controls cannot use models or the network")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)
    monkeypatch.setattr(socket, "getaddrinfo", reject_network)
    monkeypatch.setattr("faster_whisper.WhisperModel", Mock(side_effect=reject_network))
    create = TranscriptionSession.create

    def capture_session(name):
        session = create(name)
        sessions.append(session)
        return session

    monkeypatch.setattr(TranscriptionSession, "create", capture_session)

    def produce_source(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(seed, path)
        original.append(path)
        return path

    class Recorder:
        def __init__(self, _config):
            pass

        def record(self, _name):
            return produce_source(tmp_path / "recordings" / "capture.wav")

    def download(owner, _url):
        return DownloadResult(
            produce_source(owner.output_dir / "capture.wav"), "Synthetic", 3, _url
        )

    monkeypatch.setattr("scribe.cli.main.OBSRecorder", Recorder)
    monkeypatch.setattr(URLDownloader, "download", download)
    monkeypatch.setattr(
        "scribe.utils.validation.validate_media_url", lambda _value: "https://example.invalid/audio"
    )

    class Converter:
        def __init__(self):
            self.output_path_factory = None
            converter_instances.append(self)

        def get_duration(self, _source):
            return 3

        def convert_to_wav(self, source, *, output_file=None, **_kwargs):
            if output_file is None:
                # This is Transcriber's internal preparation, not the CLI conversion.
                assert self.output_path_factory is not None
                output_file = self.output_path_factory(source, "_16k_mono.wav")
            assert output_file.parent != original[0].parent
            shutil.copyfile(source, output_file)
            conversions.append(output_file)
            return output_file

    monkeypatch.setattr("scribe.core.converter.Converter", Converter)
    monkeypatch.setattr("scribe.core.transcriber.Converter", Converter)

    def primary(source, settings, phase):
        assert source == original[0] and settings.model == "large-v3" and not settings.cached_only
        phase("Synthetic primary acoustic phase")
        phase_calls.append("primary")
        return acoustic(source)

    def secondary(source, settings, phase):
        assert source == original[0] and settings.cached_only and settings.prompt == ""
        phase_calls.append("secondary")
        if scenario == "verifier_missing":
            raise FileNotFoundError("Synthetic verifier is not cached")
        result = acoustic(
            source,
            "The limit is fifty units."
            if scenario == "disagreement"
            else "The limit is fifteen units.",
        )
        result.transcript.model = settings.model
        return result

    monkeypatch.setattr("scribe.core.review_engine.bounded_pass", primary)
    monkeypatch.setattr("scribe.core.transcription_review.bounded_pass", secondary)
    if scenario == "report_failure":
        monkeypatch.setattr(
            "scribe.core.transcription_review.publish_review",
            Mock(side_effect=OSError("Synthetic review disk full")),
        )
    if scenario == "archive_failure":
        monkeypatch.setattr(
            "scribe.utils.safe_write.safe_copy",
            Mock(side_effect=OSError("Synthetic archive failure")),
        )
    args = (
        ["record", "--name", "Synthetic", "--no-notes", "--no-joke", "--no-meme"]
        if command == "record"
        else ["url", "https://example.invalid/audio", "--no-docx"]
    )
    result = CliRunner().invoke(app, args)
    review_incomplete = scenario in {"verifier_missing", "report_failure"}
    partial = review_incomplete and policy == "required"
    failed = scenario == "archive_failure"
    assert result.exit_code == (1 if partial or failed else 0), (result.output, result.exception)
    session = sessions[0]
    expected_outcome = "failed" if failed else "partial" if partial else "success"
    assert session.outcome == expected_outcome
    requires_source = review_incomplete or scenario == "disagreement"
    assert session.review_source_required is requires_source
    assert original[0].exists() is (command == "record" or requires_source or failed)
    assert conversions and all(not path.exists() for path in conversions)
    assert any(worker.output_path_factory is not None for worker in converter_instances)
    assert all(path in session.files_cleaned for path in conversions)
    assert (
        original[0] not in session.files_cleaned
        if original[0].exists()
        else original[0] in session.files_cleaned
    )
    assert phase_calls == ["primary", "secondary"]
    assert existing.read_text() == "Previously archived synthetic transcript must survive"
    if command == "url":
        progress.complete.assert_not_called() if failed else progress.complete.assert_called_once_with(
            partial=partial
        )
    else:
        assert "Synthetic primary acoustic phase" in result.output
    summaries = list(archive.glob("*_session_summary.json"))
    assert summaries and json.loads(summaries[0].read_text())["outcome"] == expected_outcome
    if failed:
        assert session.transcript_file.is_file() and session.transcript_file.parent != archive
        assert original[0].is_file()
    else:
        assert session.transcript_file.is_file() and session.transcript_file.parent == archive
        assert session.transcript_file != existing
        assert any(
            Path(move["destination"]) == session.transcript_file for move in session.files_moved
        )
        sidecar = json.loads(session.transcript_file.with_suffix(".json").read_text())
        receipt = sidecar["metadata"]["transcription_review"]
        assert receipt["source_path"] == str(original[0].resolve())
        assert receipt["source_sha256"] == source_hash(seed)
        assert receipt["requires_review"] is requires_source
        assert receipt["status"] == ("partial" if review_incomplete else "complete")
        if scenario != "report_failure":
            manifest = next(path for path in session.files_created if path.name == "review.json")
            governing = json.loads(manifest.read_text())
            assert governing == receipt
            assert all(Path(path).is_file() for path in governing["artifacts"])
            assert manifest.parent.parent == archive
