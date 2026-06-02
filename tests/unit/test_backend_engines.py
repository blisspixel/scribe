"""Tests for the backend engines (mlx, whisper.cpp, faster-whisper wrapper).

The real engines are not installed here (and mlx needs a Mac), so these cover the
pure result-to-Transcript mappings and the availability/dispatch logic using fake
modules, which is exactly the platform-independent surface CI can verify.
"""

import sys
from types import SimpleNamespace
from unittest.mock import patch

from scribe.core.backends.faster_whisper import FasterWhisperBackend
from scribe.core.backends.mlx import MLXWhisperBackend, _result_to_transcript
from scribe.core.backends.whispercpp import WhisperCppBackend, _segments_to_transcript
from scribe.models.transcript import Transcript


def test_mlx_result_mapping():
    result = {
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 1.5, "text": " Hello "},
            {"start": 1.5, "end": 3.0, "text": " world "},
        ],
    }
    transcript = _result_to_transcript(result, "large-v3")
    assert isinstance(transcript, Transcript)
    assert transcript.backend == "mlx-whisper"
    assert transcript.model == "large-v3"
    assert transcript.language == "en"
    assert transcript.duration == 3.0
    assert [(s.start, s.end, s.text) for s in transcript.segments] == [
        (0.0, 1.5, " Hello "),
        (1.5, 3.0, " world "),
    ]


def test_mlx_result_mapping_clamps_and_handles_empty():
    # end before start is clamped; negative start floored to 0.
    transcript = _result_to_transcript(
        {"segments": [{"start": -2.0, "end": -5.0, "text": "x"}]}, "base"
    )
    seg = transcript.segments[0]
    assert seg.start == 0.0 and seg.end == 0.0
    # No segments -> no duration, empty transcript.
    empty = _result_to_transcript({"segments": []}, "base")
    assert empty.segments == [] and empty.duration is None


def test_whispercpp_segment_mapping_centiseconds():
    # pywhispercpp reports t0/t1 in centiseconds.
    raw = [
        SimpleNamespace(t0=0, t1=150, text=" Hello "),
        SimpleNamespace(t0=150, t1=325, text=" world "),
    ]
    transcript = _segments_to_transcript(raw, "large-v3", "en")
    assert transcript.backend == "whisper.cpp"
    assert transcript.language == "en"
    assert transcript.duration == 3.25
    assert [(s.start, s.end, s.text) for s in transcript.segments] == [
        (0.0, 1.5, "Hello"),
        (1.5, 3.25, "world"),
    ]


def test_availability_reflects_importability():
    # Not installed on this machine.
    assert MLXWhisperBackend.is_available() is False
    assert WhisperCppBackend.is_available() is False
    # faster-whisper is a base dependency.
    assert FasterWhisperBackend.is_available() is True

    with patch("scribe.core.backends.mlx.importlib.util.find_spec", return_value=object()):
        assert MLXWhisperBackend.is_available() is True


def test_mlx_backend_transcribe_uses_fake_module(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_text("x")

    captured = {}

    def fake_transcribe(path, *, path_or_hf_repo, language, initial_prompt):
        captured["repo"] = path_or_hf_repo
        return {"language": "en", "segments": [{"start": 0.0, "end": 1.0, "text": "hi"}]}

    fake_mod = SimpleNamespace(transcribe=fake_transcribe)
    with patch.dict(sys.modules, {"mlx_whisper": fake_mod}):
        transcript = MLXWhisperBackend().transcribe(
            audio, language="en", model_size="small", beam_size=5, initial_prompt=None
        )
    assert transcript.backend == "mlx-whisper"
    assert transcript.text() == "hi"
    assert captured["repo"] == "mlx-community/whisper-small-mlx"


def test_whispercpp_backend_transcribe_uses_fake_module(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_text("x")

    class FakeModel:
        def __init__(self, name):
            self.name = name

        def transcribe(self, path, language=""):
            return [SimpleNamespace(t0=0, t1=100, text="hi")]

    fake_model_mod = SimpleNamespace(Model=FakeModel)
    fake_pkg = SimpleNamespace(model=fake_model_mod)
    with patch.dict(sys.modules, {"pywhispercpp": fake_pkg, "pywhispercpp.model": fake_model_mod}):
        transcript = WhisperCppBackend().transcribe(
            audio, language="en", model_size="large-v3", beam_size=5, initial_prompt=None
        )
    assert transcript.backend == "whisper.cpp"
    assert transcript.text() == "hi"
    assert transcript.duration == 1.0
