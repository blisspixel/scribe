"""Unit tests for gradient branding helpers."""

from unittest.mock import Mock, patch

from scribe.utils.branding import brand_header_markup


class TestBranding:
    """Test header gradient behavior and fallback rules."""

    @patch("scribe.utils.branding.get_terminal_ui_config")
    def test_fallback_markup_when_not_full(self, mock_cfg):
        mock_cfg.return_value = Mock(
            animation_mode="light",
            use_color=True,
            capabilities=Mock(supports_advanced_effects=True),
        )
        result = brand_header_markup("Scribe v1")
        assert "[bold cyan]" in result
        assert "Scribe v1" in result

    @patch("scribe.utils.branding.time.time", return_value=0.0)
    @patch("scribe.utils.branding.get_terminal_ui_config")
    def test_gradient_markup_in_full_mode(self, mock_cfg, _mock_time):
        mock_cfg.return_value = Mock(
            animation_mode="full",
            use_color=True,
            capabilities=Mock(supports_advanced_effects=True),
        )
        result = brand_header_markup("Scribe")
        assert "rgb(" in result
        for ch in "Scribe":
            assert ch in result

    @patch("scribe.utils.branding.get_terminal_ui_config")
    def test_fallback_when_no_advanced_support(self, mock_cfg):
        mock_cfg.return_value = Mock(
            animation_mode="full",
            use_color=True,
            capabilities=Mock(supports_advanced_effects=False),
        )
        result = brand_header_markup("Header")
        assert "[bold cyan]" in result
