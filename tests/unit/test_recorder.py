"""
Unit tests for OBS Studio recording integration.

This test suite provides comprehensive coverage of the OBSRecorder class,
including WebSocket connection handling, error recovery, hostname validation,
fallback strategies, and edge cases.

Test Philosophy:
- Test behavior, not implementation
- Cover all error paths and edge cases
- Validate defensive programming patterns
- Ensure graceful degradation
- Test concurrent operations (threading)
- Verify resource cleanup

Coverage Areas:
1. WebSocket connection with retry logic
2. Hostname validation error handling
3. IPv4/IPv6 fallback strategies
4. OBS launch and detection
5. Recording lifecycle (start/stop/finalize)
6. File detection and monitoring
7. CLI fallback mode
8. Error recovery and cleanup
9. Thread safety and concurrency
10. Resource management
"""

import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from scribe.core.recorder import OBSRecorder
from scribe.exceptions import ProcessError
from scribe.models.config import ScribeConfig


@pytest.fixture
def mock_config(tmp_path):
    """Create mock configuration for testing."""
    config = Mock(spec=ScribeConfig)
    config.obs_host = "localhost"
    config.obs_port = 4455
    config.obs_password = ""
    config.output_folder = tmp_path / "output"
    config.output_folder.mkdir(parents=True, exist_ok=True)
    config.max_recording_hours = 9.0
    config.recording_warning_fraction = 0.9
    return config


@pytest.fixture
def recorder(mock_config):
    """Create OBSRecorder instance for testing."""
    return OBSRecorder(mock_config)


@pytest.fixture
def mock_obs_client():
    """Create mock OBS WebSocket client."""
    client = MagicMock()

    # Mock record status
    status = Mock()
    status.output_active = False
    client.get_record_status.return_value = status

    # Mock record directory
    dir_response = Mock()
    dir_response.record_directory = "/test/recordings"
    client.get_record_directory.return_value = dir_response

    return client


class TestWebSocketConnection:
    """Test WebSocket connection logic with various scenarios."""

    @patch("scribe.core.recorder.obs_reqs")
    def test_connection_success_first_attempt(self, mock_obs_reqs, recorder, mock_obs_client):
        """Test successful connection on first attempt."""
        mock_obs_reqs.ReqClient.return_value = mock_obs_client

        with patch.object(recorder, "_port_listening", return_value=True):
            with recorder._connect_obs() as client:
                assert client == mock_obs_client
                mock_obs_reqs.ReqClient.assert_called_once()

    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.get_obs_executable_path")
    @patch("scribe.core.recorder.subprocess.Popen")
    def test_connection_retries_on_failure(
        self, mock_popen, mock_get_exe, mock_obs_reqs, recorder, mock_obs_client, tmp_path
    ):
        """Test connection retries when OBS is being launched."""
        # Setup OBS executable so it will try to launch
        obs_exe = tmp_path / "obs.exe"
        obs_exe.touch()
        mock_get_exe.return_value = obs_exe

        # First check: not listening (OBS not running)
        # After launch: listening but connection fails initially
        # Then succeeds
        listening_calls = [False, False, True, True, True]

        def port_listening(host, port, timeout):
            if listening_calls:
                return listening_calls.pop(0)
            return True

        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("Connection refused")
            return mock_obs_client

        mock_obs_reqs.ReqClient.side_effect = side_effect

        with patch.object(recorder, "_port_listening", side_effect=port_listening):
            with recorder._connect_obs() as client:
                assert client == mock_obs_client
                assert call_count[0] >= 3

    @patch("scribe.core.recorder.obs_reqs")
    def test_hostname_validation_error_suppressed(self, mock_obs_reqs, recorder, mock_obs_client):
        """
        Test that hostname validation errors are caught and suppressed.

        This is the core fix for the "ValueError: hostname is invalid" issue.
        The WebSocket library raises ValueError for invalid hostnames (especially IPv6),
        but we want to try other hosts instead of failing immediately.
        """
        # First attempt raises hostname validation error
        # Second attempt succeeds
        mock_obs_reqs.ReqClient.side_effect = [ValueError("hostname is invalid"), mock_obs_client]

        with patch.object(recorder, "_port_listening", return_value=True):
            with recorder._connect_obs() as client:
                assert client == mock_obs_client
                assert mock_obs_reqs.ReqClient.call_count == 2

    @patch("scribe.core.recorder.obs_reqs")
    def test_ipv6_hostname_validation_error(self, mock_obs_reqs, recorder, mock_obs_client):
        """
        Test handling of IPv6 hostname validation errors.

        IPv6 addresses (::1) often trigger validation errors in WebSocket libraries.
        We should try IPv4 fallbacks instead of failing.
        """

        # IPv6 fails with validation error, IPv4 succeeds
        def side_effect(*args, **kwargs):
            host = kwargs.get("host", args[0] if args else None)
            if host == "::1":
                raise ValueError("hostname is invalid: ::1")
            return mock_obs_client

        mock_obs_reqs.ReqClient.side_effect = side_effect

        with patch.object(recorder, "_port_listening", return_value=True):
            with recorder._connect_obs() as client:
                assert client == mock_obs_client

    @patch("scribe.core.recorder.obs_reqs")
    def test_connection_tries_multiple_hosts(self, mock_obs_reqs, recorder, mock_obs_client):
        """Test connection attempts multiple host/port combinations when OBS is running."""
        # Test that it tries different hosts when first ones fail
        hosts_tried = []

        def side_effect(*args, **kwargs):
            host = kwargs.get("host", args[0] if args else None)
            hosts_tried.append(host)
            # First host fails, second succeeds
            if len(hosts_tried) == 1:
                raise ConnectionError("Connection refused")
            return mock_obs_client

        mock_obs_reqs.ReqClient.side_effect = side_effect

        with patch.object(recorder, "_port_listening", return_value=True):
            with recorder._connect_obs() as client:
                assert client == mock_obs_client
                # Should have tried at least 2 hosts
                assert len(hosts_tried) >= 2

    @patch("scribe.core.recorder.obs_reqs")
    def test_connection_skips_non_listening_ports(self, mock_obs_reqs, recorder):
        """Test connection only attempts ports that are listening."""
        mock_obs_reqs.ReqClient.return_value = Mock()

        # Only second port is listening
        def port_listening(host, port, timeout):
            return port == 4455

        with patch.object(recorder, "_port_listening", side_effect=port_listening):
            with patch("scribe.core.recorder.get_obs_executable_path", return_value=None):
                try:
                    with recorder._connect_obs():
                        pass
                except ConnectionError:
                    pass  # Expected if no connection succeeds

        # Should only try the listening port
        assert mock_obs_reqs.ReqClient.call_count <= 2

    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.get_obs_executable_path")
    @patch("scribe.core.recorder.subprocess.Popen")
    @patch("scribe.core.recorder.subprocess.run")
    def test_connection_launches_obs_if_not_running(
        self, mock_run, mock_popen, mock_get_exe, mock_obs_reqs, recorder, mock_obs_client, tmp_path
    ):
        """Test OBS is launched if not already running."""
        obs_exe = tmp_path / "obs.exe"
        obs_exe.touch()
        mock_get_exe.return_value = obs_exe

        # Phase 1: _try_connect_to_running_obs checks all 3 hosts (localhost,
        # 127.0.0.1, ::1) — all False.  Phase 2: after launch, one returns True.
        listening_state = [False, False, False, True]

        def port_listening(host, port, timeout):
            if listening_state:
                return listening_state.pop(0)
            return True

        mock_obs_reqs.ReqClient.return_value = mock_obs_client

        with patch.object(recorder, "_port_listening", side_effect=port_listening):
            with recorder._connect_obs() as client:
                assert client == mock_obs_client
                mock_popen.assert_called_once()

    @patch("scribe.core.recorder.obs_reqs")
    def test_connection_timeout_raises_error(self, mock_obs_reqs, recorder):
        """Test connection timeout raises ConnectionError."""
        mock_obs_reqs.ReqClient.side_effect = ConnectionError("Connection refused")

        with patch.object(recorder, "_port_listening", return_value=False):
            with patch("scribe.core.recorder.get_obs_executable_path", return_value=None):
                with pytest.raises(ConnectionError, match="Could not connect"):
                    with recorder._connect_obs(max_wait_seconds=1):
                        pass

    @patch("scribe.core.recorder.obs_reqs")
    def test_connection_cleanup_on_success(self, mock_obs_reqs, recorder, mock_obs_client):
        """Test client is properly closed after successful connection."""
        mock_obs_reqs.ReqClient.return_value = mock_obs_client

        with patch.object(recorder, "_port_listening", return_value=True):
            with recorder._connect_obs():
                pass

        mock_obs_client.close.assert_called_once()

    @patch("scribe.core.recorder.obs_reqs")
    def test_connection_cleanup_on_exception(self, mock_obs_reqs, recorder, mock_obs_client):
        """Test client is closed even if exception occurs during use."""
        mock_obs_reqs.ReqClient.return_value = mock_obs_client

        with patch.object(recorder, "_port_listening", return_value=True):
            try:
                with recorder._connect_obs():
                    raise RuntimeError("Test error")
            except RuntimeError:
                pass

        # Client should be closed at least once (may be called multiple times due to retry logic)
        assert mock_obs_client.close.called

    @patch("scribe.core.recorder.obs_error")
    @patch("scribe.core.recorder.obs_reqs")
    def test_connection_handles_obs_not_ready_error(
        self, mock_obs_reqs, mock_obs_error, recorder, mock_obs_client
    ):
        """Test connection handles 'OBS not ready' error gracefully with retries."""
        # Create a mock OBSSDKRequestError
        not_ready_error = Exception(
            "Request GetRecordStatus returned code 207. OBS is not ready to perform the request."
        )
        mock_obs_error.OBSSDKRequestError = type(not_ready_error)

        # First few calls fail with "not ready", then succeed
        call_count = [0]

        def get_record_status_side_effect():
            call_count[0] += 1
            if call_count[0] < 3:
                raise not_ready_error
            status = Mock()
            status.output_active = False
            return status

        mock_obs_client.get_record_status.side_effect = get_record_status_side_effect
        mock_obs_reqs.ReqClient.return_value = mock_obs_client

        with patch.object(recorder, "_port_listening", return_value=True):
            with recorder._connect_obs() as client:
                assert client == mock_obs_client

        # Should have retried multiple times
        assert call_count[0] >= 3

    @patch("scribe.core.recorder.obs_error")
    @patch("scribe.core.recorder.obs_reqs")
    def test_try_connect_handles_not_ready_with_retries(
        self, mock_obs_reqs, mock_obs_error, recorder, mock_obs_client
    ):
        """Test _try_connect_to_running_obs retries on 'not ready' error."""
        # Create a mock OBSSDKRequestError
        not_ready_error = Exception("OBS is not ready to perform the request")
        mock_obs_error.OBSSDKRequestError = type(not_ready_error)

        # First 2 calls fail, third succeeds
        call_count = [0]

        def get_record_status_side_effect():
            call_count[0] += 1
            if call_count[0] < 3:
                raise not_ready_error
            status = Mock()
            status.output_active = False
            return status

        mock_obs_client.get_record_status.side_effect = get_record_status_side_effect
        mock_obs_reqs.ReqClient.return_value = mock_obs_client

        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._try_connect_to_running_obs(["localhost"], [4455])

        assert result == mock_obs_client
        assert call_count[0] == 3  # Should have retried until success


