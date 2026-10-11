"""Acoustic review policy, source binding, bounded decode, and honest failure outcomes."""

import json
import wave
from dataclasses import replace
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from typer.testing import CliRunner

from scribe.core.language_evidence import decoding_regions, scan_bounds
from scribe.core.review_engine import PassSettings, bounded_pass
from scribe.core.transcription_review import complete_review, pass_settings
from scribe.exceptions import TranscriptionError
from scribe.models.config import ScribeConfig
from scribe.models.gpu import GPUConfig
from scribe.models.transcript import Transcript, TranscriptSegment, TranscriptWord
from scribe.models.transcription_review import (
    AcousticDiagnostic,
    AcousticPass,
    LanguageWindow,
    ReviewReceipt,
)
from scribe.utils.model_selection import resolve_verification, resolve_verifier_model
from scribe.utils.review_audio import prepare_review_audio, source_hash
from scribe.utils.transcript_review import (
    compare_passes,
    primary_flags,
    render_review,
)


@pytest.fixture
def cached_checkpoint(tmp_path):
    checkpoint = tmp_path / "checkpoint"
    checkpoint.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (checkpoint / name).write_text("synthetic checkpoint")
    with patch("faster_whisper.utils.download_model", return_value=str(checkpoint)):
        yield checkpoint


def audio_file(path: Path, seconds: float = 3) -> Path:
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes((np.ones(round(seconds * 16000), dtype="<i2") * 1000).tobytes())
    return path


def transcript(text="The limit is fifteen units.", language="en", backend="faster-whisper"):
    return Transcript(
        [TranscriptSegment(0, 3, text)],
        language=language,
        duration=3,
        backend=backend,
        model="large-v3",
        metadata={"requested_language": None},
    )


def acoustic(source: Path, text="The limit is fifteen units.", language="en"):
    return AcousticPass(
        transcript(text, language),
        [LanguageWindow(0, 3, ((language, 0.95),), 3, "speech")],
        [],
        0.2,
        source_hash(source),
        str(source.resolve()),
        3,
    )


@pytest.mark.parametrize(
    "quality,expected",
    [("max", "required"), ("accurate", "off"), ("balanced", "off"), ("fast", "off")],
)
@pytest.mark.parametrize("override", [None, "required", "best-effort", "off"])
def test_profile_and_explicit_review_precedence(quality, expected, override):
    assert resolve_verification(quality, override) == (override or expected)


@pytest.mark.parametrize(
    "primary,expected",
    [
        ("large-v3", "large-v3-turbo"),
        ("turbo", "large-v3"),
        ("large-v3-turbo", "large-v3"),
        ("small", "large-v3-turbo"),
    ],
)
def test_distinct_default_checkpoint_and_explicit_model(primary, expected):
    assert resolve_verifier_model(primary, None) == expected
    assert resolve_verifier_model(primary, "medium") == "medium"


def test_default_max_and_config_env_cli_precedence(tmp_path, monkeypatch):
    from scribe import config_file
    from scribe.cli.transcription_review import apply_review_options

    path = tmp_path / "config.toml"
    path.write_text(
        '[transcription]\nquality="accurate"\nverification="off"\nverification_model="small"\n'
    )
    monkeypatch.setattr(config_file, "CONFIG_PATH", path)
    monkeypatch.setenv("SCRIBE_TRANSCRIPTION_QUALITY", "max")
    monkeypatch.setenv("SCRIBE_TRANSCRIPTION_VERIFICATION", "best-effort")
    config = ScribeConfig(
        _env_file=None, output_folder=tmp_path / "out", log_folder=tmp_path / "logs"
    )
    assert config.transcription_quality == "max"
    assert config.transcription_verification == "best-effort"
    assert config.verification_model == "small"
    apply_review_options(config, "required", "large-v3")
    assert config.transcription_verification == "required"
    assert config.verification_model == "large-v3"
    apply_review_options(config, None, None)
    assert config.transcription_verification == "required"


@given(st.floats(min_value=0.001, max_value=86400, allow_nan=False, allow_infinity=False))
def test_language_grid_covers_terminal_and_all_recording(duration):
    bounds = scan_bounds(duration)
    assert bounds[0][0] == 0 and bounds[-1][1] == duration
    assert all(0 <= start < end <= duration and end - start <= 15 for start, end in bounds)
    assert all(second[0] <= first[1] for first, second in pairwise(bounds))


