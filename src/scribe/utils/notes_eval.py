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
itself may contain colons - only the first colon is the separator).
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

from scribe.providers import get_provider

logger = logging.getLogger(__name__)

# Cloud providers in preference order (notes default is openai).
_CLOUD_PREFERENCE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("openai", ("OPENAI_API_KEY", "SCRIBE_OPENAI_API_KEY")),
    ("xai", ("XAI_API_KEY", "SCRIBE_XAI_API_KEY")),
    ("anthropic", ("ANTHROPIC_API_KEY", "SCRIBE_ANTHROPIC_API_KEY")),
    ("gemini", ("GEMINI_API_KEY", "SCRIBE_GEMINI_API_KEY")),
)

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
        if not isinstance(entry, dict):
            continue
        # Models often emit the integer candidate index as a float (1.0, 2.0);
        # accept those instead of silently dropping the score.
        cand = entry.get("candidate")
        if isinstance(cand, bool):
            continue
        if isinstance(cand, int) or (isinstance(cand, float) and cand.is_integer()):
            by_candidate[int(cand)] = entry

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


@dataclass
class ProviderAvailability:
    """What this machine can actually compare right now."""

    cloud: list[str]  # cloud providers with keys, in preference order
    ollama_models: list[str]  # installed Ollama model names, largest first
    ollama_auto: str | None  # the auto-selected local model for this GPU


def detect_availability() -> ProviderAvailability:
    """Probe env keys and the local Ollama server to see what's usable."""
    cloud = [name for name, envs in _CLOUD_PREFERENCE if any(os.getenv(e) for e in envs)]

    from scribe.utils.ollama_models import (
        available_model_memory_gb,
        list_installed_models,
        select_ollama_model,
    )

    base_url = os.getenv("SCRIBE_OLLAMA_BASE_URL")
    models = list_installed_models(base_url)
    names = [m.name for m in models]
    auto = select_ollama_model(models, available_model_memory_gb()) if models else None
    return ProviderAvailability(cloud=cloud, ollama_models=names, ollama_auto=auto)


def resolve_compare_plan(
    providers_arg: str | None,
    judge_arg: str | None,
    avail: ProviderAvailability,
) -> tuple[list[str], str | None]:
    """
    Turn a short preset (or explicit list) + judge choice into concrete specs.

    Presets: 'smart'/'' -> default cloud vs best local; 'local' -> every
    installed local model (free/offline); 'all' -> every cloud with a key plus
    best local. Anything else is treated as an explicit comma-separated list.

    Judge: 'auto' picks a cloud judge for cloud-involving runs and none for the
    offline 'local' preset; 'none'/'off' disables it; otherwise it's explicit.
    """
    raw = (providers_arg or "smart").strip()
    preset = raw.lower()
    specs: list[str]

    if preset in ("smart", "auto", ""):
        specs = []
        if avail.cloud:
            specs.append(avail.cloud[0])
        if avail.ollama_auto:
            specs.append(f"ollama:{avail.ollama_auto}")
    elif preset == "local":
        specs = [f"ollama:{m}" for m in avail.ollama_models]
    elif preset in ("all", "everything"):
        specs = list(avail.cloud)
        if avail.ollama_auto:
            specs.append(f"ollama:{avail.ollama_auto}")
    else:
        specs = [s.strip() for s in raw.split(",") if s.strip()]

    all_local = bool(specs) and all(s.lower().startswith("ollama") for s in specs)
    judge_pref = (judge_arg or "auto").strip().lower()
    if judge_pref in ("none", "off", "no", "false"):
        judge: str | None = None
    elif judge_pref == "auto":
        # Stay fully offline when every candidate is local; otherwise judge with cloud.
        judge = None if all_local else (avail.cloud[0] if avail.cloud else None)
    else:
        judge = (judge_arg or "").strip()

    return specs, judge


def summarize_verdict(results: list[EvalResult]) -> str | None:
    """Plain-English bottom line: is the free local model worth it?"""
    ok = [r for r in results if r.ok]
    locals_ = [r for r in ok if r.provider == "ollama"]
    if not locals_:
        return None

    def quality(r: EvalResult) -> float:
        # Prefer the judge verdict when present; else fold struct % onto a 1-10 scale.
        return r.judge_score if r.judge_score is not None else r.struct_score / 10.0

    best_local = max(locals_, key=quality)
    clouds = [r for r in ok if r.provider != "ollama"]
    if not clouds:
        return (
            f"Local {best_local.model} scored {best_local.struct_score:.0f}% structure "
            f"at $0.00 - fully offline."
        )

    best_cloud = max(clouds, key=quality)
    gap = quality(best_cloud) - quality(best_local)
    cloud_cost = "" if best_cloud.cost_usd is None else f" (~${best_cloud.cost_usd:.4f}/run)"
    if gap <= 1.0:
        return (
            f"Local {best_local.model} is worth it - comparable quality to "
            f"{best_cloud.model}{cloud_cost} at $0.00. Set SCRIBE_NOTES_PROVIDER=ollama."
        )
    return (
        f"{best_cloud.model}{cloud_cost} still leads on quality; "
        f"{best_local.model} is the free offline fallback."
    )


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
