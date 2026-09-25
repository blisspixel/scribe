"""Unit tests for Nemotron, Pyannote, and MLX diarization backend adapters."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from scribe.core.diarization.mlx import NemotronMLXDiarizer
from scribe.core.diarization.nemotron import NemotronDiarizer
from scribe.core.diarization.pyannote import PyannoteDiarizer
from scribe.models.transcript import Transcript, TranscriptSegment


def test_pyannote_diarizer_graceful_on_pipeline_error(tmp_path: Path) -> None:
    diarizer = PyannoteDiarizer("fake-token")
    with patch.object(diarizer, "_get_pipeline", side_effect=RuntimeError("Pipeline load error")):
        res = diarizer.diarize(tmp_path / "test.wav")
        assert res.speaker_count == 0
        assert len(res.turns) == 0
        assert "error" in res.metadata

        # apply() leaves transcript unlabeled without crashing
        transcript = Transcript(segments=[TranscriptSegment(0.0, 1.0, "hi")])
        labeled = diarizer.apply(tmp_path / "test.wav", transcript)
        assert labeled.segments[0].speaker is None


def test_pyannote_diarizer_extracts_exclusive_tracks(tmp_path: Path) -> None:
    diarizer = PyannoteDiarizer("fake-token")

    class MockSegment:
        def __init__(self, start: float, end: float) -> None:
            self.start = start
            self.end = end

    mock_exclusive = MagicMock()
    mock_exclusive.itertracks.return_value = [
        (MockSegment(0.0, 1.0), None, "SPEAKER_00"),
        (MockSegment(1.0, 2.5), None, "SPEAKER_01"),
    ]

    mock_output = MagicMock()
    mock_output.exclusive_speaker_diarization = mock_exclusive

    mock_pipeline = MagicMock(return_value=mock_output)
    diarizer._pipeline_instance = mock_pipeline

    res = diarizer.diarize(tmp_path / "test.wav")
    assert res.speaker_count == 2
    assert len(res.turns) == 2
    assert res.turns[0].speaker == "SPEAKER_00"
    assert res.turns[1].speaker == "SPEAKER_01"


def test_nemotron_diarizer_graceful_on_error(tmp_path: Path) -> None:
    diarizer = NemotronDiarizer()
    with patch.object(diarizer, "_ensure_loaded", side_effect=ImportError("Transformers missing")):
        res = diarizer.diarize(tmp_path / "test.wav")
        assert res.speaker_count == 0
        assert len(res.turns) == 0
        assert "error" in res.metadata

        transcript = Transcript(segments=[TranscriptSegment(0.0, 1.0, "hi")])
        labeled = diarizer.apply(tmp_path / "test.wav", transcript)
        assert labeled.segments[0].speaker is None


def test_nemotron_diarizer_detects_eight_speaker_limit(tmp_path: Path) -> None:
    diarizer = NemotronDiarizer()
    with patch.object(diarizer, "_ensure_loaded"):
        diarizer.model = MagicMock()
        diarizer.model.device = "cpu"
        diarizer.model.return_value = MagicMock(logits=MagicMock())

        # Mock audio loader
        with patch("scribe.core.diarization.nemotron._load_audio_waveform") as mock_load:
            import numpy as np

            mock_load.return_value = (np.zeros(16000, dtype=np.float32), 16000)

            mock_processor = MagicMock()
            # The processor returns a BatchFeature that is moved to the model device.
            batch = MagicMock()
            batch.to.return_value = {"input_features": MagicMock()}
            mock_processor.return_value = batch
            # 8 distinct speakers
            mock_processor.extract_speaker_dict.return_value = [
                [{"Start": float(i), "End": float(i + 0.8), "Speaker": i} for i in range(8)]
            ]
            diarizer.processor = mock_processor

            res = diarizer.diarize(tmp_path / "test.wav")
            assert res.speaker_count == 8
            assert res.speaker_limit_reached is True
            assert len(res.turns) == 8


def test_mlx_diarizer_availability_on_non_darwin() -> None:
    with patch("platform.system", return_value="Linux"):
        assert NemotronMLXDiarizer.is_available() is False


def test_nemotron_unavailable_when_transformers_lacks_the_model(tmp_path: Path) -> None:
    from scribe.core.diarization.base import package_has_submodule

    pkg = tmp_path / "fakepkg"
    (pkg / "models" / "other").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    spec = MagicMock(submodule_search_locations=[str(pkg)])
    with patch("importlib.util.find_spec", return_value=spec):
        assert package_has_submodule("fakepkg", "models", "other") is True
        assert package_has_submodule("fakepkg", "models", "nemotron3_diarization") is False
    with patch("importlib.util.find_spec", return_value=None):
        assert package_has_submodule("transformers", "models", "x") is False


def test_nemotron_load_audio_resamples_non_16k_wav(tmp_path: Path) -> None:
    import wave

    import numpy as np

    from scribe.core.diarization.nemotron import _load_audio_waveform

    path = tmp_path / "tone.wav"
    samples = (np.sin(np.linspace(0, 440 * 2 * np.pi, 44100)) * 10000).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(44100)
        wf.writeframes(samples.tobytes())

    fake_librosa = MagicMock()
    fake_librosa.load.return_value = (np.zeros(16000, dtype=np.float32), 16000)
    with patch.dict("sys.modules", {"librosa": fake_librosa}):
        _data, rate = _load_audio_waveform(path)
    assert rate == 16000
    fake_librosa.load.assert_called_once()
    assert fake_librosa.load.call_args.kwargs["sr"] == 16000


def test_pyannote_load_uses_token_then_legacy_keyword() -> None:
    from scribe.core.diarization.pyannote import _load_pipeline

    modern = MagicMock()
    _load_pipeline(modern, "pipe", "tok")
    modern.from_pretrained.assert_called_once_with("pipe", token="tok")  # noqa: S106

    legacy = MagicMock()
    legacy.from_pretrained.side_effect = [TypeError("unexpected keyword 'token'"), "pipeline"]
    assert _load_pipeline(legacy, "pipe", "tok") == "pipeline"
    assert legacy.from_pretrained.call_args.kwargs == {"use_auth_token": "tok"}


def test_pyannote_reads_speaker_diarization_from_diarize_output(tmp_path: Path) -> None:
    diarizer = PyannoteDiarizer("fake-token", device="cpu")
    segment = MagicMock(start=0.0, end=2.0)
    annotation = MagicMock()
    annotation.itertracks.return_value = [(segment, None, "SPEAKER_00")]

    class DiarizeOutput:
        speaker_diarization = annotation
        exclusive_speaker_diarization = None

    diarizer._pipeline_instance = MagicMock(return_value=DiarizeOutput())
    res = diarizer.diarize(tmp_path / "test.wav")
    assert [t.speaker for t in res.turns] == ["SPEAKER_00"]


def test_mlx_diarizer_reads_segments(tmp_path: Path) -> None:
    diarizer = NemotronMLXDiarizer()
    output = MagicMock()
    output.segments = [
        MagicMock(start=0.0, end=1.5, speaker=0),
        MagicMock(start=1.5, end=3.0, speaker=1),
        MagicMock(start=3.0, end=3.0, speaker=1),  # zero-length, dropped
    ]
    diarizer._model = MagicMock()
    diarizer._model.generate.return_value = output
    fake_vad = MagicMock()
    with patch.dict("sys.modules", {"mlx_audio": MagicMock(), "mlx_audio.vad": fake_vad}):
        res = diarizer.diarize(tmp_path / "a.wav")
    assert [t.speaker for t in res.turns] == ["SPEAKER_00", "SPEAKER_01"]
    assert res.speaker_count == 2
