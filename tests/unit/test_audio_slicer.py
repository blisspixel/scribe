import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from scribe.utils.audio_io import save_wav
from scribe.utils.audio_slicer import slice_audio_by_segments


def _frames(path: Path) -> tuple[int, int]:
    with wave.open(str(path), "rb") as wf:
        return wf.getframerate(), wf.getnframes()


def test_slice_audio_by_segments_writes_requested_slices(tmp_path):
    song = tmp_path / "song.wav"
    save_wav(song, np.linspace(-0.5, 0.5, 20, dtype=np.float32), 10)
    segments = [{"start": 0.0, "end": 0.5}, {"start": 0.5, "end": 1.0}]

    output_paths = slice_audio_by_segments(song, segments, output_dir=tmp_path / "slices")

    assert [p.name for p in output_paths] == ["segment_0000.wav", "segment_0001.wav"]
    assert [_frames(p) for p in output_paths] == [(10, 5), (10, 5)]


def test_slice_audio_by_segments_uses_temp_directory_when_output_missing(tmp_path):
    song = tmp_path / "song.wav"
    save_wav(song, np.ones(10, dtype=np.float32) * 0.1, 10)
    temp_output_dir = tmp_path / "generated"
    temp_output_dir.mkdir()

    with patch("tempfile.mkdtemp", return_value=str(temp_output_dir)):
        paths = slice_audio_by_segments(song, [{"start": 0.0, "end": 1.0}])

    assert paths == [temp_output_dir / "segment_0000.wav"]
    assert paths[0].exists()


def test_slice_audio_by_segments_propagates_errors(tmp_path):
    with patch("scribe.utils.audio_io.load_audio", side_effect=RuntimeError("load failed")):
        with pytest.raises(RuntimeError, match="load failed"):
            slice_audio_by_segments(tmp_path / "song.wav", [{"start": 0.0, "end": 1.0}])
