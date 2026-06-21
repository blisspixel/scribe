"""Cost helpers for provider usage accounting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import deal

USD_TICKS_PER_DOLLAR = 10_000_000_000
MODEL_PRICING_LAST_REVIEWED = "2026-05-06"


@dataclass(frozen=True)
class TextModelPricing:
    """Token pricing in USD per 1M tokens."""

    input_per_million: float
    output_per_million: float


# Fallback estimates only. Exact provider-returned costs should take precedence.
TEXT_MODEL_PRICING: dict[str, TextModelPricing] = {
    "grok-4.3": TextModelPricing(input_per_million=1.25, output_per_million=2.50),
    "grok-4.3-latest": TextModelPricing(input_per_million=1.25, output_per_million=2.50),
    "grok-4.20-non-reasoning": TextModelPricing(input_per_million=1.25, output_per_million=2.50),
    "grok-4.20-non-reasoning-latest": TextModelPricing(
        input_per_million=1.25,
        output_per_million=2.50,
    ),
}


@deal.pre(lambda cost_in_usd_ticks: cost_in_usd_ticks is None or cost_in_usd_ticks >= 0)
@deal.post(lambda result: result is None or result >= 0)
def usd_from_ticks(cost_in_usd_ticks: int | float | None) -> float | None:
    """Convert xAI USD ticks to dollars."""
    if cost_in_usd_ticks is None:
        return None
    return float(cost_in_usd_ticks) / USD_TICKS_PER_DOLLAR


def numeric_attr(obj: Any, attr_name: str) -> int | float | None:
    """Return a numeric attr value, ignoring dynamic mock/SDK placeholders."""
    value = getattr(obj, attr_name, None)
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return value
    return None


@deal.pre(
    lambda _model, prompt_tokens, completion_tokens: prompt_tokens >= 0 and completion_tokens >= 0
)
@deal.post(lambda result: result is None or result >= 0)
def estimate_text_cost_usd(
    model: str,
    prompt_tokens: int | float,
    completion_tokens: int | float,
) -> float | None:
    """Estimate text request cost when exact provider billing data is unavailable."""
    pricing = TEXT_MODEL_PRICING.get(model.lower())
    if pricing is None:
        return None

    input_cost = (float(prompt_tokens) / 1_000_000) * pricing.input_per_million
    output_cost = (float(completion_tokens) / 1_000_000) * pricing.output_per_million
    return input_cost + output_cost


def add_cost_fields(
    model: str,
    usage: dict[str, Any],
    *,
    cost_in_usd_ticks: int | float | None = None,
) -> dict[str, Any]:
    """Add exact or estimated cost fields to a usage dict."""
    updated = usage.copy()

    if cost_in_usd_ticks is not None:
        updated["cost_in_usd_ticks"] = int(cost_in_usd_ticks)
        updated["cost_usd"] = usd_from_ticks(cost_in_usd_ticks)
        updated["cost_source"] = "provider_exact"
        return updated

    estimated_cost = estimate_text_cost_usd(
        model,
        updated.get("prompt_tokens", 0),
        updated.get("completion_tokens", 0),
    )
    if estimated_cost is not None:
        updated["estimated_cost_usd"] = estimated_cost
        updated["cost_source"] = "local_estimate"

    return updated
