"""
Notes provider comparison / evaluation framework.

Answers the practical question "is the free local model worth it?" by running
the same transcript through several providers and scoring the results on three
axes, exactly as designed:

- **cost**   - $0.00 for local (Ollama), real dollars for cloud providers.
- **latency** - wall-clock per provider.
- **quality** - a *hybrid* score:
    * objective structured-fidelity (always, free, deterministic, fully offline):
      did the model return valid JSON with the required, non-empty sections?
    * an opt-in LLM-as-judge rubric (coverage / faithfulness / structure) when a
      judge provider is supplied.

This mirrors Scribe's existing bake-off pattern (``joke_bakeoff`` /
``meme_bakeoff``) but emits a scorecard instead of picking a single winner.

A provider spec is ``"<provider>"`` or ``"<provider>:<model>"``, e.g.
``"openai"``, ``"openai:gpt-5.4"``, ``"ollama:qwen2.5:14b"`` (note the model
itself may contain colons — only the first colon is the separator).
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from scribe.providers import get_provider

logger = logging.getLogger(__name__)

# Structured notes schema the eval scores against. Aligned with Scribe's notes
# output and the user's framing (decisions + action items + key claims).
EVAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "decisions": {"type": "array", "items": {"type": "string"}},
        "action_items": {"type": "array", "items": {"type": "string"}},
        "key_claims": {"type": "array", "items": {"type": "string"}},
        "blockers": {"type": "array", "items": {"type": "string"}},
        "next_steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["decisions", "action_items", "key_claims", "blockers", "next_steps"],
    "additionalProperties": False,
}

_REQUIRED_SECTIONS: tuple[str, ...] = tuple(EVAL_SCHEMA["required"])

_EXTRACT_SYSTEM = (
    "You are an expert meeting analyst. Read the transcript and extract structured "
    "notes. Return concise, factual bullet points grounded strictly in the transcript."
)


@dataclass
class EvalResult:
    """Outcome of evaluating one provider on a transcript."""

    spec: str
    provider: str
    model: str
    ok: bool
    latency_sec: float
    cost_usd: float | None
    cost_source: str | None
    struct_score: float  # 0-100, objective structured fidelity
    struct_detail: dict[str, Any] = field(default_factory=dict)
    judge_score: float | None = None  # 1-10 averaged rubric, if judged
    judge_detail: dict[str, Any] | None = None
    error: str | None = None
    content: str = ""


def parse_provider_spec(spec: str) -> tuple[str, str | None]:
    """
    Split a provider spec into ``(provider, model | None)``.

    Only the first colon separates provider from model, so Ollama tags that
    themselves contain a colon survive: ``"ollama:qwen2.5:14b"`` ->
    ``("ollama", "qwen2.5:14b")``.
    """
    spec = spec.strip()
    if ":" in spec:
        provider, model = spec.split(":", 1)
        return provider.strip().lower(), model.strip()
    return spec.lower(), None


def _balanced_objects(text: str) -> list[str]:
    """Yield top-level ``{...}`` substrings by brace matching (ignores braces in strings)."""
    objects: list[str] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for i, ch in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                objects.append(text[start : i + 1])
    return objects


def _coerce_json(text: str) -> dict[str, Any] | None:
    """
    Parse a JSON object from model output, tolerating fences, prose, and the
    ``<think>...</think>`` reasoning blocks some local models emit.
    """
    if not text:
        return None

    # Strip reasoning blocks and code fences that confuse naive parsing.
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = cleaned.replace("```json", "").replace("```", "")

    for candidate in (cleaned, text):
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # Fall back to the largest balanced object that parses to a dict.
    candidates = sorted(_balanced_objects(cleaned), key=len, reverse=True)
    for blob in candidates:
        try:
            parsed = json.loads(blob)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            continue
    return None


def objective_struct_score(content: str) -> tuple[float, dict[str, Any]]:
    """
    Score structured fidelity deterministically (0-100), no model needed.

    Components:
    - json_valid (40): output parses to a JSON object.
    - required_present (30): fraction of required sections present as lists.
    - non_empty (30): fraction of required sections that are non-empty.
    """
    parsed = _coerce_json(content)
    detail: dict[str, Any] = {
        "json_valid": parsed is not None,
        "required_present": 0.0,
        "non_empty": 0.0,
        "total_items": 0,
    }
    if parsed is None:
        return 0.0, detail

    present = 0
    non_empty = 0
    total_items = 0
    for key in _REQUIRED_SECTIONS:
        value = parsed.get(key)
        if isinstance(value, list):
            present += 1
            if value:
                non_empty += 1
                total_items += len(value)

    n = len(_REQUIRED_SECTIONS)
    detail["required_present"] = present / n
    detail["non_empty"] = non_empty / n
    detail["total_items"] = total_items

    score = 40.0 + 30.0 * (present / n) + 30.0 * (non_empty / n)
    return round(score, 1), detail


def generate_notes_breakdown(
    spec: str, transcript: str, max_tokens: int = 1200, temperature: float = 0.2
) -> EvalResult:
    """Run one provider on the transcript and score it objectively (no judge)."""
    provider_name, model = parse_provider_spec(spec)
    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM},
        {"role": "user", "content": f"Transcript:\n\n{transcript}"},
    ]

    start = time.perf_counter()
    try:
        provider = get_provider("notes", provider_name=provider_name, model=model)
        resolved_model = provider.config.model
        response = provider.chat_completion_with_json(
            messages, json_schema=EVAL_SCHEMA, max_tokens=max_tokens, temperature=temperature
        )
    except Exception as exc:
        latency = time.perf_counter() - start
        logger.warning("Eval generation failed for %s: %s", spec, exc)
        return EvalResult(
            spec=spec,
            provider=provider_name,
            model=model or "(default)",
            ok=False,
            latency_sec=round(latency, 2),
            cost_usd=None,
            cost_source=None,
            struct_score=0.0,
            error=str(exc),
        )

    latency = time.perf_counter() - start
    content = str(response.get("content", ""))
    usage = response.get("usage", {}) or {}
    cost_usd = usage.get("cost_usd")
    if cost_usd is None:
        cost_usd = usage.get("estimated_cost_usd")
    struct_score, struct_detail = objective_struct_score(content)

    return EvalResult(
        spec=spec,
        provider=provider_name,
        model=resolved_model,
        ok=True,
        latency_sec=round(latency, 2),
        cost_usd=cost_usd,
        cost_source=usage.get("cost_source"),
        struct_score=struct_score,
        struct_detail=struct_detail,
        content=content,
    )


def _judge_results(results: list[EvalResult], transcript: str, judge_spec: str) -> None:
    """Score successful results 1-10 with an LLM judge (mutates results in place)."""
    judged = [r for r in results if r.ok]
    if not judged:
        return

    provider_name, model = parse_provider_spec(judge_spec)
    candidates_block = "\n\n".join(
        f"CANDIDATE {i + 1} (id={r.spec}):\n{r.content}" for i, r in enumerate(judged)
    )
    judge_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate": {"type": "integer"},
                        "coverage": {"type": "number"},
                        "faithfulness": {"type": "number"},
                        "structure": {"type": "number"},
                    },
                    "required": ["candidate", "coverage", "faithfulness", "structure"],
                },
            }
        },
        "required": ["scores"],
    }
    messages = [
        {
            "role": "system",
            "content": (
                "You are a strict, impartial judge of meeting-notes quality. Score each "
                "candidate from 1-10 on three axes: coverage (did it capture the important "
                "decisions/actions/claims?), faithfulness (is everything grounded in the "
                "transcript with no hallucinations?), and structure (is it well-formed and "
                "usable?). Return JSON only."
            ),
        },
        {
            "role": "user",
            "content": f"TRANSCRIPT:\n{transcript}\n\nCANDIDATES:\n{candidates_block}",
        },
    ]

    try:
        judge = get_provider("notes", provider_name=provider_name, model=model)
        response = judge.chat_completion_with_json(
            messages, json_schema=judge_schema, max_tokens=1500, temperature=0.0
        )
    except Exception as exc:
        logger.warning("Judge (%s) failed: %s", judge_spec, exc)
        return

    parsed = _coerce_json(str(response.get("content", "")))
    if not parsed or "scores" not in parsed:
        logger.warning("Judge returned no usable scores")
        return

    by_candidate: dict[int, dict[str, Any]] = {}
    for entry in parsed.get("scores", []):
        if isinstance(entry, dict) and isinstance(entry.get("candidate"), int):
            by_candidate[entry["candidate"]] = entry

    for i, result in enumerate(judged):
        entry = by_candidate.get(i + 1)
        if not entry:
            continue
        axes = [entry.get("coverage"), entry.get("faithfulness"), entry.get("structure")]
        nums = [float(a) for a in axes if isinstance(a, int | float)]
        if nums:
            result.judge_score = round(sum(nums) / len(nums), 1)
            result.judge_detail = {
                "coverage": entry.get("coverage"),
                "faithfulness": entry.get("faithfulness"),
                "structure": entry.get("structure"),
                "judge": judge_spec,
            }


def run_notes_eval(
    transcript: str,
    specs: list[str],
    judge_spec: str | None = None,
) -> list[EvalResult]:
    """
    Evaluate ``specs`` on ``transcript`` and return scored results.

    Objective structured-fidelity is always computed. If ``judge_spec`` is given,
    an LLM-judge rubric is layered on top (the hybrid scoring mode).
    """
    results = [generate_notes_breakdown(spec, transcript) for spec in specs]
    if judge_spec:
        _judge_results(results, transcript, judge_spec)
    return results


def format_scorecard(results: list[EvalResult]) -> str:
    """Render results as a fixed-width plain-text scorecard (judge column if present)."""
    judged = any(r.judge_score is not None for r in results)

    header = f"{'model':<34} {'cost':>10} {'time':>8} {'struct':>7}"
    if judged:
        header += f" {'judge':>6}"
    lines = [header, "-" * len(header)]

    for r in results:
        if not r.ok:
            lines.append(f"{(r.spec)[:34]:<34} {'ERROR':>10} {r.latency_sec:>7.1f}s {'--':>7}")
            continue
        label = f"{r.provider}:{r.model}"[:34]
        if r.cost_usd is None:
            cost = "n/a"
        elif r.cost_usd == 0.0:
            cost = "$0.00"
        else:
            cost = f"${r.cost_usd:.4f}"
        row = f"{label:<34} {cost:>10} {r.latency_sec:>7.1f}s {r.struct_score:>6.1f}%"
        if judged:
            row += f" {('' if r.judge_score is None else f'{r.judge_score:.1f}'):>6}"
        lines.append(row)

    return "\n".join(lines)
