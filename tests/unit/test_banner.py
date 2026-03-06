"""Tests for the animated ASCII banner module."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from scribe.utils.banner import (
    BANNER_ART,
    _animate_sweep,
    _ease_out_cubic,
    _is_banner_enabled,
    colorize_banner,
    render_banner_plain,
    render_banner_static,
    show_banner,
)
from scribe.utils.terminal_ui import TerminalCapabilities, TerminalUIConfig

# ─── Helpers ─────────────────────────────────────────────────────────────


def _make_config(
    animation_mode="light",
    is_tty=True,
    is_ci=False,
    use_color=True,
    is_dumb=False,
    fps=10,
):
    """Build a TerminalUIConfig for testing."""
    caps = TerminalCapabilities(
        is_windows=True,
        is_tty=is_tty,
        is_dumb_terminal=is_dumb,
        is_ci=is_ci,
    )
    return TerminalUIConfig(
        animation_mode=animation_mode,
        color_mode="auto",
        fps=fps,
        frame_delay=1.0 / fps,
        use_color=use_color,
        capabilities=caps,
    )


# ─── ASCII Art ───────────────────────────────────────────────────────────


class TestBannerArt:
    """Tests for the ASCII art constant."""

    def test_art_exists_and_is_string(self):
        assert BANNER_ART
        assert isinstance(BANNER_ART, str)

    def test_art_is_three_lines(self):
        lines = BANNER_ART.split("\n")
        assert len(lines) == 3

    def test_art_contains_box_drawing_chars(self):
        assert "\u250c" in BANNER_ART  # ┌
        assert "\u2518" in BANNER_ART  # ┘
        assert "\u2500" in BANNER_ART  # ─
        assert "\u2502" in BANNER_ART  # │

    def test_art_lines_have_similar_width(self):
        lines = BANNER_ART.split("\n")
        widths = [len(line) for line in lines]
        assert max(widths) - min(widths) <= 4

    def test_art_reasonable_width(self):
        lines = BANNER_ART.split("\n")
        max_width = max(len(line) for line in lines)
        assert 15 <= max_width <= 50


# ─── Easing ──────────────────────────────────────────────────────────────


class TestEaseOutCubic:
    def test_start_is_zero(self):
        assert _ease_out_cubic(0.0) == 0.0

    def test_end_is_one(self):
        assert _ease_out_cubic(1.0) == 1.0

    def test_midpoint_above_linear(self):
        result = _ease_out_cubic(0.5)
        assert result > 0.5
        assert result < 1.0

    def test_monotonically_increasing(self):
        values = [_ease_out_cubic(t / 20) for t in range(21)]
        for i in range(len(values) - 1):
            assert values[i] <= values[i + 1]

    def test_quarter_above_linear(self):
        assert _ease_out_cubic(0.25) > 0.25

    def test_three_quarter(self):
        result = _ease_out_cubic(0.75)
        assert result > 0.75


# ─── Colorize Banner ────────────────────────────────────────────────────


class TestColorizeBanner:
    def test_full_sweep_has_rgb_markup(self):
        result = colorize_banner("AB", sweep_progress=1.0)
        assert "rgb(" in result
        assert "bold" in result

    def test_zero_sweep_first_char_colored(self):
        """At progress=0.0, col_ratio=0.0 for col 0 is <= 0.0, so first char is colored."""
        result = colorize_banner("AB", sweep_progress=0.0)
        assert "rgb(" in result

    def test_zero_sweep_second_char_muted(self):
        result = colorize_banner("AB", sweep_progress=0.0)
        assert "#606060" in result

    def test_partial_sweep_has_both(self):
        art = "ABCDEFGH"
        result = colorize_banner(art, sweep_progress=0.5)
        assert "rgb(" in result
        assert "#606060" in result

    def test_spaces_are_preserved_literally(self):
        result = colorize_banner("A B C", sweep_progress=1.0)
        # Spaces should remain as literal spaces (not wrapped in markup)
        # Non-space chars should have rgb markup
        assert "rgb(" in result
        # The result should contain literal space characters
        assert " " in result

    def test_empty_string(self):
        assert colorize_banner("") == ""

    def test_blank_lines_only(self):
        result = colorize_banner("   \n   ")
        assert result == "   \n   "

    def test_single_char(self):
        result = colorize_banner("X", sweep_progress=1.0)
        assert "rgb(" in result
        assert "X" in result

    def test_multiline_preserves_line_count(self):
        art = "AB\nCD\nEF"
        result = colorize_banner(art, sweep_progress=1.0)
        assert len(result.split("\n")) == 3

    def test_custom_hue_range(self):
        r1 = colorize_banner("ABC", start_hue=0.0, end_hue=0.0)
        r2 = colorize_banner("ABC", start_hue=0.5, end_hue=0.5)
        assert r1 != r2

    def test_banner_art_colorizes_without_error(self):
        result = colorize_banner(BANNER_ART, sweep_progress=1.0)
        assert "rgb(" in result
        assert len(result.split("\n")) == 3

    def test_sweep_progress_boundaries(self):
        for progress in [0.0, 0.25, 0.5, 0.75, 1.0]:
            result = colorize_banner(BANNER_ART, sweep_progress=progress)
            assert isinstance(result, str)
            assert len(result) > 0


# ─── Render Helpers ──────────────────────────────────────────────────────


class TestRenderBannerPlain:
    def test_returns_unmodified_text(self):
        assert render_banner_plain("hello") == "hello"

    def test_returns_art_unmodified(self):
        assert render_banner_plain(BANNER_ART) == BANNER_ART


class TestRenderBannerStatic:
    def test_returns_colored_markup(self):
        result = render_banner_static("AB")
        assert "rgb(" in result
        assert "bold" in result

    def test_full_art_colored(self):
        result = render_banner_static(BANNER_ART)
        assert "rgb(" in result
        assert len(result.split("\n")) == 3


# ─── Banner Enabled ─────────────────────────────────────────────────────


class TestIsBannerEnabled:
    def test_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCRIBE_BANNER", None)
            assert _is_banner_enabled() is True

    @pytest.mark.parametrize(
        "val", ["off", "false", "0", "no", "OFF", "False", "NO"]
    )
    def test_disabled_values(self, val):
        with patch.dict(os.environ, {"SCRIBE_BANNER": val}):
            assert _is_banner_enabled() is False

    @pytest.mark.parametrize("val", ["on", "true", "1", "yes", ""])
    def test_enabled_values(self, val):
        with patch.dict(os.environ, {"SCRIBE_BANNER": val}):
            assert _is_banner_enabled() is True


# ─── Show Banner ─────────────────────────────────────────────────────────


class TestShowBanner:
    @patch("scribe.utils.banner._is_banner_enabled", return_value=False)
    def test_disabled_returns_false(self, _mock):
        console = MagicMock()
        assert show_banner(console) is False
        console.print.assert_not_called()

    @patch("scribe.utils.banner.get_terminal_ui_config")
    @patch("scribe.utils.banner._is_banner_enabled", return_value=True)
    def test_ci_returns_false(self, _mock_enabled, mock_cfg):
        mock_cfg.return_value = _make_config(is_ci=True)
        console = MagicMock()
        assert show_banner(console) is False

    @patch("scribe.utils.banner.get_terminal_ui_config")
    @patch("scribe.utils.banner._is_banner_enabled", return_value=True)
    def test_not_tty_returns_false(self, _mock_enabled, mock_cfg):
        mock_cfg.return_value = _make_config(is_tty=False)
        console = MagicMock()
        assert show_banner(console) is False

    @patch("scribe.utils.banner.get_terminal_ui_config")
    @patch("scribe.utils.banner._is_banner_enabled", return_value=True)
    def test_no_color_shows_plain(self, _mock_enabled, mock_cfg):
        mock_cfg.return_value = _make_config(use_color=False)
        console = MagicMock()
        result = show_banner(console)
        assert result is True
        # Should have called print with plain art (no rgb markup)
        all_args = []
        for c in console.print.call_args_list:
            for arg in c.args:
                all_args.append(str(arg))
        combined = " ".join(all_args)
        # Plain art has box-drawing chars, no rgb markup
        assert "\u250c" in combined or "\u2514" in combined
        assert "rgb(" not in combined

    @patch("scribe.utils.banner._animate_sweep")
    @patch("scribe.utils.banner.get_terminal_ui_config")
    @patch("scribe.utils.banner._is_banner_enabled", return_value=True)
    def test_full_animation_mode(
        self, _mock_enabled, mock_cfg, mock_animate
    ):
        mock_cfg.return_value = _make_config(animation_mode="full")
        console = MagicMock()
        result = show_banner(console)
        assert result is True
        mock_animate.assert_called_once()
        _, kwargs = mock_animate.call_args
        assert kwargs.get("duration") == 1.5

    @patch("scribe.utils.banner._animate_sweep")
    @patch("scribe.utils.banner.get_terminal_ui_config")
    @patch("scribe.utils.banner._is_banner_enabled", return_value=True)
    def test_light_animation_mode(
        self, _mock_enabled, mock_cfg, mock_animate
    ):
        mock_cfg.return_value = _make_config(animation_mode="light")
        console = MagicMock()
        result = show_banner(console)
        assert result is True
        mock_animate.assert_called_once()
        _, kwargs = mock_animate.call_args
        assert kwargs.get("duration") == 0.5

    @patch("scribe.utils.banner.get_terminal_ui_config")
    @patch("scribe.utils.banner._is_banner_enabled", return_value=True)
    def test_off_mode_shows_static(self, _mock_enabled, mock_cfg):
        mock_cfg.return_value = _make_config(animation_mode="off")
        console = MagicMock()
        result = show_banner(console)
        assert result is True
        # Should have printed (initial newline + static banner)
        assert console.print.call_count >= 2

    @patch("scribe.utils.banner.get_terminal_ui_config")
    @patch("scribe.utils.banner._is_banner_enabled", return_value=True)
    def test_dumb_terminal_shows_static(self, _mock_enabled, mock_cfg):
        mock_cfg.return_value = _make_config(
            animation_mode="light", is_dumb=True
        )
        console = MagicMock()
        result = show_banner(console)
        assert result is True
        # Dumb terminal: supports_advanced_effects is False → static
        assert console.print.call_count >= 2

    @patch("scribe.utils.banner.get_terminal_ui_config")
    @patch("scribe.utils.banner._is_banner_enabled", return_value=True)
    def test_custom_art(self, _mock_enabled, mock_cfg):
        mock_cfg.return_value = _make_config(animation_mode="off")
        console = MagicMock()
        result = show_banner(console, art="CUSTOM ART")
        assert result is True


# ─── Animate Sweep ───────────────────────────────────────────────────────


class TestAnimateSweep:
    @patch("scribe.utils.banner.time.sleep")
    @patch("scribe.utils.banner.Live")
    def test_animation_calls_live_update(self, mock_live_cls, mock_sleep):
        mock_live = MagicMock()
        mock_live.__enter__ = MagicMock(return_value=mock_live)
        mock_live.__exit__ = MagicMock(return_value=False)
        mock_live_cls.return_value = mock_live

        console = MagicMock()
        cfg = _make_config(animation_mode="full", fps=10)
        _animate_sweep(console, BANNER_ART, cfg, duration=0.5)

        assert mock_live.update.call_count > 0
        assert mock_sleep.call_count > 0

    @patch("scribe.utils.banner.time.sleep")
    @patch("scribe.utils.banner.Live")
    def test_animation_frame_count(self, mock_live_cls, _mock_sleep):
        mock_live = MagicMock()
        mock_live.__enter__ = MagicMock(return_value=mock_live)
        mock_live.__exit__ = MagicMock(return_value=False)
        mock_live_cls.return_value = mock_live

        console = MagicMock()
        cfg = _make_config(fps=10)
        _animate_sweep(console, "ABC", cfg, duration=0.5)

        expected_frames = int(0.5 * 10) + 1  # 6 frames (0 through 5)
        assert mock_live.update.call_count == expected_frames

    @patch("scribe.utils.banner.time.sleep")
    @patch("scribe.utils.banner.Live")
    def test_animation_prints_final_state(self, mock_live_cls, _mock_sleep):
        mock_live = MagicMock()
        mock_live.__enter__ = MagicMock(return_value=mock_live)
        mock_live.__exit__ = MagicMock(return_value=False)
        mock_live_cls.return_value = mock_live

        console = MagicMock()
        cfg = _make_config(fps=10)
        _animate_sweep(console, "AB", cfg, duration=0.3)

        # After animation, should print static final state
        assert console.print.call_count >= 1

    @patch(
        "scribe.utils.banner.time.sleep", side_effect=Exception("boom")
    )
    def test_animation_fallback_on_error(self, _mock_sleep):
        console = MagicMock()
        cfg = _make_config(animation_mode="full", fps=10)

        # Should not raise — falls back to static
        _animate_sweep(console, BANNER_ART, cfg, duration=0.1)

        # Should have printed static fallback
        assert console.print.call_count >= 1

    @patch("scribe.utils.banner.time.sleep")
    @patch("scribe.utils.banner.Live")
    def test_live_created_with_transient(self, mock_live_cls, _mock_sleep):
        mock_live = MagicMock()
        mock_live.__enter__ = MagicMock(return_value=mock_live)
        mock_live.__exit__ = MagicMock(return_value=False)
        mock_live_cls.return_value = mock_live

        console = MagicMock()
        cfg = _make_config(fps=10)
        _animate_sweep(console, "X", cfg, duration=0.2)

        _, kwargs = mock_live_cls.call_args
        assert kwargs.get("transient") is True
        assert kwargs.get("console") is console


# ─── CLI Integration ─────────────────────────────────────────────────────


class TestBannerCLIIntegration:
    def test_banner_flag_in_known_commands(self):
        """The --banner flag must be in known_commands to avoid misrouting."""
        import inspect

        from scribe.cli import main as cli_module

        source = inspect.getsource(cli_module.main)
        assert "--banner" in source

    @patch("scribe.utils.banner.show_banner", return_value=True)
    def test_format_help_calls_show_banner(self, mock_show):
        """CleanGroup.format_help should call show_banner."""
        from scribe.cli.main import CleanGroup

        group = CleanGroup(name="test")
        # format_help creates its own Console, so we just verify it runs
        # We can't easily intercept the Console it creates, but we can
        # verify show_banner is called
        group.format_help(None, None)
        mock_show.assert_called_once()

    @patch("scribe.utils.banner.show_banner", return_value=False)
    def test_format_help_falls_back_on_disabled(self, mock_show):
        """When banner is disabled, format_help shows text header."""
        from scribe.cli.main import CleanGroup

        group = CleanGroup(name="test")
        # Should not raise even when banner is disabled
        group.format_help(None, None)
        mock_show.assert_called_once()