@pytest.mark.parametrize(
    "status,candidates,expected",
    [
        ("speech", (("es", 0.9), ("en", 0.1)), "es"),
        ("speech", (("en", 0.6), ("es", 0.4)), None),
        ("no_speech", (("en", 1.0),), None),
        ("uncertain", (("en", 1.0),), None),
        ("speech", (), None),
    ],
)
def test_model_score_never_means_certain_language(status, candidates, expected):
    assert LanguageWindow(0, 30, candidates, 1, status).stable_language == expected


def test_mixed_boundaries_reset_and_manual_language_still_wins():
    windows = [
        LanguageWindow(0, 30, (("en", 0.99),), 30, "speech"),
        LanguageWindow(15, 45, (("es", 0.99),), 30, "speech"),
        LanguageWindow(30, 60, (("es", 0.99),), 30, "speech"),
    ]
    regions = decoding_regions(60, windows, None)
    assert any(region.uncertain and region.language is None for region in regions)
    assert regions[0].language == "en" and regions[-1].language == "es"
    assert all(region.language == "ja" for region in decoding_regions(60, windows, "ja"))
    assert (
        max(
            region.end - region.start
            for region in decoding_regions(
                1200, [LanguageWindow(0, 1200, (("en", 0.99),), 1200, "speech")], None
            )
        )
        <= 300
    )


def test_streamed_pcm_source_hash_offsets_and_owned_cleanup(tmp_path):
    source = audio_file(tmp_path / "source.wav", 32)
    with prepare_review_audio(source, 60) as prepared:
        spool = prepared.path
        assert prepared.source_path == source.resolve() and prepared.source_sha256 == source_hash(
            source
        )
        assert prepared.duration == 32
        assert len(prepared.read(15, 31)) == 16 * 16000
        for bounds in ((-1, 2), (0, 33), (1, 1)):
            with pytest.raises(ValueError):
                prepared.read(*bounds)
    assert source.exists() and not spool.exists()


def test_stream_duration_and_section_caps(tmp_path):
    source = audio_file(tmp_path / "source.wav", 305)
    with pytest.raises(TranscriptionError, match="duration limit"):
        with prepare_review_audio(source, 2):
            pass
    with prepare_review_audio(source, 310) as prepared:
        with pytest.raises(ValueError, match="bounded"):
            prepared.read(0, 305)
    assert source.exists()


class FakeEngine:
    def __init__(self):
        self.model = Mock(compute_type="int8_float32")
        self.calls = []

    def detect_language(self, **kwargs):
        return "en", 0.98, [("en", 0.98), ("es", 0.02)]

    def transcribe(self, values, **kwargs):
        self.calls.append((len(values), kwargs))
        word = SimpleNamespace(
            start=0.0, end=min(2, len(values) / 16000), word=" Hello.", probability=0.8
        )
        segment = SimpleNamespace(
            start=0.0,
            end=word.end,
            text=" Hello.",
            words=[word],
            avg_logprob=-0.2,
            no_speech_prob=0.01,
            compression_ratio=1.0,
            temperature=0.0,
        )
        return iter([segment]), SimpleNamespace(language="en")


def test_real_pcm_fake_engine_requests_independent_cached_decode_and_releases(
    tmp_path, cached_checkpoint
):
    source = audio_file(tmp_path / "source.wav", 32)
    engine = FakeEngine()
    phases = []
    with (
        patch("faster_whisper.WhisperModel", return_value=engine) as loader,
        patch(
            "faster_whisper.vad.get_speech_timestamps",
            side_effect=lambda values: [{"start": 0, "end": len(values)}],
        ),
    ):
        result = bounded_pass(source, PassSettings("large-v3-turbo"), phases.append)
    assert loader.call_args.args == (str(cached_checkpoint.resolve()),)
    assert loader.call_args.kwargs["local_files_only"] is True
    assert loader.call_args.kwargs["num_workers"] == 1
    assert (
        engine.calls[0][1]["task"] == "transcribe" and engine.calls[0][1]["initial_prompt"] is None
    )
    assert engine.calls[0][1]["word_timestamps"] is True
    assert result.transcript.metadata["compute_type"] == "int8_float32"
    assert result.transcript.segments[0].words[0].confidence == 0.8
    assert len(result.windows) == 5 and len(result.diagnostics) == 1
    assert phases and all("elapsed" in phase for phase in phases)
    engine.model.unload_model.assert_called_once_with(to_cpu=False)


