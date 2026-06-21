"""Tests for voice setup download hygiene."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from rich.console import Console

from scribe.voice.setup import _download_file


def test_download_file_rejects_incomplete_payload(tmp_path: Path) -> None:
    """Truncated HTTP bodies must not be promoted to the final asset path."""
    dest = tmp_path / "model.bin"
    console = Console(record=True)

    class FakeResponse:
        def __init__(self) -> None:
            self.headers = {"Content-Length": "100"}

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self, chunk_size: int = 0):
            yield b"short"

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    with patch("httpx.stream", return_value=FakeResponse()):
        with pytest.raises(OSError, match="incomplete download"):
            _download_file("https://example.com/model.bin", dest, console, "model.bin")

    assert not dest.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_download_file_wraps_http_errors(tmp_path: Path) -> None:
    dest = tmp_path / "voices.bin"
    console = Console(record=True)

    def raise_http_error(*_args: object, **_kwargs: object):
        raise httpx.ConnectError("offline", request=MagicMock())

    with patch("httpx.stream", side_effect=raise_http_error):
        with pytest.raises(OSError, match="download failed"):
            _download_file("https://example.com/voices.bin", dest, console, "voices.bin")

    assert not dest.exists()
    assert list(tmp_path.glob("*.part")) == []