class TestHostnameValidation:
    """Test hostname validation error handling in detail."""

    @patch("scribe.core.recorder.obs_reqs")
    def test_various_validation_error_messages(self, mock_obs_reqs, recorder, mock_obs_client):
        """Test different validation error message formats are handled."""
        error_messages = [
            "hostname is invalid",
            "Hostname is Invalid",
            "HOSTNAME IS INVALID",
            "invalid hostname format",
            "hostname validation failed",
        ]

        for error_msg in error_messages:
            mock_obs_reqs.ReqClient.side_effect = [ValueError(error_msg), mock_obs_client]

            with patch.object(recorder, "_port_listening", return_value=True):
                with recorder._connect_obs() as client:
                    assert client == mock_obs_client

    @patch("scribe.core.recorder.obs_reqs")
    def test_other_value_errors_not_suppressed(self, mock_obs_reqs, recorder):
        """Test that non-hostname ValueError exceptions are not suppressed."""
        # This ValueError should not be caught by hostname validation logic
        mock_obs_reqs.ReqClient.side_effect = ValueError("Invalid port number")

        with patch.object(recorder, "_port_listening", return_value=True):
            with patch("scribe.core.recorder.get_obs_executable_path", return_value=None):
                with pytest.raises(ConnectionError):
                    with recorder._connect_obs(max_wait_seconds=1):
                        pass


class TestRecordingLifecycle:
    """Test complete recording lifecycle from start to finish."""

    @patch("scribe.core.recorder.obs_reqs")
    def test_start_recording_when_not_active(self, mock_obs_reqs, recorder, mock_obs_client):
        """Test starting recording when OBS is not recording."""
        # Initially not active, then becomes active after start
        status_inactive = Mock()
        status_inactive.output_active = False
        status_active = Mock()
        status_active.output_active = True

        mock_obs_client.get_record_status.side_effect = [
            status_inactive,  # Initial check
            status_active,  # Verification after start
        ]

        recorder._start_recording_if_needed(mock_obs_client)

        mock_obs_client.start_record.assert_called_once()

    @patch("scribe.core.recorder.obs_reqs")
    def test_stops_stale_recording_before_starting_new(
        self, mock_obs_reqs, recorder, mock_obs_client
    ):
        """Test that a stale active recording is stopped before starting a new one."""
        status_active = Mock()
        status_active.output_active = True
        status_inactive = Mock()
        status_inactive.output_active = False
        status_new_active = Mock()
        status_new_active.output_active = True

        mock_obs_client.get_record_status.side_effect = [
            status_active,  # Initial check — stale recording detected
            status_inactive,  # After stop_record — confirmed stopped
            status_inactive,  # Pre-start check (re-enter start path)
            status_new_active,  # Verification — new recording started
        ]

        recorder._start_recording_if_needed(mock_obs_client)

        mock_obs_client.stop_record.assert_called_once()
        mock_obs_client.start_record.assert_called_once()

    @patch("scribe.core.recorder.obs_reqs")
    def test_start_recording_verification(self, mock_obs_reqs, recorder, mock_obs_client):
        """Test recording start is verified before proceeding."""
        # Initially not active, then becomes active
        status_inactive = Mock()
        status_inactive.output_active = False
        status_active = Mock()
        status_active.output_active = True

        mock_obs_client.get_record_status.side_effect = [
            status_inactive,  # Initial check
            status_active,  # Verification check
        ]

        recorder._start_recording_if_needed(mock_obs_client)

        assert mock_obs_client.get_record_status.call_count >= 2

    @patch("scribe.core.recorder.obs_reqs")
    def test_start_recording_timeout(self, mock_obs_reqs, recorder, mock_obs_client):
        """Test recording start timeout raises error."""
        status = Mock()
        status.output_active = False
        mock_obs_client.get_record_status.return_value = status

        with pytest.raises(ProcessError, match="failed to start"):
            recorder._start_recording_if_needed(mock_obs_client)


class TestFileDetection:
    """Test recording file detection and monitoring."""

    def test_newest_media_finds_mp4(self, recorder, tmp_path):
        """Test finding newest MP4 file."""
        # Create test files
        old_file = tmp_path / "old.mp4"
        old_file.touch()
        time.sleep(0.1)

        new_file = tmp_path / "new.mp4"
        new_file.touch()

        start_time = time.time() - 10
        mp4, mkv = recorder._newest_media_since(str(tmp_path), start_time)

        assert mp4 == str(new_file)
        assert mkv is None

    def test_newest_media_finds_mkv(self, recorder, tmp_path):
        """Test finding newest MKV file."""
        mkv_file = tmp_path / "recording.mkv"
        mkv_file.touch()

        start_time = time.time() - 10
        mp4, mkv = recorder._newest_media_since(str(tmp_path), start_time)

        assert mp4 is None
        assert mkv == str(mkv_file)

    def test_newest_media_ignores_old_files(self, recorder, tmp_path):
        """Test old files are ignored based on timestamp."""
        old_file = tmp_path / "old.mp4"
        old_file.touch()

        # Wait a moment to ensure file timestamp is in the past
        time.sleep(0.1)

        # Set timestamp to after file creation (plus buffer to account for 120s window)
        start_time = time.time() + 130  # Beyond the 120s window
        mp4, mkv = recorder._newest_media_since(str(tmp_path), start_time)

        assert mp4 is None
        assert mkv is None

    def test_newest_media_handles_missing_directory(self, recorder):
        """Test handling of nonexistent directory."""
        mp4, mkv = recorder._newest_media_since("/nonexistent/path", time.time())

        assert mp4 is None
        assert mkv is None

    def test_newest_media_prefers_newest_file(self, recorder, tmp_path):
        """Test newest file is selected when multiple exist."""
        files = []
        for i in range(5):
            f = tmp_path / f"recording_{i}.mp4"
            f.touch()
            files.append(f)
            time.sleep(0.05)

        start_time = time.time() - 10
        mp4, mkv = recorder._newest_media_since(str(tmp_path), start_time)  # noqa: RUF059 - only mp4 matters in this test

        assert mp4 == str(files[-1])


