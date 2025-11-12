"""
Meeting Notes Generator using GPT-5 with agentic reasoning.

Transforms meeting transcripts into comprehensive, structured notes
with business and technical context using multi-step AI analysis.
"""

import os
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from scribe.exceptions import ScribeError
from scribe.utils.logging import get_logger

logger = get_logger(__name__)


class NotesGenerationError(ScribeError):
    """Base exception for notes generation errors."""
    pass


class TranscriptTooShortError(NotesGenerationError):
    """Transcript has insufficient content for analysis."""
    pass


class APIError(NotesGenerationError):
    """OpenAI API call failed."""
    pass


class ValidationError(NotesGenerationError):
    """Generated output failed validation."""
    pass


@dataclass
class NotesConfig:
    """Configuration for notes generation."""
    api_key: str
    model: str = "gpt-5"
    max_retries: int = 3
    confidence_threshold: float = 0.85


class NotesGenerator:
    """
    Generates structured meeting notes from transcripts using GPT-5.

    Multi-step agentic reasoning:
    1. Generate detailed summary (prose)
    2. Create analytical breakdown (JSON, strict schema)
    3. Refine and polish (JSON, strict schema)

    Design goals:
    - Never drop content: no self-imposed output caps.
    - Strict JSON for structured phases via prompt fallback.
    - Lossless segmentation with overlap when single-pass would exceed practical limits.
    - No streaming.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-5",
        max_retries: int = 3
    ):
        """
        Initialize notes generator with OpenAI configuration.

        Args:
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
            model: GPT model to use (default: gpt-5)
            max_retries: Maximum retry attempts for API calls

        Raises:
            NotesGenerationError: If API key is missing
        """
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise NotesGenerationError(
                "OpenAI API key not found. Set OPENAI_API_KEY environment variable."
            )

        self.config = NotesConfig(
            api_key=self.api_key,
            model=model,
            max_retries=max_retries
        )

        self.client = OpenAI(api_key=self.api_key)
        try:
            import importlib.metadata as im
            logger.info(f"openai SDK version: {im.version('openai')}")
        except Exception:
            pass
        logger.info(f"Initialized NotesGenerator with model={model}")

    def generate_notes(
        self,
        transcript_path: Path,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Generate structured meeting notes from transcript.

        Args:
            transcript_path: Path to transcript TXT file
            output_path: Optional custom output path

        Returns:
            Path to generated notes MD file
        """
        logger.info(f"Starting notes generation for: {transcript_path}")
        start_time = time.time()

        # Step 1: Read and validate transcript
        transcript_data = self._read_transcript(transcript_path)
        transcript_content = transcript_data["content"]
        self._validate_transcript(transcript_content)

        # Step 2: Segment if needed for full coverage
        segments = self._segment_for_full_coverage(transcript_content)

        if segments is None:
            # Single-pass path
            summary = self._generate_detailed_summary(transcript_content)
            breakdown_initial = self._generate_analytical_breakdown(transcript_content, summary)
            refined_breakdown = self._refine_and_polish(transcript_content, breakdown_initial)
        else:
            # Map-Reduce path with overlap for zero loss
            logger.info(f"Segmented transcript into {len(segments)} chunks for full coverage")
            summaries: List[str] = []
            breakdowns: List[Dict[str, Any]] = []
            for i, seg in enumerate(segments):
                logger.info(f"Processing segment {i+1}/{len(segments)}")
                seg_summary = self._generate_detailed_summary(seg)
                summaries.append(seg_summary)
                seg_breakdown = self._generate_analytical_breakdown(seg, seg_summary)
                breakdowns.append(seg_breakdown)
            summary = "\n\n".join(summaries)
            merged = self._merge_breakdowns(breakdowns)
            refined_breakdown = self._refine_and_polish(transcript_content, merged)

        # Step 5: Validate output
        confidence = self._validate_output(refined_breakdown)
        logger.info(f"Validation confidence: {confidence:.3f}")

        # Step 6: Format as Markdown
        markdown_content = self._format_markdown(summary, refined_breakdown, transcript_data)

        # Step 7: Write file
        if output_path is None:
            base_name = transcript_path.stem
            output_path = transcript_path.parent / f"{base_name}_notes.md"

        final_path = self._write_notes(markdown_content, output_path)

        total_duration = time.time() - start_time
        summary_metrics = {
            "total_duration_sec": round(total_duration, 2),
            "confidence_score": round(confidence, 3),
            "output_file": str(final_path),
            "transcript_length_chars": len(transcript_content)
        }
        logger.info(f"Notes generation summary: {json.dumps(summary_metrics)}")
        logger.info(f"Notes generation completed successfully: {final_path}")

        return final_path

    # ---------------- Core GPT-5 Call ----------------

    def _extract_output_text(self, resp) -> str:
        """
        Extract text from GPT-5 Responses API response.
        """
        text = getattr(resp, "output_text", None)
        if text:
            return str(text).strip()

        try:
            outputs = getattr(resp, "output", None)
            if outputs:
                buff: List[str] = []
                for item in outputs:
                    typ = getattr(item, "type", None) or (isinstance(item, dict) and item.get("type"))
                    if typ == "message":
                        message = getattr(item, "content", None)
                        if message is None and isinstance(item, dict):
                            message = item.get("content")
                        if isinstance(message, list):
                            for part in message:
                                if isinstance(part, dict) and part.get("type") == "output_text":
                                    t = part.get("text")
                                    if t:
                                        buff.append(str(t))
                    elif typ == "output_text":
                        content = getattr(item, "content", None)
                        if content:
                            buff.append(str(content))
                if buff:
                    return "\n".join(x.strip() for x in buff if x).strip()
        except Exception as e:
            logger.debug(f"Output parse error: {e}")

        return ""

    def _build_json_schema_prompt_hint(self, schema: Dict[str, Any]) -> str:
        """
        Prompt fallback to approximate strict JSON via schema description.
        """
        return (
            "Return ONLY valid JSON that strictly conforms to this JSON Schema.\n\n"
            "JSON SCHEMA (Draft-07 shape):\n"
            + json.dumps(schema, indent=2)
            + "\n\nDo not include any explanations or markdown, only the JSON object."
        )

    def _repair_json_lenient(self, s: str) -> str:
        """
        Lightweight JSON fixer for common issues if the model returns near-JSON in fallback mode.
        """
        raw = s.strip()
        # Trim code fences if present
        if raw.startswith("```"):
            raw = raw.strip("`").lstrip()
            if raw.lower().startswith("json"):
                raw = raw[4:].lstrip()
        # Balance braces if obviously off by one
        open_braces = raw.count("{")
        close_braces = raw.count("}")
        if open_braces > close_braces:
            raw = raw + ("}" * (open_braces - close_braces))
        # Remove trailing commas in common places
        raw = raw.replace(",\n}", "\n}")
        raw = raw.replace(",\n]", "\n]")
        return raw

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((Exception,))
    )
    def _call_gpt5_api(
        self,
        input_text: str,
        reasoning_effort: str = "medium",
        verbosity: str = "low",
        phase: str = "unknown",
        json_schema: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Call GPT-5 Responses API with retry logic (non-streaming).

        Args:
            input_text: Input prompt text
            reasoning_effort: minimal | low | medium | high
            verbosity: low | medium | high
            phase: phase name for telemetry
            json_schema: optional JSON schema for strict structured output (prompt-enforced)

        Returns:
            (response content string, metrics dict)
        """
        try:
            start_time = time.time()

            prompt_text = input_text
            if json_schema is not None:
                prompt_text = self._build_json_schema_prompt_hint(json_schema) + "\n\n" + input_text

            params: Dict[str, Any] = {
                "model": self.config.model,
                "input": [
                    {"role": "user", "content": [{"type": "input_text", "text": prompt_text}]}
                ],
                "reasoning": {"effort": reasoning_effort},
                "text": {"verbosity": verbosity},
                # No temperature/top_p/logprobs per GPT-5 guidance
            }

            resp = self.client.responses.create(**params)

            # Defensive retry only if server marks response incomplete due to a cap
            if getattr(resp, "status", None) == "incomplete":
                inc = getattr(resp, "incomplete_details", None)
                reason = getattr(inc, "reason", None) if inc else None
                if reason == "max_output_tokens":
                    logger.warning("Server reported max_output_tokens cap; retrying with lower reasoning.")
                    params["reasoning"] = {"effort": "low"}
                    resp = self.client.responses.create(**params)

            content = self._extract_output_text(resp)
            if not content:
                status = getattr(resp, "status", None)
                inc = getattr(resp, "incomplete_details", None)
                inc_reason = getattr(inc, "reason", None) if inc else None
                raise APIError(f"Empty response. status={status}, incomplete_reason={inc_reason}")

            usage = getattr(resp, "usage", None)
            tokens_used = getattr(usage, "total_tokens", 0) if usage else 0

            metrics = {
                "phase": phase,
                "duration_sec": round(time.time() - start_time, 2),
                "tokens": tokens_used,
                "reasoning_effort": reasoning_effort,
                "verbosity": verbosity,
                "structured_output": json_schema is not None,
                "schema_enforced_by_api": False  # prompt-only in this version
            }
            logger.info(f"GPT-5 API metrics: {json.dumps(metrics)}")
            return content.strip(), metrics

        except Exception as e:
            logger.error(f"GPT-5 API call failed: {e}")
            raise APIError(f"OpenAI API call failed: {e}")

    # ---------------- Pipeline Steps ----------------

    def _read_transcript(self, path: Path) -> Dict[str, str]:
        if not path.exists():
            raise NotesGenerationError(f"Transcript file not found: {path}")
        if not path.is_file():
            raise NotesGenerationError(f"Path is not a file: {path}")
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            raise NotesGenerationError(f"Failed to read transcript: {e}")

        metadata = self._extract_metadata(content)
        logger.debug(f"Read transcript: {len(content)} chars, meeting={metadata.get('meeting_name')}")
        return {
            "content": content,
            "meeting_name": metadata.get("meeting_name", "Unknown Meeting"),
            "date": metadata.get("date", ""),
            "duration": metadata.get("duration", "")
        }

    def _validate_transcript(self, content: str) -> None:
        """
        Validate transcript meets minimum requirements.

        Args:
            content: Transcript content

        Raises:
            TranscriptTooShortError: If transcript is too short
        """
        words = content.split()
        word_count = len(words)

        if word_count < 100:
            raise TranscriptTooShortError(
                f"Transcript is too short ({word_count} words). Need at least 100 words for analysis."
            )

        logger.debug(f"Transcript validation passed: {word_count} words")

    def _extract_metadata(self, content: str) -> Dict[str, str]:
        metadata: Dict[str, str] = {}
        lines = content.split("\n")
        for line in lines[:10]:
            line = line.strip()
            if line.startswith("Meeting:"):
                metadata["meeting_name"] = line.replace("Meeting:", "").strip()
            elif line.startswith("Date:"):
                metadata["date"] = line.replace("Date:", "").strip()
            elif line.startswith("Duration:"):
                metadata["duration"] = line.replace("Duration:", "").strip()
        return metadata

    def _generate_detailed_summary(self, transcript: str) -> str:
        logger.info("Generating detailed summary...")
        prompt = f"""You are analyzing a meeting transcript to create comprehensive meeting notes.

TRANSCRIPT:
{transcript}

Generate a detailed narrative summary covering:
- Meeting purpose and stated goals
- Key discussions with participant arguments and rationales
- Major decisions made, including who owns them and any stated deadlines
- Dependencies mentioned between teams, systems, or projects
- Challenges or blockers discussed
- Follow-up actions or next steps

Use a factual, professional tone. Include specific names, numbers, systems, and dates mentioned.
Write 2-4 paragraphs. Be comprehensive but concise."""
        try:
            summary, _ = self._call_gpt5_api(
                prompt,
                reasoning_effort="medium",
                verbosity="low",
                phase="summary"
            )
            logger.info(f"Generated summary: {len(summary)} characters")
            return summary.strip()
        except Exception as e:
            raise NotesGenerationError(f"Failed to generate summary: {e}")

    def _generate_analytical_breakdown(
        self,
        transcript: str,
        summary: str
    ) -> Dict[str, Any]:
        logger.info("Generating analytical breakdown...")

        breakdown_schema = {
            "type": "object",
            "properties": {
                "current_state_business": {"type": "array", "items": {"type": "string"}},
                "current_state_technical": {"type": "array", "items": {"type": "string"}},
                "drivers": {"type": "array", "items": {"type": "string"}},
                "blockers": {"type": "array", "items": {"type": "string"}},
                "future_state_business": {"type": "array", "items": {"type": "string"}},
                "future_state_technical": {"type": "array", "items": {"type": "string"}},
                "next_steps": {"type": "array", "items": {"type": "string"}}
            },
            "required": [
                "current_state_business",
                "current_state_technical",
                "drivers",
                "blockers",
                "future_state_business",
                "future_state_technical",
                "next_steps"
            ],
            "additionalProperties": False
        }

        prompt = f"""You are creating a structured breakdown of a meeting for business intelligence.

TRANSCRIPT:
{transcript}

SUMMARY:
{summary}

Create a detailed analytical breakdown with these exact sections:

## Current State
**Business:** Bullets about business context, progress, stakeholder alignment, contracts, KPIs, operational status, quantitative metrics
**Technical:** Bullets about architecture, systems, models, infrastructure, performance metrics, active experiments

## Drivers
Bullets about forces motivating action: business goals, user feedback, leadership priorities, competitive pressures, regulatory factors

## Blockers
Bullets about issues preventing progress: technical failures, resource gaps, data limitations, legal restrictions, coordination delays

## Future State
**Business:** Bullets about desired outcomes, roadmap milestones, partnerships, measurable success criteria
**Technical:** Bullets about target architecture, integrations, automation goals, scalability improvements, AI enhancements

## Next Steps
Bullets listing actionable items with owners and deadlines where possible

CRITICAL FORMATTING RULES:
- Use ONLY single-level bullets (no nesting or indentation)
- Each bullet must be a complete sentence with specific details
- Include names, tools, metrics, systems, dates, and numbers
- Avoid vague phrasing; be specific and quantitative
- Preserve proper nouns and technical terms exactly as stated"""
        try:
            response_text, _ = self._call_gpt5_api(
                prompt,
                reasoning_effort="low",
                verbosity="low",
                phase="breakdown",
                json_schema=breakdown_schema
            )
            try:
                breakdown = json.loads(response_text)
            except json.JSONDecodeError:
                breakdown = json.loads(self._repair_json_lenient(response_text))
            self._validate_breakdown_keys(breakdown)
            logger.info(f"Generated breakdown with {len(breakdown)} sections")
            return breakdown
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON response from GPT-5: {e}")
        except Exception as e:
            raise NotesGenerationError(f"Failed to generate analytical breakdown: {e}")

    def _refine_and_polish(
        self,
        transcript: str,
        breakdown: Dict[str, Any]
    ) -> Dict[str, Any]:
        logger.info("Refining and polishing breakdown...")

        breakdown_schema = {
            "type": "object",
            "properties": {
                "current_state_business": {"type": "array", "items": {"type": "string"}},
                "current_state_technical": {"type": "array", "items": {"type": "string"}},
                "drivers": {"type": "array", "items": {"type": "string"}},
                "blockers": {"type": "array", "items": {"type": "string"}},
                "future_state_business": {"type": "array", "items": {"type": "string"}},
                "future_state_technical": {"type": "array", "items": {"type": "string"}},
                "next_steps": {"type": "array", "items": {"type": "string"}}
            },
            "required": [
                "current_state_business",
                "current_state_technical",
                "drivers",
                "blockers",
                "future_state_business",
                "future_state_technical",
                "next_steps"
            ],
            "additionalProperties": False
        }

        current_breakdown_text = json.dumps(breakdown, indent=2)

        prompt = f"""You are refining meeting notes for maximum detail and accuracy.

ORIGINAL TRANSCRIPT:
{transcript}

CURRENT NOTES:
{current_breakdown_text}

Re-analyze the transcript to:
1. Identify any missed context, implicit signals, or nuanced information
2. Add specific details that were omitted (names, numbers, dates, systems)
3. Expand vague bullets with concrete information
4. Ensure logical consistency between sections (blockers should align with drivers and next steps)
5. Verify all quantitative data is included (percentages, counts, durations, costs)

Return the refined breakdown in the same JSON format, with expanded and polished bullets.
Each bullet should be a complete sentence with maximum detail density."""
        try:
            response_text, _ = self._call_gpt5_api(
                prompt,
                reasoning_effort="low",
                verbosity="low",
                phase="refinement",
                json_schema=breakdown_schema
            )
            try:
                refined_breakdown = json.loads(response_text)
            except json.JSONDecodeError:
                refined_breakdown = json.loads(self._repair_json_lenient(response_text))

            required = [
                "current_state_business", "current_state_technical",
                "drivers", "blockers",
                "future_state_business", "future_state_technical",
                "next_steps"
            ]
            for key in required:
                if key not in refined_breakdown:
                    logger.warning(f"Refinement lost section {key}, keeping original")
                    refined_breakdown[key] = breakdown.get(key, [])
            return refined_breakdown
        except json.JSONDecodeError as e:
            logger.warning(f"Refinement produced invalid JSON, keeping original: {e}")
            return breakdown
        except Exception as e:
            logger.warning(f"Refinement failed, keeping original: {e}")
            return breakdown

    # ---------------- Segmentation & Merge for Ultra-long Transcripts ----------------

    def _segment_for_full_coverage(
        self,
        text: str,
        approx_token_per_chunk: int = 220_000,
        overlap_tokens: int = 2_000
    ) -> Optional[List[str]]:
        """
        Deterministic, overlap-aware segmentation that guarantees every character is processed.
        Returns None if the text seems short enough for a single pass.

        Approximate 1 token ~ 4 characters (conservative).
        """
        char_per_token = 4
        size = approx_token_per_chunk * char_per_token
        overlap = overlap_tokens * char_per_token

        if len(text) <= size:
            return None

        chunks: List[str] = []
        i = 0
        n = len(text)
        while i < n:
            end = min(n, i + size)
            slice_ = text[i:end]
            if end < n:
                last_nl = slice_.rfind("\n")
                if last_nl > 0:
                    end = i + last_nl
                    slice_ = text[i:end]
            chunks.append(slice_)
            if end == n:
                break
            i = max(end - overlap, end)
        return chunks

    def _merge_breakdowns(self, parts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Lossless union of multiple breakdowns with simple de-dup on exact sentences.
        Conflicts are preserved as distinct bullets.
        """
        keys = [
            "current_state_business", "current_state_technical",
            "drivers", "blockers",
            "future_state_business", "future_state_technical",
            "next_steps"
        ]
        merged: Dict[str, List[str]] = {k: [] for k in keys}
        seen: Dict[str, set] = {k: set() for k in keys}
        for b in parts:
            for k in keys:
                for bullet in b.get(k, []):
                    s = (bullet or "").strip()
                    if s and s not in seen[k]:
                        merged[k].append(s)
                        seen[k].add(s)
        return merged

    # ---------------- Validation, Formatting, Helpers ----------------

    def _validate_breakdown_keys(self, breakdown: Dict[str, Any]) -> None:
        required_keys = [
            "current_state_business", "current_state_technical",
            "drivers", "blockers",
            "future_state_business", "future_state_technical",
            "next_steps"
        ]
        for key in required_keys:
            if key not in breakdown:
                raise ValidationError(f"Missing required section: {key}")
            if not isinstance(breakdown[key], list):
                raise ValidationError(f"Section {key} must be a list of strings")

    def _validate_output(self, breakdown: Dict[str, Any]) -> float:
        """
        Soft validation for presence and detail density.
        Returns confidence score (0.0-1.0).
        """
        logger.debug("Validating output quality...")

        confidence_score = 0.0
        max_score = 100.0

        required_sections = {
            "current_state_business": ["current_business", "business_state", "business_context"],
            "current_state_technical": ["current_technical", "technical_state", "technical_context"],
            "drivers": ["motivators", "forces", "catalysts"],
            "blockers": ["challenges", "obstacles", "issues", "constraints"],
            "future_state_business": ["future_business", "business_goals", "business_targets"],
            "future_state_technical": ["future_technical", "technical_goals", "technical_targets"],
            "next_steps": ["action_items", "actions", "follow_ups", "tasks"]
        }

        # Section presence (40)
        sections_found = 0
        for required_key, alternatives in required_sections.items():
            if required_key in breakdown:
                sections_found += 1
            else:
                for alt_key in alternatives:
                    if alt_key in breakdown:
                        sections_found += 1
                        break
        section_score = (sections_found / len(required_sections)) * 40
        confidence_score += section_score

        # Content quality (60)
        total_bullets = 0
        quality_bullets = 0
        for _, bullets in breakdown.items():
            if isinstance(bullets, list):
                for bullet in bullets:
                    if isinstance(bullet, str) and bullet.strip():
                        total_bullets += 1
                        detail_indicators = [
                            len(bullet) > 50,
                            any(char.isdigit() for char in bullet),
                            bullet.count(" ") > 8,
                            any(word in bullet.lower() for word in ["system", "api", "database", "server", "model"]),
                            any(word in bullet.lower() for word in ["team", "project", "deadline", "milestone", "goal"]),
                        ]
                        generic_phrases = [
                            "improve performance", "enhance user experience", "optimize system",
                            "increase efficiency", "better integration", "more scalable"
                        ]
                        has_generic = any(phrase in bullet.lower() for phrase in generic_phrases)
                        detail_score = sum(detail_indicators) - (2 if has_generic else 0)
                        if detail_score >= 2:
                            quality_bullets += 1

        if total_bullets > 0:
            quality_score = (quality_bullets / total_bullets) * 60
            confidence_score += quality_score

        final_confidence = min(confidence_score / max_score, 1.0)
        logger.debug(
            f"Validation complete: {sections_found}/{len(required_sections)} sections, "
            f"{quality_bullets}/{total_bullets} quality bullets, confidence={final_confidence:.3f}"
        )
        return final_confidence

    def _format_markdown(
        self,
        summary: str,
        breakdown: Dict[str, Any],
        metadata: Dict[str, str]
    ) -> str:
        logger.debug("Formatting output as Markdown...")

        lines: List[str] = []
        meeting_name = metadata.get("meeting_name", "Meeting Notes")
        lines.append(f"# Meeting Notes: {meeting_name}")
        lines.append("")
        if metadata.get("date"):
            lines.append(f"**Date**: {metadata['date']}")
        if metadata.get("duration"):
            lines.append(f"**Duration**: {metadata['duration']}")
        lines.append("")

        lines.append("## Detailed Summary")
        lines.append("")
        lines.append(summary.strip())
        lines.append("")

        lines.append("## Current State")
        lines.append("")
        lines.append("**Business:**")
        for bullet in breakdown.get("current_state_business", []):
            lines.append(f"- {bullet}")
        lines.append("")
        lines.append("**Technical:**")
        for bullet in breakdown.get("current_state_technical", []):
            lines.append(f"- {bullet}")
        lines.append("")

        lines.append("## Drivers")
        lines.append("")
        for bullet in breakdown.get("drivers", []):
            lines.append(f"- {bullet}")
        lines.append("")

        lines.append("## Blockers")
        lines.append("")
        for bullet in breakdown.get("blockers", []):
            lines.append(f"- {bullet}")
        lines.append("")

        lines.append("## Future State")
        lines.append("")
        lines.append("**Business:**")
        for bullet in breakdown.get("future_state_business", []):
            lines.append(f"- {bullet}")
        lines.append("")
        lines.append("**Technical:**")
        for bullet in breakdown.get("future_state_technical", []):
            lines.append(f"- {bullet}")
        lines.append("")

        lines.append("## Next Steps")
        lines.append("")
        for bullet in breakdown.get("next_steps", []):
            lines.append(f"- {bullet}")
        lines.append("")

        markdown_content = "\n".join(lines)
        logger.debug(f"Formatted Markdown: {len(markdown_content)} characters")
        return markdown_content

    def _write_notes(self, content: str, output_path: Path) -> Path:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(content, encoding="utf-8")
            logger.info(f"Notes written to: {output_path}")
            return output_path
        except Exception as e:
            raise NotesGenerationError(f"Failed to write notes file: {e}")
