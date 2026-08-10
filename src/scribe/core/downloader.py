"""
URL media downloader for Scribe.

Downloads audio/video from URLs (YouTube, Vimeo, direct links, etc.)
using yt-dlp, then passes the local file to the transcription pipeline.
"""

import contextlib
import logging
import shutil
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scribe.exceptions import DownloadError
from scribe.utils.network import safe_url_for_logs
from scribe.utils.validation import validate_media_url

logger = logging.getLogger(__name__)


@dataclass
class DownloadResult:
    """Result of a URL download operation."""

    file_path: Path
    title: str
    duration: float | None  # seconds, None if unknown
    source_url: str


class URLDownloader:
    """
    Download media from URLs using yt-dlp.

    Supports YouTube, Vimeo, Twitter/X, direct HTTP links,
    and 1000+ other sites via yt-dlp extractors.

    Args:
        output_dir: Directory to save downloads (default: temp dir)
        audio_only: Download audio stream only (saves bandwidth)
        timeout: Download timeout in seconds
        max_file_size_gb: Maximum allowed file size
        progress_callback: Called with (fraction: float) during download
    """

    def __init__(
        self,
        output_dir: Path | None = None,
        audio_only: bool = True,
        timeout: int = 600,
        max_file_size_gb: float = 25.0,
        progress_callback: Callable[[float], None] | None = None,
        cookies_from_browser: str | None = None,
    ):
        self.owns_output_dir = output_dir is None
        self.output_dir = output_dir or Path(tempfile.mkdtemp(prefix="scribe_dl_"))
        self.audio_only = audio_only
        self.timeout = timeout
        self.max_file_size_gb = max_file_size_gb
        self.progress_callback = progress_callback
        self.cookies_from_browser = cookies_from_browser
        self._download_started_at: float | None = None
        self._existing_paths: set[Path] = set()

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def download(self, url: str) -> DownloadResult:
        """
        Download media from a URL.

        Args:
            url: HTTP/HTTPS URL to download from

        Returns:
            DownloadResult with local file path and metadata

        Raises:
            DownloadError: If download fails for any reason
        """
        try:
            import yt_dlp  # type: ignore[import-untyped]
        except ImportError as e:
            raise DownloadError(
                "yt-dlp is required for URL downloads. Reinstall or update Scribe from its source.",
                context={"url": safe_url_for_logs(url)},
            ) from e

        validated_url = validate_media_url(url)
        safe_url = safe_url_for_logs(validated_url)
        logger.info("Downloading from URL: %s", safe_url)
        self._download_started_at = time.monotonic()
        self._existing_paths = {
            path.resolve() for path in self.output_dir.iterdir() if path.exists()
        }

        # Build yt-dlp options
        ydl_opts = self._build_options()

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                self._install_request_guard(ydl)
                # Extract info first to validate before downloading
                info = ydl.extract_info(validated_url, download=False)
                if info is None:
                    raise DownloadError(
                        "Could not extract media info from URL", context={"url": safe_url}
                    )

                title = info.get("title", "download")
                duration = info.get("duration")

                # Check duration limits (convert max_file_size to rough duration estimate)
                if duration and duration > 48 * 3600:
                    raise DownloadError(
                        f"Media too long ({duration / 3600:.1f} hours, max 48 hours)",
                        context={"url": safe_url, "duration_hours": duration / 3600},
                    )

                # Check estimated file size if available
                filesize = info.get("filesize") or info.get("filesize_approx")
                if filesize and filesize > self.max_file_size_gb * 1024**3:
                    size_gb = filesize / 1024**3
                    raise DownloadError(
                        f"File too large ({size_gb:.1f}GB, max {self.max_file_size_gb}GB)",
                        context={"url": safe_url, "size_gb": size_gb},
                    )

                logger.info(f"Downloading: {title} (duration: {duration}s)")

                # Download and get final info (includes post-processor file renames)
                final_info = ydl.extract_info(validated_url, download=True)

                # Find the downloaded file using final_info (has correct paths
                # after FFmpegExtractAudio postprocessor runs)
                downloaded_file = self._find_downloaded_file(final_info or info)

                if not downloaded_file or not downloaded_file.exists():
                    raise DownloadError(
                        "Download completed but output file not found",
                        context={"url": safe_url, "output_dir": str(self.output_dir)},
                    )

                actual_size = downloaded_file.stat().st_size
                if actual_size > self.max_bytes:
                    with contextlib.suppress(OSError):
                        downloaded_file.unlink()
                    raise DownloadError(
                        "Downloaded file exceeds the configured size limit",
                        context={"url": safe_url, "size_bytes": actual_size},
                    )

                logger.info(f"Downloaded to: {downloaded_file}")

                return DownloadResult(
                    file_path=downloaded_file,
                    title=title,
                    duration=duration,
                    source_url=validated_url,
                )

        except DownloadError:
            raise
        except Exception as e:
            error_msg = str(e)
            # Provide user-friendly messages for common errors
            if "is not a valid URL" in error_msg or "Unsupported URL" in error_msg:
                raise DownloadError(
                    f"URL not supported: {safe_url}", context={"url": safe_url}
                ) from e
            if "Video unavailable" in error_msg or "Private video" in error_msg:
                raise DownloadError(
                    "Video is unavailable or private", context={"url": safe_url}
                ) from e
            if "Sign in" in error_msg or "age" in error_msg.lower():
                raise DownloadError(
                    "Video requires authentication or is age-restricted"
                    "\nTry: scribe url <link> --cookies edge",
                    context={"url": safe_url},
                ) from e
            if "403" in error_msg or "Forbidden" in error_msg:
                hint = (
                    "\nUpdate Scribe from its source to refresh yt-dlp"
                    "\n  or: scribe url <link> --cookies edge"
                )
                raise DownloadError(
                    f"Download blocked (HTTP 403). YouTube may require browser cookies.{hint}",
                    context={"url": safe_url},
                ) from e
            raise DownloadError("Download failed", context={"url": safe_url}) from e

    @property
    def max_bytes(self) -> int:
        """Return the configured download ceiling in bytes."""
        return int(self.max_file_size_gb * 1024**3)

    def _install_request_guard(self, ydl: Any) -> None:
        """Validate yt-dlp request targets before each outbound request."""
        original_urlopen = getattr(ydl, "urlopen", None)
        if not callable(original_urlopen):
            return

        def guarded_urlopen(request: Any) -> Any:
            request_url = (
                request
                if isinstance(request, str)
                else getattr(request, "url", None) or getattr(request, "full_url", None)
            )
            if request_url:
                validate_media_url(str(request_url))
            response = original_urlopen(request)
            final_url = getattr(response, "url", None)
            if final_url is None and callable(getattr(response, "geturl", None)):
                final_url = response.geturl()
            if final_url:
                validate_media_url(str(final_url))
            return response

        ydl.urlopen = guarded_urlopen

    def _build_options(self) -> dict[str, Any]:
        """Build yt-dlp options dict."""
        opts: dict[str, Any] = {
            "outtmpl": str(self.output_dir / "%(title).100s.%(ext)s"),
            "socket_timeout": self.timeout,
            "max_filesize": self.max_bytes,
            "retries": 10,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "noplaylist": True,  # Single videos only
            "restrictfilenames": True,
            "http_headers": {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            },
        }

        if self.cookies_from_browser:
            opts["cookiesfrombrowser"] = (self.cookies_from_browser,)

        if self.audio_only:
            # Download best audio only and let Scribe's converter normalize format later.
            # Avoiding yt-dlp FFmpegExtractAudio here prevents Windows postprocess
            # path edge cases ("Error opening output files").
            opts["format"] = "bestaudio/best"
        else:
            # Download best quality with audio
            opts["format"] = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

        # The hook enforces byte and elapsed-time limits even without a UI callback.
        opts["progress_hooks"] = [self._progress_hook]
        if self.progress_callback:
            opts["noprogress"] = False

        return opts

    def _progress_hook(self, d: dict[str, Any]) -> None:
        """yt-dlp progress hook - translates to our callback."""
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = int(d.get("downloaded_bytes", 0) or 0)
            if downloaded > self.max_bytes:
                raise DownloadError("Download exceeded the configured size limit")
            if (
                self._download_started_at is not None
                and time.monotonic() - self._download_started_at > self.timeout
            ):
                raise DownloadError("Download exceeded the configured time limit")
            if self.progress_callback and total and total > 0:
                self.progress_callback(min(downloaded / total, 1.0))
        elif d.get("status") == "finished" and self.progress_callback:
            self.progress_callback(1.0)

    def _find_downloaded_file(self, info: dict[str, Any]) -> Path | None:
        """Find the actual downloaded file on disk."""
        # yt-dlp prepares the filename - use it directly
        if info.get("requested_downloads"):
            for download in info["requested_downloads"]:
                filepath = download.get("filepath")
                if filepath:
                    path = self._contained_file(Path(filepath))
                    if path is not None:
                        return path

        # Fallback: search output_dir for recently created files
        def _safe_mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return 0.0

        candidates = sorted(
            self.output_dir.iterdir(),
            key=_safe_mtime,
            reverse=True,
        )
        for candidate in candidates:
            if (
                candidate.resolve() not in self._existing_paths
                and candidate.is_file()
                and candidate.suffix.lower()
                in (
                    ".wav",
                    ".mp3",
                    ".m4a",
                    ".mp4",
                    ".mkv",
                    ".webm",
                    ".ogg",
                    ".opus",
                    ".flac",
                )
            ):
                return candidate

        return None

    def _contained_file(self, candidate: Path) -> Path | None:
        """Return a regular candidate only when it stays below output_dir."""
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self.output_dir.resolve(strict=True))
        except (OSError, ValueError):
            return None
        return resolved if resolved.is_file() else None

    def cleanup_owned_output_dir(self) -> None:
        """Remove only the exact temporary directory created by this instance."""
        if not self.owns_output_dir or not self.output_dir.exists():
            return
        resolved = self.output_dir.resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        if resolved.parent != temp_root or not resolved.name.startswith("scribe_dl_"):
            raise DownloadError("Refusing to remove an unowned download directory")
        shutil.rmtree(resolved)
