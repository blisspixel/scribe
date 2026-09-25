"""Dependency-light audio loading and WAV writing.

Scribe converts every input to 16 kHz mono PCM WAV before transcription, so the
common case is read directly with the standard library ``wave`` module. Anything
else (compressed formats, other rates, channel changes) is decoded by FFmpeg,
which Scribe already requires. This replaces torchaudio, whose recent releases
need the separate torchcodec package to load audio and whose CUDA builds can
disagree with the installed PyTorch build.

Arrays are float32 in [-1, 1] with shape ``(channels, frames)``.
"""

from __future__ import annotations

import json
import subprocess
import wave
from pathlib import Path
from typing import Any

import numpy as np

from scribe.utils.platform import get_ffmpeg_path, get_ffprobe_path

AudioArray = np.ndarray[Any, np.dtype[np.float32]]

_PCM_SCALE = {1: 128.0, 2: 32768.0, 4: 2147483648.0}
_PCM_DTYPE = {2: np.int16, 4: np.int32}


def _read_pcm_wav(path: Path) -> tuple[AudioArray, int] | None:
    """Read an 8, 16, or 32-bit PCM WAV, or return None when it is not one."""
    try:
        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate()
            channels = wf.getnchannels()
            width = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError, OSError):
        return None
    if width == 1:
        samples = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width in _PCM_DTYPE:
        samples = np.frombuffer(raw, dtype=_PCM_DTYPE[width]).astype(np.float32)
        samples /= _PCM_SCALE[width]
    else:
        return None
    usable = len(samples) - len(samples) % channels
    return samples[:usable].reshape(-1, channels).T.copy(), rate


def _probe_channels(path: Path) -> int | None:
    ffprobe = get_ffprobe_path()
    if ffprobe is None:
        return None
    try:
        result = subprocess.run(  # noqa: S603 - trusted local ffprobe binary
            [
                str(ffprobe),
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=channels",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        streams = json.loads(result.stdout or "{}").get("streams") or []
        return int(streams[0]["channels"]) if streams else None
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError):
        return None


def _decode_with_ffmpeg(
    path: Path, sample_rate: int | None, channels: int | None
) -> tuple[AudioArray, int]:
    ffmpeg = get_ffmpeg_path()
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is required to decode this audio file but was not found")
    out_channels = channels or _probe_channels(path) or 1
    out_rate = sample_rate or 16000
    if sample_rate is None:
        # Preserve the native rate when the caller did not ask for one.
        native = _read_pcm_wav(path)
        if native is not None:
            out_rate = native[1]
    command = [
        str(ffmpeg),
        "-v",
        "error",
        "-nostdin",
        "-i",
        str(path),
        "-f",
        "f32le",
        "-acodec",
        "pcm_f32le",
        "-ac",
        str(out_channels),
    ]
    if sample_rate is not None:
        command += ["-ar", str(sample_rate)]
    command.append("-")
    result = subprocess.run(command, capture_output=True, check=False)  # noqa: S603
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()[:300]
        raise RuntimeError(f"FFmpeg could not decode {path.name}: {message}")
    samples = np.frombuffer(result.stdout, dtype=np.float32)
    usable = len(samples) - len(samples) % out_channels
    return samples[:usable].reshape(-1, out_channels).T.copy(), out_rate


def load_audio(
    path: Path, *, sample_rate: int | None = None, channels: int | None = 1
) -> tuple[AudioArray, int]:
    """Load audio as float32 ``(channels, frames)`` plus its sample rate.

    ``sample_rate`` resamples when set; ``channels`` downmixes (1) or up/downmixes
    to that count when set, and keeps the file's layout when None.
    """
    native = _read_pcm_wav(path)
    if native is not None:
        data, rate = native
        if sample_rate is None or sample_rate == rate:
            if channels == 1 and data.shape[0] > 1:
                data = data.mean(axis=0, keepdims=True)
            elif channels is not None and channels != data.shape[0]:
                if data.shape[0] == 1:
                    data = np.repeat(data, channels, axis=0)
                else:
                    return _decode_with_ffmpeg(path, sample_rate, channels)
            return data.astype(np.float32, copy=False), rate
    return _decode_with_ffmpeg(path, sample_rate, channels)


def save_wav(path: Path, data: AudioArray, sample_rate: int) -> None:
    """Write float audio shaped ``(channels, frames)`` or ``(frames,)`` as 16-bit PCM."""
    array = np.asarray(data, dtype=np.float32)
    if array.ndim == 1:
        array = array[None, :]
    pcm = (np.clip(array, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(pcm.shape[0])
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm.T.tobytes())
