"""Grounded note prompts, the shared structured shape, and Markdown rendering."""

from __future__ import annotations

import json
from typing import Any, cast

BREAKDOWN_KEYS = (
    "current_state_business",
    "current_state_technical",
    "drivers",
    "blockers",
    "future_state_business",
    "future_state_technical",
    "next_steps",
)
BREAKDOWN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {key: {"type": "array", "items": {"type": "string"}} for key in BREAKDOWN_KEYS},
    "required": list(BREAKDOWN_KEYS),
    "additionalProperties": False,
}

GROUNDING_RULES = """The transcript may be a meeting, interview, lecture, or fictional reading.
Do not assume that a meeting took place. Describe the actual content and its genre.
Use only facts explicitly supported by the transcript. Do not infer business goals,
technical plans, decisions, attendees, owners, deadlines, or a recording date.
Fictional events and characters must be described as part of the story.
File names and transcript header dates are not evidence of an event or recording date.
Do not fill gaps with plausible details. Omit irrelevant material.
Do not include signatures, meta-commentary, attributions, emojis, or em dashes."""


def summary_prompt(transcript: str) -> str:
    return f"""Create factual notes from the following transcript.
{GROUNDING_RULES}

TRANSCRIPT:
{transcript}

Write a detailed narrative summary in 2-4 paragraphs of plain prose, not JSON.
Cover the actual subject, arguments or events, and specific details. Include decisions,
challenges, and follow-up actions only when explicitly discussed. Preserve stated names,
numbers, and dates accurately; do not turn a character's actions into meeting decisions."""


def breakdown_prompt(transcript: str, summary: str, *, evidence_catalog: str | None = None) -> str:
    evidence = ""
    if evidence_catalog:
        evidence = f"""

{evidence_catalog}

For next_steps only, each item is an object with text, source_id, and quote.
Every other category stays an array of strings. Empty arrays are valid.
"""
    return f"""Organize transcript-supported information into structured notes.
{GROUNDING_RULES}

TRANSCRIPT:
{transcript}

DRAFT SUMMARY (verify against the transcript):
{summary}

Return the required JSON object with single-level arrays of complete-sentence bullets.
Use these categories only for information actually discussed:
- current_state_business: stated business context, progress, or operations.
- current_state_technical: stated systems, architecture, or technical status.
- drivers: explicit motivations for action.
- blockers: explicit obstacles to progress.
- future_state_business: explicitly proposed business outcomes.
- future_state_technical: explicitly proposed technical changes.
- next_steps: explicitly agreed or proposed follow-up actions, with owners and deadlines
  only if stated. Narrative events are not follow-up actions.
Use an empty array for every irrelevant or undiscussed category. All arrays may be empty
for a reading or lecture; the narrative summary still captures the content. Never invent
material to populate a category. Preserve proper nouns and quantitative details exactly.{evidence}"""


def refinement_prompt(
    transcript: str, breakdown: dict[str, Any], *, evidence_catalog: str | None = None
) -> str:
    evidence = ""
    if evidence_catalog:
        evidence = f"""

{evidence_catalog}

Keep next_steps as objects with text, source_id, and quote. Drop a next step whose
quote is not verbatim in the named source. Do not invent timestamps.
"""
    return f"""Review structured notes against their source transcript for accuracy.
{GROUNDING_RULES}

ORIGINAL TRANSCRIPT:
{transcript}

CURRENT NOTES (may contain errors):
{json.dumps(breakdown, indent=2)}

Return the same JSON shape. Remove unsupported claims and irrelevant business or technical
content. Keep undiscussed categories as empty arrays. Correct errors and add omitted details
only when explicit in the transcript. Do not add implicit signals or speculative context.
Preserve stated names, quantities, dates, owners, and deadlines without inventing any.{evidence}"""


def transcript_body(content: str) -> str:
    """Exclude Scribe's leading file metadata from the model's evidence.

    The Date header may be generated from today's transcription date. Keep the
    actual transcript, including any spoken dates and speaker-name information.
    """
    lines = content.splitlines()
    index = 0
    while index < len(lines) and lines[index].startswith(("Meeting:", "Date:", "Duration:")):
        index += 1
    return "\n".join(lines[index:]).strip() if index else content


def summary_prose(summary: str) -> str:
    """Render an accidental JSON response as paragraphs, never raw object syntax."""
    text = summary.strip()
    if not text:
        raise ValueError("Summary response contains no prose")
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if not text:
            raise ValueError("Summary response contains no prose")
    try:
        parsed: object = json.loads(text)
    except json.JSONDecodeError:
        return text

    def paragraphs(value: object) -> list[str]:
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, dict):
            values = cast(dict[str, object], value).values()
            return [paragraph for item in values for paragraph in paragraphs(item)]
        if isinstance(value, list):
            return [
                paragraph for item in cast(list[object], value) for paragraph in paragraphs(item)
            ]
        return []

    result = "\n\n".join(paragraphs(parsed))
    if not result:
        raise ValueError("Summary response contains no prose")
    return result


def format_notes(summary: str, breakdown: dict[str, Any], metadata: dict[str, str]) -> str:
    """Omit undiscussed categories and do not assert a header date as an event date."""
    title = metadata.get("meeting_name") or "Transcript"
    lines = [f"# Transcript Notes: {title}", ""]
    if duration := metadata.get("duration"):
        lines.extend([f"**Transcript duration**: {duration}", ""])
    lines.extend(["## Detailed Summary", "", summary_prose(summary), ""])
    for heading, sections in (
        (
            "Current State",
            (("Business", "current_state_business"), ("Technical", "current_state_technical")),
        ),
        ("Drivers", (("", "drivers"),)),
        ("Blockers", (("", "blockers"),)),
        (
            "Future State",
            (("Business", "future_state_business"), ("Technical", "future_state_technical")),
        ),
        ("Next Steps", (("", "next_steps"),)),
    ):
        if not any(breakdown.get(key) for _, key in sections):
            continue
        lines.extend([f"## {heading}", ""])
        for label, key in sections:
            if not (bullets := breakdown.get(key)):
                continue
            if label:
                lines.append(f"**{label}:**")
            lines.extend(f"- {bullet}" for bullet in bullets)
            lines.append("")
    return "\n".join(lines)
