"""Tests for the animated ASCII banner module."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from scribe.utils.banner import (
    BANNER_ART,
    _animate_sweep,
    _ease_in_out_cubic,
    _is_banner_enabled,
    _precise_sleep,
    _precompute_gradient,
    _render_ansi_frame,
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

    def test_art_is_six_lines(self):
        lines = BANNER_ART.split("\n")
        assert len(lines) == 6

    def test_art_contains_box_drawing_chars(self):
        assert "\u2588" in BANNER_ART  # █ (full block)
        assert "\u2554" in BANNER_ART  # ╔ (double top-left)
        assert "\u2551" in BANNER_ART  # ║ (double vertical)
        assert "\u2550" in BANNER_ART  # ═ (double horizontal)

    def test_art_lines_have_similar_width(self):
        lines = BANNER_ART.split("\n")
        widths = [len(line) for line in lines]
        assert max(widths) - min(widths) <= 4

    def test_art_reasonable_width(self):
        lines = BANNER_ART.split("\n")
        max_width = max(len(line) for line in lines)
        assert 15 <= max_width <= 50


# ─── Easing ──────────────────────────────────────────────────────────────


class TestEaseInOutCubic:
    def test_start_is_zero(self):
        assert _ease_in_out_cubic(0.0) == 0.0

    def test_end_is_one(self):
        assert _ease_in_out_cubic(1.0) == 1.0

    def test_midpoint_is_half(self):
        result = _ease_in_out_cubic(0.5)
        assert abs(result - 0.5) < 0.001

    def test_monotonically_increasing(self):
        values = [_ease_in_out_cubic(t / 20) for t in range(21)]
        for i in range(len(values) - 1):
            assert values[i] <= values[i + 1]

    def test_quarter_below_linear(self):
        assert _ease_in_out_cubic(0.25) < 0.25

    def test_three_quarter_above_linear(self):
        result = _ease_in_out_cubic(0.75)
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
        assert len(result.split("\n")) == 6

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
        assert len(result.split("\n")) == 6


# ─── Banner Enabled ─────────────────────────────────────────────────────


class TestIsBannerEnabled:
    def test_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SCRIBE_BANNER", None)
            assert _is_banner_enabled() is True

    @pytest.mark.parametrize("val", ["off", "false", "0", "no", "OFF", "False", "NO"])
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
        # Plain art has block/box-drawing chars, no rgb markup
        assert "\u2588" in combined or "\u2554" in combined
        assert "rgb(" not in combined

    @patch("scribe.utils.banner._animate_sweep")
    @patch("scribe.utils.banner.get_terminal_ui_config")
    @patch("scribe.utils.banner._is_banner_enabled", return_value=True)
    def test_full_animation_mode(self, _mock_enabled, mock_cfg, mock_animate):
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
    def test_light_animation_mode(self, _mock_enabled, mock_cfg, mock_animate):
        mock_cfg.return_value = _make_config(animation_mode="light")
        console = MagicMock()
        result = show_banner(console)
        assert result is True
        mock_animate.assert_called_once()
        _, kwargs = mock_animate.call_args
        assert kwargs.get("duration") == 0.8

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
        mock_cfg.return_value = _make_config(animation_mode="light", is_dumb=True)
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


# ─── Raw ANSI Rendering ──────────────────────────────────────────────────


class TestPrecomputeGradient:
    def test_returns_correct_count(self):
        codes = _precompute_gradient(10)
        assert len(codes) == 10

    def test_codes_are_ansi_rgb(self):
        codes = _precompute_gradient(5)
        for code in codes:
            assert code.startswith("\033[1;38;2;")
            assert code.endswith("m")


class TestRenderAnsiFrame:
    def test_contains_ansi_codes(self):
        lines = ["AB"]
        codes = _precompute_gradient(2)
        frame = _render_ansi_frame(lines, 2, 1.0, codes, "\033[38;2;96;96;96m")
        assert "\033[1;38;2;" in frame

    def test_muted_chars_use_muted_code(self):
        lines = ["AB"]
        codes = _precompute_gradient(2)
        muted = "\033[38;2;96;96;96m"
        frame = _render_ansi_frame(lines, 2, 0.0, codes, muted)
        # At 0.0 sweep, only first char (col_ratio=0.0) is colored
        assert muted in frame

    def test_spaces_are_literal(self):
        lines = ["A B"]
        codes = _precompute_gradient(3)
        frame = _render_ansi_frame(lines, 3, 1.0, codes, "\033[38;2;96;96;96m")
        # Space should appear as-is without ANSI codes around it
        assert " " in frame

    def test_multiline_has_newlines(self):
        lines = ["A", "B"]
        codes = _precompute_gradient(1)
        frame = _render_ansi_frame(lines, 1, 1.0, codes, "\033[38;2;96;96;96m")
        assert "\n" in frame

    def test_ends_with_reset(self):
        lines = ["AB"]
        codes = _precompute_gradient(2)
        frame = _render_ansi_frame(lines, 2, 1.0, codes, "\033[38;2;96;96;96m")
        assert frame.endswith("\033[0m")


class TestPreciseSleep:
    @patch("scribe.utils.banner.time.perf_counter", side_effect=[100.0, 100.005, 100.011])
    @patch("scribe.utils.banner.time.sleep")
    def test_sleeps_when_remaining(self, mock_sleep, _mock_counter):
        _precise_sleep(100.010)
        assert mock_sleep.called

    @patch("scribe.utils.banner.time.perf_counter", return_value=100.0)
    @patch("scribe.utils.banner.time.sleep")
    def test_skips_when_past_target(self, mock_sleep, _mock_counter):
        _precise_sleep(99.0)
        assert not mock_sleep.called


# ─── Animate Sweep ───────────────────────────────────────────────────────


class TestAnimateSweep:
    @patch("scribe.utils.banner._precise_sleep")
    @patch("scribe.utils.banner.time.perf_counter", return_value=0.0)
    def test_animation_writes_to_console_file(self, _mock_counter, _mock_sleep):
        console = MagicMock()
        cfg = _make_config(animation_mode="full", fps=10)
        _animate_sweep(console, BANNER_ART, cfg, duration=0.5)

        assert console.file.write.call_count > 0
        assert console.file.flush.call_count > 0

    @patch("scribe.utils.banner._precise_sleep")
    @patch("scribe.utils.banner.time.perf_counter", return_value=0.0)
    def test_animation_frame_count(self, _mock_counter, _mock_sleep):
        console = MagicMock()
        cfg = _make_config(fps=10)
        _animate_sweep(console, "ABC", cfg, duration=0.5)

        # 60fps * 0.5s = 30 frames; _precise_sleep called for frames 1..30
        expected_sleeps = int(0.5 * 60)
        assert _mock_sleep.call_count == expected_sleeps

    @patch("scribe.utils.banner._precise_sleep")
    @patch("scribe.utils.banner.time.perf_counter", return_value=0.0)
    def test_animation_hides_and_shows_cursor(self, _mock_counter, _mock_sleep):
        console = MagicMock()
        cfg = _make_config(fps=10)
        _animate_sweep(console, "AB", cfg, duration=0.3)

        writes = [c.args[0] for c in console.file.write.call_args_list]
        assert writes[0] == "\033[?25l"  # hide cursor first
        all_output = "".join(writes)
        assert "\033[?25h" in all_output  # show cursor at end

    @patch(
        "scribe.utils.banner._precise_sleep",
        side_effect=Exception("boom"),
    )
    @patch("scribe.utils.banner.time.perf_counter", return_value=0.0)
    def test_animation_fallback_on_error(self, _mock_counter, _mock_sleep):
        console = MagicMock()
        cfg = _make_config(animation_mode="full", fps=10)

        # Should not raise — falls back to static
        _animate_sweep(console, BANNER_ART, cfg, duration=0.1)

        # Should have printed static fallback via Rich
        assert console.print.call_count >= 1

    @patch("scribe.utils.banner._precise_sleep")
    @patch("scribe.utils.banner.time.perf_counter", return_value=0.0)
    def test_animation_writes_cursor_up_codes(self, _mock_counter, _mock_sleep):
        console = MagicMock()
        cfg = _make_config(fps=10)
        _animate_sweep(console, "X\nY", cfg, duration=0.2)

        writes = [c.args[0] for c in console.file.write.call_args_list]
        cursor_ups = [w for w in writes if "\033[" in w and "A" in w]
        assert len(cursor_ups) > 0  # used cursor-up for frame updates


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
