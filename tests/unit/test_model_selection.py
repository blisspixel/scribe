"""
Unit tests for effective local Whisper model resolution.

These cover the rule that keeps `scribe info` and the transcription pipeline
reporting the same model: an explicitly pinned model always wins, and hardware
auto-tuning applies only to the untouched default.
"""

from scribe.utils.model_selection import resolve_local_model


class TestResolveLocalModel:
    """Test model resolution between configured preference and hardware."""

    def test_explicit_choice_wins_over_hardware(self):
        """A model the user pinned is never downgraded by hardware detection."""
        model, adjusted = resolve_local_model("large-v3", {"default_model"}, "base")
        assert model == "large-v3"
        assert adjusted is False

    def test_untouched_default_is_tuned_to_hardware(self):
        """A CPU-only machine runs the smaller recommended model."""
        model, adjusted = resolve_local_model("large-v3", set(), "base")
        assert model == "base"
        assert adjusted is True

    def test_no_adjustment_reported_when_recommendation_matches(self):
        """A GPU that wants the default reports no adjustment."""
        model, adjusted = resolve_local_model("large-v3", set(), "large-v3")
        assert model == "large-v3"
        assert adjusted is False

    def test_explicit_choice_matching_hardware_is_not_flagged(self):
        """Pinning the model the hardware would pick anyway is not an override."""
        model, adjusted = resolve_local_model("base", {"default_model"}, "base")
        assert model == "base"
        assert adjusted is False

    def test_other_explicit_fields_do_not_pin_the_model(self):
        """Setting an unrelated field leaves the model free to auto-tune."""
        model, adjusted = resolve_local_model("large-v3", {"default_language"}, "base")
        assert model == "base"
        assert adjusted is True
