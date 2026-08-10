"""Unit tests for terminal UI capability/config resolution."""

from scribe.utils import terminal_ui


class TestTerminalUIConfig:
    """Test environment-driven terminal UI configuration."""

    def teardown_method(self):
        """Reset cache between tests."""
        terminal_ui.get_terminal_ui_config.cache_clear()

    def test_animation_mode_env_override(self, monkeypatch):
        monkeypatch.setenv("SCRIBE_ANIMATIONS", "off")
        terminal_ui.get_terminal_ui_config.cache_clear()

        cfg = terminal_ui.get_terminal_ui_config()

        assert cfg.animation_mode == "off"

    def test_color_mode_never_disables_color(self, monkeypatch):
        monkeypatch.setenv("SCRIBE_COLOR", "never")
        terminal_ui.get_terminal_ui_config.cache_clear()

        cfg = terminal_ui.get_terminal_ui_config()

        assert cfg.color_mode == "never"
        assert cfg.use_color is False

    def test_fps_env_is_clamped(self, monkeypatch):
        monkeypatch.setenv("SCRIBE_FPS", "999")
        terminal_ui.get_terminal_ui_config.cache_clear()

        cfg = terminal_ui.get_terminal_ui_config()

        assert cfg.fps == 30
        assert cfg.frame_delay > 0

    def test_invalid_animation_mode_falls_back(self, monkeypatch):
        monkeypatch.setenv("SCRIBE_ANIMATIONS", "invalid-value")
        terminal_ui.get_terminal_ui_config.cache_clear()

        cfg = terminal_ui.get_terminal_ui_config()

        assert cfg.animation_mode in {"off", "light", "full"}
