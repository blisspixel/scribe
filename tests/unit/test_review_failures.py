"""Failure controls at cache, media timeline, and actual command boundaries."""

import json
import socket
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest
from typer.testing import CliRunner

from scribe.core.review_engine import PassSettings, bounded_pass
from scribe.core.transcription_review import complete_review, unavailable_review
from scribe.exceptions import TranscriptionError
from scribe.models.config import ScribeConfig
from scribe.models.gpu import GPUConfig
from scribe.utils.review_audio import prepare_review_audio
from scribe.utils.review_checkpoint import resolve_cached_checkpoint
from tests.unit.test_transcription_review import FakeEngine, acoustic, audio_file, transcript


@pytest.mark.parametrize("missing", ["model.bin", "config.json", "tokenizer.json"])
def test_incomplete_local_checkpoint_never_constructs_engine_or_uses_network(tmp_path, missing):
    for name in ("model.bin", "config.json", "tokenizer.json"):
        if name != missing:
            (tmp_path / name).write_text("synthetic")
    with (
        patch("faster_whisper.utils.download_model", return_value=str(tmp_path)) as cache,
        patch("faster_whisper.WhisperModel") as loader,
        patch.object(socket.socket, "connect", side_effect=AssertionError("egress")),
        patch.object(socket, "getaddrinfo", side_effect=AssertionError("DNS")),
    ):
        with pytest.raises(TranscriptionError, match=missing):
            bounded_pass(tmp_path / "unused.wav", PassSettings("large-v3-turbo"))
    assert cache.call_args.kwargs == {"local_files_only": True}
    loader.assert_not_called()


def test_complete_explicit_checkpoint_skips_hub_lookup(tmp_path):
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (tmp_path / name).write_text("synthetic")
    with patch("faster_whisper.utils.download_model") as hub:
        assert resolve_cached_checkpoint(str(tmp_path)) == tmp_path.resolve()
    hub.assert_not_called()


def test_missing_cache_is_not_retried_online(tmp_path):
    with (
        patch(
            "faster_whisper.utils.download_model", side_effect=FileNotFoundError("not cached")
        ) as hub,
        patch("faster_whisper.WhisperModel") as loader,
    ):
        with pytest.raises(FileNotFoundError, match="not cached"):
            bounded_pass(tmp_path / "unused", PassSettings("large-v3-turbo"))
    hub.assert_called_once_with("turbo", local_files_only=True)
    loader.assert_not_called()


@pytest.mark.parametrize("policy", ["required", "best-effort", "off"])
@pytest.mark.parametrize("timed_primary", [False, True])
def test_music_capability_gap_has_receipt_without_secondary_load(tmp_path, policy, timed_primary):
    from scribe.core.transcriber import Transcriber
    from scribe.models.session import TranscriptionSession
    from scribe.utils.review_audio import source_hash

    source = audio_file(tmp_path / "original.wav")
    primary_path = tmp_path / "lyrics.txt"
    primary_path.write_text("Synthetic retained lyrics")
    config = ScribeConfig(
        output_folder=tmp_path / "out",
        log_folder=tmp_path / "logs",
        transcription_verification=policy,
    )
    session = TranscriptionSession.create("Synthetic")
    session.source_file = source
    with (
        patch("scribe.core.transcriber.Converter"),
        patch.object(GPUConfig, "detect", return_value=GPUConfig(has_gpu=False)),
        patch.object(Transcriber, "release_resources"),
        patch.object(Transcriber, "choose_method", return_value="local"),
        patch.object(Transcriber, "_prepare_audio_for_method", return_value=source),
        patch("scribe.core.transcriber.validate_audio_file"),
        patch("scribe.core.transcription_review.bounded_pass") as verifier,
    ):
        worker = Transcriber(config)

        def music_primary(*args):
            worker.last_transcript = transcript() if timed_primary else None
            return primary_path

        with patch.object(worker, "_transcribe_local", side_effect=music_primary):
            assert worker.transcribe(source, session=session, music_mode=True) == primary_path
    verifier.assert_not_called()
    assert source.exists() and primary_path.read_text() == "Synthetic retained lyrics"
    manifests = [p for p in session.files_created if p.name == "review.json"]
    assert bool(manifests) is (policy != "off")
    assert bool(session.artifact_errors) is (policy == "required")
    assert session.review_source_required is (policy != "off")
    if policy != "off":
        receipt = json.loads(manifests[0].read_text())
        assert receipt["status"] == "partial" and receipt["requires_review"] is True
        assert "unavailable for music" in receipt["error"]
        assert receipt["source_path"] == str(source.resolve())
        assert receipt["source_sha256"] == source_hash(source)
        assert receipt["source_retention"] == "required_for_review"
        assert receipt["primary_options"]["primary_text_path"] == str(primary_path.resolve())
        assert not any(p.name == "secondary.json" for p in session.files_created)


