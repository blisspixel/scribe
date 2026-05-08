import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from scribe.utils.audio_slicer import slice_audio_by_segments


def test_slice_audio_by_segments_writes_requested_slices(tmp_path):
    waveform = np.arange(20, dtype=float).reshape(1, 20)
    saved_paths = []

    def save_audio(path, segment_waveform, sample_rate):
        saved_path = Path(path)
        saved_path.write_text(f"{sample_rate}:{segment_waveform.shape[1]}", encoding="utf-8")
        saved_paths.append(saved_path)

    fake_torchaudio = SimpleNamespace(
        load=lambda _path: (waveform, 10),
        save=save_audio,
    )
    segments = [{"start": 0.0, "end": 0.5}, {"start": 0.5, "end": 1.0}]

    with patch.dict(sys.modules, {"torchaudio": fake_torchaudio}):
        output_paths = slice_audio_by_segments(
            tmp_path / "song.wav", segments, output_dir=tmp_path / "slices"
        )

    assert output_paths == saved_paths
    assert [path.read_text(encoding="utf-8") for path in output_paths] == ["10:5", "10:5"]


def test_slice_audio_by_segments_uses_temp_directory_when_output_missing(tmp_path):
    waveform = np.ones((1, 10), dtype=float)

    def save_audio(path, _segment_waveform, _sample_rate):
        Path(path).write_text("saved", encoding="utf-8")

    fake_torchaudio = SimpleNamespace(
        load=lambda _path: (waveform, 10),
        save=save_audio,
    )
    temp_output_dir = tmp_path / "generated"
    temp_output_dir.mkdir()

    with (
        patch.dict(sys.modules, {"torchaudio": fake_torchaudio}),
        patch("tempfile.mkdtemp", return_value=str(temp_output_dir)),
    ):
        paths = slice_audio_by_segments(tmp_path / "song.wav", [{"start": 0.0, "end": 1.0}])

    assert paths == [temp_output_dir / "segment_0000.wav"]
    assert paths[0].exists()


def test_slice_audio_by_segments_propagates_errors(tmp_path):
    fake_torchaudio = SimpleNamespace(
        load=lambda _path: (_ for _ in ()).throw(RuntimeError("load failed"))
    )

    with patch.dict(sys.modules, {"torchaudio": fake_torchaudio}):
        with pytest.raises(RuntimeError, match="load failed"):
            slice_audio_by_segments(tmp_path / "song.wav", [{"start": 0.0, "end": 1.0}])
