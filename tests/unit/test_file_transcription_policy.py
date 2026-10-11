"""Exercise file policy through orchestration and real backend call boundaries."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from scribe.cli.main import app
from scribe.core.backends.hardware import HardwareInfo
from scribe.core.local_whisper import LocalWhisperTranscriber
from scribe.core.transcriber import Transcriber
from scribe.exceptions import TranscriptionError
from scribe.models.config import ScribeConfig
from scribe.models.gpu import GPUConfig
from scribe.models.transcript import Transcript, TranscriptSegment
from scribe.utils.model_selection import resolve_local_language


@pytest.fixture
def converter_boundary(monkeypatch):
    """Policy tests do not perform audio conversion or require installed FFmpeg."""
    monkeypatch.setattr("scribe.core.transcriber.Converter", Mock())


@pytest.mark.parametrize(
    ("vendor", "vram", "tier_model"),
    [
        ("cpu", 0, "base"),
        ("amd", 0, "base"),
        ("intel", 0, "base"),
        ("apple", 16, "base"),
        ("nvidia", 4, "small"),
        ("nvidia", 8, "large-v2"),
        ("nvidia", 24, "large-v3"),
    ],
)
def test_accurate_file_model_survives_hardware_tiers(
    vendor, vram, tier_model, tmp_path, converter_boundary
):
    config = ScribeConfig(_env_file=None)
    gpu = GPUConfig(has_gpu=vendor == "nvidia", model_size=tier_model, gpu_memory_gb=vram)
    engine = Mock(last_transcript=None)
    engine.transcribe.return_value = tmp_path / "out.txt"
    with (
        patch.object(GPUConfig, "detect", return_value=gpu),
        patch("scribe.core.backends.detect_hardware", return_value=HardwareInfo(vendor=vendor)),
        patch(
            "scribe.core.backends.registry.backend_availability",
            return_value={"cpu": True, "faster-whisper": True},
        ),
        patch(
            "scribe.core.transcriber.LocalWhisperTranscriber", return_value=engine
        ) as constructor,
    ):
        Transcriber(config)._transcribe_local(tmp_path / "a.wav", None)
    assert constructor.call_args.kwargs["model_size"] == "large-v3"
    assert constructor.call_args.kwargs["language"] is None
    assert constructor.call_args.kwargs["batch_size"] == 0


def test_explicit_cpu_backend_is_cpu_even_on_nvidia(tmp_path, converter_boundary):
    config = ScribeConfig(local_backend="cpu", local_compute_type="float32", local_batch_size=8)
    gpu = GPUConfig(has_gpu=True, gpu_name="NVIDIA", use_fp16=True)
    with (
        patch.object(GPUConfig, "detect", return_value=gpu),
        patch(
            "scribe.core.backends.registry.backend_availability",
            return_value={"cpu": True, "faster-whisper": True},
        ),
        patch("scribe.core.transcriber.LocalWhisperTranscriber") as constructor,
    ):
        Transcriber(config)._transcribe_local(tmp_path / "a.wav", None)
    assert constructor.call_args.kwargs["gpu_config"].has_gpu is False
    assert constructor.call_args.kwargs["compute_type"] == "float32"
    assert constructor.call_args.kwargs["batch_size"] == 8
    assert gpu.has_gpu is True  # detected hardware remains distinct from execution


def test_explicit_unavailable_backend_fails_before_another_engine_runs(
    tmp_path, converter_boundary
):
    with (
        patch(
            "scribe.core.backends.registry.backend_availability",
            return_value={"cpu": True, "mlx": False},
        ),
        patch("scribe.core.transcriber.LocalWhisperTranscriber") as engine,
    ):
        with pytest.raises(TranscriptionError, match="Requested local backend"):
            Transcriber(ScribeConfig(local_backend="mlx"))._transcribe_local(
                tmp_path / "a.wav", None
            )
    engine.assert_not_called()


@pytest.mark.parametrize("language", ["en", "es", "ja"])
def test_detected_language_and_backend_score_are_preserved(language, tmp_path):
    worker = LocalWhisperTranscriber(gpu_config=GPUConfig(has_gpu=False))
    worker.model = Mock()
    worker.model.transcribe.return_value = (
        [SimpleNamespace(start=0, end=1, text="test")],
        SimpleNamespace(language=language, language_probability=0.91),
    )
    transcript = worker._execute_transcription(tmp_path / "audio.wav", 1.0, "")
    assert worker.model.transcribe.call_args.kwargs["language"] is None
    assert transcript.language == language
    assert transcript.metadata["detected_language"] == language
    assert transcript.metadata["language_probability"] == 0.91
    assert transcript.metadata["language_mode"] == "automatic"
    assert worker._prepare_initial_prompt(None, music_mode=False) == ""


def test_forced_language_is_not_reported_as_detected(tmp_path):
    worker = LocalWhisperTranscriber(language="es", gpu_config=GPUConfig(has_gpu=False))
    worker.model = Mock()
    worker.model.transcribe.return_value = (
        [],
        SimpleNamespace(language="es", language_probability=1.0),
    )
    transcript = worker._execute_transcription(tmp_path / "audio.wav", 1.0, "")
    assert worker.model.transcribe.call_args.kwargs["language"] == "es"
    assert transcript.language == "es"
    assert transcript.metadata["detected_language"] is None
    assert transcript.metadata["language_probability"] is None
    assert transcript.metadata["language_mode"] == "forced"


@pytest.mark.parametrize("primary", ["en", "es", "ja"])
def test_primary_is_a_manual_preset_not_an_auto_detection_prior(primary):
    assert resolve_local_language(None, True, primary) is None
    assert resolve_local_language(None, False, primary) == primary
    assert resolve_local_language("fr", True, primary) == "fr"
    assert resolve_local_language("fr", False, primary) == "fr"


def test_cpu_precision_is_forwarded_without_implicit_precision_fallback():
    worker = LocalWhisperTranscriber(gpu_config=GPUConfig(has_gpu=False), compute_type="float32")
    with (
        patch("ctranslate2.get_supported_compute_types", return_value={"int8", "float32"}),
        patch("faster_whisper.WhisperModel") as constructor,
        patch("scribe.core.local_whisper.get_gpu_manager") as manager,
        patch("psutil.virtual_memory", return_value=SimpleNamespace(available=32 * 1024**3)),
    ):
        manager.return_value.get_current_model.return_value = None
        constructor.return_value.model.compute_type = "float32"
        worker._load_model()
    assert constructor.call_args.kwargs["device"] == "cpu"
    assert constructor.call_args.kwargs["compute_type"] == "float32"
    assert worker.compute_type == "float32"


def test_unsupported_precision_fails_before_model_download():
    worker = LocalWhisperTranscriber(gpu_config=GPUConfig(has_gpu=False), compute_type="float16")
    with (
        patch("ctranslate2.get_supported_compute_types", return_value={"int8", "float32"}),
        patch("faster_whisper.WhisperModel") as constructor,
    ):
        with pytest.raises(TranscriptionError, match="No precision fallback"):
            worker._load_model()
    constructor.assert_not_called()


@pytest.mark.parametrize("command", ["transcribe", "url", "batch", "music"])
def test_file_commands_offer_profile_and_automatic_language(command):
    from click import unstyle

    result = CliRunner().invoke(app, [command, "--help"])
    assert result.exit_code == 0
    assert "--quality" in unstyle(result.output)
    assert "auto detects" in unstyle(result.output)


def test_cli_auto_language_overrides_pinned_language_and_primary(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"audio")
    config = ScribeConfig(default_language="en", auto_detect_language=False, primary_language="ja")
    with (
        patch("scribe.cli.main._load_transcription_config", return_value=config),
        patch("scribe.cli.main.setup_logging"),
        patch(
            "scribe.cli.main.Transcriber", side_effect=TranscriptionError("stop before decoding")
        ),
    ):
        result = CliRunner().invoke(
            app, ["transcribe", str(audio), "--language", "auto", "--quality", "fast"]
        )
    assert result.exit_code != 0
    assert config.default_language is None
    assert config.auto_detect_language is True
    assert config.transcription_quality == "fast"
    assert (
        resolve_local_language(
            config.default_language, config.auto_detect_language, config.primary_language
        )
        is None
    )


@pytest.mark.parametrize("setting", [{"local_compute_type": "float32"}, {"local_batch_size": 8}])
def test_native_backend_rejects_unsupported_explicit_execution_setting(
    setting, tmp_path, converter_boundary
):
    config = ScribeConfig(local_backend="whispercpp", **setting)
    with (
        patch(
            "scribe.core.backends.registry.backend_availability",
            return_value={"cpu": True, "whispercpp": True},
        ),
        patch("scribe.core.backends.build_backend") as builder,
    ):
        with pytest.raises(TranscriptionError, match="does not support"):
            Transcriber(config)._transcribe_local(tmp_path / "audio.wav", None)
    builder.assert_not_called()


@pytest.mark.parametrize("backend", ["mlx", "whispercpp"])
def test_native_music_autodetection_never_loads_faster_whisper(
    backend, tmp_path, converter_boundary
):
    transcript = Transcript(
        segments=[TranscriptSegment(start=0, end=1, text="Hola")],
        language="es",
        backend=backend,
    )
    engine = Mock()
    engine.transcribe.return_value = transcript
    with (
        patch.object(GPUConfig, "detect", return_value=GPUConfig(has_gpu=False)),
        patch(
            "scribe.core.backends.registry.backend_availability",
            return_value={backend: True, "cpu": True},
        ),
        patch("scribe.core.backends.build_backend", return_value=engine),
        patch("scribe.core.transcriber.LocalWhisperTranscriber") as faster_whisper,
        patch.object(Transcriber, "_detect_language_for_music") as prepass,
        patch("scribe.core.local_whisper.write_clean_transcript"),
        patch("scribe.utils.audio.get_audio_duration", return_value=1.0),
    ):
        Transcriber(ScribeConfig(local_backend=backend))._transcribe_local(
            tmp_path / "song.wav", None, music_mode=True
        )
    assert engine.transcribe.call_args.kwargs["language"] is None
    faster_whisper.assert_not_called()
    prepass.assert_not_called()


def test_music_prepass_reuses_decoder_and_emits_one_cpu_guidance(tmp_path, converter_boundary):
    model = Mock()
    model.transcribe.side_effect = [
        (
            [SimpleNamespace(start=0, end=1, text="Hola a todo el mundo")],
            SimpleNamespace(language="es", language_probability=0.91),
        ),
        (
            [SimpleNamespace(start=0, end=1, text="Hola a todo el mundo")],
            SimpleNamespace(language="es", language_probability=1.0),
        ),
    ]
    gpu = GPUConfig(has_gpu=False)
    with (
        patch.object(GPUConfig, "detect", return_value=gpu),
        patch("scribe.core.backends.detect_hardware", return_value=HardwareInfo(vendor="cpu")),
        patch("scribe.core.backends.registry.backend_availability", return_value={"cpu": True}),
        patch(
            "scribe.core.transcriber.LocalWhisperTranscriber", wraps=LocalWhisperTranscriber
        ) as worker,
        patch("faster_whisper.WhisperModel", return_value=model) as load,
        patch("scribe.core.local_whisper.get_gpu_manager") as manager,
        patch("psutil.virtual_memory", return_value=SimpleNamespace(available=32 * 1024**3)),
        patch("scribe.core.local_whisper.get_audio_duration", return_value=1.0),
        patch.object(LocalWhisperTranscriber, "_write_clean_transcript"),
        patch("scribe.core.local_whisper.logger") as cpu_log,
        patch("scribe.core.transcriber.logger") as selector_log,
    ):
        manager.return_value.get_current_model.return_value = None
        transcriber = Transcriber(ScribeConfig())
        assert transcriber.choose_method("local") == "local"
        assert transcriber.choose_method("auto") == "local"
        transcriber._transcribe_local(tmp_path / "song.wav", None, music_mode=True)
    worker.assert_called_once()
    load.assert_called_once()
    assert model.transcribe.call_args_list[0].kwargs["language"] is None
    assert model.transcribe.call_args_list[1].kwargs["language"] == "es"
    assert transcriber.last_transcript.metadata["language_mode"] == "automatic (music pre-pass)"
    assert transcriber.last_transcript.metadata["language_probability"] == 0.91
    guidance = [call for call in cpu_log.warning.call_args_list if "CPU int8:" in str(call)]
    assert len(guidance) == 1
    selector_log.warning.assert_not_called()


def test_music_explicit_language_bypasses_detection(tmp_path, converter_boundary):
    engine = Mock(last_transcript=None)
    with (
        patch.object(GPUConfig, "detect", return_value=GPUConfig(has_gpu=False)),
        patch("scribe.core.transcriber.LocalWhisperTranscriber", return_value=engine),
        patch.object(Transcriber, "_detect_language_for_music") as prepass,
    ):
        Transcriber(ScribeConfig(default_language="ja"))._transcribe_faster_whisper(
            tmp_path / "song.wav", "large-v3", "ja", None, music_mode=True
        )
    prepass.assert_not_called()
    engine.transcribe.assert_called_once()
