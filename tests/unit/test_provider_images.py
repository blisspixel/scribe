"""Provider image decoding stays on the patched Pillow formats."""

import io
from unittest.mock import patch

import pytest
from PIL import Image

from scribe.utils.images import open_provider_image
from scribe.utils.meme_compositor import MemeCompositor


def _encoded(image_format: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 4), "white").save(buffer, format=image_format)
    return buffer.getvalue()


def test_open_provider_image_accepts_png_jpeg_and_webp():
    for image_format in ("PNG", "JPEG", "WEBP"):
        image = open_provider_image(_encoded(image_format))
        assert image.size == (8, 4)
        assert image.mode == "RGB"


def test_open_provider_image_rejects_empty_oversized_malformed_and_other_formats():
    with pytest.raises(ValueError, match="non-empty bytes"):
        open_provider_image(b"")
    with pytest.raises(ValueError, match="non-empty bytes"):
        open_provider_image(bytearray(b"png"))  # type: ignore[arg-type]

    with (
        patch("scribe.utils.images._MAX_PROVIDER_IMAGE_BYTES", 4),
        pytest.raises(ValueError, match="32 MiB"),
    ):
        open_provider_image(b"12345")

    with pytest.raises(ValueError, match="could not be decoded"):
        open_provider_image(b"not an image")

    with pytest.raises(ValueError, match="not supported"):
        open_provider_image(_encoded("GIF"))

    frames = [Image.new("RGB", (1, 1), "red"), Image.new("RGB", (1, 1), "blue")]
    animated = io.BytesIO()
    frames[0].save(
        animated,
        format="WEBP",
        save_all=True,
        append_images=frames[1:],
        duration=100,
        loop=0,
    )
    with pytest.raises(ValueError, match="single frame"):
        open_provider_image(animated.getvalue())


def test_compositor_draws_on_a_decoded_provider_image():
    buffer = io.BytesIO()
    Image.new("RGB", (80, 40), "white").save(buffer, format="PNG")
    image = open_provider_image(buffer.getvalue())
    result = MemeCompositor().overlay_text(image, top_text="hello", bottom_text="notes")

    assert result.size == image.size
    assert result is not image
