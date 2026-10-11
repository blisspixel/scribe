"""Bounded timeline comparison and literal-safe acoustic review publication."""

import json
import math
import re
import unicodedata
from difflib import SequenceMatcher
from hashlib import file_digest
from pathlib import Path

from scribe.models.transcript import Transcript
from scribe.models.transcription_review import AcousticPass, ReviewReceipt, ReviewSpan
from scribe.utils.review_timeline import TimedTextIndex
from scribe.utils.safe_write import atomic_write, safe_copy
from scribe.utils.transcript_writers import transcript_to_dict


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    words = []
    for match in re.finditer(r"\w+(?:[.,]\d+)*", text):
        word = match.group()
        if word[0].isdigit():
            start = match.start()
            while start and (
                text[start - 1] in "+-±\u2212" or unicodedata.category(text[start - 1]) == "Sc"
            ):
                start -= 1
            end = match.end()
            while end < len(text) and (
                text[end] in "%‰‱\u066a" or unicodedata.category(text[end]) == "Sc"
            ):
                end += 1
            word = text[start:end].replace("\u2212", "-")
        words.append(word)
    return [
        piece
        for word in words
        for piece in (
            list(word)
            if any(
                "CJK" in unicodedata.name(c, "")
                or "HIRAGANA" in unicodedata.name(c, "")
                or "KATAKANA" in unicodedata.name(c, "")
                for c in word
            )
            else [word]
        )
    ]


def _shared_speech_gaps(
    primary: TimedTextIndex, secondary: AcousticPass, secondary_index: TimedTextIndex
) -> list[ReviewSpan]:
    """Exact VAD locations expose omissions even when both decodes agree on nothing."""
    intervals: list[tuple[float, float]] = []
    for start, end in sorted(span for window in secondary.windows for span in window.speech_spans):
        if intervals and start <= intervals[-1][1]:
            previous = intervals.pop()
            intervals.append((previous[0], max(previous[1], end)))
        else:
            intervals.append((start, end))
    coverage: dict[int, float] = {}
    for start, end in intervals:
        start, end = max(0, start), min(secondary.normalized_seconds, end)
        cursor = start
        while cursor < end:
            bucket = int(cursor // 5)
            stop = min(end, (bucket + 1) * 5)
            coverage[bucket] = coverage.get(bucket, 0) + stop - cursor
            cursor = stop
    gaps = []
    for bucket, speech_seconds in sorted(coverage.items()):
        start, end = bucket * 5.0, min((bucket + 1) * 5.0, secondary.normalized_seconds)
        if (
            speech_seconds >= 0.5
            and not primary.has_text(start, end)
            and not secondary_index.has_text(start, end)
        ):
            gaps.append(
                ReviewSpan(
                    start, end, ("possible speech omitted by both passes; listen to source",)
                )
            )
    return gaps


def compare_passes(primary: Transcript, secondary: AcousticPass) -> list[ReviewSpan]:
    """Short time buckets bound edit alignment; disagreement is not reference WER."""
    duration = secondary.normalized_seconds
    if not math.isfinite(duration) or not 0 < duration <= 48 * 3600:
        raise ValueError("Invalid prepared source duration; acoustic comparison refused")
    if primary.duration is not None and (
        not math.isfinite(primary.duration) or primary.duration < 0
    ):
        raise ValueError("Invalid primary duration; acoustic comparison refused")
    primary_index = TimedTextIndex.build(primary)
    secondary_index = TimedTextIndex.build(secondary.transcript)
    spans = _shared_speech_gaps(primary_index, secondary, secondary_index)
    if primary.duration is not None and abs(primary.duration - duration) > 1:
        spans.append(ReviewSpan(0, duration, ("primary duration differs from decoded source",)))
    start = 0.0
    while start < duration:
        end = min(duration, start + 15)
        first = primary_index.text_at(start, end)
        second = secondary_index.text_at(start, end)
        left, right = _tokens(first), _tokens(second)
        if left != right:
            reasons: tuple[str, ...]
            # Never align an unbounded transcript or pathological model output.
            if max(len(left), len(right)) > 2048:
                reasons = ("comparison token limit; requires source review",)
            else:
                matcher = SequenceMatcher(None, left, right, autojunk=False)
                reasons = tuple(
                    sorted({tag for tag, *_ in matcher.get_opcodes() if tag != "equal"})
                )
                if [token for token in left if any(c.isdigit() for c in token)] != [
                    token for token in right if any(c.isdigit() for c in token)
                ]:
                    reasons += ("numeric disagreement",)
                if not left or not right:
                    reasons += ("speech coverage disagreement",)
            spans.append(ReviewSpan(start, end, reasons, first, second))
        start = end
    for window in secondary.windows:
        if window.stable_language is None and window.status != "no_speech":
            spans.append(ReviewSpan(window.start, window.end, ("uncertain language",)))
        if window.speech_seconds >= 0.25 and not primary_index.has_text(window.start, window.end):
            spans.append(ReviewSpan(window.start, window.end, ("possible primary speech gap",)))
    for diagnostic in secondary.diagnostics:
        diagnostic_reasons = []
        if diagnostic.avg_logprob < -1:
            diagnostic_reasons.append("weak acoustic score")
        if diagnostic.compression_ratio > 2.4:
            diagnostic_reasons.append("repetition risk")
        if diagnostic.temperature > 0:
            diagnostic_reasons.append("temperature fallback")
        if diagnostic_reasons:
            spans.append(ReviewSpan(diagnostic.start, diagnostic.end, tuple(diagnostic_reasons)))
    return sorted(spans, key=lambda span: (span.start, span.end, span.reasons))


def primary_flags(acoustic: AcousticPass) -> list[ReviewSpan]:
    spans = []
    previous: str | None = None
    forced = acoustic.transcript.metadata.get("requested_language")
    for window in acoustic.windows:
        language = window.stable_language
        reasons = []
        if language and previous and language != previous:
            reasons.append("language switch boundary; short switches may be missed")
        if forced and language and forced != language:
            reasons.append("observed language conflicts with forced primary language")
        if window.status != "no_speech" and language is None:
            reasons.append("uncertain primary language")
        if reasons:
            spans.append(ReviewSpan(window.start, window.end, tuple(reasons)))
        if language:
            previous = language
    for diagnostic in acoustic.diagnostics:
        if (
            diagnostic.avg_logprob < -1
            or diagnostic.compression_ratio > 2.4
            or diagnostic.temperature > 0
        ):
            spans.append(
                ReviewSpan(
                    diagnostic.start,
                    diagnostic.end,
                    ("primary acoustic diagnostic requires review",),
                )
            )
    return spans


def _clock(seconds: float) -> str:
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours:02}:{minutes:02}:{seconds:04.1f}"