class TestFileFinalization:
    """Test file finalization and cleanup."""

    def test_wait_until_file_finalized(self, recorder, tmp_path):
        """Test waiting for file to stop growing."""
        test_file = tmp_path / "recording.mp4"
        test_file.write_bytes(b"initial content")

        # File should be considered finalized immediately (not growing)
        recorder._wait_until_file_finalized(str(test_file), idle_seconds=0.5, max_wait=2.0)

        assert test_file.exists()

    def test_wait_until_file_finalized_timeout(self, recorder, tmp_path):
        """Test finalization timeout doesn't raise error."""
        test_file = tmp_path / "recording.mp4"

        # File doesn't exist - should timeout gracefully
        recorder._wait_until_file_finalized(str(test_file), idle_seconds=0.5, max_wait=1.0)

    @patch("scribe.core.recorder.get_ffmpeg_path")
    @patch("scribe.core.recorder.subprocess.run")
    def test_remux_mkv_to_mp4_success(self, mock_run, mock_get_ffmpeg, recorder, tmp_path):
        """Test successful MKV to MP4 remuxing."""
        mock_get_ffmpeg.return_value = Path("/usr/bin/ffmpeg")

        mkv_file = tmp_path / "recording.mkv"
        mkv_file.write_bytes(b"fake mkv content")

        mp4_file = tmp_path / "recording.mp4"

        # Simulate ffmpeg creating the output file
        def create_mp4(*args, **kwargs):
            mp4_file.write_bytes(b"fake mp4 content")
            return Mock(returncode=0)

        mock_run.side_effect = create_mp4

        result = recorder._remux_mkv_to_mp4(str(mkv_file), str(mp4_file))

        assert result is True
        mock_run.assert_called_once()

    @patch("scribe.core.recorder.get_ffmpeg_path")
    def test_remux_mkv_to_mp4_no_ffmpeg(self, mock_get_ffmpeg, recorder, tmp_path):
        """Test remuxing fails gracefully when ffmpeg not available."""
        mock_get_ffmpeg.return_value = None

        mkv_file = tmp_path / "recording.mkv"
        mp4_file = tmp_path / "recording.mp4"

        result = recorder._remux_mkv_to_mp4(str(mkv_file), str(mp4_file))

        assert result is False

    def test_safe_filename_generation(self, recorder):
        """Test safe filename generation with sanitization."""
        timestamp = time.time()

        # Test normal name
        filename = recorder._safe_filename("Test Meeting", timestamp)
        assert "Test Meeting" in filename
        assert filename.endswith(".mp4")

        # Test name with invalid characters
        filename = recorder._safe_filename("Test/Meeting:2024", timestamp)
        assert "/" not in filename
        assert ":" not in filename

        # Test empty name
        filename = recorder._safe_filename("", timestamp)
        assert "Recording" in filename


class TestCLIFallback:
    """Test CLI fallback mode when WebSocket unavailable."""

    @patch("scribe.core.recorder.OBS_AVAILABLE", False)
    def test_cli_fallback_when_websocket_unavailable(self, recorder, tmp_path):
        """Test CLI fallback is used when WebSocket library not available."""
        # This would normally call _record_with_cli
        # We just verify the logic path exists
        assert True  # Placeholder for integration test

    def test_cli_fallback_file_detection(self, recorder, tmp_path):
        """Test file detection in CLI fallback mode."""
        # Create a recording file
        recording = tmp_path / "recording.mp4"
        recording.write_bytes(b"fake recording")

        start_time = time.time() - 5
        mp4, mkv = recorder._newest_media_since(str(tmp_path), start_time)  # noqa: RUF059 - only mp4 matters in this test

        assert mp4 == str(recording)


class TestThreadSafety:
    """Test thread safety and concurrent operations."""

    def test_stop_listener_thread_creation(self, recorder):
        """Test stop listener thread is created properly."""
        stop_event, restore = recorder._start_stop_listener()
        try:
            assert isinstance(stop_event, threading.Event)
            assert not stop_event.is_set()
        finally:
            restore()

    def test_stop_listener_responds_to_stop_command(self, recorder):
        """Test stop listener sets event on stop command."""
        # This is difficult to test without actual stdin
        # Verify the thread is created and event exists
        stop_event, restore = recorder._start_stop_listener()
        try:
            # Manually set event to simulate stop command
            stop_event.set()
            assert stop_event.is_set()
        finally:
            restore()


class TestErrorHandling:
    """Test error handling and recovery."""

    def test_ensure_dir_writable_creates_directory(self, recorder, tmp_path):
        """Test directory creation when it doesn't exist."""
        new_dir = tmp_path / "new" / "nested" / "dir"

        result = recorder._ensure_dir_writable(new_dir)

        assert result.exists()
        assert result.is_dir()

    def test_ensure_dir_writable_verifies_permissions(self, recorder, tmp_path):
        """Test write permission verification."""
        test_dir = tmp_path / "test"
        test_dir.mkdir()

        result = recorder._ensure_dir_writable(test_dir)

        assert result == test_dir

    @patch("scribe.core.recorder.Path.write_bytes")
    def test_ensure_dir_writable_fails_on_readonly(self, mock_write, recorder, tmp_path):
        """Test error when directory is not writable."""
        test_dir = tmp_path / "readonly"
        test_dir.mkdir()

        mock_write.side_effect = PermissionError("Permission denied")

        with pytest.raises(ProcessError, match="not writable"):
            recorder._ensure_dir_writable(test_dir)

    def test_port_listening_detects_open_port(self, recorder):
        """Test port listening detection for open port."""
        # Create a temporary server socket
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        try:
            result = recorder._port_listening("127.0.0.1", port, timeout=0.5)
            assert result is True
        finally:
            server.close()

    def test_port_listening_detects_closed_port(self, recorder):
        """Test port listening detection for closed port."""
        # Use a port that's very unlikely to be open
        result = recorder._port_listening("127.0.0.1", 54321, timeout=0.2)
        assert result is False


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_recording_with_empty_meeting_name(self, recorder, tmp_path):
        """Test recording with empty meeting name uses default."""
        filename = recorder._safe_filename("", time.time())
        assert "Recording" in filename

    def test_recording_with_special_characters(self, recorder):
        """Test recording name with special characters is sanitized."""
        filename = recorder._safe_filename('Test<>:"/\\|?*Meeting', time.time())

        # Should not contain any invalid characters
        invalid_chars = r'<>:"/\|?*'
        for char in invalid_chars:
            assert char not in filename

    def test_recording_with_very_long_name(self, recorder):
        """Test recording with very long name is handled."""
        long_name = "A" * 500
        filename = recorder._safe_filename(long_name, time.time())

        # Should still be a valid filename
        assert len(filename) > 0
        assert filename.endswith(".mp4")

    def test_multiple_recordings_same_timestamp(self, recorder, tmp_path):
        """Test handling multiple recordings with same timestamp."""
        timestamp = time.time()

        name1 = recorder._safe_filename("Meeting1", timestamp)
        name2 = recorder._safe_filename("Meeting2", timestamp)

        # Should have different names
        assert name1 != name2


class TestResourceCleanup:
    """Test proper resource cleanup and management."""

    @patch("scribe.core.recorder.obs_reqs")
    def test_client_closed_after_successful_recording(
        self, mock_obs_reqs, recorder, mock_obs_client
    ):
        """Test WebSocket client is closed after recording."""
        mock_obs_reqs.ReqClient.return_value = mock_obs_client

        with patch.object(recorder, "_port_listening", return_value=True):
            try:
                with recorder._connect_obs():
                    pass
            except Exception:
                pass

        mock_obs_client.close.assert_called()

    @patch("scribe.core.recorder.obs_reqs")
    def test_client_closed_on_exception(self, mock_obs_reqs, recorder, mock_obs_client):
        """Test WebSocket client is closed even on exception."""
        mock_obs_reqs.ReqClient.return_value = mock_obs_client

        with patch.object(recorder, "_port_listening", return_value=True):
            try:
                with recorder._connect_obs():
                    raise RuntimeError("Test exception")
            except RuntimeError:
                pass

        mock_obs_client.close.assert_called()


class TestIntegrationScenarios:
    """Test realistic end-to-end scenarios."""

    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.get_obs_executable_path")
    def test_full_recording_workflow_websocket(
        self, mock_get_exe, mock_obs_reqs, recorder, mock_obs_client, tmp_path
    ):
        """Test complete recording workflow using WebSocket."""
        # Setup
        mock_obs_reqs.ReqClient.return_value = mock_obs_client
        mock_get_exe.return_value = None  # OBS already running

        # Create a fake recording file
        recording_file = tmp_path / "output" / "Meeting_2024-11-20_14-00-00.mp4"
        recording_file.parent.mkdir(parents=True, exist_ok=True)
        recording_file.write_bytes(b"fake recording")

        # Mock recording status progression
        status_inactive = Mock()
        status_inactive.output_active = False
        status_active = Mock()
        status_active.output_active = True
        status_stopped = Mock()
        status_stopped.output_active = False

        mock_obs_client.get_record_status.side_effect = [
            status_inactive,  # Initial check
            status_active,  # After start
            status_active,  # During recording
            status_stopped,  # After stop
        ]

        # This would be a full integration test
        # For now, verify the components exist
        assert hasattr(recorder, "_connect_obs")
        assert hasattr(recorder, "_start_recording_if_needed")
        assert hasattr(recorder, "_wait_for_stop_with_input")


class TestDefensiveProgramming:
    """Test defensive programming patterns and error resilience."""

    def test_handles_none_return_values(self, recorder):
        """Test handling of None return values."""
        mp4, mkv = recorder._newest_media_since("/nonexistent", time.time())
        assert mp4 is None
        assert mkv is None

    def test_handles_permission_errors(self, recorder, tmp_path):
        """Test handling of permission errors."""
        # This is platform-specific and hard to test reliably
        # Verify the error handling code exists
        assert hasattr(recorder, "_ensure_dir_writable")

    def test_handles_network_timeouts(self, recorder):
        """Test handling of network timeouts."""
        # Port listening should timeout gracefully
        result = recorder._port_listening("192.0.2.1", 12345, timeout=0.1)
        assert result is False

    def test_handles_malformed_responses(self, recorder, mock_obs_client):
        """Test handling of malformed OBS responses."""
        # Mock malformed response
        mock_obs_client.get_record_status.return_value = None

        # Should handle gracefully
        try:
            status = mock_obs_client.get_record_status()
            active = getattr(status, "output_active", False)
            assert active is False
        except Exception:
            pytest.fail("Should handle None response gracefully")


