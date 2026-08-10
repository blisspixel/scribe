"""Unit tests for shimmer rendering utilities."""

from scribe.utils.shimmer import shimmer_markup


class TestShimmerMarkup:
    """Test shimmer status line rendering."""

    def test_shimmer_markup_contains_original_text(self):
        rendered = shimmer_markup("Processing", phase=0.25)
        assert "P" in rendered
        assert "g" in rendered
        assert "[" in rendered

    def test_shimmer_markup_escapes_markup_chars(self):
        rendered = shimmer_markup("[x]", phase=0.5)
        assert "[x]" not in rendered
        assert "x" in rendered

    def test_shimmer_markup_handles_empty(self):
        assert shimmer_markup("", phase=0.1) == ""