def render_review(receipt: ReviewReceipt) -> str:
    lines = [
        "# Acoustic transcription review",
        "",
        receipt.to_dict()["limits"],
        "",
        f"Status: {receipt.status}; requires source review: {receipt.requires_review}",
        f"Primary: {receipt.primary_backend} / {receipt.primary_model}",
        f"Secondary: faster-whisper / {receipt.secondary_model}",
        f"Comparison: {receipt.comparison_kind}",
        f"Source: {json.dumps(receipt.source_path, ensure_ascii=False)}",
        f"Source SHA-256: {receipt.source_sha256 or 'unavailable'}",
        f"Measured review elapsed: {receipt.elapsed_seconds:.1f} seconds",
        "",
        "Language scores and acoustic scores are model outputs, not calibrated correctness.",
        "Language windows cover the timeline; brief or within-window switches can be missed.",
        "Review time buckets can flag timestamp jitter as disagreement. No text was corrected.",
        "",
    ]
    for label, windows in (
        ("Primary", receipt.language_windows),
        ("Secondary", receipt.secondary_language_windows),
    ):
        if not windows:
            continue
        lines.extend(
            [
                f"## {label} language observations",
                "",
                "| Source time | Observed model language/score | Status |",
                "| --- | --- | --- |",
            ]
        )
        for window in windows[:100]:
            candidate = (
                f"{window.candidates[0][0]} / {window.candidates[0][1]:.3f}"
                if window.candidates
                else "none"
            )
            candidate = candidate.replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {_clock(window.start)} to {_clock(window.end)} | {candidate} | {window.status} |"
            )
        lines.extend(
            [
                "",
                "All windows and speech spans are retained in review.json; this table shows up to 100 windows.",
                "",
            ]
        )
    if receipt.error:
        lines.extend(["Incomplete requested review: " + receipt.error, ""])
    if not receipt.spans:
        lines.extend(["No differences were flagged. This does not establish accuracy.", ""])
    for span in receipt.spans:
        lines.extend(
            [
                f"## {_clock(span.start)} to {_clock(span.end)}",
                "",
                "Requires review: " + "; ".join(span.reasons),
                "",
                f"Listen to source {_clock(max(0, span.start - 2))} to {_clock(span.end + 2)}.",
                "",
            ]
        )
        for label, text in (("Primary", span.primary), ("Secondary", span.secondary)):
            if text:
                # Indent source text so model-produced Markdown stays literal.
                lines.extend([label + ":", "", *("    " + line for line in text.splitlines()), ""])
    return "\n".join(lines)


def publish_review(
    folder: Path,
    receipt: ReviewReceipt,
    primary: Transcript | None,
    secondary: Transcript | None,
    *,
    primary_text_path: Path | None = None,
) -> list[Path]:
    """Write individual files atomically; publish the governing receipt last."""
    artifacts = []
    if primary_text_path is not None:
        snapshot = safe_copy(primary_text_path, folder / "primary-text.txt")
        with snapshot.open("rb") as stream:
            snapshot_sha256 = file_digest(stream, "sha256").hexdigest()
        receipt.primary_options.update(
            original_primary_text_path=str(primary_text_path.resolve()),
            primary_text_path=str(snapshot.resolve()),
            primary_text_sha256=snapshot_sha256,
        )
        artifacts.append(snapshot)
    for name, transcript in (("primary-acoustic.json", primary), ("secondary.json", secondary)):
        if transcript is not None:
            path = folder / name
            atomic_write(
                path,
                json.dumps(transcript_to_dict(transcript), ensure_ascii=False, indent=2) + "\n",
            )
            artifacts.append(path)
    markdown = folder / "review.md"
    atomic_write(markdown, render_review(receipt))
    artifacts.append(markdown)
    manifest = folder / "review.json"
    receipt.artifacts = [str(path) for path in [*artifacts, manifest]]
    atomic_write(manifest, json.dumps(receipt.to_dict(), ensure_ascii=False, indent=2) + "\n")
    return [*artifacts, manifest]