def test_uncertain_language_disables_previous_text_and_forced_override(tmp_path, cached_checkpoint):
    source = audio_file(tmp_path / "source.wav")
    engine = FakeEngine()
    engine.detect_language = Mock(return_value=("en", 0.51, [("en", 0.51), ("es", 0.49)]))
    with (
        patch("faster_whisper.WhisperModel", return_value=engine),
        patch(
            "faster_whisper.vad.get_speech_timestamps", return_value=[{"start": 0, "end": 32000}]
        ),
    ):
        bounded_pass(
            source,
            PassSettings("large-v3", language="ja", prompt="Operator glossary", cached_only=False),
        )
    assert engine.calls[0][1]["condition_on_previous_text"] is False
    assert engine.calls[0][1]["language"] == "ja"
    assert engine.calls[0][1]["initial_prompt"] == "Operator glossary"


@pytest.mark.parametrize(
    "failure", [RuntimeError("decode failure"), MemoryError("out of memory"), KeyboardInterrupt()]
)
def test_model_is_unloaded_when_lazy_decode_raises(tmp_path, failure, cached_checkpoint):
    source = audio_file(tmp_path / "source.wav")
    engine = FakeEngine()

    def broken(*args, **kwargs):
        raise failure

    engine.transcribe = broken
    with (
        patch("faster_whisper.WhisperModel", return_value=engine),
        patch("faster_whisper.vad.get_speech_timestamps", return_value=[]),
    ):
        with pytest.raises(type(failure)):
            bounded_pass(source, PassSettings("large-v3"))
    engine.model.unload_model.assert_called_once()
    assert source.exists()


def test_silence_has_no_language_and_no_empty_success(tmp_path, cached_checkpoint):
    source = audio_file(tmp_path / "source.wav")
    engine = FakeEngine()
    engine.transcribe = Mock(return_value=(iter([]), None))
    with (
        patch("faster_whisper.WhisperModel", return_value=engine),
        patch("faster_whisper.vad.get_speech_timestamps", return_value=[]),
    ):
        with pytest.raises(TranscriptionError, match="No speech"):
            bounded_pass(source, PassSettings("large-v3"))


@pytest.mark.parametrize("bad_score", [float("nan"), float("inf"), 1.2, -0.1])
def test_malformed_language_scores_fail_closed(tmp_path, bad_score, cached_checkpoint):
    source = audio_file(tmp_path / "source.wav")
    engine = FakeEngine()
    engine.detect_language = Mock(return_value=("en", bad_score, [("en", bad_score)]))
    with (
        patch("faster_whisper.WhisperModel", return_value=engine),
        patch(
            "faster_whisper.vad.get_speech_timestamps", return_value=[{"start": 0, "end": 16000}]
        ),
    ):
        result = bounded_pass(source, PassSettings("large-v3"))
        assert "score" in result.transcript.metadata["language_scan_error"]
        assert all(window.status == "uncertain" for window in result.windows)
        assert engine.calls[0][1]["condition_on_previous_text"] is False
    engine.model.unload_model.assert_called_once()


@pytest.mark.parametrize(
    "first,second,reason",
    [
        ("15 units", "50 units", "numeric disagreement"),
        ("Do not proceed", "Do proceed", "delete"),
        ("hello", "", "speech coverage disagreement"),
        ("", "hello", "speech coverage disagreement"),
        ("東京です", "大阪です", "replace"),
    ],
)
def test_meaningful_timed_disagreements(first, second, reason, tmp_path):
    source = audio_file(tmp_path / "source.wav")
    spans = compare_passes(transcript(first), acoustic(source, second))
    assert any(reason in span.reasons for span in spans)


