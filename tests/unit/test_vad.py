from unittest.mock import Mock, patch

import pytest

from scribe.utils.vad import VocalActivityDetector, detect_vocal_segments


class FakeWaveform:
    def __init__(self, channels=2):
        self.shape = (channels, 160)

    def mean(self, dim=0, keepdim=True):
        assert dim == 0
        assert keepdim is True
        return FakeWaveform(channels=1)

    def squeeze(self):
        return "flattened-waveform"


def test_vad_load_model_and_merge_segments():
    detector = VocalActivityDetector()
    model = Mock()
    utils = (Mock(), None, None, None, None)

    with patch("torch.hub.load", return_value=(model, utils)):
        detector._load_model()
        detector._load_model()

    assert detector.model is model
    assert detector.utils is utils
    assert detector._merge_close_segments(
        [{"start": 0.0, "end": 1.0}, {"start": 1.2, "end": 2.0}, {"start": 3.0, "end": 4.0}],
        gap_threshold=0.5,
    ) == [{"start": 0.0, "end": 2.0}, {"start": 3.0, "end": 4.0}]


def test_vad_detects_segments_and_handles_errors(tmp_path):
    detector = VocalActivityDetector()
    detector.model = None
    detector.utils = None
    with patch.object(detector, "_load_model", return_value=None):
        with pytest.raises(RuntimeError, match="Silero VAD model failed to load"):
            detector.detect_vocal_segments(tmp_path / "vocals.wav")


def test_vad_load_model_and_convenience_function_propagate_failures(tmp_path):
    detector = VocalActivityDetector()

    with patch("torch.hub.load", side_effect=RuntimeError("hub failed")):
        with pytest.raises(RuntimeError, match="hub failed"):
            detector._load_model()

    with patch(
        "scribe.utils.vad.VocalActivityDetector.detect_vocal_segments",
        return_value=[{"start": 0.0, "end": 1.0}],
    ):
        assert detect_vocal_segments(tmp_path / "vocals.wav") == [{"start": 0.0, "end": 1.0}]
