"""Small CLI helpers for acoustic review options and requested-artifact outcomes."""

from pathlib import Path

from rich.console import Console
from rich.markup import escape

from scribe.models.config import ScribeConfig
from scribe.models.options import ModelSize, VerificationPolicy


def apply_review_options(
    config: ScribeConfig,
    verification: VerificationPolicy | None,
    verification_model: ModelSize | None,
) -> None:
    if verification is not None:
        config.transcription_verification = verification
    if verification_model is not None:
        config.verification_model = verification_model


def review_errors(session: object) -> list[str]:
    errors = getattr(session, "artifact_errors", [])
    return [error for error in errors if isinstance(error, str)] if isinstance(errors, list) else []


def review_requires_source(session: object) -> bool:
    """A completed comparison can need source retention without being a processing failure."""
    return getattr(session, "review_source_required", False) is True or bool(review_errors(session))


def show_review_summary(console: Console, worker: object) -> None:
    metadata = getattr(getattr(worker, "last_transcript", None), "metadata", None)
    receipt = metadata.get("transcription_review") if isinstance(metadata, dict) else None
    if not isinstance(receipt, dict):
        return
    spans = receipt.get("spans", [])
    count = len(spans) if isinstance(spans, list) else 0
    console.print(
        f"[yellow]Acoustic review: {escape(str(receipt.get('status', 'partial')))}; "
        f"{count} flagged spans. Agreement is not proof of accuracy.[/yellow]"
    )
    paths = receipt.get("artifacts", [])
    if isinstance(paths, list):
        for path in paths:
            if isinstance(path, str) and Path(path).name == "review.md":
                console.print(f"[dim]Review report: {escape(path)}[/dim]", soft_wrap=True)
