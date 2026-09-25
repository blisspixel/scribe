"""NVIDIA Nemotron-3 Diarization backend adapter via Hugging Face Transformers.

Runs nvidia/Nemotron-3-Diarization (ungated, openmdw-1.1) to produce speaker
activity at 10 ms frame resolution for up to 8 speakers. The offline forward pass
chunks long recordings internally, so a whole meeting is one call. It runs on CUDA
when the installed PyTorch build can use it and on CPU everywhere else; no Hugging
Face token is required.

The model is native to Transformers from 5.18 onward (the
``nemotron3_diarization`` model package), and its feature extractor needs librosa.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import wave
from pathlib import Path
from typing import Any

import numpy as np

from scribe.core.diarization.alignment import align_diarization
from scribe.core.diarization.base import DiarizationResult, SpeakerTurn, package_has_submodule
from scribe.core.diarization.device import resolve_torch_device
from scribe.models.transcript import Transcript
from scribe.utils.logging import get_logger

logger = get_logger(__name__)

#: Sample rate the Nemotron feature extractor expects.
TARGET_SAMPLE_RATE = 16000


def _module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _load_audio_waveform(
    audio_path: Path, target_rate: int = TARGET_SAMPLE_RATE
) -> tuple[np.ndarray[Any, Any], int]:
    """Load audio as a mono float32 waveform at ``target_rate``.

    The fast path reads the 16 kHz mono PCM WAV that Scribe's pipeline produces
    with the standard library. Anything else (other rates, compressed formats) is
    decoded and resampled by librosa, which the Nemotron extra already requires.
    """
    try:
        with wave.open(str(audio_path), "rb") as wf:
            sample_rate = wf.getframerate()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            if sample_rate == target_rate and sampwidth in (2, 4):
                raw = wf.readframes(wf.getnframes())
                if sampwidth == 2:
                    arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                else:
                    arr = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
                if n_channels > 1:
                    arr = arr.reshape(-1, n_channels).mean(axis=1)
                return arr, sample_rate
    except (wave.Error, EOFError, OSError):
        pass

    import librosa

    data, sr = librosa.load(str(audio_path), sr=target_rate, mono=True)
    return np.asarray(data, dtype=np.float32), int(sr)


class NemotronDiarizer:
    """Runs NVIDIA Nemotron-3 Diarization via Transformers."""

    name = "nemotron"
    MODEL_ID = "nvidia/Nemotron-3-Diarization"
    MAX_SPEAKERS = 8

    def __init__(
        self,
        *,
        device: str | None = None,
        model_id: str | None = None,
    ) -> None:
        self.device = resolve_torch_device(device)
        self.model_id = model_id or self.MODEL_ID
        self.processor: Any = None
        self.model: Any = None

    @classmethod
    def is_available(cls) -> bool:
        """True when torch, librosa, and a Transformers build with the model exist.

        Uses import-spec probes only, so ``scribe info`` stays fast. Older
        Transformers releases import fine but cannot load this model, which is why
        the model package itself is probed rather than the Auto classes.
        """
        return (
            _module_exists("torch")
            and _module_exists("librosa")
            and package_has_submodule("transformers", "models", "nemotron3_diarization")
        )

    def _ensure_loaded(self) -> None:
        if self.model is not None and self.processor is not None:
            return

        # Quiet Transformers before its first import; it logs at import time.
        os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
        # Imported as Any so type checking is identical with or without the extra.
        transformers: Any = importlib.import_module("transformers")

        # Keep Transformers' weight-loading progress bars out of Scribe's console.
        transformers.utils.logging.disable_progress_bar()
        transformers.utils.logging.set_verbosity_error()

        logger.info(
            f"Loading Nemotron diarization model ({self.model_id}, {self.device}); "
            "the first run downloads it from Hugging Face"
        )
        self.processor = transformers.AutoProcessor.from_pretrained(self.model_id)
        # Load then move, rather than device_map, which would also require accelerate.
        model = transformers.AutoModelForAudioFrameClassification.from_pretrained(self.model_id)
        self.model = model.to(self.device).eval()

    def diarize(self, audio_path: Path) -> DiarizationResult:
        """Run Nemotron-3 diarization and return a normalized DiarizationResult."""
        try:
            self._ensure_loaded()
            import torch

            waveform, sample_rate = _load_audio_waveform(audio_path)
            inputs = self.processor(waveform, sampling_rate=sample_rate, return_tensors="pt")
            inputs = inputs.to(self.model.device, dtype=self.model.dtype)

            with torch.inference_mode():
                logits = self.model(**inputs).logits

            # One list per batch item of {"Start": s, "End": s, "Speaker": index}.
            speaker_dicts = self.processor.extract_speaker_dict(
                logits, inputs.get("attention_mask")
            )
            raw_turns = speaker_dicts[0] if speaker_dicts else []

            turns = tuple(
                SpeakerTurn(
                    start=float(item["Start"]),
                    end=float(item["End"]),
                    speaker=f"SPEAKER_{int(item['Speaker']):02d}",
                )
                for item in raw_turns
                if float(item["End"]) > float(item["Start"])
            )

            speaker_count = len({t.speaker for t in turns})
            limit_reached = speaker_count >= self.MAX_SPEAKERS
            if limit_reached:
                logger.warning(
                    f"{speaker_count} speakers detected, which is Nemotron's limit. If the "
                    "recording has more speakers, rerun with --diarizer pyannote."
                )
            logger.info(f"Nemotron diarization found {speaker_count} speakers ({len(turns)} turns)")

            return DiarizationResult(
                turns=turns,
                backend=self.name,
                model=self.model_id,
                speaker_count=speaker_count,
                frame_resolution_ms=10,
                supports_overlap=True,
                speaker_limit_reached=limit_reached,
                metadata={"model_max_speakers": self.MAX_SPEAKERS, "device": self.device},
            )
        except Exception as e:
            logger.warning(f"Nemotron diarization failed, leaving transcript unlabeled: {e}")
            return DiarizationResult(
                turns=(),
                backend=self.name,
                model=self.model_id,
                speaker_count=0,
                metadata={"error": str(e)},
            )

    def apply(self, audio_path: Path, transcript: Transcript) -> Transcript:
        """Label ``transcript`` with locally-detected speakers (no-op on failure)."""
        result = self.diarize(audio_path)
        if not result.turns:
            return transcript
        return align_diarization(transcript, result, prefer_word_alignment=True)
