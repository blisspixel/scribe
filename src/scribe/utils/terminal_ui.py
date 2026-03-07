"""
Terminal UI capability and animation configuration helpers.

This module centralizes cross-platform CLI rendering behavior so status/progress
components can make consistent decisions about color and animation.
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from rich.console import Console

AnimationMode = Literal["off", "light", "full"]
ColorMode = Literal["auto", "always", "never"]

_VALID_ANIMATION_MODES = {"off", "light", "full"}
_VALID_COLOR_MODES = {"auto", "always", "never"}


@dataclass(frozen=True)
class TerminalCapabilities:
    """Detected terminal capabilities relevant to UI behavior."""

    is_windows: bool
    is_tty: bool
    is_dumb_terminal: bool
    is_ci: bool

    @property
    def supports_advanced_effects(self) -> bool:
        return self.is_tty and not self.is_dumb_terminal and not self.is_ci


@dataclass(frozen=True)
class TerminalUIConfig:
    """Resolved runtime configuration for terminal visuals."""

    animation_mode: AnimationMode
    color_mode: ColorMode
    fps: int
    frame_delay: float
    use_color: bool
    capabilities: TerminalCapabilities


def _parse_animation_mode(value: str | None) -> AnimationMode | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in _VALID_ANIMATION_MODES:
        return normalized  # type: ignore[return-value]
    return None


def _parse_color_mode(value: str | None) -> ColorMode:
    if value is None:
        return "auto"
    normalized = value.strip().lower()
    if normalized in _VALID_COLOR_MODES:
        return normalized  # type: ignore[return-value]
    return "auto"


def detect_terminal_capabilities(console: Console | None = None) -> TerminalCapabilities:
    """Detect terminal capabilities from runtime and Rich console."""
    rich_console = console or Console()
    return TerminalCapabilities(
        is_windows=platform.system() == "Windows",
        is_tty=bool(rich_console.is_terminal),
        is_dumb_terminal=bool(rich_console.is_dumb_terminal),
        is_ci=bool(os.environ.get("CI")),
    )


def _resolve_animation_mode(capabilities: TerminalCapabilities) -> AnimationMode:
    env_mode = _parse_animation_mode(os.environ.get("SCRIBE_ANIMATIONS"))
    if env_mode is not None:
        return env_mode
    if capabilities.supports_advanced_effects:
        return "light"
    return "off"


def _resolve_fps(capabilities: TerminalCapabilities, mode: AnimationMode) -> int:
    env_value = os.environ.get("SCRIBE_FPS")
    if env_value:
        try:
            parsed = int(env_value.strip())
            return min(30, max(2, parsed))
        except ValueError:
            pass

    if mode == "off":
        return 2
    return 15


def _resolve_use_color(
    color_mode: ColorMode, capabilities: TerminalCapabilities, console: Console | None
) -> bool:
    if color_mode == "always":
        return True
    if color_mode == "never":
        return False
    rich_console = console or Console()
    return capabilities.is_tty and not rich_console.no_color


@lru_cache(maxsize=1)
def get_terminal_ui_config() -> TerminalUIConfig:
    """
    Get resolved terminal UI configuration.

    Cached for process lifetime so all renderers share the same behavior.
    """
    color_mode = _parse_color_mode(os.environ.get("SCRIBE_COLOR"))
    capabilities = detect_terminal_capabilities()
    animation_mode = _resolve_animation_mode(capabilities)
    fps = _resolve_fps(capabilities, animation_mode)
    frame_delay = 1.0 / float(fps)
    use_color = _resolve_use_color(color_mode, capabilities, None)
    return TerminalUIConfig(
        animation_mode=animation_mode,
        color_mode=color_mode,
        fps=fps,
        frame_delay=frame_delay,
        use_color=use_color,
        capabilities=capabilities,
    )