def test_unavailable_review_report_failure_preserves_source_and_primary(tmp_path):
    source = audio_file(tmp_path / "original.wav")
    primary = transcript()
    primary_path = tmp_path / "primary.txt"
    primary_path.write_text(primary.text())
    with patch("scribe.core.transcription_review.publish_review", side_effect=OSError("disk full")):
        receipt, paths = unavailable_review(
            ScribeConfig(output_folder=tmp_path / "out", log_folder=tmp_path / "logs"),
            source,
            primary,
            primary_path,
            "Requested capability unavailable",
        )
    assert receipt.status == "partial" and receipt.requires_review
    assert "disk full" in receipt.error and not paths
    assert source.exists() and primary_path.read_text() == primary.text()
    assert primary.metadata["transcription_review"]["status"] == "partial"


def test_language_scan_failure_preserves_primary_and_required_review_is_partial(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    engine = FakeEngine()
    engine.detect_language = Mock(side_effect=RuntimeError("scan unavailable"))
    with (
        patch("faster_whisper.WhisperModel", return_value=engine),
        patch(
            "faster_whisper.vad.get_speech_timestamps", return_value=[{"start": 0, "end": 16000}]
        ),
    ):
        first = bounded_pass(source, PassSettings("large-v3", cached_only=False))
    assert (
        first.transcript.text()
        and "scan unavailable" in first.transcript.metadata["language_scan_error"]
    )
    assert engine.calls[0][1]["condition_on_previous_text"] is False
    with patch("scribe.core.transcription_review.bounded_pass", return_value=acoustic(source)):
        receipt, paths = complete_review(
            ScribeConfig(output_folder=tmp_path / "out", log_folder=tmp_path / "logs"),
            GPUConfig(has_gpu=False),
            source,
            first.transcript,
            first,
        )
    assert receipt.status == "partial" and "scan failed" in receipt.error
    assert any(path.name == "primary-acoustic.json" and path.exists() for path in paths)


def test_unload_error_does_not_mask_original_decode_error(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    engine = FakeEngine()
    engine.transcribe = Mock(side_effect=RuntimeError("original decode failure"))
    engine.model.unload_model.side_effect = OSError("unload failure")
    with (
        patch("faster_whisper.WhisperModel", return_value=engine),
        patch("faster_whisper.vad.get_speech_timestamps", return_value=[]),
    ):
        with pytest.raises(RuntimeError, match="original decode failure"):
            bounded_pass(source, PassSettings("large-v3", cached_only=False))


def test_explicit_batch_keeps_requested_cap_and_timed_words(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    engine = FakeEngine()
    pipeline = Mock()
    pipeline.transcribe.side_effect = engine.transcribe
    with (
        patch("faster_whisper.WhisperModel", return_value=engine),
        patch("faster_whisper.BatchedInferencePipeline", return_value=pipeline),
        patch("faster_whisper.vad.get_speech_timestamps", return_value=[]),
    ):
        result = bounded_pass(source, PassSettings("medium", batch_size=8, cached_only=False))
    assert pipeline.transcribe.call_args.kwargs["batch_size"] == 8
    assert result.transcript.metadata["decoding"] == "bounded regional batched"
    assert result.transcript.segments[0].words


def test_explicit_unsupported_precision_fails_before_loading(tmp_path):
    with (
        patch("ctranslate2.get_supported_compute_types", return_value={"int8"}),
        patch("faster_whisper.WhisperModel") as engine,
    ):
        with pytest.raises(TranscriptionError, match="unsupported"):
            bounded_pass(
                tmp_path / "unused",
                PassSettings("medium", compute_type="float16", strict_compute_type=True),
            )
    engine.assert_not_called()


@pytest.mark.parametrize("times,expected_error", [([0, 2], False), ([0, 0.2], True)])
def test_media_timestamp_gap_preserved_and_overlap_rejected(tmp_path, times, expected_error):
    source = tmp_path / "source.wav"
    source.write_bytes(b"synthetic media control")
    frames = [SimpleNamespace(time=t, samples=16000, sample_rate=16000, pts=0) for t in times]
    container = Mock()
    container.start_time = 0
    container.decode.return_value = iter(frames)
    context = Mock()
    context.__enter__ = Mock(return_value=container)
    context.__exit__ = Mock(return_value=False)
    normalized = SimpleNamespace(to_ndarray=lambda: np.ones((1, 16000), dtype=np.float32))
    resampler = Mock()
    resampler.resample.side_effect = lambda frame: [] if frame is None else [normalized]
    with (
        patch("scribe.utils.review_audio.av.open", return_value=context),
        patch("scribe.utils.review_audio.av.AudioResampler", return_value=resampler),
    ):
        if expected_error:
            with pytest.raises(TranscriptionError, match="overlapping"):
                with prepare_review_audio(source, 5):
                    pytest.fail("overlapping clock published")
        else:
            with prepare_review_audio(source, 5) as audio:
                assert audio.duration == 3
                assert np.all(audio.read(1, 2) == 0)
                spool = audio.path
            assert not spool.exists()
    assert source.read_bytes() == b"synthetic media control"


@pytest.mark.parametrize("command", ["record", "rec"])
def test_record_cli_quality_and_verification_overrides_reach_config(tmp_path, command):
    from scribe.cli.main import app

    config = ScribeConfig(output_folder=tmp_path / "out", log_folder=tmp_path / "logs")
    observed = []

    def boundary(*args):
        observed.append(
            (
                config.default_model,
                config.transcription_quality,
                config.transcription_verification,
                config.verification_model,
            )
        )
        return False

    with (
        patch("scribe.cli.main._load_transcription_config", return_value=config),
        patch("scribe.cli.main._show_command_banner"),
        patch("scribe.cli.consent.ensure_recording_consent", side_effect=boundary),
    ):
        result = CliRunner().invoke(
            app,
            [
                command,
                "--model",
                "medium",
                "--quality",
                "accurate",
                "--verification",
                "best-effort",
                "--verification-model",
                "small",
            ],
        )
    assert result.exit_code == 0, result.output
    assert observed == [("medium", "accurate", "best-effort", "small")]


@pytest.mark.parametrize("command", ["transcribe", "url"])
@pytest.mark.parametrize(
    "policy,failure,disagreement",
    [(None, True, False), (None, False, True), (None, False, False), ("best-effort", True, False)],
)
def test_actual_cli_review_terminal_outcome_and_source_retention(
    tmp_path, command, policy, failure, disagreement
):
    from scribe.cli.main import app
    from scribe.models.session import TranscriptionSession

    source = audio_file(tmp_path / "source.wav")
    config = ScribeConfig(
        output_folder=tmp_path / "out",
        log_folder=tmp_path / "logs",
        local_backend="cpu",
        local_only=True,
        transcription_verification=policy,
    )
    config.output_folder.mkdir(exist_ok=True)
    converter = Mock()
    converter.get_duration.return_value = 3
    converter.convert_to_wav.return_value = source
    session = TranscriptionSession.create("Synthetic")
    with (
        patch("scribe.cli.main._load_transcription_config", return_value=config),
        patch("scribe.cli.main._show_command_banner"),
        patch("scribe.cli.main.setup_logging"),
        patch("scribe.cli.main.get_current_log_file", return_value=None),
        patch("scribe.cli.main.TranscriptionSession.create", return_value=session),
        patch("scribe.core.transcriber.Converter", return_value=converter),
        patch("scribe.core.converter.Converter", return_value=converter),
        patch("scribe.utils.audio.get_audio_duration", return_value=3),
        patch.object(GPUConfig, "detect", return_value=GPUConfig(has_gpu=False)),
        patch("scribe.core.backends.registry.backend_availability", return_value={"cpu": True}),
        patch("scribe.core.review_engine.bounded_pass", return_value=acoustic(source)),
        patch(
            "scribe.core.transcription_review.bounded_pass",
            side_effect=FileNotFoundError("verifier absent") if failure else None,
            return_value=acoustic(
                source, "different" if disagreement else "The limit is fifteen units."
            ),
        ),
        patch("scribe.utils.unified_progress.UnifiedProgress") as progress,
        patch("scribe.core.downloader.URLDownloader") as downloader,
        patch(
            "scribe.utils.validation.validate_media_url",
            return_value="https://example.invalid/audio.wav",
        ),
        patch("scribe.core.transcriber.Transcriber.cleanup_intermediate_files", return_value=[]),
    ):
        progress.return_value.frame_delay = 0.01
        downloader.return_value.download.return_value = SimpleNamespace(
            file_path=source, title="Synthetic", duration=3
        )
        args = [
            command,
            str(source) if command == "transcribe" else "https://example.invalid/audio.wav",
            "--no-docx",
            "--keep-all",
        ]
        result = CliRunner().invoke(app, args)
    partial = failure and policy != "best-effort"
    assert result.exit_code == (1 if partial else 0), (result.output, result.exception)
    assert ("Transcription Partial" in result.output) is partial
    assert ("Transcription Complete" in result.output) is not partial
    assert session.transcript_file.exists()
    assert session.outcome == ("partial" if partial else "success")
    assert bool(session.artifact_errors) is partial
    retained = failure or disagreement
    assert session.review_source_required is retained
    assert source.exists() is (command == "transcribe" or retained)
    if command == "url" and retained:
        assert "Source audio retained" in result.output
        downloader.return_value.cleanup_owned_output_dir.assert_not_called()
    assert any(
        path.name == "primary-acoustic.json" and path.exists() for path in session.files_created
    )
    assert progress.return_value.stop.called
    assert progress.return_value.complete.called is not partial
    summaries = list(config.output_folder.glob("*_session_summary.json"))
    assert summaries and json.loads(summaries[0].read_text())["outcome"] == session.outcome


@pytest.mark.parametrize("backend", ["mlx", "whispercpp"])
@pytest.mark.parametrize("failure", [False, True])
def test_selected_native_primary_is_honored_without_silent_switch(tmp_path, backend, failure):
    from scribe.core.transcriber import Transcriber
    from scribe.models.session import TranscriptionSession

    source = audio_file(tmp_path / "source.wav")
    primary = transcript(backend=backend)
    native = Mock()
    native.transcribe.side_effect = TranscriptionError("native failure") if failure else None
    native.transcribe.return_value = primary
    config = ScribeConfig(
        output_folder=tmp_path / "out", log_folder=tmp_path / "logs", local_backend=backend
    )
    session = TranscriptionSession.create("Synthetic")
    session.add_file(source, "source")
    converter = Mock()
    converter.convert_to_wav.return_value = source
    with (
        patch("scribe.core.transcriber.Converter", return_value=converter),
        patch.object(GPUConfig, "detect", return_value=GPUConfig(has_gpu=False)),
        patch("scribe.core.backends.select_backend", return_value=backend),
        patch("scribe.core.backends.build_backend", return_value=native),
        patch(
            "scribe.core.transcription_review.bounded_pass", return_value=acoustic(source)
        ) as verifier,
        patch("scribe.core.transcriber.LocalWhisperTranscriber") as fallback,
        patch("scribe.core.transcriber.OpenAITranscriber") as cloud,
    ):
        worker = Transcriber(config)
        if failure:
            with pytest.raises(TranscriptionError, match="native failure"):
                worker.transcribe(source, session=session)
            verifier.assert_not_called()
        else:
            output = worker.transcribe(source, session=session)
            assert output.exists() and worker.last_transcript.backend == backend
            assert session.artifact_errors and session.review_source_required
            assert worker.last_transcript.metadata["transcription_review"]["status"] == "partial"
            verifier.assert_called_once()
    assert source.exists()
    native.transcribe.assert_called_once()
    fallback.assert_not_called()
    cloud.assert_not_called()


def _timestamp_media(path, starts, samples):
    from fractions import Fraction

    import av

    with av.open(str(path), "w", format="matroska") as container:
        stream = container.add_stream("pcm_s16le", rate=16000)
        for start in starts:
            frame = av.AudioFrame.from_ndarray(
                np.full((1, samples), 1000, dtype=np.int16), format="s16", layout="mono"
            )
            frame.sample_rate = 16000
            frame.pts = start
            frame.time_base = Fraction(1, 16000)
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    return path


def test_real_matroska_small_repeated_gaps_keep_original_time(tmp_path):
    source = _timestamp_media(tmp_path / "gaps.mka", (0, 16800, 33600), 16000)
    with prepare_review_audio(source, 10) as prepared:
        assert prepared.duration == 3.1
        assert np.all(prepared.read(1, 1.05) == 0)
        assert np.all(prepared.read(2.05, 2.1) == 0)
    assert source.exists()


def test_real_matroska_timestamp_rounding_does_not_invent_gaps_or_overlap(tmp_path):
    source = _timestamp_media(tmp_path / "rounding.mka", range(0, 200 * 1001, 1001), 1001)
    with prepare_review_audio(source, 20) as prepared:
        assert prepared.samples == 200 * 1001
        assert np.all(prepared.read(0, prepared.duration) > 0)
    assert source.exists()
