"""
Unit tests for URL downloader module.

Tests download logic, error handling, progress callbacks, and cleanup
using mocked yt-dlp to avoid network calls.
"""

from unittest.mock import MagicMock, patch

import pytest

from scribe.core.downloader import DownloadResult, URLDownloader
from scribe.exceptions import DownloadError


class TestDownloadResult:
    """Test DownloadResult dataclass."""

    def test_creation(self, tmp_path):
        result = DownloadResult(
            file_path=tmp_path / "video.wav",
            title="Test Video",
            duration=120.0,
            source_url="https://youtube.com/watch?v=abc123",
        )
        assert result.title == "Test Video"
        assert result.duration == 120.0
        assert result.source_url == "https://youtube.com/watch?v=abc123"

    def test_none_duration(self, tmp_path):
        result = DownloadResult(
            file_path=tmp_path / "video.wav",
            title="Test",
            duration=None,
            source_url="https://example.com/audio.mp3",
        )
        assert result.duration is None


class TestURLDownloader:
    """Test URLDownloader class."""

    def test_init_defaults(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path)
        assert dl.audio_only is True
        assert dl.timeout == 600
        assert dl.max_file_size_gb == 25.0
        assert dl.output_dir == tmp_path
        assert dl.cookies_from_browser is None

    def test_init_custom_options(self, tmp_path):
        dl = URLDownloader(
            output_dir=tmp_path,
            audio_only=False,
            timeout=120,
            max_file_size_gb=5.0,
            cookies_from_browser="edge",
        )
        assert dl.audio_only is False
        assert dl.timeout == 120
        assert dl.max_file_size_gb == 5.0
        assert dl.cookies_from_browser == "edge"

    def test_init_creates_output_dir(self, tmp_path):
        new_dir = tmp_path / "downloads" / "nested"
        URLDownloader(output_dir=new_dir)
        assert new_dir.exists()

    def test_init_temp_dir_when_none(self):
        dl = URLDownloader(output_dir=None)
        assert dl.output_dir.exists()
        assert "scribe_dl_" in str(dl.output_dir)

    @patch("scribe.core.downloader.yt_dlp", create=True)
    def test_download_success(self, _mock_yt_dlp_module, tmp_path):
        """Test successful download flow."""
        # Create a fake downloaded file
        fake_file = tmp_path / "Test_Video.wav"
        fake_file.write_text("fake audio data")

        info = {
            "title": "Test Video",
            "duration": 180,
            "requested_downloads": [{"filepath": str(fake_file)}],
        }

        # Mock yt-dlp — extract_info called twice: once dry-run, once with download
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = info
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            dl = URLDownloader(output_dir=tmp_path)
            result = dl.download("https://youtube.com/watch?v=abc123")

        assert result.title == "Test Video"
        assert result.duration == 180
        assert result.file_path == fake_file
        assert result.source_url == "https://youtube.com/watch?v=abc123"

    @patch("scribe.core.downloader.yt_dlp", create=True)
    def test_download_no_info_raises(self, _mock_yt_dlp_module, tmp_path):
        """Test that None info raises DownloadError."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = None
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            dl = URLDownloader(output_dir=tmp_path)
            with pytest.raises(DownloadError, match="Could not extract media info"):
                dl.download("https://example.com/bad")

    @patch("scribe.core.downloader.yt_dlp", create=True)
    def test_download_too_long_raises(self, _mock_yt_dlp_module, tmp_path):
        """Test that overly long media is rejected."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {
            "title": "Super Long Video",
            "duration": 200_000,  # >48 hours
        }
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            dl = URLDownloader(output_dir=tmp_path)
            with pytest.raises(DownloadError, match="too long"):
                dl.download("https://example.com/long")

    @patch("scribe.core.downloader.yt_dlp", create=True)
    def test_download_too_large_raises(self, _mock_yt_dlp_module, tmp_path):
        """Test that oversized files are rejected."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.return_value = {
            "title": "Huge Video",
            "duration": 60,
            "filesize": 30 * 1024**3,  # 30 GB
        }
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            dl = URLDownloader(output_dir=tmp_path, max_file_size_gb=25.0)
            with pytest.raises(DownloadError, match="too large"):
                dl.download("https://example.com/huge")

    def test_download_no_ytdlp_raises(self, tmp_path):
        """Test that missing yt-dlp gives a clear error."""
        dl = URLDownloader(output_dir=tmp_path)
        with (
            patch.dict("sys.modules", {"yt_dlp": None}),
            pytest.raises(DownloadError, match="yt-dlp is required"),
        ):
            dl.download("https://youtube.com/watch?v=abc")

    @patch("scribe.core.downloader.yt_dlp", create=True)
    def test_download_unsupported_url(self, _mock_yt_dlp_module, tmp_path):
        """Test unsupported URL error handling."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = Exception("Unsupported URL: https://bad.example")
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            dl = URLDownloader(output_dir=tmp_path)
            with pytest.raises(DownloadError, match="URL not supported"):
                dl.download("https://bad.example/page")

    @patch("scribe.core.downloader.yt_dlp", create=True)
    def test_download_private_video(self, _mock_yt_dlp_module, tmp_path):
        """Test private video error handling."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = Exception(
            "Private video. Sign in if you've been granted access."
        )
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            dl = URLDownloader(output_dir=tmp_path)
            with pytest.raises(DownloadError, match="unavailable or private"):
                dl.download("https://youtube.com/watch?v=private")

    @patch("scribe.core.downloader.yt_dlp", create=True)
    def test_download_age_restricted(self, _mock_yt_dlp_module, tmp_path):
        """Test age-restricted video error handling."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = Exception("Sign in to confirm your age")
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            dl = URLDownloader(output_dir=tmp_path)
            with pytest.raises(DownloadError, match="authentication or is age-restricted"):
                dl.download("https://youtube.com/watch?v=age")

    @patch("scribe.core.downloader.yt_dlp", create=True)
    def test_download_403_forbidden(self, _mock_yt_dlp_module, tmp_path):
        """Test HTTP 403 Forbidden gives actionable error message."""
        mock_ydl = MagicMock()
        mock_ydl.extract_info.side_effect = Exception("HTTP Error 403: Forbidden")
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)

        with patch("yt_dlp.YoutubeDL", return_value=mock_ydl):
            dl = URLDownloader(output_dir=tmp_path)
            with pytest.raises(DownloadError, match="403.*cookies"):
                dl.download("https://youtube.com/watch?v=blocked")


