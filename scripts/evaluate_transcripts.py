#!/usr/bin/env python3
"""Score a JSONL transcription manifest with reproducible WER and RTF metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scribe import __version__
from scribe.evaluation import EvaluationSample, NormalizationConfig, evaluate_samples
from scribe.utils.safe_write import atomic_write_json


def _sample_from_record(record: dict[str, Any], line_number: int) -> EvaluationSample:
    required = ("id", "reference", "hypothesis", "audio_seconds", "processing_seconds")
    missing = [key for key in required if key not in record]
    if missing:
        raise ValueError(f"line {line_number}: missing fields: {', '.join(missing)}")

    for field_name in ("id", "reference", "hypothesis"):
        if not isinstance(record[field_name], str):
            raise ValueError(f"line {line_number}: {field_name} must be a string")
    for field_name in ("audio_seconds", "processing_seconds"):
        value = record[field_name]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"line {line_number}: {field_name} must be a number")

    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in metadata.items()
    ):
        raise ValueError(f"line {line_number}: metadata must map strings to strings")

    return EvaluationSample(
        sample_id=record["id"],
        reference=record["reference"],
        hypothesis=record["hypothesis"],
        audio_seconds=float(record["audio_seconds"]),
        processing_seconds=float(record["processing_seconds"]),
        metadata=metadata,
    )


def load_manifest(path: Path) -> tuple[EvaluationSample, ...]:
    """Load and validate the documented JSONL evaluation schema."""
    samples: list[EvaluationSample] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            record = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValueError(f"line {line_number}: invalid JSON: {error.msg}") from error
        if not isinstance(record, dict):
            raise ValueError(f"line {line_number}: each JSONL value must be an object")
        samples.append(_sample_from_record(record, line_number))
    if not samples:
        raise ValueError("manifest contains no evaluation samples")
    return tuple(samples)


def build_report(
    manifest: Path,
    *,
    case_sensitive: bool = False,
    keep_punctuation: bool = False,
    revision: str | None = None,
) -> dict[str, Any]:
    """Build a versioned, machine-readable evaluation report."""
    raw_manifest = manifest.read_bytes()
    evaluation = evaluate_samples(
        load_manifest(manifest),
        NormalizationConfig(
            case_sensitive=case_sensitive,
            strip_punctuation=not keep_punctuation,
        ),
    )
    return {
        "schema": "scribe.evaluation/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "source_revision": revision or os.getenv("GITHUB_SHA") or "unknown",
        "manifest": {
            "path": str(manifest.resolve()),
            "sha256": hashlib.sha256(raw_manifest).hexdigest(),
        },
        "environment": {
            "scribe_version": __version__,
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "normalization": {
            "unicode": "NFKC",
            "case_sensitive": case_sensitive,
            "strip_punctuation": not keep_punctuation,
        },
        "results": evaluation.to_dict(),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="JSONL evaluation manifest")
    parser.add_argument("--output", type=Path, help="Write the JSON report atomically")
    parser.add_argument("--revision", help="Source revision associated with the hypotheses")
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument("--keep-punctuation", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_report(
            args.manifest,
            case_sensitive=args.case_sensitive,
            keep_punctuation=args.keep_punctuation,
            revision=args.revision,
        )
    except (OSError, TypeError, ValueError) as error:
        print(f"Evaluation failed: {error}", file=sys.stderr)
        return 2

    if args.output:
        atomic_write_json(args.output, report)
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