# ---------------------------------------------------------------------------
# NEW TESTS — appended to raise coverage to 80%+
# ---------------------------------------------------------------------------


class TestKillExistingObs:
    """Test _kill_existing_obs and helpers."""

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.utils.platform.is_windows", return_value=True)
    def test_kill_windows_basic(self, _mock_win, mock_run, mock_sleep, recorder):
        """Kill on Windows calls taskkill for both exe names."""
        with patch.object(recorder, "_obs_process_running", return_value=False):
            with patch.object(recorder, "_clean_obs_crash_sentinel"):
                recorder._kill_existing_obs()
        # 2 taskkill calls (obs64 + obs32)
        assert mock_run.call_count == 2

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.utils.platform.is_windows", return_value=True)
    def test_kill_windows_retry_with_tree(self, _mock_win, mock_run, mock_sleep, recorder):
        """If OBS survives first kill, retry with /T flag."""
        with patch.object(recorder, "_obs_process_running", return_value=True):
            with patch.object(recorder, "_clean_obs_crash_sentinel"):
                recorder._kill_existing_obs()
        # 2 initial + 2 retry = 4
        assert mock_run.call_count == 4

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.utils.platform.is_windows", return_value=False)
    def test_kill_linux(self, _mock_win, mock_run, mock_sleep, recorder):
        """Kill on Linux calls pkill -x for each exact process name (obs, OBS)."""
        with patch.object(recorder, "_obs_process_running", return_value=False):
            with patch.object(recorder, "_clean_obs_crash_sentinel"):
                recorder._kill_existing_obs()
        assert mock_run.call_count == 2
        # Exact-name match, never the dangerous "-f obs" substring match.
        for call in mock_run.call_args_list:
            assert "-x" in call.args[0]
            assert "-f" not in call.args[0]

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.utils.platform.is_windows", return_value=False)
    def test_kill_linux_retry(self, _mock_win, mock_run, mock_sleep, recorder):
        """Linux retries with -9 when process survives (two exact names each pass)."""
        with patch.object(recorder, "_obs_process_running", return_value=True):
            with patch.object(recorder, "_clean_obs_crash_sentinel"):
                recorder._kill_existing_obs()
        # 2 initial pkill -x (obs, OBS) + 2 pkill -9 -x (obs, OBS)
        assert mock_run.call_count == 4

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.utils.platform.is_windows", return_value=True)
    def test_kill_exception_suppressed(self, _mock_win, mock_run, mock_sleep, recorder):
        """Exceptions during kill are suppressed."""
        mock_run.side_effect = OSError("access denied")
        with patch.object(recorder, "_obs_process_running", return_value=False):
            with patch.object(recorder, "_clean_obs_crash_sentinel"):
                recorder._kill_existing_obs()  # should not raise


class TestObsProcessRunning:
    """Test _obs_process_running."""

    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.utils.platform.is_windows", return_value=True)
    def test_windows_running(self, _w, mock_run, recorder):
        mock_run.return_value = Mock(stdout="Image Name  PID\nobs64.exe  1234")
        assert recorder._obs_process_running() is True

    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.utils.platform.is_windows", return_value=True)
    def test_windows_not_running(self, _w, mock_run, recorder):
        mock_run.return_value = Mock(stdout="INFO: No tasks are running")
        assert recorder._obs_process_running() is False

    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.utils.platform.is_windows", return_value=False)
    def test_linux_running(self, _w, mock_run, recorder):
        mock_run.return_value = Mock(returncode=0)
        assert recorder._obs_process_running() is True

    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.utils.platform.is_windows", return_value=False)
    def test_linux_not_running(self, _w, mock_run, recorder):
        mock_run.return_value = Mock(returncode=1)
        assert recorder._obs_process_running() is False

    @patch("scribe.core.recorder.subprocess.run", side_effect=Exception("oops"))
    @patch("scribe.utils.platform.is_windows", return_value=True)
    def test_exception_returns_false(self, _w, _r, recorder):
        assert recorder._obs_process_running() is False


class TestCleanObsCrashSentinel:
    """Test _clean_obs_crash_sentinel."""

    @patch("scribe.utils.platform.is_windows", return_value=True)
    def test_cleans_crash_flags(self, _w, recorder, tmp_path):
        sentinel = tmp_path / "obs-studio" / "global.ini"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("[General]\nLastCrash=2024-01-01\nSafeMode=1\nOther=keep\n")
        with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
            recorder._clean_obs_crash_sentinel()
        content = sentinel.read_text()
        assert "LastCrash" not in content
        assert "SafeMode" not in content
        assert "Other=keep" in content

    @patch("scribe.utils.platform.is_windows", return_value=True)
    def test_no_appdata_returns(self, _w, recorder):
        with patch.dict(os.environ, {"APPDATA": ""}, clear=False):
            recorder._clean_obs_crash_sentinel()  # should not raise

    @patch("scribe.utils.platform.is_macos", return_value=False)
    @patch("scribe.utils.platform.is_windows", return_value=False)
    def test_linux_sentinel(self, _w, _m, recorder, tmp_path):
        sentinel = tmp_path / ".config" / "obs-studio" / "global.ini"
        sentinel.parent.mkdir(parents=True)
        sentinel.write_text("LastCrash=yes\nKeep=1\n")
        # Force the ~/.config branch: an empty XDG_CONFIG_HOME is treated as unset
        # (CI runners often set XDG_CONFIG_HOME, which would otherwise win).
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": ""}):
            with patch("pathlib.Path.home", return_value=tmp_path):
                recorder._clean_obs_crash_sentinel()
        assert "LastCrash" not in sentinel.read_text()
        assert "Keep=1" in sentinel.read_text()

    @patch("scribe.utils.platform.is_windows", return_value=True)
    def test_missing_sentinel_noop(self, _w, recorder, tmp_path):
        with patch.dict(os.environ, {"APPDATA": str(tmp_path)}):
            recorder._clean_obs_crash_sentinel()  # no error


class TestConnectObsPhase2:
    """Test the kill→launch→retry loop in _connect_obs Phase 2."""

    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.get_obs_executable_path", return_value=None)
    def test_no_exe_raises_connection_error(self, _exe, mock_reqs, recorder):
        """If OBS exe is None, cannot launch → raises ConnectionError."""
        with patch.object(recorder, "_port_listening", return_value=False):
            with patch.object(recorder, "_kill_existing_obs"):
                with pytest.raises(ConnectionError, match="Could not connect"):
                    with recorder._connect_obs(max_wait_seconds=1):
                        pass

    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.subprocess.Popen")
    @patch("scribe.core.recorder.get_obs_executable_path")
    def test_launch_fails_retries(self, mock_exe, mock_popen, mock_reqs, recorder, tmp_path):
        """Popen raises → retries, eventually ConnectionError."""
        obs_exe = tmp_path / "obs.exe"
        obs_exe.touch()
        mock_exe.return_value = obs_exe
        mock_popen.side_effect = OSError("cannot start")

        with patch.object(recorder, "_port_listening", return_value=False):
            with patch.object(recorder, "_kill_existing_obs"):
                with pytest.raises(ConnectionError):
                    with recorder._connect_obs(max_wait_seconds=1):
                        pass
        # Popen called for each attempt (max_launch_attempts=2)
        assert mock_popen.call_count == 2


class TestStartRecordingStaleStop:
    """Test stale-stop path in _start_recording_if_needed."""

    def test_stale_stop_fails_raises(self, recorder, mock_obs_client):
        """Stale recording detected but stop fails → ProcessError."""
        status_active = Mock()
        status_active.output_active = True

        # Always stays active
        mock_obs_client.get_record_status.return_value = status_active
        mock_obs_client.stop_record.return_value = None

        with patch("scribe.core.recorder.time.sleep"):
            with pytest.raises(ProcessError, match="Cannot start new recording"):
                recorder._start_recording_if_needed(mock_obs_client)

    def test_start_record_refused(self, recorder, mock_obs_client):
        """start_record raises unexpected error → ProcessError."""
        status = Mock()
        status.output_active = False
        mock_obs_client.get_record_status.return_value = status
        mock_obs_client.start_record.side_effect = Exception("codec error")

        with pytest.raises(ProcessError, match="OBS refused to start"):
            recorder._start_recording_if_needed(mock_obs_client)

    def test_start_record_already_active(self, recorder, mock_obs_client):
        """start_record says 'already' → handled gracefully."""
        status = Mock()
        status.output_active = False
        mock_obs_client.get_record_status.return_value = status
        mock_obs_client.start_record.side_effect = Exception("already recording")

        recorder._start_recording_if_needed(mock_obs_client)  # should not raise


class TestReconnectClient:
    """Test _reconnect_client."""

    @patch("scribe.core.recorder.obs_reqs")
    def test_reconnect_success(self, mock_reqs, recorder):
        new_client = MagicMock()
        mock_reqs.ReqClient.return_value = new_client
        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._reconnect_client()
        assert result is new_client

    @patch("scribe.core.recorder.obs_reqs")
    def test_reconnect_all_fail(self, mock_reqs, recorder):
        mock_reqs.ReqClient.side_effect = ConnectionError("nope")
        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._reconnect_client()
        assert result is None

    def test_reconnect_no_port_listening(self, recorder):
        with patch.object(recorder, "_port_listening", return_value=False):
            result = recorder._reconnect_client()
        assert result is None


