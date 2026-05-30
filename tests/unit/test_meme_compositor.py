from unittest.mock import Mock, patch

import pytest

from scribe.utils import meme_compositor
from scribe.utils.meme_compositor import MemeCompositor


def test_meme_compositor_initializes_platform_font_paths():
    with (
        patch("platform.system", return_value="Windows"),
        patch("pathlib.Path.exists", return_value=False),
    ):
        compositor = MemeCompositor()

    assert compositor.font_path is None


@pytest.mark.requires_pillow
def test_overlay_text_draws_top_and_bottom_captions():
    image = Mock()
    image.copy.return_value = Mock(size=(800, 600))
    draw = Mock()
    font = Mock()

    with (
        patch.object(MemeCompositor, "_ensure_pillow_available"),
        patch.object(meme_compositor.ImageDraw, "Draw", return_value=draw),
        patch.object(meme_compositor.ImageFont, "truetype", return_value=font),
        patch.object(MemeCompositor, "_draw_caption") as mock_draw_caption,
    ):
        compositor = MemeCompositor(font_path="impact.ttf")
        result = compositor.overlay_text(image, top_text="top", bottom_text="bottom")

    assert result is image.copy.return_value
    assert mock_draw_caption.call_count == 2
    top_call = mock_draw_caption.call_args_list[0]
    bottom_call = mock_draw_caption.call_args_list[1]
    assert top_call.kwargs["position"] == "top"
    assert bottom_call.kwargs["position"] == "bottom"


@pytest.mark.requires_pillow
def test_overlay_text_falls_back_to_default_font_when_truetype_fails():
    image = Mock()
    image.copy.return_value = Mock(size=(400, 400))

    with (
        patch.object(MemeCompositor, "_ensure_pillow_available"),
        patch.object(meme_compositor.ImageDraw, "Draw", return_value=Mock()),
        patch.object(meme_compositor.ImageFont, "truetype", side_effect=OSError("missing")),
        patch.object(
            meme_compositor.ImageFont, "load_default", return_value=Mock()
        ) as mock_load_default,
        patch.object(MemeCompositor, "_draw_caption"),
    ):
        MemeCompositor(font_path="missing.ttf").overlay_text(image, top_text="only top")

    mock_load_default.assert_called_once_with()


def test_draw_caption_wraps_lines_and_uses_fallback_width_calculation():
    draw = Mock()
    font = Mock()
    font.getbbox.side_effect = lambda line: (0, 0, len(line) * 10, 30)

    compositor = MemeCompositor()
    compositor._draw_caption(
        draw,
        font,
        "THIS IS A LONG CAPTION THAT SHOULD WRAP",
        width=220,
        height=200,
        position="bottom",
        base_font_size=40,
    )

    assert draw.text.call_count >= 2
    for call in draw.text.call_args_list:
        assert call.kwargs["fill"] == "white"
        assert call.kwargs["stroke_fill"] == "black"


def test_ensure_pillow_available_requires_optional_dependency():
    with (
        patch.object(meme_compositor, "Image", None),
        patch.object(meme_compositor, "ImageDraw", None),
        patch.object(meme_compositor, "ImageFont", None),
    ):
        with pytest.raises(RuntimeError, match="Pillow is required"):
            MemeCompositor._ensure_pillow_available()
