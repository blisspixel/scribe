"""Typed acoustic evidence, separate from transcript wording and correctness claims."""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from scribe.models.transcript import Transcript

REVIEW_SCHEMA = "scribe.transcription-review/v1"
REVIEW_LIMIT = (
    "Agreement is not proof of accuracy. The Whisper checkpoints are related. "
    "Listen to flagged spans and sample unflagged audio before relying on this transcript."
)


@dataclass(frozen=True)
class LanguageWindow:
    start: float
    end: float
    candidates: tuple[tuple[str, float], ...]
    speech_seconds: float
    status: Literal["speech", "no_speech", "uncertain"]
    speech_spans: tuple[tuple[float, float], ...] = ()

    @property
    def stable_language(self) -> str | None:
        if self.status != "speech" or not self.candidates:
            return None
        language, score = self.candidates[0]
        runner_up = self.candidates[1][1] if len(self.candidates) > 1 else 0.0
        return language if score >= 0.8 and score - runner_up >= 0.2 else None


@dataclass(frozen=True)
class AcousticDiagnostic:
    start: float
    end: float
    avg_logprob: float
    no_speech_probability: float
    compression_ratio: float
    temperature: float


@dataclass(frozen=True)
class ReviewSpan:
    start: float
    end: float
    reasons: tuple[str, ...]
    primary: str = ""
    secondary: str = ""


@dataclass
class AcousticPass:
    transcript: Transcript
    windows: list[LanguageWindow]
    diagnostics: list[AcousticDiagnostic]
    elapsed_seconds: float
    source_sha256: str
    source_path: str
    normalized_seconds: float


@dataclass
class ReviewReceipt:
    policy: str
    primary_backend: str | None
    primary_model: str | None
    secondary_model: str
    source_path: str
    source_sha256: str = ""
    status: Literal["complete", "partial"] = "partial"
    error: str | None = None
    requires_review: bool = True
    source_retention: str = "required_for_review"
    comparison_kind: str = "different_checkpoint_related_family"
    language_windows: list[LanguageWindow] = field(default_factory=list)
    secondary_language_windows: list[LanguageWindow] = field(default_factory=list)
    spans: list[ReviewSpan] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    primary_options: dict[str, Any] = field(default_factory=dict)
    secondary_options: dict[str, Any] = field(default_factory=dict)
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"schema": REVIEW_SCHEMA, "limits": REVIEW_LIMIT, **asdict(self)}
