"""Validate source references on generated next-step bullets.

A matching quote is navigable evidence. It is not proof that the bullet
follows from the source, and it is not an acoustic-accuracy verdict.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

EVIDENCE_SCHEMA = "scribe.notes-evidence/v1"
TRANSCRIPT_SCHEMA = "scribe.transcript/v1"
PIPELINE = "production notes breakdown with validated next-step references"

_NON_COMMITMENT = (
    "withdrawn",
    "not agreed",
    "no longer",
    "do not",
    "don't",
    "no follow-up",
    "not a commitment",
    "was retracted",
)


class EvidenceError(ValueError):
    """The notes evidence could not be tied to the identified source."""


@dataclass(frozen=True)
class SourceSpan:
    """One addressable passage in a hashed source snapshot."""

    source_id: str
    text: str
    start: float | None = None
    end: float | None = None
    review_warning: str | None = None


@dataclass(frozen=True)
class SourceSnapshot:
    """The exact source a note may cite."""

    kind: str
    source_sha256: str
    timing_available: bool
    spans: tuple[SourceSpan, ...]
    schema: str | None = None


@dataclass(frozen=True)
class ResolvedStep:
    """A next-step bullet after local reference checks."""

    text: str
    status: str
    source_ids: tuple[str, ...]
    quotes: tuple[str, ...]
    start: float | None
    end: float | None
    review_warning: str | None
    reason: str | None


def normalize_quote(value: str) -> str:
    """Collapse whitespace. Comparison stays case-sensitive."""
    return " ".join(value.split())


def quote_in_span(quote: str, span_text: str) -> bool:
    """Return whether the normalized quote is an explicit excerpt of the span."""
    needle = normalize_quote(quote)
    haystack = normalize_quote(span_text)
    return bool(needle) and needle in haystack


def _review_warning_for_segment(
    segment: dict[str, Any], warnings: list[dict[str, Any]]
) -> str | None:
    own = segment.get("review_warning")
    if isinstance(own, str) and own.strip():
        return own.strip()
    start = segment.get("start")
    end = segment.get("end")
    if not isinstance(start, int | float) or not isinstance(end, int | float):
        return None
    for warning in warnings:
        message = warning.get("message")
        warn_start = warning.get("start")
        warn_end = warning.get("end")
        if not isinstance(message, str) or not message.strip():
            continue
        if not isinstance(warn_start, int | float) or not isinstance(warn_end, int | float):
            continue
        if float(start) < float(warn_end) and float(end) > float(warn_start):
            return message.strip()
    return None


def _structured_snapshot(payload: dict[str, Any], digest: str) -> SourceSnapshot | None:
    if payload.get("schema") != TRANSCRIPT_SCHEMA or not isinstance(payload.get("segments"), list):
        return None
    metadata = payload.get("metadata")
    raw_warnings = metadata.get("acoustic_warnings") if isinstance(metadata, dict) else None
    warnings = (
        [item for item in raw_warnings if isinstance(item, dict)]
        if isinstance(raw_warnings, list)
        else []
    )
    spans: list[SourceSpan] = []
    for index, segment in enumerate(payload["segments"], start=1):
        if not isinstance(segment, dict):
            continue
        text = segment.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        start = segment.get("start")
        end = segment.get("end")
        spans.append(
            SourceSpan(
                source_id=f"s{index:04d}",
                text=text.strip(),
                start=float(start) if isinstance(start, int | float) else None,
                end=float(end) if isinstance(end, int | float) else None,
                review_warning=_review_warning_for_segment(segment, warnings),
            )
        )
    timing = any(span.start is not None and span.end is not None for span in spans)
    return SourceSnapshot(
        kind="structured",
        source_sha256=digest,
        timing_available=timing,
        spans=tuple(spans),
        schema=TRANSCRIPT_SCHEMA,
    )


def load_snapshot(path: Path) -> SourceSnapshot:
    """Build a snapshot from structured transcript JSON or from text lines.

    Text snapshots say that audio timing is unavailable. Files are never paired
    by a similar name: the caller passes the exact path, and the hash identifies
    that content.
    """
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        structured = _structured_snapshot(parsed, digest)
        if structured is not None:
            return structured

    text = data.decode("utf-8", errors="replace")
    spans: list[SourceSpan] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        spans.append(SourceSpan(source_id=f"l{line_number:04d}", text=line.strip()))
    return SourceSnapshot(
        kind="text",
        source_sha256=digest,
        timing_available=False,
        spans=tuple(spans),
        schema=None,
    )


def assert_same_source(snapshot: SourceSnapshot, path: Path) -> None:
    """Fail when the file is missing or its bytes are not the cited snapshot."""
    if not path.is_file():
        raise EvidenceError(f"Cited source is missing: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != snapshot.source_sha256:
        raise EvidenceError(
            "Cited source content does not match the note snapshot. "
            "Refusing to point this note at a different recording."
        )


def catalog_for_prompt(snapshot: SourceSnapshot) -> str:
    """Source ids and excerpts the model may cite. Times are not included."""
    lines = [
        "SOURCE CATALOG",
        "For each next step, return text, one source_id from this catalog, and a short",
        "verbatim quote from that source. Do not invent ids, quotes, owners, deadlines,",
        "or timestamps. Omit a next step you cannot support.",
    ]
    if not snapshot.timing_available:
        lines.append("Audio timing is unavailable for this text snapshot.")
    for span in snapshot.spans:
        lines.append(f"{span.source_id}: {normalize_quote(span.text)[:240]}")
    return "\n".join(lines)


def evidence_breakdown_schema(base: dict[str, Any]) -> dict[str, Any]:
    """Production breakdown schema with object-valued next steps."""
    schema = cast(dict[str, Any], json.loads(json.dumps(base)))
    properties = schema.setdefault("properties", {})
    properties["next_steps"] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "source_id": {"type": "string"},
                "quote": {"type": "string"},
            },
            "required": ["text", "source_id", "quote"],
            "additionalProperties": False,
        },
    }
    return schema


def _non_commitment(text: str) -> bool:
    lowered = text.casefold()
    return any(phrase in lowered for phrase in _NON_COMMITMENT)


def _proposal_refs(item: Any) -> tuple[str, list[tuple[str, str]]] | None:
    if not isinstance(item, dict):
        return None
    text = item.get("text")
    source_id = item.get("source_id")
    quote = item.get("quote")
    if not isinstance(text, str) or not isinstance(source_id, str) or not isinstance(quote, str):
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    extra = item.get("refs")
    refs: list[tuple[str, str]] = []
    if isinstance(extra, list):
        for ref in extra:
            if (
                isinstance(ref, dict)
                and isinstance(ref.get("source_id"), str)
                and isinstance(ref.get("quote"), str)
            ):
                refs.append((ref["source_id"].strip(), ref["quote"].strip()))
    if not refs:
        refs = [(source_id.strip(), quote.strip())]
    return cleaned, refs


def merge_step_objects(parts: list[list[Any]]) -> list[dict[str, Any]]:
    """Dedupe repeated next steps and keep every supporting reference."""
    merged: list[dict[str, Any]] = []
    index_by_text: dict[str, int] = {}
    for part in parts:
        for item in part:
            parsed = _proposal_refs(item)
            if parsed is None:
                merged.append({"text": "", "source_id": "", "quote": "", "malformed": item})
                continue
            text, refs = parsed
            key = normalize_quote(text).casefold()
            existing = index_by_text.get(key)
            if existing is None:
                index_by_text[key] = len(merged)
                first_id, first_quote = refs[0]
                merged.append(
                    {
                        "text": text,
                        "source_id": first_id,
                        "quote": first_quote,
                        "refs": [
                            {"source_id": source_id, "quote": quote} for source_id, quote in refs
                        ],
                    }
                )
                continue
            kept = merged[existing]
            seen = {(ref["source_id"], ref["quote"]) for ref in kept["refs"]}
            for source_id, quote in refs:
                if (source_id, quote) not in seen:
                    kept["refs"].append({"source_id": source_id, "quote": quote})
                    seen.add((source_id, quote))
    return merged


def resolve_next_steps(snapshot: SourceSnapshot, proposals: Any) -> list[ResolvedStep]:
    """Check each proposal against the snapshot. Invented references stay unverified."""
    if not isinstance(proposals, list):
        return [
            ResolvedStep(
                text="",
                status="unverified",
                source_ids=(),
                quotes=(),
                start=None,
                end=None,
                review_warning=None,
                reason="Next steps were not a list.",
            )
        ]
    by_id = {span.source_id: span for span in snapshot.spans}
    resolved: list[ResolvedStep] = []
    for item in proposals:
        parsed = _proposal_refs(item)
        if parsed is None:
            resolved.append(
                ResolvedStep(
                    text="" if not isinstance(item, str) else item.strip(),
                    status="unverified",
                    source_ids=(),
                    quotes=(),
                    start=None,
                    end=None,
                    review_warning=None,
                    reason="Malformed next-step reference.",
                )
            )
            continue
        text, refs = parsed
        accepted: list[SourceSpan] = []
        accepted_quotes: list[str] = []
        reasons: list[str] = []
        seen_refs: set[tuple[str, str]] = set()
        for source_id, quote in refs:
            identity = (source_id, normalize_quote(quote))
            if identity in seen_refs:
                continue
            seen_refs.add(identity)
            span = by_id.get(source_id)
            if span is None:
                reasons.append(f"Unknown source id {source_id}.")
                continue
            if not quote_in_span(quote, span.text):
                reasons.append(f"Quote is not in {source_id}.")
                continue
            accepted.append(span)
            accepted_quotes.append(normalize_quote(quote))
        if not accepted:
            resolved.append(
                ResolvedStep(
                    text=text,
                    status="unverified",
                    source_ids=(),
                    quotes=(),
                    start=None,
                    end=None,
                    review_warning=None,
                    reason=" ".join(reasons) or "No resolvable source reference.",
                )
            )
            continue
        warning = next((span.review_warning for span in accepted if span.review_warning), None)
        if _non_commitment(text):
            status = "not-a-commitment"
        elif warning:
            status = "source-review"
        else:
            status = "referenced"
        timed_starts: list[float] = []
        timed_ends: list[float] = []
        for span in accepted:
            if span.start is not None and span.end is not None:
                timed_starts.append(span.start)
                timed_ends.append(span.end)
        resolved.append(
            ResolvedStep(
                text=text,
                status=status,
                source_ids=tuple(span.source_id for span in accepted),
                quotes=tuple(accepted_quotes),
                start=min(timed_starts) if timed_starts else None,
                end=max(timed_ends) if timed_ends else None,
                review_warning=warning,
                reason=None,
            )
        )
    return resolved


def _clock(seconds: float) -> str:
    total_ms = round(max(0.0, seconds) * 1000)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{ms:03d}"


def display_bullet(step: ResolvedStep, *, timing_available: bool) -> str:
    """One Markdown bullet. Unverified steps are not displayed as next steps."""
    label = step.text
    if step.status == "not-a-commitment":
        label = f"[not a commitment] {label}"
    elif step.status == "source-review":
        warning = step.review_warning or "the cited span has an acoustic-review warning"
        label = f"[source review] {label} ({warning})"
    refs = ", ".join(step.source_ids)
    quote = step.quotes[0] if step.quotes else ""
    if timing_available and step.start is not None and step.end is not None:
        when = f"{_clock(step.start)}-{_clock(step.end)}"
        return f"{label} ({refs}, {when}): {quote}"
    if not timing_available:
        return f"{label} ({refs}; audio timing unavailable): {quote}"
    return f"{label} ({refs}): {quote}"


def evidence_lines(snapshot: SourceSnapshot, steps: list[ResolvedStep]) -> list[str]:
    """Renderable next-step lines, omitting unverified bullets."""
    shown = [step for step in steps if step.status != "unverified"]
    omitted = sum(1 for step in steps if step.status == "unverified")
    lines = [display_bullet(step, timing_available=snapshot.timing_available) for step in shown]
    if omitted:
        lines.append(f"Unverified next steps omitted: {omitted}.")
    if not snapshot.timing_available:
        lines.append("Audio timing is unavailable for this text snapshot.")
    lines.append(
        "A matching quote is navigable evidence, not proof of entailment or acoustic correctness."
    )
    return lines


def sidecar_document(snapshot: SourceSnapshot, steps: list[ResolvedStep]) -> dict[str, Any]:
    """Versioned evidence record. It stores no invented owner or deadline fields."""
    return {
        "schema": EVIDENCE_SCHEMA,
        "pipeline": PIPELINE,
        "source_sha256": snapshot.source_sha256,
        "source_kind": snapshot.kind,
        "timing_available": snapshot.timing_available,
        "limitation": (
            "Reference validity is not a human-assessed support or omission score, "
            "and it is not acoustic verification."
        ),
        "steps": [
            {
                "text": step.text,
                "status": step.status,
                "source_ids": list(step.source_ids),
                "quotes": list(step.quotes),
                "start": step.start,
                "end": step.end,
                "review_warning": step.review_warning,
                "reason": step.reason,
            }
            for step in steps
        ],
        "omitted_unverified": sum(1 for step in steps if step.status == "unverified"),
    }


def write_sidecar(path: Path, snapshot: SourceSnapshot, steps: list[ResolvedStep]) -> Path:
    """Write the evidence sidecar next to the notes file."""
    path.write_text(
        json.dumps(sidecar_document(snapshot, steps), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
