"""Bounded primary output preserves the existing model-free silence policy."""

import socket
from pathlib import Path
from unittest.mock import Mock

import pytest

from scribe.core.transcriber import Transcriber
from scribe.models.config import ScribeConfig
from scribe.models.transcript import Transcript, TranscriptSegment


@pytest.mark.parametrize(
    "enabled,duration,error,expected",
    [
        (True, 400, None, [(10.0, 315.0)]),
        (False, 400, None, []),
        (True, 300, None, []),
        (True, 400, RuntimeError("Synthetic detector failure"), []),
        (True, 400, ValueError("Synthetic invalid audio"), []),
        (True, 400, OSError("Synthetic unavailable source"), []),
    ],
)
def test_bounded_writer_preserves_silence_markers_without_loading_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled, duration, error, expected
) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("Writing an existing acoustic transcript cannot load models or use networking")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr("faster_whisper.WhisperModel", forbidden)
    monkeypatch.setattr("scribe.core.transcriber.LocalWhisperTranscriber", forbidden)
    detector = Mock(return_value=[(10.0, 315.0)], side_effect=error)
    monkeypatch.setattr("scribe.core.local_whisper.detect_silence_periods", detector)
    original = tmp_path / "original.mp4"
    converted = tmp_path / "workspace" / "original_16k_mono.wav"
    converted.parent.mkdir()
    # Exercise only the output boundary: no converter or hardware constructor is needed.
    worker = Transcriber.__new__(Transcriber)
    worker.config = ScribeConfig(
        _env_file=None,
        output_folder=tmp_path / "archive",
        log_folder=tmp_path / "logs",
        enable_silence_detection=enabled,
    )
    worker._review_source = original
    transcript = Transcript(
        [
            TranscriptSegment(0, 5, "Before the pause."),
            TranscriptSegment(315, 400, "After the pause."),
        ],
        duration=duration,
        model="large-v3",
        backend="faster-whisper",
    )
    output = worker._write_bounded_primary(converted, transcript, None)

    assert output == converted.parent / "original_transcription.txt"
    text = output.read_text()
    assert "Meeting: original" in text
    assert "Before the pause." in text and "After the pause." in text
    assert ("[NO AUDIO FOR 5 MINUTES - 00:00:10 to 00:05:15]" in text) is bool(expected)
    assert transcript.metadata["silence_periods"] == [list(span) for span in expected]
    assert worker.last_transcript is transcript
    if enabled and duration > 300:
        detector.assert_called_once_with(
            original, silence_threshold=-45.0, min_silence_duration=60.0
        )
    else:
        detector.assert_not_called()
