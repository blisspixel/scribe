"""Unit tests for spinner progress display behavior."""

from unittest.mock import Mock, patch

from scribe.utils.spinner import SpinnerProgress


class TestSpinnerProgress:
    """Test spinner behavior across animation modes."""

    @patch("scribe.utils.spinner.console")
    def test_off_mode_prints_static_message(self, mock_console):
        sp = SpinnerProgress("Working")
        sp.ui_config = Mock(animation_mode="off")
        sp.__enter__()
        assert mock_console.print.called
        assert sp.progress is None

    @patch("scribe.utils.spinner.Progress")
    def test_light_mode_starts_progress(self, mock_progress_cls):
        mock_progress = Mock()
        mock_progress_cls.return_value = mock_progress

        sp = SpinnerProgress("Working")
        sp.ui_config = Mock(
            animation_mode="light",
            fps=10,
            frame_delay=0.1,
            capabilities=Mock(is_windows=False, supports_advanced_effects=True),
        )
        sp.__enter__()
        sp.__exit__(None, None, None)

        assert mock_progress.start.called
        assert mock_progress.add_task.called

    def test_full_mode_shimmer_flag_requires_capability(self):
        sp = SpinnerProgress("Working")
        sp.ui_config = Mock(
            animation_mode="full",
            capabilities=Mock(supports_advanced_effects=False),
        )
        assert sp._shimmer_enabled() is False