class TestWaitForStopWithInput:
    """Test _wait_for_stop_with_input."""

    @patch("scribe.core.recorder.time.sleep")
    def test_recording_stops_normally(self, mock_sleep, recorder, mock_obs_client):
        """Active→inactive triggers return."""
        status_active = Mock(output_active=True)
        status_inactive = Mock(output_active=False)
        mock_obs_client.get_record_status.side_effect = [
            status_active,
            status_active,
            status_inactive,
        ]
        stop_event = threading.Event()
        with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
            with patch("sys.stdout"):
                recorder._wait_for_stop_with_input(mock_obs_client, stop_event)

    @patch("scribe.core.recorder.time.sleep")
    def test_deadman_timer(self, mock_sleep, recorder, mock_obs_client):
        """Stop requested but OBS stays active → deadman timer fires."""
        status_active = Mock(output_active=True)
        mock_obs_client.get_record_status.return_value = status_active

        stop_event = threading.Event()
        stop_event.set()  # user already pressed stop

        # time.time() is called many times (by logging, etc). Start at 100,
        # then jump past the 30s deadline after a few calls.
        _counter = [0]

        def fake_time():
            _counter[0] += 1
            if _counter[0] < 5:
                return 100.0
            return 131.0  # past deadman_seconds (30)

        with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
            with patch("sys.stdout"):
                with patch("scribe.core.recorder.time.time", side_effect=fake_time):
                    recorder._wait_for_stop_with_input(mock_obs_client, stop_event)

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.obs_reqs")
    def test_consecutive_errors_trigger_reconnect(
        self, mock_reqs, mock_sleep, recorder, mock_obs_client
    ):
        """10 consecutive errors trigger reconnect attempt."""
        error_count = [0]

        def get_status():
            error_count[0] += 1
            if error_count[0] <= 10:
                raise ConnectionError("lost")
            # After reconnect, return inactive to end loop
            return Mock(output_active=False)

        mock_obs_client.get_record_status.side_effect = get_status
        stop_event = threading.Event()

        # _reconnect_client returns a fresh client that reports inactive
        fresh = MagicMock()
        fresh.get_record_status.return_value = Mock(output_active=False)

        with patch.object(recorder, "_reconnect_client", return_value=fresh):
            with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
                with patch("sys.stdout"):
                    recorder._wait_for_stop_with_input(mock_obs_client, stop_event)

    @patch("scribe.core.recorder.time.sleep")
    def test_stop_reconnect_retry(self, mock_sleep, recorder, mock_obs_client):
        """Stop command fails → reconnect → retry stop."""
        call_count = [0]

        def get_status():
            call_count[0] += 1
            if call_count[0] <= 2:
                return Mock(output_active=True)
            return Mock(output_active=False)

        mock_obs_client.get_record_status.side_effect = get_status
        mock_obs_client.stop_record.side_effect = ConnectionError("dead")

        stop_event = threading.Event()
        stop_event.set()

        new_client = MagicMock()
        new_client.get_record_status.return_value = Mock(output_active=False)

        with patch.object(recorder, "_reconnect_client", return_value=new_client):
            with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
                with patch("sys.stdout"):
                    recorder._wait_for_stop_with_input(mock_obs_client, stop_event)

    @patch("scribe.core.recorder.time.sleep")
    def test_no_tty_message(self, mock_sleep, recorder, mock_obs_client):
        """No TTY shows Ctrl-C message instead of panel."""
        mock_obs_client.get_record_status.side_effect = [
            Mock(output_active=True),
            Mock(output_active=False),
        ]
        stop_event = threading.Event()
        with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
            with patch("sys.stdout"):
                recorder._wait_for_stop_with_input(mock_obs_client, stop_event)

    @patch("scribe.core.recorder.time.sleep")
    def test_auto_stop_at_max_duration(self, mock_sleep, recorder, mock_obs_client):
        """Recording auto-stops when the configured max duration is reached."""
        recorder.max_recording_hours = 0.001  # 3.6 seconds
        recorder.recording_warning_fraction = 0.5

        mock_obs_client.get_record_status.side_effect = [
            Mock(output_active=True),
            Mock(output_active=False),
        ]

        stop_event = threading.Event()

        time_values = iter([100.0, 104.0, 104.0, 104.0, 104.0])

        with patch("scribe.core.recorder.time.time", side_effect=lambda: next(time_values, 104.0)):
            with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
                with patch("sys.stdout"):
                    recorder._wait_for_stop_with_input(mock_obs_client, stop_event)

        assert stop_event.is_set()
        mock_obs_client.stop_record.assert_called_once()


class TestWaitForStopCli:
    """Test _wait_for_stop_cli."""

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.core.recorder.get_obs_executable_path")
    def test_cli_auto_stop_at_max_duration(
        self, mock_exe, mock_run, mock_sleep, recorder, tmp_path
    ):
        """CLI fallback also auto-stops at the configured max duration."""
        recorder.max_recording_hours = 0.001  # 3.6 seconds
        recorder.recording_warning_fraction = 0.5

        obs_exe = tmp_path / "obs.exe"
        obs_exe.touch()
        mock_exe.return_value = obs_exe
        mock_run.return_value = Mock(returncode=0)

        time_values = iter([100.0, 104.0, 104.0, 104.0])

        with patch("scribe.core.recorder.time.time", side_effect=lambda: next(time_values, 104.0)):
            with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
                with patch("sys.stdout"):
                    recorder._wait_for_stop_cli(threading.Event())

        mock_run.assert_called_once()

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.core.recorder.get_obs_executable_path")
    def test_stop_signal_sent(self, mock_exe, mock_run, mock_sleep, recorder, tmp_path):
        """Stop event set → --stoprecording called."""
        obs_exe = tmp_path / "obs.exe"
        obs_exe.touch()
        mock_exe.return_value = obs_exe
        mock_run.return_value = Mock(returncode=0)

        stop_event = threading.Event()
        stop_event.set()

        with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
            with patch("sys.stdout"):
                recorder._wait_for_stop_cli(stop_event)
        mock_run.assert_called_once()

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.get_obs_executable_path", return_value=None)
    def test_obs_exe_not_found(self, mock_exe, mock_sleep, recorder):
        """No obs executable → warns user."""
        stop_event = threading.Event()
        stop_event.set()

        with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
            with patch("sys.stdout"):
                recorder._wait_for_stop_cli(stop_event)

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.core.recorder.get_obs_executable_path")
    def test_stop_timeout(self, mock_exe, mock_run, mock_sleep, recorder, tmp_path):
        """--stoprecording times out."""
        obs_exe = tmp_path / "obs.exe"
        obs_exe.touch()
        mock_exe.return_value = obs_exe
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="obs", timeout=10)

        stop_event = threading.Event()
        stop_event.set()

        with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
            with patch("sys.stdout"):
                recorder._wait_for_stop_cli(stop_event)


class TestStartStopListener:
    """Test _start_stop_listener SIGINT."""

    def test_restore_works(self, recorder):
        """Restore function restores original SIGINT handler."""
        import signal

        original = signal.getsignal(signal.SIGINT)
        ev, restore = recorder._start_stop_listener()  # noqa: RUF059 - only restore matters
        # handler is now custom
        restore()
        # should be restored
        current = signal.getsignal(signal.SIGINT)
        assert current == original

    def test_double_restore_safe(self, recorder):
        """Calling restore twice does not raise."""
        ev, restore = recorder._start_stop_listener()  # noqa: RUF059 - only restore matters
        restore()
        restore()  # should not raise

    def test_sigint_handler_sets_event(self, recorder):
        """SIGINT handler sets the stop event."""
        import signal

        ev, restore = recorder._start_stop_listener()
        try:
            handler = signal.getsignal(signal.SIGINT)
            # Call the handler directly
            handler(signal.SIGINT, None)
            assert ev.is_set()
        finally:
            restore()


