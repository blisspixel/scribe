"""Exercise the installed faster-whisper decoder without a model or network."""

from __future__ import annotations

import tempfile
import wave
from pathlib import Path

from faster_whisper.audio import decode_audio


def main() -> None:
    """Decode synthetic PCM through the exact upstream PyAV integration."""
    sample_rate = 16_000
    with tempfile.TemporaryDirectory(prefix="scribe-decode-smoke-") as directory:
        source = Path(directory) / "silence.wav"
        with wave.open(str(source), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(sample_rate)
            audio.writeframes(b"\x00\x00" * sample_rate)
        decoded = decode_audio(str(source), sampling_rate=sample_rate)
        if len(decoded) != sample_rate or decoded.dtype.name != "float32":
            raise RuntimeError("Installed local decoder did not preserve one second of PCM")
        if decoded.any():
            raise RuntimeError("Installed local decoder changed synthetic silence")
    print("Installed local decoder passed: one second of synthetic PCM, no model or API.")


if __name__ == "__main__":
    main()
