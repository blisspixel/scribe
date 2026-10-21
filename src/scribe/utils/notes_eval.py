"""
Notes provider comparison / evaluation framework.

Answers the practical question "is the free local model worth it?" by running
the same transcript through several providers and scoring the results on three
axes, exactly as designed:

- **cost**   - $0.00 for local (Ollama), real dollars for cloud providers.
- **latency** - wall-clock per provider.
- **shape** - schema compliance of a single-call extraction probe. Valid empty
  arrays are valid. Shape is not factual quality.
- **judge** - an opt-in faithfulness score. A missing or failed judge is
  unassessed and is never filled in from the shape score.

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
from typing import Any, TypeGuard

from scribe.providers import get_provider

logger = logging.getLogger(__name__)

# Cloud providers in preference order (notes default is openai).
_CLOUD_PREFERENCE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("openai", ("OPENAI_API_KEY", "SCRIBE_OPENAI_API_KEY")),
    ("xai", ("XAI_API_KEY", "SCRIBE_XAI_API_KEY")),
    ("anthropic", ("ANTHROPIC_API_KEY", "SCRIBE_ANTHROPIC_API_KEY")),
    ("gemini", ("GEMINI_API_KEY", "SCRIBE_GEMINI_API_KEY")),
)

# Single-call extraction probe. This is not the seven-section production notes
# contract. Shape compliance here is not factual quality.
EXTRACTION_PROBE = "single-call extraction probe"
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
    struct_score: float  # 0-100 schema compliance of the extraction probe
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
    """Score schema compliance of the extraction probe, from 0 to 100.

    A required section counts only when it is present as a list of strings.
    An empty list is valid. Non-empty lists do not raise the score. The result
    is not a factual-quality score.
    """
    parsed = _coerce_json(content)
    detail: dict[str, Any] = {
        "json_valid": parsed is not None,
        "pipeline": EXTRACTION_PROBE,
        "sections_valid": 0,
        "rejected": [],
        "total_items": 0,
    }
    if parsed is None:
        detail["rejected"].append("Output is not a JSON object.")
        return 0.0, detail

    valid = 0
    total_items = 0
    rejected: list[str] = []
    for key in _REQUIRED_SECTIONS:
        value = parsed.get(key)
        if not isinstance(value, list):
            rejected.append(f"{key} is missing or is not a list.")
            continue
        bad = [item for item in value if not isinstance(item, str)]
        if bad:
            rejected.append(f"{key} contains a non-string item.")
            continue
        valid += 1
        total_items += len(value)

    count = len(_REQUIRED_SECTIONS)
    detail["sections_valid"] = valid
    detail["rejected"] = rejected
    detail["total_items"] = total_items
    return round(100.0 * valid / count, 1), detail


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


def _is_score(value: object) -> TypeGuard[int | float]:
    """True for a numeric judge axis. Booleans are not scores."""
    return not isinstance(value, bool) and isinstance(value, int | float)


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
        coverage = entry.get("coverage")
        faithfulness = entry.get("faithfulness")
        structure = entry.get("structure")
        if not (_is_score(coverage) and _is_score(faithfulness) and _is_score(structure)):
            continue
        result.judge_score = round(
            (float(coverage) + float(faithfulness) + float(structure)) / 3, 1
        )
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

    Shape compliance of the extraction probe is always computed. If ``judge_spec``
    is given, a separate judge score is added. Shape never fills a missing judge.
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


def _judge_value(result: EvalResult) -> float | None:
    if result.judge_score is None:
        return None
    return result.judge_score


def summarize_verdict(results: list[EvalResult]) -> str | None:
    """Compare judge scores only. Shape compliance never picks a winner."""
    ok = [r for r in results if r.ok]
    locals_ = [r for r in ok if r.provider == "ollama"]
    if not locals_:
        return None

    clouds = [r for r in ok if r.provider != "ollama"]
    judged_locals = [r for r in locals_ if _judge_value(r) is not None]
    judged_clouds = [r for r in clouds if _judge_value(r) is not None]
    if not clouds:
        if judged_locals and len(judged_locals) == len(locals_):
            best_local = max(judged_locals, key=lambda item: item.judge_score or 0)
            return (
                f"Local {best_local.model} judge score {best_local.judge_score:.1f} "
                "at $0.00. Fully offline. Shape compliance is not factual quality."
            )
        return (
            "Local comparison stayed offline at $0.00. Factual quality was not assessed. "
            "Shape compliance is not a quality score."
        )

    if len(judged_locals) != len(locals_) or len(judged_clouds) != len(clouds):
        return (
            "Factual quality was not compared. A missing, failed, or partial judge "
            "leaves quality unassessed. Shape compliance is not a quality score."
        )

    best_local = max(judged_locals, key=lambda item: item.judge_score or 0)
    best_cloud = max(judged_clouds, key=lambda item: item.judge_score or 0)
    gap = (best_cloud.judge_score or 0) - (best_local.judge_score or 0)
    cloud_cost = "" if best_cloud.cost_usd is None else f" (~${best_cloud.cost_usd:.4f}/run)"
    if gap <= 1.0:
        return (
            f"Local {best_local.model} is worth it on the judge score versus "
            f"{best_cloud.model}{cloud_cost} at $0.00. "
            "Schema compliance was not used as quality."
        )
    return (
        f"{best_cloud.model}{cloud_cost} still leads on the judge score; "
        f"{best_local.model} is the free offline fallback. "
        "Schema compliance was not used as quality."
    )


def format_scorecard(results: list[EvalResult]) -> str:
    """Render cost, latency, shape, and judge scores as separate columns."""
    judged = any(r.judge_score is not None for r in results)
    header = f"{'model':<34} {'cost':>10} {'time':>8} {'shape':>7}"
    if judged:
        header += f" {'judge':>6}"
    lines = [
        f"Pipeline: {EXTRACTION_PROBE}. Shape is schema compliance, not factual quality.",
        header,
        "-" * len(header),
    ]

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
            cell = "n/a" if r.judge_score is None else f"{r.judge_score:.1f}"
            row += f" {cell:>6}"
        lines.append(row)

    if judged and any(r.ok and r.judge_score is None for r in results):
        lines.append("Missing judge scores were not assessed and were not filled from shape.")
    return "\n".join(lines)