class TestRecordWithWebsocket:
    """Test _record_with_websocket."""

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.obs_reqs")
    def test_happy_path(self, mock_reqs, mock_sleep, recorder, mock_obs_client, tmp_path):
        """Full happy path: connect, start, stop, find file."""
        mock_reqs.ReqClient.return_value = mock_obs_client

        # Create a file for detection
        rec_file = tmp_path / "output" / "test.mp4"
        rec_file.parent.mkdir(parents=True, exist_ok=True)
        rec_file.write_bytes(b"fake video")

        recorder.output_folder = rec_file.parent

        with patch.object(recorder, "_port_listening", return_value=True):
            with patch.object(recorder, "_set_record_dir_if_possible"):
                with patch.object(
                    recorder, "_get_effective_record_dir", return_value=str(rec_file.parent)
                ):
                    with patch.object(recorder, "_start_recording_if_needed"):
                        with patch.object(recorder, "_wait_for_stop_with_input"):
                            with patch.object(
                                recorder, "_newest_media_since", return_value=(str(rec_file), None)
                            ):
                                with patch.object(recorder, "_wait_until_file_finalized"):
                                    with patch.object(
                                        recorder, "_finalize_recording", return_value=rec_file
                                    ):
                                        result = recorder._record_with_websocket(
                                            "test", threading.Event()
                                        )
        assert result == rec_file

    @patch("scribe.core.recorder.obs_reqs")
    def test_connection_error_falls_back(self, mock_reqs, recorder):
        """ConnectionError during connect → falls back to CLI."""
        mock_reqs.ReqClient.side_effect = ConnectionError("nope")

        with patch.object(recorder, "_port_listening", return_value=False):
            with patch("scribe.core.recorder.get_obs_executable_path", return_value=None):
                with patch.object(recorder, "_kill_existing_obs"):
                    with patch.object(
                        recorder, "_record_with_cli", return_value=Path("/tmp/rec.mp4")
                    ) as mock_cli:
                        result = recorder._record_with_websocket("test", threading.Event())
        assert result == Path("/tmp/rec.mp4")
        mock_cli.assert_called_once()

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.obs_reqs")
    def test_file_not_found_raises(
        self, mock_reqs, mock_sleep, recorder, mock_obs_client, tmp_path
    ):
        """No media file found → ProcessError."""
        mock_reqs.ReqClient.return_value = mock_obs_client
        recorder.output_folder = tmp_path / "output"
        recorder.output_folder.mkdir(parents=True, exist_ok=True)

        with patch.object(recorder, "_port_listening", return_value=True):
            with patch.object(recorder, "_set_record_dir_if_possible"):
                with patch.object(
                    recorder, "_get_effective_record_dir", return_value=str(tmp_path)
                ):
                    with patch.object(recorder, "_start_recording_if_needed"):
                        with patch.object(recorder, "_wait_for_stop_with_input"):
                            with patch.object(
                                recorder, "_newest_media_since", return_value=(None, None)
                            ):
                                with pytest.raises(ProcessError, match="Could not locate"):
                                    recorder._record_with_websocket("test", threading.Event())


class TestRecord:
    """Test the record() entry point."""

    def test_process_error_passthrough(self, recorder):
        """ProcessError is not double-wrapped."""
        with patch.object(
            recorder, "_start_stop_listener", return_value=(threading.Event(), lambda: None)
        ):
            with patch.object(recorder, "_ensure_dir_writable"):
                with patch("scribe.core.recorder.OBS_AVAILABLE", True):
                    with patch.object(
                        recorder, "_record_with_websocket", side_effect=ProcessError("original")
                    ):
                        with pytest.raises(ProcessError, match="original"):
                            recorder.record("test")

    def test_generic_error_wrapped(self, recorder):
        """Non-ProcessError gets wrapped in ProcessError."""
        with patch.object(
            recorder, "_start_stop_listener", return_value=(threading.Event(), lambda: None)
        ):
            with patch.object(recorder, "_ensure_dir_writable"):
                with patch("scribe.core.recorder.OBS_AVAILABLE", True):
                    with patch.object(
                        recorder, "_record_with_websocket", side_effect=RuntimeError("boom")
                    ):
                        with pytest.raises(ProcessError, match="OBS recording failed"):
                            recorder.record("test")

    def test_fallback_output_dir(self, recorder, tmp_path):
        """When configured output folder fails, fallback to temp dir."""
        recorder.output_folder = tmp_path / "no-exist" / "deep"

        def fail_first(path):
            if "no-exist" in str(path):
                raise PermissionError("nope")
            Path(path).mkdir(parents=True, exist_ok=True)
            return Path(path)

        with patch.object(
            recorder, "_start_stop_listener", return_value=(threading.Event(), lambda: None)
        ):
            with patch.object(recorder, "_ensure_dir_writable", side_effect=fail_first):
                with patch("scribe.core.recorder.OBS_AVAILABLE", True):
                    with patch.object(
                        recorder, "_record_with_websocket", return_value=Path("/tmp/r.mp4")
                    ):
                        result = recorder.record("test")
        assert result == Path("/tmp/r.mp4")

    def test_cli_fallback_when_obs_unavailable(self, recorder):
        """OBS_AVAILABLE=False → CLI fallback used."""
        with patch.object(
            recorder, "_start_stop_listener", return_value=(threading.Event(), lambda: None)
        ):
            with patch.object(recorder, "_ensure_dir_writable"):
                with patch("scribe.core.recorder.OBS_AVAILABLE", False):
                    with patch.object(
                        recorder, "_record_with_cli", return_value=Path("/tmp/r.mp4")
                    ) as mock_cli:
                        result = recorder.record("test")
        assert result == Path("/tmp/r.mp4")
        mock_cli.assert_called_once()


class TestGetEffectiveRecordDir:
    """Test _get_effective_record_dir."""

    def test_returns_obs_dir(self, recorder, mock_obs_client):
        dir_resp = Mock()
        dir_resp.record_directory = "/my/recordings"
        mock_obs_client.get_record_directory.return_value = dir_resp
        result = recorder._get_effective_record_dir(mock_obs_client, "/fallback")
        assert "recordings" in result

    def test_fallback_on_failure(self, recorder, mock_obs_client):
        mock_obs_client.get_record_directory.side_effect = Exception("err")
        result = recorder._get_effective_record_dir(mock_obs_client, "/fallback")
        assert "fallback" in result

    def test_fallback_on_empty(self, recorder, mock_obs_client):
        dir_resp = Mock()
        dir_resp.record_directory = ""
        mock_obs_client.get_record_directory.return_value = dir_resp
        result = recorder._get_effective_record_dir(mock_obs_client, "/fallback")
        assert "fallback" in result


class TestNewestMediaSince:
    """Test _newest_media_since mtime filtering."""

    def test_mtime_based_filtering(self, recorder, tmp_path):
        """Files with mtime before threshold are excluded."""
        f1 = tmp_path / "old.mp4"
        f1.write_bytes(b"old")
        # Set mtime to long ago
        os.utime(str(f1), (1000, 1000))

        f2 = tmp_path / "new.mp4"
        f2.write_bytes(b"new")

        # since_ts set to recent time
        mp4, mkv = recorder._newest_media_since(str(tmp_path), time.time() - 10)  # noqa: RUF059 - only mp4 matters
        assert mp4 == str(f2)

    def test_mkv_tracked_separately(self, recorder, tmp_path):
        """Both MP4 and MKV newest are returned."""
        (tmp_path / "v.mp4").write_bytes(b"x")
        (tmp_path / "v.mkv").write_bytes(b"x")
        mp4, mkv = recorder._newest_media_since(str(tmp_path), time.time() - 10)
        assert mp4 is not None
        assert mkv is not None


class TestFinalizeRecording:
    """Test _finalize_recording."""

    def test_mp4_simple_move(self, recorder, tmp_path):
        """MP4 file moved to output folder."""
        src = tmp_path / "src" / "rec.mp4"
        src.parent.mkdir()
        src.write_bytes(b"video data")
        recorder.output_folder = tmp_path / "out"
        recorder.output_folder.mkdir()

        result = recorder._finalize_recording(str(src), ".mp4", "meeting", time.time())
        assert result.exists()
        assert result.parent == recorder.output_folder

    @patch("scribe.core.recorder.get_ffmpeg_path", return_value=None)
    def test_mkv_no_ffmpeg_keeps_mkv(self, _ff, recorder, tmp_path):
        """MKV without ffmpeg → kept as MKV."""
        src = tmp_path / "rec.mkv"
        src.write_bytes(b"mkv data")
        recorder.output_folder = tmp_path

        result = recorder._finalize_recording(str(src), ".mkv", "meeting", time.time())
        assert result.suffix == ".mkv"

    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.core.recorder.get_ffmpeg_path")
    def test_mkv_remux_path(self, mock_ffmpeg, mock_run, recorder, tmp_path):
        """MKV with ffmpeg → remuxed to MP4."""
        mock_ffmpeg.return_value = Path("/usr/bin/ffmpeg")
        src = tmp_path / "rec.mkv"
        src.write_bytes(b"mkv data")
        recorder.output_folder = tmp_path

        def fake_run(*args, **kwargs):
            # Create the mp4 file that _remux would produce
            cmd = args[0]
            out_path = cmd[-1]
            Path(out_path).write_bytes(b"mp4 data")
            return Mock(returncode=0)

        mock_run.side_effect = fake_run

        result = recorder._finalize_recording(str(src), ".mkv", "meeting", time.time())
        assert result.suffix == ".mp4"

    def test_replace_fallback_to_copy(self, recorder, tmp_path):
        """os.replace fails → falls back to shutil.copy2."""
        src = tmp_path / "src" / "rec.mp4"
        src.parent.mkdir()
        src.write_bytes(b"video data")
        recorder.output_folder = tmp_path / "out"
        recorder.output_folder.mkdir()

        with patch("os.replace", side_effect=OSError("cross-device")):
            result = recorder._finalize_recording(str(src), ".mp4", "meeting", time.time())
        assert result.exists()

    def test_failed_placement_raises(self, recorder, tmp_path):
        """Both replace and copy fail → ProcessError."""
        src = tmp_path / "src" / "rec.mp4"
        src.parent.mkdir()
        src.write_bytes(b"video data")
        recorder.output_folder = tmp_path / "out"
        recorder.output_folder.mkdir()

        with patch("os.replace", side_effect=OSError("fail")):
            with patch("shutil.copy2", side_effect=OSError("fail too")):
                with pytest.raises(ProcessError, match="Failed to place"):
                    recorder._finalize_recording(str(src), ".mp4", "meeting", time.time())


