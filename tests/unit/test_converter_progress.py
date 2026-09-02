"""Regression tests for terminal-safe FFmpeg progress rendering."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from scribe.core import converter


def _ui_config(animation_mode: str) -> SimpleNamespace:
    return SimpleNamespace(animation_mode=animation_mode)


def test_progress_is_disabled_when_shared_terminal_policy_disables_animation() -> None:
    with patch.object(converter, "get_terminal_ui_config", return_value=_ui_config("off")):
        assert converter._show_rich_progress() is False


def test_progress_is_disabled_when_stream_cannot_encode_rich_bar() -> None:
    stream = SimpleNamespace(encoding="cp1252")
    with (
        patch.object(converter, "get_terminal_ui_config", return_value=_ui_config("light")),
        patch.object(type(converter.console), "file", new_callable=PropertyMock) as file_prop,
    ):
        file_prop.return_value = stream
        assert converter._show_rich_progress() is False


def test_progress_remains_available_on_utf8_terminal() -> None:
    stream = SimpleNamespace(encoding="utf-8")
    with (
        patch.object(converter, "get_terminal_ui_config", return_value=_ui_config("light")),
        patch.object(type(converter.console), "file", new_callable=PropertyMock) as file_prop,
    ):
        file_prop.return_value = stream
        assert converter._show_rich_progress() is True


def test_progress_cleanup_swallows_unicode_delivery_failure() -> None:
    progress = MagicMock()
    progress.__exit__ = MagicMock(
        side_effect=UnicodeEncodeError("cp1252", "\u2839", 0, 1, "cannot encode")
    )

    converter._stop_progress_safely(progress)


def test_progress_cleanup_does_not_hide_programming_error() -> None:
    progress = MagicMock()
    progress.__exit__ = MagicMock(side_effect=ValueError("invalid progress state"))

    with pytest.raises(ValueError, match="invalid progress state"):
        converter._stop_progress_safely(progress)
