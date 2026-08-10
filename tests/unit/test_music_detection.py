import builtins
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import numpy as np

from scribe.utils.music_detection import MusicDetector, is_music


def _make_fake_librosa():
    module = ModuleType("librosa")

    def load_audio(_path, sr=22050):
        return np.array([0.1, -0.1, 0.2, -0.2]), sr

    def onset_strength(_y, _sr):
        return np.array([1.0, 2.0])

    def beat_track(_onset_envelope, _sr):
        return 120.0, np.array([1, 2, 3])

    def tempo_values(_onset_envelope, _sr, _aggregate=None):
        return np.array([130.0])

    module.beat = SimpleNamespace(
        beat_track=beat_track,
        tempo=tempo_values,
    )
    chroma = np.zeros((12, 12))
    chroma[9] = 1.0

    def chroma_cqt(_y, _sr):
        return chroma

    def rms_values(_y):
        return np.array([[0.2, 0.4]])

    def spectral_centroid(_y, _sr):
        return np.array([[800.0]])

    def zero_crossing_rate(_y):
        return np.array([[0.1]])

    def hpss(_y):
        return np.array([0.6, 0.6]), np.array([0.3, 0.3])

    module.load = load_audio
    module.onset = SimpleNamespace(onset_strength=onset_strength)
    module.feature = SimpleNamespace(
        chroma_cqt=chroma_cqt,
        rms=rms_values,
        spectral_centroid=spectral_centroid,
        zero_crossing_rate=zero_crossing_rate,
    )
    module.effects = SimpleNamespace(hpss=hpss)
    return module


def test_music_detector_extracts_metadata_and_validates_music():
    detector = MusicDetector()
    fake_librosa = _make_fake_librosa()
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "librosa":
            return fake_librosa
        return original_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        metadata = detector._extract_metadata(np.array([0.1, -0.1, 0.2, -0.2]), 22050, 12.3)

    assert metadata["tempo"] in {0, 120.0}
    assert metadata["key"] in {"A", "C", "Unknown"}
    assert metadata["duration"] == 12.3
    assert "characteristics" in metadata

    validation_metadata = {
        "tempo": 120.0,
        "harmonic_ratio": 0.3,
        "percussive_ratio": 0.3,
        "spectral_centroid": 800.0,
        "technical": {"rms_energy": 0.2, "zero_crossing_rate": 0.1},
    }

    is_music_result, confidence, reason = detector._validate_music(
        np.array([0.1, -0.1]), 22050, validation_metadata
    )
    assert is_music_result is True
    assert confidence >= 0.6
    assert "Music detected" in reason

    not_music_result, _, reason = detector._validate_music(
        np.array([0.1, -0.1]),
        22050,
        {
            "tempo": 0,
            "harmonic_ratio": 0.0,
            "percussive_ratio": 0.0,
            "spectral_centroid": 0,
            "technical": {"rms_energy": 0.0, "zero_crossing_rate": 0.5},
        },
    )
    assert not_music_result is False
    assert "Not music" in reason


def test_music_detector_analyze_and_fallback_paths(tmp_path):
    detector = MusicDetector()
    fake_librosa = _make_fake_librosa()
    audio_path = tmp_path / "song.wav"
    audio_path.write_bytes(b"audio")

    expected_metadata = {
        "tempo": 120.0,
        "technical": {"rms_energy": 0.2, "zero_crossing_rate": 0.1},
        "harmonic_ratio": 0.3,
        "percussive_ratio": 0.3,
        "spectral_centroid": 800.0,
    }
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "librosa":
            return fake_librosa
        return original_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=fake_import),
        patch("scribe.utils.audio.get_audio_duration", return_value=12.3),
        patch.object(detector, "_extract_metadata", return_value=expected_metadata),
        patch.object(detector, "_validate_music", return_value=(True, 0.8, "Music detected")),
    ):
        result = detector.analyze_music(audio_path)

    assert result["is_music"] is True
    assert result["metadata"]["tempo"] == 120.0

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "librosa":
            raise ImportError("missing librosa")
        return original_import(name, *args, **kwargs)

    with (
        patch("builtins.__import__", side_effect=fake_import),
        patch("scribe.utils.audio.get_audio_duration", return_value=5.0),
    ):
        fallback = detector.analyze_music(audio_path)

    assert fallback["reason"] == "Music analysis unavailable (librosa not installed)"
    assert fallback["metadata"]["duration_formatted"] == "0:05"
    assert detector.is_music(audio_path)["reason"]

    with patch(
        "scribe.utils.music_detection.MusicDetector.is_music", return_value={"is_music": True}
    ):
        assert is_music(audio_path) is True