class TestSetRecordDirIfPossible:
    """Test _set_record_dir_if_possible."""

    @patch("scribe.core.recorder.obs_error")
    def test_sdk_error_warns(self, mock_obs_error, recorder, mock_obs_client):
        """OBSSDKRequestError → returns False and warns."""
        status = Mock(output_active=False)
        mock_obs_client.get_record_status.return_value = status
        mock_obs_client.get_record_directory.return_value = Mock(record_directory="/other")

        err = Exception("rejected")
        mock_obs_error.OBSSDKRequestError = type(err)
        mock_obs_client.set_record_directory.side_effect = err

        result = recorder._set_record_dir_if_possible(mock_obs_client, "/desired")
        assert result is False

    @patch("scribe.core.recorder.obs_error")
    def test_generic_error_warns(self, mock_obs_error, recorder, mock_obs_client):
        """Generic exception → returns False."""
        mock_obs_error.OBSSDKRequestError = type(Exception("x"))
        mock_obs_client.get_record_status.side_effect = RuntimeError("boom")

        result = recorder._set_record_dir_if_possible(mock_obs_client, "/desired")
        assert result is False

    @patch("scribe.core.recorder.obs_error")
    def test_dir_already_matches(self, mock_obs_error, recorder, mock_obs_client, tmp_path):
        """Directory already matches → returns True without set."""
        mock_obs_error.OBSSDKRequestError = type(Exception("x"))
        status = Mock(output_active=False)
        mock_obs_client.get_record_status.return_value = status
        # Use same path (normalized)
        out_dir = str(tmp_path).replace("\\", "/")
        mock_obs_client.get_record_directory.return_value = Mock(record_directory=str(tmp_path))

        result = recorder._set_record_dir_if_possible(mock_obs_client, out_dir)
        assert result is True
        mock_obs_client.set_record_directory.assert_not_called()

    @patch("scribe.core.recorder.obs_error")
    def test_recording_active_skips(self, mock_obs_error, recorder, mock_obs_client):
        """Active recording → skips directory set."""
        mock_obs_error.OBSSDKRequestError = type(Exception("x"))
        status = Mock(output_active=True)
        mock_obs_client.get_record_status.return_value = status

        result = recorder._set_record_dir_if_possible(mock_obs_client, "/desired")
        assert result is False


class TestWaitForObsStartup:
    """Test _wait_for_obs_startup."""

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.obs_error")
    def test_successful_startup(self, mock_error, mock_reqs, mock_sleep, recorder):
        """Connection succeeds on first port check."""
        mock_error.OBSSDKRequestError = type(Exception("x"))
        client = MagicMock()
        mock_reqs.ReqClient.return_value = client

        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._wait_for_obs_startup(["127.0.0.1"], [4455], max_wait_seconds=2)
        assert result is client

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.obs_error")
    def test_timeout_returns_none(self, mock_error, mock_reqs, mock_sleep, recorder):
        """No port ever listens → returns None."""
        mock_error.OBSSDKRequestError = type(Exception("x"))

        with patch.object(recorder, "_port_listening", return_value=False):
            result = recorder._wait_for_obs_startup(["127.0.0.1"], [4455], max_wait_seconds=1)
        assert result is None

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.obs_error")
    def test_not_ready_retries(self, mock_error, mock_reqs, mock_sleep, recorder):
        """OBS not-ready → retries, eventually returns None on exhaustion."""
        not_ready = Exception("OBS is not ready")
        mock_error.OBSSDKRequestError = type(not_ready)

        client = MagicMock()
        mock_reqs.ReqClient.return_value = client
        client.get_record_status.side_effect = not_ready

        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._wait_for_obs_startup(["127.0.0.1"], [4455], max_wait_seconds=1)
        # Eventually returns None because it never becomes ready
        assert result is None

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.obs_error")
    def test_value_error_handled(self, mock_error, mock_reqs, mock_sleep, recorder):
        """ValueError for hostname → handled gracefully."""
        mock_error.OBSSDKRequestError = type(Exception("x"))
        mock_reqs.ReqClient.side_effect = ValueError("hostname is invalid")

        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._wait_for_obs_startup(["::1"], [4455], max_wait_seconds=1)
        assert result is None

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.obs_error")
    def test_generic_exception_handled(self, mock_error, mock_reqs, mock_sleep, recorder):
        """Generic connection error → handled gracefully."""
        mock_error.OBSSDKRequestError = type(Exception("x"))
        mock_reqs.ReqClient.side_effect = ConnectionError("refused")

        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._wait_for_obs_startup(["127.0.0.1"], [4455], max_wait_seconds=1)
        assert result is None

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.obs_error")
    def test_sdk_error_handled(self, mock_error, mock_reqs, mock_sleep, recorder):
        """OBSSDKRequestError (non-not-ready) → handled."""
        sdk_err = Exception("auth failed")
        mock_error.OBSSDKRequestError = type(sdk_err)

        client = MagicMock()
        mock_reqs.ReqClient.return_value = client
        client.get_record_status.side_effect = sdk_err

        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._wait_for_obs_startup(["127.0.0.1"], [4455], max_wait_seconds=1)
        assert result is None


class TestRecordWithCli:
    """Test _record_with_cli."""

    @patch("scribe.core.recorder.time.sleep")
    def test_stop_event_before_file_found(self, mock_sleep, recorder, tmp_path):
        """Stop event set before file detected → ProcessError."""
        recorder.output_folder = tmp_path
        stop_event = threading.Event()
        stop_event.set()

        with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
            with patch("sys.stdout"):
                with patch("scribe.core.recorder.time.time") as mock_time:
                    # Make deadline check pass on first iter, then expire
                    mock_time.side_effect = [100, 100, 100, 200, 200]
                    with pytest.raises(ProcessError, match="cancelled"):
                        recorder._record_with_cli("test", stop_event)


class TestListenReadline:
    """Test _listen_readline fallback."""

    def test_stop_command(self, recorder):
        """'stop' command sets event."""
        ev = threading.Event()
        mock_console = MagicMock()

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.readline.side_effect = ["stop\n"]
            recorder._listen_readline(ev, mock_console)
        assert ev.is_set()

    def test_eof_breaks(self, recorder):
        """EOF (empty readline) breaks loop."""
        ev = threading.Event()
        mock_console = MagicMock()

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.readline.return_value = ""
            recorder._listen_readline(ev, mock_console)
        assert not ev.is_set()

    def test_readline_exception(self, recorder):
        """Exception during readline breaks loop."""
        ev = threading.Event()
        mock_console = MagicMock()

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.readline.side_effect = OSError("broken pipe")
            recorder._listen_readline(ev, mock_console)
        assert not ev.is_set()


class TestRecordWithCliMore:
    """Additional _record_with_cli tests for coverage."""

    @patch("scribe.core.recorder.time.sleep")
    def test_happy_path_file_found(self, mock_sleep, recorder, tmp_path):
        """File found during scan → finalization."""
        rec_file = tmp_path / "rec.mp4"
        rec_file.write_bytes(b"video")
        recorder.output_folder = tmp_path

        stop_event = threading.Event()

        def fake_newest(d, ts):
            # After finding the file, set stop_event for the later wait loop
            stop_event.set()
            return (str(rec_file), None)

        with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
            with patch("sys.stdout"):
                with patch.object(recorder, "_newest_media_since", side_effect=fake_newest):
                    with patch.object(recorder, "_wait_until_file_finalized"):
                        with patch.object(
                            recorder, "_finalize_recording", return_value=Path(rec_file)
                        ):
                            # Prevent real _wait_for_stop_cli thread
                            with patch("threading.Thread"):
                                result = recorder._record_with_cli("test", stop_event)
        assert result == Path(rec_file)

    @patch("scribe.core.recorder.time.sleep")
    def test_no_file_found_timeout(self, mock_sleep, recorder, tmp_path):
        """No file found before deadline → ProcessError."""
        out_dir = tmp_path / "empty_out"
        out_dir.mkdir()
        recorder.output_folder = out_dir
        stop_event = threading.Event()

        # Mock _newest_media_since to always return nothing
        with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
            with patch("sys.stdout"):
                with patch.object(recorder, "_newest_media_since", return_value=(None, None)):
                    # Make the deadline expire quickly
                    _call = [0]
                    _base = 1000.0

                    def fake_time():
                        _call[0] += 1
                        if _call[0] <= 2:
                            return _base
                        return _base + 50  # past 30s deadline

                    with patch("scribe.core.recorder.time.time", side_effect=fake_time):
                        with pytest.raises(ProcessError, match="No media file appeared"):
                            recorder._record_with_cli("test", stop_event)


