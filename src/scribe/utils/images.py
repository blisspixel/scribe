"""Decode provider image bytes before Scribe draws on them or sends them on.

Provider and user image bytes are untrusted. Pillow 13 is the required decoder.
This helper still refuses formats the meme and vision paths do not accept, and
it refuses multi-frame images so a later draw cannot follow a mode switch.
"""

from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

_ACCEPTED_FORMATS = frozenset({"PNG", "JPEG", "WEBP"})
_MAX_PROVIDER_IMAGE_BYTES = 32 * 1024 * 1024


def open_provider_image(image_bytes: bytes) -> Image.Image:
    """Return a decoded single-frame PNG, JPEG, or WebP.

    Raises:
        ValueError: The bytes are empty, too large, not an accepted image, or
            cannot be decoded. The message does not include the image bytes.
    """

    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError("Provider image must be non-empty bytes")
    if len(image_bytes) > _MAX_PROVIDER_IMAGE_BYTES:
        raise ValueError("Provider image is larger than 32 MiB")

    try:
        opened = Image.open(io.BytesIO(image_bytes))
    except UnidentifiedImageError as exc:
        raise ValueError("Provider image could not be decoded") from exc

    with opened as image:
        image_format = image.format
        if image_format not in _ACCEPTED_FORMATS:
            raise ValueError(
                "Provider image format "
                f"{image_format or 'unknown'} is not supported. "
                "Use a single-frame PNG, JPEG, or WebP."
            )
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Provider image must be a single frame")
        try:
            image.load()
        except OSError as exc:
            raise ValueError("Provider image could not be decoded") from exc
        return image.copy()