def test_agreement_does_not_certify_and_markdown_is_literal(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    primary = transcript()
    assert not compare_passes(primary, acoustic(source))
    receipt = ReviewReceipt(
        "required",
        "faster-whisper",
        "large-v3",
        "turbo",
        str(source),
        status="complete",
        requires_review=False,
    )
    rendered = render_review(receipt)
    assert "Agreement is not proof" in rendered and "does not establish accuracy" in rendered
    receipt.spans = compare_passes(transcript("# injected heading"), acoustic(source, "other"))
    assert "    # injected heading" in render_review(receipt)


def test_word_timestamps_and_segmentation_do_not_become_different_text(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    first = Transcript(
        [
            TranscriptSegment(
                0,
                3,
                "Hello world",
                words=(TranscriptWord(0, 1, "Hello"), TranscriptWord(1, 2, "world")),
            )
        ],
        duration=3,
    )
    second = acoustic(source, "hello world")
    assert compare_passes(first, second) == []


def test_gaps_weak_scores_and_forced_language_are_reviewable(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    second = acoustic(source)
    second.diagnostics = [AcousticDiagnostic(0, 3, -2, 0.7, 3.0, 0.4)]
    assert {"weak acoustic score", "repetition risk", "temperature fallback"} <= {
        reason for span in compare_passes(transcript(""), second) for reason in span.reasons
    }
    second.transcript.metadata["requested_language"] = "ja"
    assert any("forced" in reason for span in primary_flags(second) for reason in span.reasons)


@pytest.mark.parametrize("policy", ["required", "best-effort"])
def test_missing_verifier_preserves_primary_and_publishes_partial(tmp_path, policy):
    source = audio_file(tmp_path / "source.wav")
    primary = transcript()
    first = acoustic(source)
    config = ScribeConfig(
        output_folder=tmp_path / "out",
        log_folder=tmp_path / "logs",
        transcription_verification=policy,
    )
    with patch(
        "scribe.core.transcription_review.bounded_pass",
        side_effect=FileNotFoundError("cached checkpoint missing"),
    ):
        receipt, paths = complete_review(config, GPUConfig(has_gpu=False), source, primary, first)
    assert source.exists() and receipt.status == "partial" and receipt.requires_review
    assert "no download or cloud fallback" in receipt.error
    assert any(path.name == "primary-acoustic.json" for path in paths)
    manifest = json.loads(next(path for path in paths if path.name == "review.json").read_text())
    assert manifest["source_sha256"] == source_hash(source) and manifest["status"] == "partial"
    assert primary.metadata["transcription_review"]["status"] == "partial"


def test_successful_review_uses_independent_prompt_and_distinct_unique_outputs(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    primary = transcript()
    first = acoustic(source)
    config = ScribeConfig(output_folder=tmp_path / "out", log_folder=tmp_path / "logs")
    with patch(
        "scribe.core.transcription_review.bounded_pass",
        return_value=acoustic(source, "fifty units"),
    ) as runner:
        receipt, paths = complete_review(config, GPUConfig(has_gpu=False), source, primary, first)
        _, next_paths = complete_review(config, GPUConfig(has_gpu=False), source, primary, first)
    assert receipt.status == "complete" and receipt.requires_review and receipt.spans
    settings = runner.call_args.args[1]
    assert settings.cached_only and settings.prompt == "" and settings.language is None
    assert paths[0].parent != next_paths[0].parent
    assert "primary-acoustic.json" in {p.name for p in paths}
    assert json.loads(paths[0].read_text())["segments"][0]["text"] == "The limit is fifteen units."


def test_native_primary_is_preserved_and_capability_gap_is_partial(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    primary = transcript(backend="mlx-whisper")
    config = ScribeConfig(output_folder=tmp_path / "out", log_folder=tmp_path / "logs")
    with patch("scribe.core.transcription_review.bounded_pass", return_value=acoustic(source)):
        receipt, _ = complete_review(config, GPUConfig(has_gpu=False), source, primary, None)
    assert receipt.status == "partial" and "native/cloud primary" in receipt.error
    assert primary.backend == "mlx-whisper"


def test_source_changed_between_passes_refuses_comparison(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    second = replace(acoustic(source), source_sha256="different")
    with patch("scribe.core.transcription_review.bounded_pass", return_value=second):
        receipt, _ = complete_review(
            ScribeConfig(output_folder=tmp_path / "out", log_folder=tmp_path / "logs"),
            GPUConfig(has_gpu=False),
            source,
            transcript(),
            acoustic(source),
        )
    assert receipt.status == "partial" and "Source changed" in receipt.error


def test_required_report_write_failure_is_partial_and_keeps_raw(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    with (
        patch("scribe.core.transcription_review.bounded_pass", return_value=acoustic(source)),
        patch("scribe.core.transcription_review.publish_review", side_effect=OSError("disk full")),
    ):
        receipt, paths = complete_review(
            ScribeConfig(output_folder=tmp_path / "out", log_folder=tmp_path / "logs"),
            GPUConfig(has_gpu=False),
            source,
            transcript(),
            acoustic(source),
        )
    assert receipt.status == "partial" and "disk full" in receipt.error
    assert source.exists() and paths[0].exists()


def test_same_checkpoint_repeat_is_labeled(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    config = ScribeConfig(
        output_folder=tmp_path / "out", log_folder=tmp_path / "logs", verification_model="large-v3"
    )
    with patch("scribe.core.transcription_review.bounded_pass", return_value=acoustic(source)):
        receipt, _ = complete_review(
            config, GPUConfig(has_gpu=False), source, transcript(), acoustic(source)
        )
    assert receipt.comparison_kind.startswith("same_checkpoint_repeat")


def test_settings_preserve_cpu_precision_beam_and_primary_language(tmp_path):
    config = ScribeConfig(
        output_folder=tmp_path / "out",
        log_folder=tmp_path / "logs",
        local_compute_type="float32",
        local_batch_size=8,
    )
    settings = pass_settings(
        config,
        GPUConfig(has_gpu=True, beam_size=7),
        "medium",
        primary=True,
        language="es",
        prompt="custom",
        force_cpu=True,
    )
    assert (
        settings.device,
        settings.compute_type,
        settings.beam_size,
        settings.batch_size,
        settings.language,
        settings.prompt,
    ) == ("cpu", "float32", 7, 8, "es", "custom")
    assert not settings.cached_only and settings.strict_compute_type


@pytest.mark.parametrize("command", ["transcribe", "url", "batch", "music", "record", "rec"])
def test_cli_exposes_max_and_local_review_options(command):
    from scribe.cli.main import app

    result = CliRunner().invoke(app, [command, "--help"], terminal_width=160)
    assert result.exit_code == 0, result.output
    assert "--verification-model" in result.output and "--verification" in result.output
    assert "max" in result.output and "accurate" in result.output


@pytest.mark.parametrize(
    "policy,failure,expected_error",
    [(None, False, False), (None, True, True), ("best-effort", True, False), ("off", False, False)],
)
def test_actual_untouched_max_orchestration_and_retention(
    tmp_path, policy, failure, expected_error
):
    from scribe.core.transcriber import Transcriber
    from scribe.models.session import TranscriptionSession
    from scribe.utils.vocabulary import CustomVocabulary

    source = audio_file(tmp_path / "recording.wav")
    config = ScribeConfig(
        output_folder=tmp_path / "out",
        log_folder=tmp_path / "logs",
        local_backend="cpu",
        transcription_verification=policy,
    )
    assert config.transcription_quality == "max" and "default_model" not in config.model_fields_set
    session = TranscriptionSession.create("Synthetic")
    session.add_file(source, "source")
    first = acoustic(source, "misheard")
    second = acoustic(source, "other")
    glossary = CustomVocabulary(["Canonical"], {"Canonical": ["misheard"]})
    with (
        patch.object(GPUConfig, "detect", return_value=GPUConfig(has_gpu=False)),
        patch("scribe.core.transcriber.Converter"),
        patch("scribe.core.backends.registry.backend_availability", return_value={"cpu": True}),
        patch("scribe.core.review_engine.bounded_pass", return_value=first) as primary_runner,
        patch(
            "scribe.core.transcription_review.bounded_pass",
            side_effect=FileNotFoundError("missing cached verifier") if failure else None,
            return_value=second,
        ) as verifier_runner,
        patch("scribe.core.transcriber.LocalWhisperTranscriber") as one_pass,
    ):
        one_pass.return_value.transcribe.return_value = source.with_suffix(".txt")
        one_pass.return_value.last_transcript = transcript()
        worker = Transcriber(config)
        worker.converter.convert_to_wav = Mock(return_value=source)
        output = worker.transcribe(source, session=session, custom_vocabulary=glossary)
    assert source.exists()
    assert bool(worker.review_error) is expected_error
    assert bool(session.artifact_errors) is expected_error
    if policy == "off":
        primary_runner.assert_not_called()
        verifier_runner.assert_not_called()
        one_pass.return_value.transcribe.assert_called_once()
    else:
        assert output.exists() and "Canonical" in output.read_text()
        assert primary_runner.call_args.args[1].model == "large-v3"
        assert verifier_runner.call_args.args[1].cached_only is True
        raw = next(path for path in session.files_created if path.name == "primary-acoustic.json")
        assert json.loads(raw.read_text())["segments"][0]["text"] == "misheard"
        assert worker.last_transcript.metadata["transcription_review"]["status"] == (
            "partial" if failure else "complete"
        )
        one_pass.assert_not_called()


def test_primary_failure_never_calls_verifier_or_cloud_and_preserves_original(tmp_path):
    from scribe.core.transcriber import Transcriber
    from scribe.models.session import TranscriptionSession

    source = audio_file(tmp_path / "recording.wav")
    session = TranscriptionSession.create("Synthetic")
    session.add_file(source, "source")
    with (
        patch.object(GPUConfig, "detect", return_value=GPUConfig(has_gpu=False)),
        patch("scribe.core.transcriber.Converter"),
        patch("scribe.core.backends.registry.backend_availability", return_value={"cpu": True}),
        patch(
            "scribe.core.review_engine.bounded_pass",
            side_effect=TranscriptionError("primary failed"),
        ),
        patch("scribe.core.transcription_review.bounded_pass") as secondary,
        patch("scribe.core.transcriber.OpenAITranscriber") as cloud,
    ):
        worker = Transcriber(
            ScribeConfig(
                output_folder=tmp_path / "out", log_folder=tmp_path / "logs", local_backend="cpu"
            )
        )
        worker.converter.convert_to_wav = Mock(return_value=source)
        with pytest.raises(TranscriptionError, match="primary failed"):
            worker.transcribe(source, session=session)
    assert source.exists()
    secondary.assert_not_called()
    cloud.assert_not_called()


def test_session_partial_reason_reaches_cli_owner_without_mock_attribute_leaks():
    from scribe.cli.transcription_review import review_errors
    from scribe.models.session import TranscriptionSession

    session = TranscriptionSession.create("Synthetic")
    session.artifact_errors.append("required review missing")
    assert review_errors(session) == ["required review missing"]
    assert review_errors(Mock()) == []


def test_shared_wrong_number_is_not_numeric_disagreement(tmp_path):
    source = audio_file(tmp_path / "source.wav")
    spans = compare_passes(
        transcript("80,000 soldiers arrived today"),
        acoustic(source, "80,000 soldiers arrived yesterday"),
    )
    assert spans and all("numeric disagreement" not in span.reasons for span in spans)


def test_exact_speech_spans_flag_shared_omission_without_flagging_real_silence(tmp_path):
    source = audio_file(tmp_path / "source.wav", 30)
    later = Transcript([TranscriptSegment(22, 29, "Spanish speech")], duration=30)
    second = AcousticPass(
        later,
        [LanguageWindow(0, 30, (("es", 0.99),), 20, "speech", ((0.2, 20.2), (22, 29)))],
        [],
        1,
        source_hash(source),
        str(source),
        30,
    )
    spans = compare_passes(later, second)
    gaps = [span for span in spans if any("both passes" in reason for reason in span.reasons)]
    assert [(span.start, span.end) for span in gaps] == [(0, 5), (5, 10), (10, 15), (15, 20)]
    assert all(span.end <= 20 for span in gaps)
    # Overlapping scan windows cannot count the same half-second of speech twice.
    second.windows = [LanguageWindow(0, 30, (), 0.3, "speech", ((0, 0.3),))] * 4
    assert not any(
        "both passes" in reason for span in compare_passes(later, second) for reason in span.reasons
    )


@pytest.mark.parametrize("duration", [float("inf"), float("nan"), -1])
def test_malformed_duration_cannot_create_unbounded_comparison(tmp_path, duration):
    source = audio_file(tmp_path / "source.wav")
    first = transcript()
    first.duration = duration
    with pytest.raises(ValueError, match="duration"):
        compare_passes(first, acoustic(source))
    with pytest.raises(ValueError, match="duration"):
        compare_passes(transcript(), replace(acoustic(source), normalized_seconds=duration))


def test_fine_language_grid_preserves_clean_prefix_before_mixed_window():
    windows = [
        LanguageWindow(0, 15, (("en", 0.99),), 15, "speech"),
        LanguageWindow(7.5, 22.5, (("en", 0.99),), 15, "speech"),
        LanguageWindow(15, 30, (("es", 0.99),), 15, "speech"),
        LanguageWindow(22.5, 37.5, (("es", 0.99),), 15, "speech"),
    ]
    regions = decoding_regions(37.5, windows, None)
    assert regions[0].language == "en" and regions[0].end == 15
    assert any(region.uncertain and region.start == 15 for region in regions)
    assert regions[-1].language == "es"


def test_report_shows_actual_language_timeline_with_bounded_table():
    receipt = ReviewReceipt("required", "faster-whisper", "large-v3", "turbo", "source.wav")
    receipt.language_windows = [
        LanguageWindow(0, 15, (("en", 0.99),), 12, "speech"),
        LanguageWindow(7.5, 22.5, (("es", 0.95),), 12, "speech"),
    ]
    report = render_review(receipt)
    assert "en / 0.990" in report and "es / 0.950" in report
    assert "00:00:07.5" in report and "speech spans" in report