class TestURLDownloaderOptions:
    """Test yt-dlp option building."""

    def test_audio_only_options(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path, audio_only=True)
        opts = dl._build_options()
        assert opts["format"] == "bestaudio/best"
        assert "postprocessors" not in opts

    def test_video_options(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path, audio_only=False)
        opts = dl._build_options()
        assert "bestvideo" in opts["format"]
        assert "postprocessors" not in opts

    def test_noplaylist(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path)
        opts = dl._build_options()
        assert opts["noplaylist"] is True

    def test_timeout_in_options(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path, timeout=120)
        opts = dl._build_options()
        assert opts["socket_timeout"] == 120

    def test_progress_callback_wired(self, tmp_path):
        callback = MagicMock()
        dl = URLDownloader(output_dir=tmp_path, progress_callback=callback)
        opts = dl._build_options()
        assert "progress_hooks" in opts
        assert len(opts["progress_hooks"]) == 1

    def test_no_progress_callback(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path)
        opts = dl._build_options()
        assert "progress_hooks" not in opts

    def test_retries_increased(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path)
        opts = dl._build_options()
        assert opts["retries"] == 10
        assert opts["fragment_retries"] == 10

    def test_user_agent_set(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path)
        opts = dl._build_options()
        assert "User-Agent" in opts["http_headers"]
        assert "Mozilla" in opts["http_headers"]["User-Agent"]

    def test_cookies_from_browser_option(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path, cookies_from_browser="edge")
        opts = dl._build_options()
        assert opts["cookiesfrombrowser"] == ("edge",)

    def test_no_cookies_by_default(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path)
        opts = dl._build_options()
        assert "cookiesfrombrowser" not in opts


