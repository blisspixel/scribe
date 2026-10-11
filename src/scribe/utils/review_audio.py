"""Stream source audio into an owned disk spool, keeping section reads bounded."""

import math
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

import av
import numpy as np
from numpy.typing import NDArray

from scribe.exceptions import TranscriptionError

SAMPLE_RATE = 16_000
MAX_SECTION_SECONDS = 302.0


@dataclass(frozen=True)
class PreparedAudio:
    path: Path
    samples: int
    source_path: Path
    source_sha256: str

    @property
    def duration(self) -> float:
        return self.samples / SAMPLE_RATE

    def read(self, start: float, end: float) -> NDArray[np.float32]:
        if not 0 <= start < end <= self.duration + 1 / SAMPLE_RATE:
            raise ValueError("Invalid audio section bounds")
        if end - start > MAX_SECTION_SECONDS + 1 / SAMPLE_RATE:
            raise ValueError("Audio section exceeds bounded decoding limit")
        first = round(start * SAMPLE_RATE)
        count = min(round(end * SAMPLE_RATE), self.samples) - first
        with self.path.open("rb") as stream:
            stream.seek(first * 4)
            result = np.fromfile(stream, dtype="<f4", count=count)
        if result.size != count:
            raise TranscriptionError("Prepared audio changed during transcription")
        return result


def source_hash(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


@contextmanager
def prepare_review_audio(source: Path, max_seconds: float) -> Iterator[PreparedAudio]:
    """Decode mono 16 kHz PCM incrementally; only this context owns its spool."""
    before = source.stat()
    digest = source_hash(source)
    with TemporaryDirectory(prefix="scribe-review-") as directory:
        spool = Path(directory) / "audio.f32"
        samples = 0
        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
        with av.open(str(source), mode="r", metadata_errors="ignore") as container:
            with spool.open("wb") as stream:
                expected_time = 0.0
                origin = (container.start_time or 0) / av.time_base

                def write_values(values: NDArray[np.float32]) -> None:
                    nonlocal samples
                    samples += values.size
                    if samples / SAMPLE_RATE > max_seconds:
                        raise TranscriptionError("Audio exceeds the configured duration limit")
                    stream.write(values.astype("<f4", copy=False).tobytes())

                for frame in container.decode(audio=0):
                    timestamp = (
                        float(frame.time) - origin if frame.time is not None else expected_time
                    )
                    tolerance = max(1 / SAMPLE_RATE, float(getattr(frame, "time_base", None) or 0))
                    delta = timestamp - expected_time
                    if not math.isfinite(timestamp) or delta < -tolerance:
                        raise TranscriptionError(
                            "Audio has overlapping or invalid timestamps; source retained. "
                            "Create a continuous audio export explicitly before transcription."
                        )
                    if delta > tolerance:
                        for normalized in resampler.resample(None):
                            write_values(
                                normalized.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                            )
                        gap = round(delta * SAMPLE_RATE)
                        expected_time += gap / SAMPLE_RATE
                        while gap:
                            count = min(gap, SAMPLE_RATE)
                            write_values(np.zeros(count, dtype=np.float32))
                            gap -= count
                        resampler = av.AudioResampler(format="flt", layout="mono", rate=SAMPLE_RATE)
                    expected_time += frame.samples / frame.sample_rate
                    frame.pts = None
                    for normalized in resampler.resample(frame):
                        write_values(
                            normalized.to_ndarray().reshape(-1).astype(np.float32, copy=False)
                        )
                for normalized in resampler.resample(None):
                    write_values(normalized.to_ndarray().reshape(-1).astype(np.float32, copy=False))
        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise TranscriptionError("Source audio changed while preparing review")
        if samples == 0 or samples / SAMPLE_RATE > max_seconds:
            raise TranscriptionError("Source audio is empty or exceeds the duration limit")
        yield PreparedAudio(spool, samples, source.resolve(), digest)
