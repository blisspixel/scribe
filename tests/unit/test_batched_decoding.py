"""Batched GPU decoding: VRAM-aware batch sizing and the sequential fallback."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest

from scribe.core.local_whisper import LocalWhisperTranscriber, choose_batch_size
from scribe.models.gpu import GPUConfig


def _gpu(batch_size: int = 16) -> GPUConfig:
    return GPUConfig(
        has_gpu=True,
        gpu_name="NVIDIA RTX 4090",
        gpu_memory_gb=24.0,
        cuda_available=True,
        model_size="large-v3",
        beam_size=5,
        batch_size=batch_size,
        use_fp16=True,
        enable_tensor_cores=False,
    )


@pytest.mark.parametrize(
    ("model", "requested", "free", "expected"),
    [
        ("large-v3", 16, 22.0, 16),  # idle 4090: full tier batch
        ("large-v3", 16, None, 16),  # unknown free memory trusts the tier
        ("large-v3", 16, 8.0, 8),  # shrinks to what fits
        ("large-v3", 16, 5.0, 0),  # too little room: sequential
        ("large-v3-turbo", 16, 7.0, 5),
        ("medium", 8, 4.5, 6),
        ("large-v3", 2, 22.0, 0),  # tiny requested batches are not worth it
        ("large-v3", 0, 22.0, 0),  # explicit sequential
    ],
)
def test_choose_batch_size(model: str, requested: int, free: float | None, expected: int) -> None:
    assert choose_batch_size(model, requested, free) == expected


def _seg(text: str, start: float = 0.0, end: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(start=start, end=end, text=text, words=None)


def test_batched_path_used_when_batch_size_positive(tmp_path: Path) -> None:
    t = LocalWhisperTranscriber(gpu_config=_gpu())
    t.model = Mock()
    t.batch_size = 8
    pipeline = MagicMock()
    pipeline.return_value.transcribe.return_value = ([_seg(" hi")], SimpleNamespace(language="en"))
    with patch("faster_whisper.BatchedInferencePipeline", pipeline):
        transcript = t._execute_transcription(tmp_path / "a.wav", 10.0, "")
    assert [s.text for s in transcript.segments] == [" hi"]
    assert pipeline.return_value.transcribe.call_args.kwargs["batch_size"] == 8
    assert transcript.metadata["batch_size"] == 8
    assert transcript.metadata["decoding"] == "batched"
    t.model.transcribe.assert_not_called()


def test_batched_failure_retries_sequentially(tmp_path: Path) -> None:
    t = LocalWhisperTranscriber(gpu_config=_gpu())
    t.model = Mock()
    t.model.transcribe.return_value = ([_seg(" seq")], SimpleNamespace(language="en"))
    t.batch_size = 16
    pipeline = MagicMock()
    pipeline.return_value.transcribe.side_effect = RuntimeError("CUDA failed: out of memory")
    with (
        patch("faster_whisper.BatchedInferencePipeline", pipeline),
        patch("scribe.core.local_whisper.clear_gpu_cache") as clear,
    ):
        transcript = t._execute_transcription(tmp_path / "a.wav", 10.0, "")
    assert [s.text for s in transcript.segments] == [" seq"]
    clear.assert_called_once()
    assert transcript.model == "large-v3"
    assert transcript.metadata["batch_size"] == 0
    assert transcript.metadata["decoding"] == "conditioned sequential"
    assert transcript.metadata["compute_type"] == "float16"


def test_sequential_when_batch_size_zero(tmp_path: Path) -> None:
    t = LocalWhisperTranscriber(gpu_config=_gpu(), batch_size=0)
    t.model = Mock()
    t.model.transcribe.return_value = ([_seg(" seq")], SimpleNamespace(language="en"))
    with patch("faster_whisper.BatchedInferencePipeline") as pipeline:
        t._execute_transcription(tmp_path / "a.wav", 10.0, "")
    pipeline.assert_not_called()
    kwargs = t.model.transcribe.call_args.kwargs
    assert kwargs["beam_size"] == 5
    # Conditioning keeps punctuation across windows; fallback guards against loops.
    assert kwargs["condition_on_previous_text"] is True
    assert kwargs["temperature"][0] == 0.0 and len(kwargs["temperature"]) > 1
    assert kwargs["compression_ratio_threshold"] == 2.4


def test_4090_tier_uses_beam_5() -> None:
    config = GPUConfig(has_gpu=True, gpu_name="NVIDIA GeForce RTX 4090", gpu_memory_gb=24.0)
    config._configure_for_gpu()
    assert config.beam_size == 5
    assert config.batch_size == 16


def _words(spec: list[tuple[float, float, str]]) -> tuple:
    from scribe.models.transcript import TranscriptWord

    return tuple(TranscriptWord(start=s, end=e, text=t) for s, e, t in spec)


def _segment(words: tuple):
    from scribe.models.transcript import TranscriptSegment

    return TranscriptSegment(
        start=words[0].start, end=words[-1].end, text="".join(w.text for w in words), words=words
    )


def test_split_long_segment_at_sentence_ends() -> None:
    from scribe.core.local_whisper import split_long_segment

    spec = []
    t = 0.0
    for _sentence in range(4):
        for i in range(6):
            text = " word" + ("." if i == 5 else "")
            spec.append((t, t + 0.6, text))
            t += 0.7
    seg = _segment(_words(spec))
    pieces = split_long_segment(seg)
    assert len(pieces) == 4
    assert all(p.text.strip().endswith(".") for p in pieces)
    assert "".join(p.text for p in pieces) == seg.text  # nothing added or lost
    assert [w for p in pieces for w in p.words] == list(seg.words)


def test_split_long_segment_without_punctuation_cuts_at_longest_pause() -> None:
    from scribe.core.local_whisper import split_long_segment

    spec = [(i * 0.5, i * 0.5 + 0.4, " w") for i in range(20)]
    spec += [(12.0 + i * 0.5, 12.0 + i * 0.5 + 0.4, " w") for i in range(20)]  # 2 s pause
    pieces = split_long_segment(_segment(_words(spec)))
    assert len(pieces) >= 2
    assert pieces[0].end == 9.9  # cut at the 2 s pause
    assert all(p.end - p.start <= 12.0 for p in pieces)
    assert sum(len(p.words) for p in pieces) == 40


def test_split_keeps_short_or_wordless_segments() -> None:
    from scribe.core.local_whisper import split_long_segment
    from scribe.models.transcript import TranscriptSegment

    short = _segment(_words([(0.0, 0.5, " hi."), (0.5, 1.0, " there.")]))
    assert split_long_segment(short) == [short]
    wordless = TranscriptSegment(start=0.0, end=30.0, text="long", words=None)
    assert split_long_segment(wordless) == [wordless]


def test_batched_output_drops_words_unless_requested(tmp_path: Path) -> None:
    from scribe.models.transcript import TranscriptWord

    t = LocalWhisperTranscriber(gpu_config=_gpu())
    t.model = Mock()
    t.batch_size = 8
    word = SimpleNamespace(start=0.0, end=0.5, word=" hi", probability=0.9)
    raw = SimpleNamespace(start=0.0, end=0.5, text=" hi", words=[word])
    pipeline = MagicMock()
    pipeline.return_value.transcribe.return_value = ([raw], SimpleNamespace(language="en"))
    with patch("faster_whisper.BatchedInferencePipeline", pipeline):
        plain = t._execute_transcription(tmp_path / "a.wav", 1.0, "", word_timestamps=False)
        rich = t._execute_transcription(tmp_path / "a.wav", 1.0, "", word_timestamps=True)
    assert pipeline.return_value.transcribe.call_args.kwargs["word_timestamps"] is True
    assert plain.segments[0].words is None
    assert rich.segments[0].words == (
        TranscriptWord(start=0.0, end=0.5, text=" hi", confidence=0.9),
    )
