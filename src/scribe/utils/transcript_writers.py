"""
Structured output writers for the Transcript model.

These serialize a ``Transcript`` (models/transcript.py) into machine-readable and
subtitle formats so a transcript is ingestible by other tools and queryable. The
plain ``.txt`` produced by the transcription backends is unchanged; these are
additional artifacts written alongside it.

Formats:
- ``json``: the full structured transcript (segments, speakers, provenance).
- ``vtt`` / ``srt``: subtitle cues with timestamps and speaker prefixes.
- ``md``: Markdown with a YAML frontmatter block of metadata.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scribe.models.transcript import Transcript

JSON_SCHEMA = "scribe.transcript/v1"

# Formats this module can produce (besides the always-written plain "txt").
SUPPORTED_FORMATS = ("txt", "json", "vtt", "srt", "md")


def _clock(seconds: float, *, millis_sep: str) -> str:
    """HH:MM:SS<sep>mmm timestamp; ``,`` for SRT, ``.`` for VTT."""
    seconds = max(0.0, seconds)
    total_ms = round(seconds * 1000)
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{millis_sep}{ms:03d}"


def transcript_to_dict(transcript: Transcript) -> dict[str, Any]:
    """The JSON-serializable representation of a transcript."""
    return {
        "schema": JSON_SCHEMA,
        "language": transcript.language,
        "duration": transcript.duration,
        "backend": transcript.backend,
        "model": transcript.model,
        "speakers": transcript.speakers,
        "metadata": transcript.metadata,
        "segments": [
            {
                "start": round(s.start, 3),
                "end": round(s.end, 3),
                "text": s.text.strip(),
                "speaker": s.speaker,
                "confidence": s.confidence,
            }
            for s in transcript.segments
        ],
    }


def write_json(transcript: Transcript, path: Path) -> Path:
    path.write_text(
        json.dumps(transcript_to_dict(transcript), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def write_vtt(transcript: Transcript, path: Path) -> Path:
    lines = ["WEBVTT", ""]
    for segment in transcript.segments:
        text = segment.text.strip()
        if not text:
            continue
        lines.append(
            f"{_clock(segment.start, millis_sep='.')} --> {_clock(segment.end, millis_sep='.')}"
        )
        lines.append(f"<v {segment.speaker}>{text}" if segment.speaker else text)
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_srt(transcript: Transcript, path: Path) -> Path:
    lines: list[str] = []
    index = 1
    for segment in transcript.segments:
        text = segment.text.strip()
        if not text:
            continue
        lines.append(str(index))
        lines.append(
            f"{_clock(segment.start, millis_sep=',')} --> {_clock(segment.end, millis_sep=',')}"
        )
        lines.append(f"{segment.speaker}: {text}" if segment.speaker else text)
        lines.append("")
        index += 1
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    # Quote when the value contains a structural character, has surrounding
    # whitespace, is empty, or begins with a YAML indicator character (which would
    # otherwise be parsed as an anchor, alias, tag, block scalar, directive, etc.).
    needs_quote = (
        not text
        or text != text.strip()
        or any(c in text for c in ":#[]{}\n\"'")
        or text[0] in "!&*?|>%@`,-"
    )
    if needs_quote:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def write_markdown(transcript: Transcript, path: Path, extra: dict[str, Any] | None = None) -> Path:
    """Markdown with a YAML frontmatter block, then speaker-turned body."""
    front: dict[str, Any] = {
        "backend": transcript.backend,
        "model": transcript.model,
        "language": transcript.language,
        "duration": transcript.duration,
        "speakers": transcript.speakers,
    }
    if extra:
        front.update(extra)

    lines = ["---"]
    for key, value in front.items():
        if isinstance(value, list):
            rendered = ", ".join(_yaml_scalar(v) for v in value)
            lines.append(f"{key}: [{rendered}]")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    lines.append("")

    for speaker, turn in transcript.iter_speaker_turns():
        text = " ".join(s.text.strip() for s in turn if s.text.strip())
        if not text:
            continue
        lines.append(f"**{speaker}:** {text}" if speaker else text)
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


_WRITERS = {"json": write_json, "vtt": write_vtt, "srt": write_srt, "md": write_markdown}


def write_formats(transcript: Transcript, txt_path: Path, formats: list[str]) -> list[Path]:
    """Write the requested formats next to ``txt_path``. Returns the paths written.

    ``txt`` is ignored here (the backends already wrote it). Unknown formats are skipped.
    """
    written: list[Path] = []
    for fmt in formats:
        writer = _WRITERS.get(fmt.lower())
        if writer is None:
            continue
        out = txt_path.with_suffix(f".{fmt.lower()}")
        written.append(writer(transcript, out))
    return written
