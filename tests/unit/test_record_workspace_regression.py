"""Recording outputs survive owned conversion cleanup and terminal failures."""

import json
import math
import socket
import struct
import wave
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from scribe.cli.main import app
from scribe.core.local_whisper import write_clean_transcript
from scribe.core.transcriber import Transcriber
from scribe.exceptions import ProcessError, TranscriptionError
from scribe.models.config import ScribeConfig
from scribe.models.gpu import GPUConfig
from scribe.models.session import TranscriptionSession
from scribe.models.transcript import Transcript, TranscriptSegment


@pytest.mark.parametrize("failure", [None, "conversion", "asr", "summary"])
def test_record_archives_real_decoder_paths_before_workspace_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str | None
) -> None:
    archive = tmp_path / "archive"
    source = tmp_path / "capture" / "meeting.wav"
    unrelated = source.with_name("previous_converted.mp3")
    source.parent.mkdir()
    unrelated.write_bytes(b"Unrelated synthetic recording must survive")
    conversions: list[Path] = []
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    monkeypatch.setattr("scribe.config_file.load_config_file", lambda: {})
    config = ScribeConfig(
        _env_file=None,
        output_folder=archive,
        log_folder=tmp_path / "logs",
        local_only=True,
        enable_notes=False,
        enable_joke=False,
        enable_meme=False,
        keep_intermediate_files=False,
    )
    monkeypatch.setattr("scribe.cli.main._load_transcription_config", lambda _spend: config)
    monkeypatch.setattr("scribe.cli.main._show_command_banner", Mock())
    monkeypatch.setattr("scribe.cli.main.setup_logging", Mock(return_value=Mock()))
    monkeypatch.setattr("scribe.cli.consent.ensure_recording_consent", lambda _console: True)
    monkeypatch.setattr(GPUConfig, "detect", lambda **_kwargs: GPUConfig(has_gpu=False))

    def reject_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Recording ownership tests cannot contact a network")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket, "getaddrinfo", reject_network)
    real_decoder = Mock(side_effect=AssertionError("No ASR model may load in this test"))
    monkeypatch.setattr("scribe.core.transcriber.LocalWhisperTranscriber", real_decoder)

    class SyntheticRecorder:
        def __init__(self, _config: ScribeConfig) -> None:
            pass

        def record(self, _name: str) -> Path:
            with wave.open(str(source), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(
                    struct.pack(
                        "<16000h",
                        *(
                            int(4000 * math.sin(2 * math.pi * 440 * i / 16000))
                            for i in range(16000)
                        ),
                    )
                )
            return source

    class SyntheticConverter:
        def __init__(self) -> None:
            self.output_path_factory = None

        def convert_to_wav(self, _source: Path, *, output_file: Path, **_kwargs: object) -> Path:
            assert output_file.parent != source.parent
            output_file.write_bytes(source.read_bytes())
            conversions.append(output_file)
            if failure == "conversion":
                raise ProcessError("Synthetic owned conversion failure")
            return output_file

    def decode(
        owner: Transcriber,
        audio: Path,
        _session: TranscriptionSession,
        *_args: object,
    ) -> Path:
        if failure == "asr":
            raise TranscriptionError("Synthetic ASR failure")
        owner.last_transcript = Transcript(
            segments=[TranscriptSegment(start=0, end=1, text="Confirmed synthetic words.")],
            language="en",
            duration=1,
            backend="synthetic",
        )
        # Match the real local writer: output follows the actual converted audio.
        path = audio.with_name(f"{audio.stem.replace('_16k_mono', '')}_transcription.txt")
        write_clean_transcript(owner.last_transcript, path, audio, [])
        return path

    monkeypatch.setattr("scribe.cli.main.OBSRecorder", SyntheticRecorder)
    monkeypatch.setattr("scribe.core.converter.Converter", SyntheticConverter)
    monkeypatch.setattr("scribe.core.transcriber.Converter", SyntheticConverter)
    monkeypatch.setattr(Transcriber, "_transcribe_local", decode)
    save_summary = TranscriptionSession.save_summary
    summary_calls = 0

    def save(owner: TranscriptionSession, output_dir: Path) -> Path:
        nonlocal summary_calls
        summary_calls += 1
        if failure == "summary" and summary_calls == 1:
            raise OSError("Synthetic summary write failure")
        return save_summary(owner, output_dir)

    monkeypatch.setattr(TranscriptionSession, "save_summary", save)
    result = CliRunner().invoke(
        app,
        ["record", "--name", "Synthetic meeting", "--method", "local", "--no-joke", "--no-meme"],
    )
    assert result.exit_code == (0 if failure is None else 1), result.output
    summary = json.loads(next(archive.glob("*_session_summary.json")).read_text())
    assert summary["outcome"] == ("success" if failure is None else "failed")
    assert source.is_file()
    assert summary["source_file"] == str(source)
    assert str(source) in summary["files_created"]  # This command created the recording.
    assert str(source) not in summary["files_cleaned"]
    assert unrelated.read_bytes() == b"Unrelated synthetic recording must survive"
    assert len(conversions) == 1
    assert all(not path.exists() for path in conversions)
    assert str(conversions[0]) in summary["files_cleaned"]
    real_decoder.assert_not_called()
    if failure in ("conversion", "asr"):
        assert summary["transcript_file"] is None
        assert not conversions[0].parent.exists()
        assert "Recording & Transcription Complete" not in result.output
        return
    try:
        transcript = Path(summary["transcript_file"])
        assert transcript.parent == archive
        assert "Confirmed synthetic words" in transcript.read_text()
        assert Path(summary["docx_file"]).parent == archive
        assert Path(summary["docx_file"]).is_file()
        assert not conversions[0].parent.exists()
        if failure == "summary":
            assert summary_calls >= 2
            assert "Synthetic summary write failure" in summary["error_message"]
            assert "Recording & Transcription Complete" not in result.output
    finally:
        # The unfixed path retains artifacts in /tmp; do not leak synthetic evidence.
        if conversions[0].parent.exists():
            for created in summary["files_created"]:
                path = Path(created)
                if path.parent == conversions[0].parent:
                    path.unlink(missing_ok=True)
            conversions[0].parent.rmdir()
