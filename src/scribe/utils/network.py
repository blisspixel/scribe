"""Shared outbound-network policy for untrusted URLs."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

import httpx

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_REDIRECTS = 5


class OutboundURLPolicyError(ValueError):
    """Raised when an outbound URL violates Scribe's public-network policy."""


def safe_url_for_logs(url: str) -> str:
    """Return only a URL's scheme and authority for logs and error context."""
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname or "invalid-host"
        port = parsed.port
    except (TypeError, ValueError):
        return "invalid-url"
    if scheme not in {"http", "https"}:
        return "invalid-url"
    authority = f"[{host}]" if ":" in host else host
    if port is not None:
        authority = f"{authority}:{port}"
    return f"{scheme}://{authority}"


def _reject_non_public_addresses(addresses: Iterable[str]) -> None:
    seen = False
    for address in addresses:
        seen = True
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as error:
            raise OutboundURLPolicyError("URL host resolved to an invalid address") from error
        if not ip.is_global:
            raise OutboundURLPolicyError("URL host resolves to a non-public network")
    if not seen:
        raise OutboundURLPolicyError("URL host did not resolve to an address")


def validate_public_url(
    url: str,
    *,
    allowed_schemes: frozenset[str] = frozenset({"https"}),
    resolve_dns: bool = True,
) -> str:
    """Validate an outbound URL and reject local or non-public destinations."""
    if not url or not url.strip():
        raise OutboundURLPolicyError("URL cannot be empty")
    value = url.strip()
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as error:
        raise OutboundURLPolicyError("URL has an invalid authority") from error

    scheme = parsed.scheme.lower()
    if scheme not in allowed_schemes:
        schemes = ", ".join(sorted(allowed_schemes))
        raise OutboundURLPolicyError(f"URL must use one of these schemes: {schemes}")
    if parsed.username or parsed.password:
        raise OutboundURLPolicyError("URLs containing credentials are not allowed")

    host = parsed.hostname
    if not host:
        raise OutboundURLPolicyError("URL must include a hostname")
    normalized_host = host.lower().rstrip(".")
    if (
        normalized_host == "localhost"
        or normalized_host.endswith((".localhost", ".local", ".internal"))
        or "." not in normalized_host
    ):
        raise OutboundURLPolicyError("URL points to a local or internal host")

    try:
        literal = ipaddress.ip_address(normalized_host)
    except ValueError:
        literal = None
    if literal is not None:
        _reject_non_public_addresses([str(literal)])
    elif resolve_dns:
        try:
            records = socket.getaddrinfo(
                normalized_host,
                port or (443 if scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except OSError as error:
            raise OutboundURLPolicyError("URL hostname could not be resolved") from error
        _reject_non_public_addresses(str(record[4][0]) for record in records)

    return value


def _looks_like_image(data: bytes) -> bool:
    return (
        data.startswith(b"\x89PNG\r\n\x1a\n")
        or data.startswith(b"\xff\xd8\xff")
        or data.startswith((b"GIF87a", b"GIF89a"))
        or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    )


def download_public_image(
    url: str,
    *,
    timeout: float = 30.0,
    max_bytes: int = MAX_IMAGE_BYTES,
) -> bytes:
    """Download a bounded image while validating every redirect destination."""
    current_url = validate_public_url(url)
    timeout_config = httpx.Timeout(timeout, connect=min(timeout, 10.0))

    with httpx.Client(follow_redirects=False, timeout=timeout_config, trust_env=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            with client.stream(
                "GET", current_url, headers={"Accept": "image/*,application/octet-stream"}
            ) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise OutboundURLPolicyError("Image redirect did not include a location")
                    current_url = validate_public_url(urljoin(current_url, location))
                    continue

                response.raise_for_status()
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                if content_type and not (
                    content_type.startswith("image/") or content_type == "application/octet-stream"
                ):
                    raise OutboundURLPolicyError("Image response has an unexpected content type")

                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        declared_size = int(content_length)
                    except ValueError as error:
                        raise OutboundURLPolicyError(
                            "Image response has an invalid content length"
                        ) from error
                    if declared_size > max_bytes:
                        raise OutboundURLPolicyError("Image response exceeds the size limit")

                chunks: list[bytes] = []
                total = 0
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise OutboundURLPolicyError("Image response exceeds the size limit")
                    chunks.append(chunk)
                data = b"".join(chunks)
                if not data or not _looks_like_image(data):
                    raise OutboundURLPolicyError(
                        "Image response is empty or has an invalid signature"
                    )
                return data

    raise OutboundURLPolicyError("Image response exceeded the redirect limit")