class TestProgressHook:
    """Test yt-dlp progress hook translation."""

    def test_downloading_progress(self, tmp_path):
        callback = MagicMock()
        dl = URLDownloader(output_dir=tmp_path, progress_callback=callback)

        dl._progress_hook(
            {
                "status": "downloading",
                "total_bytes": 1000,
                "downloaded_bytes": 500,
            }
        )
        callback.assert_called_once_with(0.5)

    def test_downloading_with_estimate(self, tmp_path):
        callback = MagicMock()
        dl = URLDownloader(output_dir=tmp_path, progress_callback=callback)

        dl._progress_hook(
            {
                "status": "downloading",
                "total_bytes_estimate": 2000,
                "downloaded_bytes": 1000,
            }
        )
        callback.assert_called_once_with(0.5)

    def test_finished_status(self, tmp_path):
        callback = MagicMock()
        dl = URLDownloader(output_dir=tmp_path, progress_callback=callback)

        dl._progress_hook({"status": "finished"})
        callback.assert_called_once_with(1.0)

    def test_no_callback_is_noop(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path)
        # Should not raise
        dl._progress_hook({"status": "downloading", "total_bytes": 100, "downloaded_bytes": 50})

    def test_unknown_total_no_crash(self, tmp_path):
        callback = MagicMock()
        dl = URLDownloader(output_dir=tmp_path, progress_callback=callback)

        dl._progress_hook(
            {
                "status": "downloading",
                "downloaded_bytes": 500,
            }
        )
        callback.assert_not_called()


class TestFindDownloadedFile:
    """Test file discovery after download."""

    def test_find_from_requested_downloads(self, tmp_path):
        fake_file = tmp_path / "video.wav"
        fake_file.write_text("data")

        dl = URLDownloader(output_dir=tmp_path)
        info = {"requested_downloads": [{"filepath": str(fake_file)}]}

        result = dl._find_downloaded_file(info)
        assert result == fake_file

    def test_fallback_to_directory_scan(self, tmp_path):
        fake_file = tmp_path / "downloaded.mp3"
        fake_file.write_text("data")

        dl = URLDownloader(output_dir=tmp_path)
        info = {}  # No requested_downloads

        result = dl._find_downloaded_file(info)
        assert result == fake_file

    def test_ignores_non_media_files(self, tmp_path):
        txt_file = tmp_path / "readme.txt"
        txt_file.write_text("not media")

        dl = URLDownloader(output_dir=tmp_path)
        result = dl._find_downloaded_file({})
        assert result is None

    def test_returns_none_when_empty(self, tmp_path):
        dl = URLDownloader(output_dir=tmp_path)
        result = dl._find_downloaded_file({})
        assert result is None


class TestDownloadErrorException:
    """Test DownloadError exception."""

    def test_basic_download_error(self):
        error = DownloadError("Download failed")
        assert str(error) == "Download failed"
        assert isinstance(error, DownloadError)

    def test_download_error_with_context(self):
        error = DownloadError(
            "Video unavailable", context={"url": "https://example.com", "reason": "private"}
        )
        assert "Video unavailable" in str(error)
        assert error.context["url"] == "https://example.com"

    def test_download_error_is_scribe_error(self):
        from scribe.exceptions import ScribeError

        error = DownloadError("test")
        assert isinstance(error, ScribeError)


class TestMediaUrlValidation:
    """Test validate_media_url function."""

    def test_valid_youtube_url(self):
        from scribe.utils.validation import validate_media_url

        url = validate_media_url("https://www.youtube.com/watch?v=abc123")
        assert url == "https://www.youtube.com/watch?v=abc123"

    def test_valid_direct_link(self):
        from scribe.utils.validation import validate_media_url

        url = validate_media_url("https://example.com/audio.mp3")
        assert url == "https://example.com/audio.mp3"

    def test_empty_url_raises(self):
        from scribe.exceptions import ValidationError
        from scribe.utils.validation import validate_media_url

        with pytest.raises(ValidationError):
            validate_media_url("")

    def test_invalid_format_raises(self):
        from scribe.exceptions import ValidationError
        from scribe.utils.validation import validate_media_url

        with pytest.raises(ValidationError):
            validate_media_url("not-a-url")

    def test_http_url_accepted(self):
        from scribe.utils.validation import validate_media_url

        url = validate_media_url("http://example.com/video.mp4")
        assert url.startswith("http://")
