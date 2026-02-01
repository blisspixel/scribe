"""
Local meme text compositor using Pillow.

Overlays Impact font text on images to bypass AI text rendering issues
and safety filters.
"""

import logging
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
import textwrap

logger = logging.getLogger(__name__)


class MemeCompositor:
    """
    Compositor for applying Impact-font captions to meme images.
    
    Handles dynamic font sizing, text wrapping, and stroke rendering.
    """
    
    def __init__(self, font_path: Optional[str] = None):
        """
        Initialize compositor with Impact font.
        
        Args:
            font_path: Path to Impact.ttf font file (optional)
        """
        self.font_path = font_path
        
        # Try to find Impact font in common locations
        if not self.font_path:
            import platform
            system = platform.system()
            
            if system == "Windows":
                self.font_path = "C:/Windows/Fonts/impact.ttf"
            elif system == "Darwin":  # macOS
                self.font_path = "/System/Library/Fonts/Supplemental/Impact.ttf"
            else:  # Linux
                # Try common Linux font paths
                possible_paths = [
                    "/usr/share/fonts/truetype/msttcorefonts/Impact.ttf",
                    "/usr/share/fonts/TTF/impact.ttf",
                ]
                for path in possible_paths:
                    if Path(path).exists():
                        self.font_path = path
                        break
        
        if self.font_path and not Path(self.font_path).exists():
            logger.warning(f"Impact font not found at {self.font_path}, will use default")
            self.font_path = None
    
    def overlay_text(
        self,
        image: Image.Image,
        top_text: str = "",
        bottom_text: str = "",
        font_size_ratio: float = 0.08
    ) -> Image.Image:
        """
        Overlay meme text on image with Impact font styling.
        
        Args:
            image: PIL Image to overlay text on
            top_text: Text for top of image
            bottom_text: Text for bottom of image
            font_size_ratio: Font size as ratio of image height (default: 0.08)
            
        Returns:
            Image with text overlaid
        """
        # Work on a copy
        img = image.copy()
        draw = ImageDraw.Draw(img)
        width, height = img.size
        
        # Calculate dynamic font size
        base_font_size = int(height * font_size_ratio)
        
        # Load font
        try:
            if self.font_path:
                font = ImageFont.truetype(self.font_path, base_font_size)
            else:
                # Fallback to default font
                font = ImageFont.load_default()
                logger.warning("Using default font (Impact not available)")
        except Exception as e:
            logger.warning(f"Failed to load font: {e}, using default")
            font = ImageFont.load_default()
        
        # Draw top text
        if top_text:
            self._draw_caption(
                draw, font, top_text.upper(), width, height,
                position="top", base_font_size=base_font_size
            )
        
        # Draw bottom text
        if bottom_text:
            self._draw_caption(
                draw, font, bottom_text.upper(), width, height,
                position="bottom", base_font_size=base_font_size
            )
        
        return img
    
    def _draw_caption(
        self,
        draw: ImageDraw.ImageDraw,
        font: ImageFont.FreeTypeFont,
        text: str,
        width: int,
        height: int,
        position: str,
        base_font_size: int
    ):
        """Draw a single caption (top or bottom) with wrapping and stroke."""
        if not text:
            return
        
        # Text wrapping - estimate chars per line
        chars_per_line = max(10, int(width / (base_font_size * 0.6)))
        lines = textwrap.wrap(text, width=chars_per_line)
        
        # Calculate stroke width (5% of font size)
        stroke_width = max(2, int(base_font_size * 0.05))
        
        # Calculate total text block height
        line_spacing = int(base_font_size * 0.1)
        total_height = 0
        line_heights = []
        
        for line in lines:
            try:
                bbox = font.getbbox(line)
                line_height = bbox[3] - bbox[1]
            except (AttributeError, TypeError):
                # Fallback for older Pillow versions
                line_height = base_font_size
            line_heights.append(line_height)
            total_height += line_height + line_spacing
        
        # Determine starting Y position
        if position == "top":
            current_y = 20  # Padding from top
        else:  # bottom
            current_y = height - total_height - 20  # Padding from bottom
        
        # Draw each line
        for line, line_height in zip(lines, line_heights):
            # Center horizontally
            try:
                bbox = font.getbbox(line)
                text_width = bbox[2] - bbox[0]
            except (AttributeError, TypeError):
                # Fallback
                text_width = len(line) * base_font_size * 0.6
            
            x = (width - text_width) / 2
            
            # Draw text with stroke
            draw.text(
                (x, current_y),
                line,
                font=font,
                fill="white",
                stroke_width=stroke_width,
                stroke_fill="black"
            )
            
            current_y += line_height + line_spacing
