"""Tests for provider cost helpers."""

from scribe.utils.costs import add_cost_fields, estimate_text_cost_usd, usd_from_ticks


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