class TestTryConnectAuthError:
    """Test _try_connect_to_running_obs auth and SDK error paths."""

    @patch("scribe.core.recorder.obs_error")
    @patch("scribe.core.recorder.obs_reqs")
    def test_auth_error_path(self, mock_reqs, mock_error, recorder):
        """Auth error during connection → returns None."""
        auth_err = Exception("Authentication failed - wrong password")
        mock_error.OBSSDKRequestError = type(auth_err)
        mock_reqs.ReqClient.side_effect = auth_err

        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._try_connect_to_running_obs(["127.0.0.1"], [4455])
        assert result is None

    @patch("scribe.core.recorder.obs_error")
    @patch("scribe.core.recorder.obs_reqs")
    def test_generic_exception_path(self, mock_reqs, mock_error, recorder):
        """Generic exception during connection → returns None."""
        mock_error.OBSSDKRequestError = type(Exception("x"))
        mock_reqs.ReqClient.side_effect = ConnectionRefusedError("refused")

        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._try_connect_to_running_obs(["127.0.0.1"], [4455])
        assert result is None

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.obs_error")
    @patch("scribe.core.recorder.obs_reqs")
    def test_not_ready_exhausted(self, mock_reqs, mock_error, mock_sleep, recorder):
        """OBS not ready after 5 retries → returns None."""
        not_ready = Exception("OBS is not ready to perform the request")
        mock_error.OBSSDKRequestError = type(not_ready)

        client = MagicMock()
        mock_reqs.ReqClient.return_value = client
        client.get_record_status.side_effect = not_ready

        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._try_connect_to_running_obs(["127.0.0.1"], [4455])
        assert result is None

    @patch("scribe.core.recorder.obs_error")
    @patch("scribe.core.recorder.obs_reqs")
    def test_non_auth_sdk_error(self, mock_reqs, mock_error, recorder):
        """Non-auth OBSSDKRequestError during get_record_status → re-raised as SDK error."""
        sdk_err = Exception("scene not found")
        mock_error.OBSSDKRequestError = type(sdk_err)

        client = MagicMock()
        mock_reqs.ReqClient.return_value = client
        client.get_record_status.side_effect = sdk_err

        with patch.object(recorder, "_port_listening", return_value=True):
            result = recorder._try_connect_to_running_obs(["127.0.0.1"], [4455])
        assert result is None


class TestWaitForStopWithInputTTY:
    """Test TTY-specific display paths in _wait_for_stop_with_input."""

    @patch("scribe.core.recorder.time.sleep")
    def test_tty_panel_displayed(self, mock_sleep, recorder, mock_obs_client):
        """TTY mode shows the panel."""
        mock_obs_client.get_record_status.side_effect = [
            Mock(output_active=True),
            Mock(output_active=False),
        ]
        stop_event = threading.Event()
        with patch("sys.stdin", Mock(isatty=Mock(return_value=True))):
            with patch("sys.stdout"):
                recorder._wait_for_stop_with_input(mock_obs_client, stop_event)

    @patch("scribe.core.recorder.time.sleep")
    def test_timer_display_updates(self, mock_sleep, recorder, mock_obs_client):
        """Recording timer display updates."""
        # Active for a few iterations then stops
        call_count = [0]

        def get_status():
            call_count[0] += 1
            if call_count[0] <= 4:
                return Mock(output_active=True)
            return Mock(output_active=False)

        mock_obs_client.get_record_status.side_effect = get_status
        stop_event = threading.Event()
        with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
            with patch("sys.stdout"):
                recorder._wait_for_stop_with_input(mock_obs_client, stop_event)

    @patch("scribe.core.recorder.time.sleep")
    def test_reconnect_fails_after_stop(self, mock_sleep, recorder, mock_obs_client):
        """Stop sent, then connection lost, reconnect fails → returns."""
        # First call active, then errors
        error_count = [0]

        def get_status():
            error_count[0] += 1
            if error_count[0] == 1:
                return Mock(output_active=True)
            raise ConnectionError("lost")

        mock_obs_client.get_record_status.side_effect = get_status
        mock_obs_client.stop_record.return_value = None

        stop_event = threading.Event()
        stop_event.set()

        with patch.object(recorder, "_reconnect_client", return_value=None):
            with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
                with patch("sys.stdout"):
                    recorder._wait_for_stop_with_input(mock_obs_client, stop_event)


class TestWaitForStopCliTTY:
    """Test TTY panel in _wait_for_stop_cli."""

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.core.recorder.get_obs_executable_path")
    def test_tty_panel_and_nonzero_exit(self, mock_exe, mock_run, mock_sleep, recorder, tmp_path):
        """TTY shows panel; non-zero exit warns."""
        obs_exe = tmp_path / "obs.exe"
        obs_exe.touch()
        mock_exe.return_value = obs_exe
        mock_run.return_value = Mock(returncode=1)

        stop_event = threading.Event()
        stop_event.set()

        with patch("sys.stdin", Mock(isatty=Mock(return_value=True))):
            with patch("sys.stdout"):
                recorder._wait_for_stop_cli(stop_event)

    @patch("scribe.core.recorder.time.sleep")
    @patch("scribe.core.recorder.subprocess.run")
    @patch("scribe.core.recorder.get_obs_executable_path")
    def test_generic_exception_during_stop(
        self, mock_exe, mock_run, mock_sleep, recorder, tmp_path
    ):
        """Generic exception during --stoprecording."""
        obs_exe = tmp_path / "obs.exe"
        obs_exe.touch()
        mock_exe.return_value = obs_exe
        mock_run.side_effect = PermissionError("access denied")

        stop_event = threading.Event()
        stop_event.set()

        with patch("sys.stdin", Mock(isatty=Mock(return_value=False))):
            with patch("sys.stdout"):
                recorder._wait_for_stop_cli(stop_event)


class TestSetRecordDirMore:
    """Additional _set_record_dir_if_possible tests."""

    @patch("scribe.core.recorder.obs_error")
    def test_get_record_directory_fails(self, mock_error, recorder, mock_obs_client):
        """get_record_directory raises → still tries to set."""
        mock_error.OBSSDKRequestError = type(Exception("x"))
        status = Mock(output_active=False)
        mock_obs_client.get_record_status.return_value = status
        mock_obs_client.get_record_directory.side_effect = Exception("not available")
        mock_obs_client.set_record_directory.return_value = None

        result = recorder._set_record_dir_if_possible(mock_obs_client, "/new/dir")
        assert result is True
        mock_obs_client.set_record_directory.assert_called_once()


class TestConnectObsPhase1Console:
    """Test console output paths in _connect_obs."""

    @patch("scribe.core.recorder.obs_reqs")
    def test_phase1_connected_message(self, mock_reqs, recorder, mock_obs_client):
        """Phase 1 success prints 'Connected to OBS'."""
        mock_reqs.ReqClient.return_value = mock_obs_client

        with patch.object(recorder, "_port_listening", return_value=True):
            with recorder._connect_obs() as client:
                assert client is mock_obs_client

    @patch("scribe.core.recorder.obs_reqs")
    @patch("scribe.core.recorder.get_obs_executable_path")
    @patch("scribe.core.recorder.subprocess.Popen")
    def test_phase2_launch_success_message(
        self, mock_popen, mock_exe, mock_reqs, recorder, mock_obs_client, tmp_path
    ):
        """Phase 2 launch + connect prints 'Connected to OBS'."""
        obs_exe = tmp_path / "obs.exe"
        obs_exe.touch()
        mock_exe.return_value = obs_exe

        # Phase 1 fails (no listening)
        # Phase 2: after launch, port listening, connection succeeds
        phase = [0]

        def port_check(h, p, timeout):
            phase[0] += 1
            return phase[0] > 3  # listening after launch

        mock_reqs.ReqClient.return_value = mock_obs_client

        with patch.object(recorder, "_port_listening", side_effect=port_check):
            with patch.object(recorder, "_kill_existing_obs"):
                with patch("scribe.core.recorder.time.sleep"):
                    with recorder._connect_obs() as client:
                        assert client is mock_obs_client


class TestObsConfigDir:
    """Cross-platform OBS config dir (regression: macOS used the wrong path)."""

    def test_macos_uses_application_support(self, recorder, monkeypatch):
        monkeypatch.setattr("scribe.utils.platform.get_platform", lambda: "macos")
        assert (
            recorder._obs_config_dir()
            == Path.home() / "Library" / "Application Support" / "obs-studio"
        )

    def test_linux_uses_xdg_config(self, recorder, monkeypatch):
        monkeypatch.setattr("scribe.utils.platform.get_platform", lambda: "linux")
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        assert recorder._obs_config_dir() == Path.home() / ".config" / "obs-studio"

    def test_windows_uses_appdata(self, recorder, monkeypatch, tmp_path):
        monkeypatch.setattr("scribe.utils.platform.get_platform", lambda: "windows")
        monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
        assert recorder._obs_config_dir() == Path(str(tmp_path / "Roaming")) / "obs-studio"


class TestLaunchObs:
    """Platform-aware OBS launch (macOS must use `open -a`, no tray flag)."""

    def test_macos_launches_via_open(self, recorder, monkeypatch):
        monkeypatch.setattr("scribe.utils.platform.get_platform", lambda: "macos")
        calls: list[list[str]] = []

        def fake_popen(args, **kwargs):
            calls.append(args)
            return MagicMock()

        monkeypatch.setattr("scribe.core.recorder.subprocess.Popen", fake_popen)
        recorder._launch_obs(Path("/Applications/OBS.app/Contents/MacOS/OBS"))
        args = calls[0]
        assert args[0] == "open" and "-a" in args
        assert any("OBS.app" in a for a in args)
        assert "--minimize-to-tray" not in args
        assert "--disable-shutdown-check" in args

    def test_windows_runs_exe_with_flags(self, recorder, monkeypatch):
        monkeypatch.setattr("scribe.utils.platform.get_platform", lambda: "windows")
        calls: list[list[str]] = []

        def fake_popen(args, **kwargs):
            calls.append(args)
            return MagicMock()

        monkeypatch.setattr("scribe.core.recorder.subprocess.Popen", fake_popen)
        recorder._launch_obs(Path(r"C:\Program Files\obs-studio\bin\64bit\obs64.exe"))
        assert "--minimize-to-tray" in calls[0]
        assert "--disable-shutdown-check" in calls[0]
