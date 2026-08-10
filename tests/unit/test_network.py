"""Tests for the shared outbound URL and bounded image policy."""

import socket
from unittest.mock import patch

import httpx
import pytest

from scribe.utils.network import (
    OutboundURLPolicyError,
    download_public_image,
    safe_url_for_logs,
    validate_public_url,
)


def _public_dns(_host, port, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]


def test_safe_url_for_logs_removes_path_query_fragment_and_credentials():
    value = "https://user:password@example.com:8443/private?token=secret#fragment"
    assert safe_url_for_logs(value) == "https://example.com:8443"
    assert "secret" not in safe_url_for_logs(value)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.1/image.png",
        "https://127.0.0.1/image.png",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/image.png",
        "file:///etc/passwd",
        "https://user:password@example.com/image.png",
    ],
)
def test_validate_public_url_rejects_non_public_targets(url):
    with pytest.raises(OutboundURLPolicyError):
        validate_public_url(url)


def test_validate_public_url_rejects_public_name_resolving_privately(monkeypatch):
    def private_dns(_host, port, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.7", port))]

    monkeypatch.setattr("scribe.utils.network.socket.getaddrinfo", private_dns)
    with pytest.raises(OutboundURLPolicyError, match="non-public"):
        validate_public_url("https://example.com/image.png")


def test_download_public_image_streams_a_valid_bounded_image(monkeypatch):
    monkeypatch.setattr("scribe.utils.network.socket.getaddrinfo", _public_dns)
    image = b"\x89PNG\r\n\x1a\n" + b"content"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-type": "image/png", "content-length": str(len(image))},
            content=image,
            request=request,
        )
    )
    client = httpx.Client(transport=transport)
    with patch("scribe.utils.network.httpx.Client", return_value=client):
        assert download_public_image("https://example.com/image.png") == image


def test_download_public_image_rejects_actual_bytes_over_limit(monkeypatch):
    monkeypatch.setattr("scribe.utils.network.socket.getaddrinfo", _public_dns)
    image = b"\x89PNG\r\n\x1a\n" + b"content"
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=image, request=request)
    )
    client = httpx.Client(transport=transport)
    with (
        patch("scribe.utils.network.httpx.Client", return_value=client),
        pytest.raises(OutboundURLPolicyError, match="size limit"),
    ):
        download_public_image("https://example.com/image.png", max_bytes=8)


def test_download_public_image_revalidates_redirect(monkeypatch):
    monkeypatch.setattr("scribe.utils.network.socket.getaddrinfo", _public_dns)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            302, headers={"location": "https://127.0.0.1/private.png"}, request=request
        )
    )
    client = httpx.Client(transport=transport)
    with (
        patch("scribe.utils.network.httpx.Client", return_value=client),
        pytest.raises(OutboundURLPolicyError),
    ):
        download_public_image("https://example.com/image.png")
