from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from scribe.core.local_whisper import LocalWhisperTranscriber, transcribe_with_local_whisper
from scribe.exceptions import TranscriptionError
from scribe.models.gpu import GPUConfig
from scribe.models.transcript import Transcript, TranscriptSegment


def _gpu_config() -> GPUConfig:
    return GPUConfig(
        has_gpu=True,
        gpu_name="NVIDIA RTX 4090",
        gpu_memory_gb=24.0,
        cuda_available=True,
        cuda_version="12.4",
        model_size="large-v3",
        beam_size=10,
        batch_size=16,
        use_fp16=True,
        enable_tensor_cores=True,
        recommendation="local",
        reason="GPU available",
    )


def test_init_applies_gpu_optimizations() -> None:
    config = _gpu_config()

    with patch("scribe.core.local_whisper.set_gpu_optimizations") as mock_set:
        transcriber = LocalWhisperTranscriber(gpu_config=config)

    assert transcriber.gpu_config is config
    mock_set.assert_called_once_with(enable_tensor_cores=True)


def test_detect_language_returns_detected_language(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_text("audio")
    transcriber = LocalWhisperTranscriber(gpu_config=_gpu_config())
    transcriber.model = Mock()
    transcriber.model.transcribe.return_value = (
        [SimpleNamespace(text="hello world", end=5.0)],
        SimpleNamespace(language="en", language_probability=0.95),
    )

    detected = transcriber.detect_language(audio_path)

    assert detected == ("en", 0.95, True)


def test_detect_language_handles_low_confidence_and_failures(tmp_path: Path) -> None:
    audio_path = tmp_path / "audio.wav"
    audio_path.write_text("audio")
    transcriber = LocalWhisperTranscriber(gpu_config=_gpu_config())
    transcriber.model = Mock()
    transcriber.model.transcribe.return_value = (
        [SimpleNamespace(text="hello world", end=5.0)],
        SimpleNamespace(language="fr", language_probability=0.2),
    )

    assert transcriber.detect_language(audio_path) == (None, 0.2, True)

    transcriber.model.transcribe.side_effect = RuntimeError("boom")
    assert transcriber.detect_language(audio_path) == (None, 0.0, True)


def test_load_model_maps_legacy_turbo_alias() -> None:
    transcriber = LocalWhisperTranscriber(model_size="large-v3-turbo", gpu_config=_gpu_config())
    whisper_model = Mock()
    mock_module = SimpleNamespace(WhisperModel=whisper_model)
    gpu_manager = Mock(get_current_model=Mock(return_value=None))

    with (
        patch.dict("sys.modules", {"faster_whisper": mock_module}),
        patch("scribe.core.local_whisper.get_gpu_manager", return_value=gpu_manager),
    ):
        transcriber._load_model()

    whisper_model.assert_called_once()
    assert whisper_model.call_args.args[0] == "turbo"
    assert transcriber.model == whisper_model.return_value


def test_load_model_wraps_missing_dependency() -> None:
    transcriber = LocalWhisperTranscriber(gpu_config=_gpu_config())

    with patch.dict("sys.modules", {"faster_whisper": None}):
        with pytest.raises(TranscriptionError, match="faster-whisper not installed"):
            transcriber._load_model()


def test_generate_output_path_and_duration_correction(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting_16k_mono.wav"
    audio_path.write_text("audio")
    original_mp4 = tmp_path / "meeting.mp4"
    original_mp4.write_text("video")
    transcriber = LocalWhisperTranscriber(gpu_config=_gpu_config())

    output_path = transcriber._generate_output_path(audio_path, None)
    assert output_path.name == "meeting_transcription.txt"

    with patch("scribe.core.local_whisper.get_audio_duration", return_value=120.0):
        corrected = transcriber._validate_and_correct_duration(audio_path, 8000.0)

    assert corrected == 120.0


def test_detect_silence_if_needed_returns_empty_on_skip_or_failure(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting.wav"
    audio_path.write_text("audio")
    transcriber = LocalWhisperTranscriber(gpu_config=_gpu_config())

    assert transcriber._detect_silence_if_needed(audio_path, 100.0, True) == []

    with patch(
        "scribe.core.local_whisper.detect_silence_periods",
        return_value=[(120.0, 260.0)],
    ):
        assert transcriber._detect_silence_if_needed(audio_path, 600.0, True) == [(120.0, 260.0)]

    with patch(
        "scribe.core.local_whisper.detect_silence_periods",
        side_effect=RuntimeError("bad"),
    ):
        assert transcriber._detect_silence_if_needed(audio_path, 600.0, True) == []


def test_prepare_initial_prompt_respects_modes() -> None:
    transcriber = LocalWhisperTranscriber(gpu_config=_gpu_config())

    assert "Meeting recording" in transcriber._prepare_initial_prompt(None, music_mode=False)
    assert transcriber._prepare_initial_prompt("Song lyrics.", music_mode=True) == "Song lyrics."
    assert "Key terms: alpha, beta" in transcriber._prepare_initial_prompt(
        "alpha, beta", music_mode=False
    )


def test_execute_transcription_returns_transcript(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting.wav"
    audio_path.write_text("audio")
    transcriber = LocalWhisperTranscriber(gpu_config=_gpu_config())
    transcriber.model = Mock()
    transcriber.model.transcribe.return_value = (
        [
            SimpleNamespace(start=0.0, end=1.5, text=" Hello "),
            SimpleNamespace(start=2.0, end=3.5, text=" world "),
        ],
        SimpleNamespace(),
    )

    transcript = transcriber._execute_transcription(audio_path, 60.0, "prompt")

    assert isinstance(transcript, Transcript)
    assert transcript.backend == "faster-whisper"
    assert transcript.duration == 60.0
    assert [(s.start, s.end, s.text) for s in transcript.segments] == [
        (0.0, 1.5, " Hello "),
        (2.0, 3.5, " world "),
    ]


def test_transcribe_success_and_error_paths(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting.wav"
    audio_path.write_text("audio")
    output_path = tmp_path / "meeting.txt"
    transcriber = LocalWhisperTranscriber(gpu_config=_gpu_config())

    with (
        patch("scribe.core.local_whisper.get_audio_duration", return_value=120.0),
        patch.object(transcriber, "_load_model"),
        patch.object(transcriber, "_detect_silence_if_needed", return_value=[]),
        patch.object(
            transcriber,
            "_execute_transcription",
            return_value=Transcript(
                segments=[TranscriptSegment(start=0.0, end=1.0, text="Hello")], duration=120.0
            ),
        ),
        patch.object(transcriber, "_write_clean_transcript") as mock_write,
        patch("scribe.core.local_whisper.clear_gpu_cache") as mock_clear,
    ):
        result = transcriber.transcribe(audio_path, output_path=output_path, detect_silence=False)

    assert result == output_path
    mock_write.assert_called_once()
    mock_clear.assert_called_once()

    with (
        patch("scribe.core.local_whisper.get_audio_duration", return_value=0.5),
        patch.object(transcriber, "_load_model"),
        patch.object(transcriber, "_detect_silence_if_needed", return_value=[]),
        patch.object(
            transcriber,
            "_execute_transcription",
            return_value=Transcript(segments=[], duration=0.5),
        ),
        pytest.raises(TranscriptionError, match="too short"),
    ):
        transcriber.transcribe(audio_path, output_path=output_path)


def test_write_clean_transcript_includes_header_and_silence_marker(tmp_path: Path) -> None:
    output_path = tmp_path / "meeting.txt"
    audio_path = tmp_path / "meeting_2025-11-07_16k_mono.wav"
    audio_path.write_text("audio")
    transcriber = LocalWhisperTranscriber(gpu_config=_gpu_config())

    with (
        patch("scribe.core.local_whisper.extract_date_from_filename", return_value="2025-11-07"),
        patch("scribe.core.local_whisper.format_date", return_value="November 07, 2025"),
        patch("scribe.core.local_whisper.format_duration_minutes", return_value="2 minutes"),
        patch("scribe.core.local_whisper.format_timestamp", side_effect=["00:02:00", "00:04:40"]),
    ):
        transcriber._write_clean_transcript(
            transcript=Transcript(
                segments=[TranscriptSegment(start=300.0, end=330.0, text=" Hello world ")],
                duration=120.0,
            ),
            output_path=output_path,
            audio_path=audio_path,
            silence_periods=[(120.0, 280.0)],
        )

    content = output_path.read_text(encoding="utf-8")
    assert "Meeting: meeting_2025-11-07" in content
    assert "Date: November 07, 2025" in content
    assert "[NO AUDIO FOR 3 MINUTES - 00:02:00 to 00:04:40]" in content
    assert "Hello world" in content


def test_transcribe_with_local_whisper_convenience_wrapper(tmp_path: Path) -> None:
    audio_path = tmp_path / "meeting.wav"
    audio_path.write_text("audio")
    expected = tmp_path / "meeting.txt"

    with patch("scribe.core.local_whisper.LocalWhisperTranscriber") as mock_class:
        mock_class.return_value.transcribe.return_value = expected
        result = transcribe_with_local_whisper(audio_path, model_size="medium", language="es")

    assert result == expected
    mock_class.assert_called_once_with(model_size="medium", language="es")
