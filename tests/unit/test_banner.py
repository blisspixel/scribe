"""Tests for the static wordmark and root help banner rules."""

from __future__ import annotations

import os

from rich.console import Console

from scribe.utils.banner import BANNER_ART, banner_allowed, show_banner


def test_banner_art_is_six_lines():
    assert len(BANNER_ART.splitlines()) == 6


def test_banner_hidden_when_color_or_tty_is_off(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("SCRIBE_BANNER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(os, "isatty", lambda _fd: False, raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    assert banner_allowed() is False

    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setenv("NO_COLOR", "1")
    assert banner_allowed() is False

    monkeypatch.delenv("NO_COLOR")
    monkeypatch.setenv("FORCE_COLOR", "0")
    assert banner_allowed() is False

    monkeypatch.delenv("FORCE_COLOR")
    monkeypatch.setenv("CI", "true")
    assert banner_allowed() is False

    monkeypatch.delenv("CI")
    monkeypatch.setenv("SCRIBE_BANNER", "off")
    assert banner_allowed() is False


def test_show_banner_is_static_and_single_accent(monkeypatch, capsys):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("SCRIBE_BANNER", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    console = Console(force_terminal=True, color_system="truecolor")
    assert show_banner(console, art="SCRIBE") is True
    captured = capsys.readouterr().out
    assert "SCRIBE" in captured
    assert "rgb(" not in captured
    assert "#EA23E7" not in captured


def test_show_banner_prints_nothing_when_disabled(monkeypatch, capsys):
    monkeypatch.setenv("NO_COLOR", "1")
    console = Console(force_terminal=True, color_system="truecolor")
    assert show_banner(console) is False
    assert capsys.readouterr().out == ""


def test_help_has_no_banner_and_bare_invocation_may_show_one(monkeypatch, capsys):
    from scribe.cli.main import CleanGroup

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr("sys.argv", ["scribe", "--help"])
    CleanGroup(name="scribe").format_help(None, None)
    helped = capsys.readouterr().out
    assert "Start here:" in helped
    assert "██████" not in helped

    monkeypatch.setattr("sys.argv", ["scribe"])
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)
    CleanGroup(name="scribe").format_help(None, None)
    bare = capsys.readouterr().out
    assert "Start here:" in bare
    assert "██████" not in bare


def test_truecolor_help_stays_under_fifty_escapes(monkeypatch, capsys):
    from scribe.cli.main import CleanGroup

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setattr("sys.argv", ["scribe", "--help"])
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    CleanGroup(name="scribe").format_help(None, None)
    helped = capsys.readouterr().out
    assert "Start here:" in helped
    assert "██████" not in helped
    assert helped.count("\x1b") < 50


def test_bare_tty_wordmark_stays_at_or_below_blue(monkeypatch, capsys):
    import colorsys
    import re

    from scribe.cli.main import CleanGroup

    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("SCRIBE_BANNER", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("COLORTERM", "truecolor")
    monkeypatch.setattr("sys.argv", ["scribe"])
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    CleanGroup(name="scribe").format_help(None, None)
    bare = capsys.readouterr().out
    assert "██" in bare
    assert bare.count("██") == BANNER_ART.count("██")
    for red, green, blue in re.findall(r"38;2;(\d+);(\d+);(\d+)", bare):
        hue = colorsys.rgb_to_hsv(int(red) / 255, int(green) / 255, int(blue) / 255)[0] * 360
        assert hue <= 260
