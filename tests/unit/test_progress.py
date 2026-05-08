from types import SimpleNamespace
from unittest.mock import Mock, patch

from scribe.utils.progress import (
    ProgressTracker,
    create_progress_bar,
    format_eta,
    format_speed_ratio,
)


def test_progress_tracker_start_and_update_reset_state():
    tracker = ProgressTracker(total_duration=100.0, operation="Testing")
    tracker.update(25.0)
    assert tracker.measurements == []

    with patch("time.time", return_value=100.0):
        tracker.start()

    with patch("time.time", side_effect=[110.0, 110.0]):
        tracker.update(50.0)

    assert tracker.start_time == 100.0
    assert len(tracker.measurements) == 1
    assert tracker.measurements[0].progress == 0.5
    assert tracker.speed_estimate == 0.05


def test_progress_tracker_updates_kalman_filter_and_eta():
    tracker = ProgressTracker(total_duration=100.0)

    with patch("time.time", return_value=10.0):
        tracker.start()

    with patch("time.time", side_effect=[20.0, 20.0]):
        tracker.update(25.0)

    initial_speed = tracker.speed_estimate

    with patch("time.time", side_effect=[30.0, 30.0]):
        tracker.update(75.0)

    assert initial_speed is not None
    assert tracker.speed_estimate is not None
    assert tracker.speed_estimate > initial_speed
    assert tracker.variance < 1.0
    assert tracker.get_eta(0.75) > 0


def test_progress_tracker_speed_ratio_and_complete_logging():
    tracker = ProgressTracker(total_duration=200.0, operation="Transcribing")

    with patch("time.time", return_value=50.0):
        tracker.start()

    with patch("time.time", side_effect=[70.0, 70.0]):
        tracker.update(100.0)

    assert tracker.get_speed_ratio() == 5.0

    mock_logger = Mock()
    with (
        patch("logging.getLogger", return_value=mock_logger),
        patch("time.time", return_value=75.0),
    ):
        tracker.complete()

    mock_logger.info.assert_called_once()


def test_progress_tracker_handles_missing_speed_information():
    tracker = ProgressTracker(total_duration=120.0)

    assert tracker.get_eta(0.5) == float("inf")
    assert tracker.get_speed_ratio() == 0.0

    tracker.start_time = 10.0
    tracker.measurements = [SimpleNamespace(progress=0.5, elapsed=0.0)]
    assert tracker.get_speed_ratio() == 0.0


def test_create_progress_bar_uses_ui_fps_floor():
    mock_progress = Mock(return_value="progress")

    with (
        patch("scribe.utils.progress.get_terminal_ui_config", return_value=SimpleNamespace(fps=1)),
        patch("scribe.utils.progress.Progress", mock_progress),
    ):
        progress = create_progress_bar("Loading")

    assert progress == "progress"
    assert mock_progress.call_args.kwargs["refresh_per_second"] == 2
    assert mock_progress.call_args.kwargs["transient"] is False


def test_format_speed_ratio_and_eta_cover_boundaries():
    assert format_speed_ratio(0) == "calculating..."
    assert format_speed_ratio(0.5) == "0.50x realtime"
    assert format_speed_ratio(2.34) == "2.3x realtime"

    assert format_eta(float("inf")) == "calculating..."
    assert format_eta(-1) == "calculating..."
    assert format_eta(45) == "45s"
    assert format_eta(125) == "2m 5s"
    assert format_eta(3700) == "1h 1m"
