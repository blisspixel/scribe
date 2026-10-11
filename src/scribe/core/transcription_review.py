"""File review orchestration; preserve primary output on secondary failures."""

import time
from pathlib import Path
from uuid import uuid4

from scribe.core.review_engine import PassSettings, PhaseCallback, bounded_pass
from scribe.models.config import ScribeConfig
from scribe.models.gpu import GPUConfig
from scribe.models.transcript import Transcript
from scribe.models.transcription_review import AcousticPass, ReviewReceipt
from scribe.utils.logging import get_logger
from scribe.utils.model_selection import resolve_verification, resolve_verifier_model
from scribe.utils.review_audio import source_hash
from scribe.utils.transcript_review import compare_passes, primary_flags, publish_review

logger = get_logger(__name__)


def unavailable_review(
    config: ScribeConfig, source: Path, primary: Transcript | None, primary_path: Path, reason: str
) -> tuple[ReviewReceipt, list[Path]]:
    """Publish a requested capability gap without loading another model."""
    policy = resolve_verification(config.transcription_quality, config.transcription_verification)
    model = primary.model if primary else None
    receipt = ReviewReceipt(
        policy,
        primary.backend if primary else None,
        model,
        resolve_verifier_model(model or "", config.verification_model),
        str(source.resolve()),
        error=reason + ". Primary and source retained; choose --quality accurate for one pass.",
    )
    receipt.primary_options = {
        **(primary.metadata if primary else {}),
        "primary_text_path": str(primary_path.resolve()),
        "timed_primary_available": primary is not None,
    }
    paths: list[Path] = []
    try:
        receipt.source_sha256 = source_hash(source)
        folder = config.output_folder / f"{source.stem}_review_{uuid4().hex[:10]}"
        folder.mkdir(parents=True)
        paths = publish_review(folder, receipt, primary, None)
    except Exception as error:
        receipt.error = (
            f"{receipt.error} Review evidence could not be saved ({type(error).__name__}: {error})."
        )
        logger.warning("Could not publish unavailable review evidence: %s", error)
    if primary is not None:
        primary.metadata["transcription_review"] = receipt.to_dict()
    return receipt, paths


def pass_settings(
    config: ScribeConfig,
    gpu: GPUConfig,
    model: str,
    *,
    primary: bool,
    language: str | None = None,
    prompt: str = "",
    force_cpu: bool = False,
) -> PassSettings:
    cuda = gpu.has_gpu and not force_cpu
    return PassSettings(
        model=model,
        device="cuda" if cuda else "cpu",
        compute_type=config.local_compute_type
        or ("float16" if cuda and gpu.use_fp16 else "float32" if cuda else "int8"),
        beam_size=gpu.beam_size,
        batch_size=config.local_batch_size or 0 if primary else 0,
        language=language if primary else None,
        prompt=prompt if primary else "",
        cached_only=not primary,
        strict_compute_type=config.local_compute_type is not None,
        max_seconds=config.max_audio_duration_hours * 3600,
    )


def complete_review(
    config: ScribeConfig,
    gpu: GPUConfig,
    source: Path,
    primary: Transcript,
    acoustic: AcousticPass | None,
    phase: PhaseCallback | None = None,
) -> tuple[ReviewReceipt, list[Path]]:
    """A missing capability is partial; no primary engine or wording is changed."""
    started = time.monotonic()
    policy = resolve_verification(config.transcription_quality, config.transcription_verification)
    verifier = resolve_verifier_model(primary.model or "", config.verification_model)
    receipt = ReviewReceipt(policy, primary.backend, primary.model, verifier, str(source.resolve()))
    aliases = {"large": "large-v3", "turbo": "large-v3-turbo"}
    if aliases.get(primary.model or "", primary.model) == aliases.get(verifier, verifier):
        receipt.comparison_kind = "same_checkpoint_repeat; no independent checkpoint evidence"
    receipt.primary_options = {
        key: value for key, value in primary.metadata.items() if key != "transcription_review"
    }
    folder = config.output_folder / f"{source.stem}_review_{uuid4().hex[:10]}"
    artifacts: list[Path] = []
    secondary: AcousticPass | None = None
    try:
        folder.mkdir(parents=True)
        # Raw primary evidence is durable before a secondary model is loaded.
        from scribe.utils.safe_write import atomic_write_json
        from scribe.utils.transcript_writers import transcript_to_dict

        raw = folder / "primary-acoustic.json"
        atomic_write_json(raw, transcript_to_dict(primary))
        artifacts.append(raw)
        receipt.source_sha256 = acoustic.source_sha256 if acoustic else source_hash(source)
        if phase:
            phase(f"Secondary acoustic pass ({verifier}, cached local weights only)")
        secondary = bounded_pass(
            source,
            pass_settings(
                config, gpu, verifier, primary=False, force_cpu=config.local_backend == "cpu"
            ),
            phase,
        )
        if secondary.source_sha256 != receipt.source_sha256:
            raise ValueError("Source changed between acoustic passes; comparison refused")
        receipt.secondary_options = dict(secondary.transcript.metadata)
        receipt.secondary_language_windows = secondary.windows
        receipt.spans = compare_passes(primary, secondary)
        if acoustic is None:
            receipt.error = (
                "Recording-wide primary language diagnostics are unavailable for the selected "
                "native/cloud primary. Primary preserved; set "
                "SCRIBE_LOCAL_BACKEND=faster-whisper, or --quality accurate for one-pass output."
            )
        else:
            receipt.language_windows = acoustic.windows
            receipt.spans.extend(primary_flags(acoustic))
            if acoustic.transcript.metadata.get("language_scan_error"):
                receipt.error = "Primary recording-wide language scan failed; primary retained."
        if secondary.transcript.metadata.get("language_scan_error"):
            receipt.error = "Secondary recording-wide language scan failed; primary retained."
        receipt.status = "partial" if receipt.error else "complete"
        receipt.requires_review = bool(receipt.spans) or bool(receipt.error)
        receipt.source_retention = (
            "required_for_review" if receipt.requires_review else "workflow_policy"
        )
        receipt.elapsed_seconds = time.monotonic() - started
        if phase:
            phase("Saving acoustic review evidence")
        artifacts = publish_review(folder, receipt, primary, secondary.transcript)
    except Exception as error:
        receipt.status = "partial"
        receipt.requires_review = True
        receipt.source_retention = "required_for_review"
        receipt.error = (
            f"Local review incomplete ({type(error).__name__}: {error}). Primary and source retained. "
            "The verifier must already be cached; no download or cloud fallback was attempted. "
            "Use --quality accurate or --verification off for deliberate one-pass output."
        )
        receipt.elapsed_seconds = time.monotonic() - started
        try:
            if folder.is_dir():
                artifacts = publish_review(
                    folder, receipt, primary, secondary.transcript if secondary else None
                )
        except Exception as publication_error:
            logger.warning("Could not publish partial review evidence: %s", publication_error)
    receipt.source_retention = (
        "required_for_review" if receipt.requires_review else "workflow_policy"
    )
    primary.metadata["transcription_review"] = receipt.to_dict()
    return receipt, artifacts
