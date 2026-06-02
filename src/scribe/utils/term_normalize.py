"""Deterministic domain-term normalization for transcripts.

Prompt biasing (Whisper's ``initial_prompt``) nudges the model toward your terms;
this is the reliable other half. Given a glossary of canonical terms and their known
misrecognitions ("aliases"), it rewrites the transcript text so the variants become
the canonical form: ``post gray sequel`` -> ``PostgreSQL``. It is plain, offline
find-and-replace, no model and no network, applied per segment over the shared
``Transcript`` so the ``.txt`` and the structured outputs come out consistent.

The matching is whole-word and case-insensitive, longest variant first so a longer
phrase wins over a shorter substring of it. Replacements never chain: each span of
the original text is rewritten at most once.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import replace

from scribe.models.transcript import Transcript, TranscriptSegment

# A compiled variant pattern paired with the canonical form it maps to.
Replacement = tuple[re.Pattern[str], str]


def build_replacements(aliases: Mapping[str, Iterable[str]]) -> list[Replacement]:
    """Compile (variant -> canonical) rules, longest variant first.

    Each canonical term also maps from itself, which fixes capitalization when the
    model produced the right word with the wrong case (``postgresql`` -> ``PostgreSQL``).
    """
    pairs: list[tuple[str, str]] = []
    for canonical, variants in aliases.items():
        canonical = canonical.strip()
        if not canonical:
            continue
        seen: set[str] = set()
        for variant in [canonical, *variants]:
            variant = variant.strip()
            key = variant.lower()
            if variant and key not in seen:
                seen.add(key)
                pairs.append((variant, canonical))
    # Longest variant first so "post gray sequel" beats a stray "sequel" rule.
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return [
        (re.compile(rf"(?<!\w){re.escape(variant)}(?!\w)", re.IGNORECASE), canonical)
        for variant, canonical in pairs
    ]


def normalize_text(text: str, replacements: list[Replacement]) -> str:
    """Apply compiled replacements to ``text`` without chaining rewrites.

    Matches are collected across all rules and the earliest, longest non-overlapping
    ones are applied in a single pass, so an already-canonical replacement cannot be
    re-matched by a later, shorter rule.
    """
    if not text or not replacements:
        return text

    spans: list[tuple[int, int, str]] = []
    for pattern, canonical in replacements:
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end(), canonical))

    if not spans:
        return text

    # Prefer earlier matches, and longer ones at the same start.
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))

    out: list[str] = []
    cursor = 0
    for start, end, canonical in spans:
        if start < cursor:
            continue  # overlaps an already-applied replacement
        out.append(text[cursor:start])
        out.append(canonical)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def normalize_transcript(
    transcript: Transcript, aliases: Mapping[str, Iterable[str]]
) -> Transcript:
    """Return a copy of ``transcript`` with each segment's text normalized."""
    replacements = build_replacements(aliases)
    if not replacements:
        return transcript
    segments: list[TranscriptSegment] = [
        replace(segment, text=normalize_text(segment.text, replacements))
        for segment in transcript.segments
    ]
    return replace(transcript, segments=segments)


def normalize_txt_body(text: str, replacements: list[Replacement]) -> str:
    """Normalize the body of a written ``.txt`` transcript, leaving the header alone.

    The header is the first lines up to and including the separator rule; only the
    transcript body below it is rewritten, so meeting names and dates are untouched.
    """
    marker = "\n" + "─" * 80 + "\n"
    idx = text.find(marker)
    if idx == -1:
        return normalize_text(text, replacements)
    split = idx + len(marker)
    return text[:split] + normalize_text(text[split:], replacements)
