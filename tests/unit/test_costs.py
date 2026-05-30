"""Tests for provider cost helpers."""

from scribe.utils.costs import (
    TEXT_MODEL_PRICING,
    USD_TICKS_PER_DOLLAR,
    add_cost_fields,
    estimate_text_cost_usd,
    usd_from_ticks,
)


def test_usd_from_ticks():
    """Test converting xAI USD ticks to dollars."""
    assert usd_from_ticks(37_756_000) == 0.0037756


def test_estimate_text_cost_usd_for_grok_43():
    """Test local budget estimate for Grok 4.3."""
    cost = estimate_text_cost_usd(
        "grok-4.3",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
    )

    assert cost == 3.75


def test_add_cost_fields_prefers_provider_exact_cost():
    """Test exact provider costs win over local estimates."""
    usage = add_cost_fields(
        "grok-4.3",
        {"prompt_tokens": 1_000_000, "completion_tokens": 1_000_000, "total_tokens": 2_000_000},
        cost_in_usd_ticks=37_756_000,
    )

    assert usage["cost_usd"] == 0.0037756
    assert usage["cost_source"] == "provider_exact"
    assert "estimated_cost_usd" not in usage


def test_add_cost_fields_estimates_known_model_without_exact_cost():
    """Test local estimates are available when exact provider cost is absent."""
    usage = add_cost_fields(
        "grok-4.20-non-reasoning",
        {"prompt_tokens": 1000, "completion_tokens": 2000, "total_tokens": 3000},
    )

    assert usage["estimated_cost_usd"] == 0.00625
    assert usage["cost_source"] == "local_estimate"


# --- Hypothesis property tests (Step 3 Engineering Excellence) ---

from hypothesis import given, strategies as st

# Known models from the pricing table (for targeted testing)
KNOWN_MODELS = list(TEXT_MODEL_PRICING.keys())


@given(
    ticks=st.integers(min_value=0, max_value=10**12),
)
def test_usd_from_ticks_is_non_negative_and_inverts(ticks: int):
    """usd_from_ticks always returns non-negative or None; roundtrip is stable within float error."""
    usd = usd_from_ticks(ticks)
    if usd is not None:
        assert usd >= 0
        # Converting back should recover the original within reasonable precision
        recovered_ticks = int(usd * USD_TICKS_PER_DOLLAR)
        assert abs(recovered_ticks - ticks) <= 1  # allow for floating point


@given(
    model=st.sampled_from(KNOWN_MODELS + ["unknown-model-xyz"]),
    prompt=st.floats(min_value=0, max_value=10_000_000),
    completion=st.floats(min_value=0, max_value=10_000_000),
)
def test_estimate_text_cost_usd_never_negative(model: str, prompt: float, completion: float):
    """Cost estimates are either None or non-negative for any non-negative token counts."""
    cost = estimate_text_cost_usd(model, prompt, completion)
    if cost is not None:
        assert cost >= 0


@given(
    model=st.sampled_from(KNOWN_MODELS),
    prompt=st.integers(min_value=0, max_value=5_000_000),
    completion=st.integers(min_value=0, max_value=5_000_000),
)
def test_estimate_text_cost_usd_matches_pricing_math(model: str, prompt: int, completion: int):
    """For known models the estimate exactly follows the pricing table math."""
    pricing = TEXT_MODEL_PRICING[model.lower()]
    expected = (
        (prompt / 1_000_000) * pricing.input_per_million
        + (completion / 1_000_000) * pricing.output_per_million
    )
    actual = estimate_text_cost_usd(model, prompt, completion)
    assert actual == expected


@given(
    usage=st.dictionaries(
        keys=st.text(min_size=1, max_size=20),
        values=st.one_of(st.integers(), st.floats(allow_nan=False), st.text()),
        min_size=0,
        max_size=10,
    ),
    ticks=st.integers(min_value=0, max_value=10**11) | st.none(),
)
def test_add_cost_fields_always_adds_cost_fields(usage: dict, ticks: int | None):
    """add_cost_fields always adds cost_* keys and never removes original data."""
    result = add_cost_fields("grok-4.3", usage.copy(), cost_in_usd_ticks=ticks)

    # Original keys preserved
    for k in usage:
        assert k in result

    if ticks is not None:
        assert "cost_usd" in result
        assert result["cost_source"] == "provider_exact"
    else:
        # For known model it should at least attempt an estimate
        assert "estimated_cost_usd" in result or "cost_usd" in result
        assert result.get("cost_source") in {"local_estimate", "provider_exact"}
