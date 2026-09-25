import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from scribe.utils.source_separation import VocalSeparator, separate_vocals


class FakeWaveform:
    def __init__(self, channels=1):
        self.shape = (channels, 100)
        self.device = None

    def repeat(self, channels, _samples):
        return FakeWaveform(channels=channels)

    def to(self, device):
        self.device = device
        return self

    def __getitem__(self, item):
        if item is None:
            return self
        raise TypeError(f"Unexpected index: {item}")


class FakeSource:
    def cpu(self):
        return self

    def numpy(self):
        return self


class FakeNoGrad:
    def __enter__(self):
        return None

    def __exit__(self, exc_type, exc, tb):
        return False


def test_vocal_separator_loads_model_and_reuses_it():
    model = Mock()
    pretrained_module = ModuleType("demucs.pretrained")

    def get_model(_name):
        return model

    pretrained_module.get_model = get_model
    demucs_module = ModuleType("demucs")
    demucs_module.pretrained = pretrained_module

    # Pin the device so the test does not depend on the host having a GPU.
    separator = VocalSeparator(device="cuda")

    with patch.dict(sys.modules, {"demucs": demucs_module, "demucs.pretrained": pretrained_module}):
        separator._load_model()
        separator._load_model()

    assert separator.model is model
    model.to.assert_called_once_with("cuda")
    model.eval.assert_called_once_with()


def test_vocal_separator_load_model_reports_missing_dependency():
    separator = VocalSeparator()

    with patch.dict(sys.modules, {"demucs": None, "demucs.pretrained": None}):
        with pytest.raises(ImportError, match="Demucs is not installed"):
            separator._load_model()


def test_separate_vocals_returns_cached_output_and_runs_full_pipeline(tmp_path):
    separator = VocalSeparator(device="cpu")
    separator.model = Mock()
    cached_output = tmp_path / "song_vocals.wav"
    cached_output.write_text("cached", encoding="utf-8")
    assert separator.separate_vocals(tmp_path / "song.wav", output_dir=tmp_path) == cached_output

    apply_module = ModuleType("demucs.apply")

    def apply_model(*_args, **_kwargs):
        return [[FakeSource(), FakeSource(), FakeSource(), FakeSource()]]

    demucs_module = ModuleType("demucs")
    demucs_module.apply = apply_module

    def save_audio(path, _vocals, sr):
        Path(path).write_text(f"{sr}", encoding="utf-8")

    loaded = []

    def load_audio(_path, *, sample_rate=None, channels=1):
        loaded.append((sample_rate, channels))
        return "samples", 44100

    fake_torch = SimpleNamespace(
        no_grad=lambda: FakeNoGrad(), from_numpy=lambda _data: FakeWaveform(channels=2)
    )
    apply_module.apply_model = apply_model
    output_dir = tmp_path / "fresh"

    with (
        patch.dict(
            sys.modules,
            {"demucs": demucs_module, "demucs.apply": apply_module, "torch": fake_torch},
        ),
        patch("scribe.utils.audio_io.load_audio", side_effect=load_audio),
        patch("scribe.utils.audio_io.save_wav", side_effect=save_audio),
    ):
        result = separator.separate_vocals(tmp_path / "song.wav", output_dir=output_dir)

    # Demucs needs 44.1 kHz stereo, requested from the loader.
    assert loaded == [(44100, 2)]

    assert result == output_dir / "song_vocals.wav"
    assert result.read_text(encoding="utf-8") == "44100"


def test_separate_vocals_raises_when_model_missing_or_processing_fails(tmp_path):
    separator = VocalSeparator()

    with patch.object(separator, "_load_model", return_value=None):
        with pytest.raises(RuntimeError, match="Demucs model failed to load"):
            separator.separate_vocals(tmp_path / "song.wav")

    separator.model = Mock()
    fake_torch = SimpleNamespace(no_grad=lambda: FakeNoGrad())
    apply_module = ModuleType("demucs.apply")

    def apply_model(*_args, **_kwargs):
        return []

    apply_module.apply_model = apply_model
    demucs_module = ModuleType("demucs")
    demucs_module.apply = apply_module

    with (
        patch.dict(
            sys.modules,
            {"demucs": demucs_module, "demucs.apply": apply_module, "torch": fake_torch},
        ),
        patch("scribe.utils.audio_io.load_audio", side_effect=RuntimeError("decode failed")),
    ):
        with pytest.raises(RuntimeError, match="decode failed"):
            separator.separate_vocals(tmp_path / "song.wav", output_dir=tmp_path / "out")


def test_separate_vocals_convenience_function(tmp_path):
    output_path = tmp_path / "vocals.wav"

    with patch(
        "scribe.utils.source_separation.VocalSeparator.separate_vocals", return_value=output_path
    ):
        assert separate_vocals(tmp_path / "song.wav") == output_path
