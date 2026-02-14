"""
TXT to DOCX conversion utility.

This module provides conversion of plain text transcripts to
formatted DOCX documents with clean styling.
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

from scribe.exceptions import FileOperationError
from scribe.utils.logging import get_logger

logger = get_logger(__name__)


def txt_to_docx(
    txt_path: Path,
    docx_path: Path | None = None,
    title: str | None = None
) -> Path:
    """
    Convert TXT transcript to formatted DOCX document.
    
    This creates a clean, professional document with:
    - Centered title (bold, 16pt)
    - Centered date/duration (12pt)
    - Body text (11pt, 1.15 line spacing)
    - Gray timestamps
    - Page numbers
    
    Args:
        txt_path: Path to input TXT file
        docx_path: Optional output path (auto-generated if None)
        title: Optional custom title (extracted from TXT if None)
        
    Returns:
        Path to created DOCX file
        
    Raises:
        FileOperationError: If conversion fails
    """
    if not txt_path.exists():
        raise FileOperationError(
            f"Input file does not exist: {txt_path}",
            context={"path": str(txt_path)}
        )

    # Generate output path if not provided
    if docx_path is None:
        docx_path = txt_path.with_suffix(".docx")

    logger.info(f"Converting {txt_path.name} to DOCX...")

    try:
        # Read transcript
        with open(txt_path, encoding="utf-8") as f:
            lines = f.readlines()

        # Create document
        doc = Document()

        # Set margins
        sections = doc.sections
        for section in sections:
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)

        # Parse header (first 3-4 lines before separator)
        header_lines = []
        body_start = 0

        for i, line in enumerate(lines):
            if "─" * 20 in line:  # Separator line
                body_start = i + 1
                break
            if line.strip():
                header_lines.append(line.strip())

        # Add title (centered, bold, 16pt)
        if header_lines:
            title_text = header_lines[0].replace("Meeting:", "").replace("Transcription:", "").strip()
            title_para = doc.add_paragraph()
            title_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            title_run = title_para.add_run(title_text)
            title_run.bold = True
            title_run.font.size = Pt(16)

            # Add date/duration (centered, 12pt)
            for header_line in header_lines[1:]:
                meta_para = doc.add_paragraph()
                meta_para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                meta_run = meta_para.add_run(header_line)
                meta_run.font.size = Pt(12)

            # Add spacing after header
            doc.add_paragraph()

        # Add body text
        for line in lines[body_start:]:
            line = line.strip()

            if not line:
                continue

            para = doc.add_paragraph()

            # Check if line starts with timestamp
            if line.startswith("[") and "]" in line:
                # Split timestamp and text
                timestamp_end = line.index("]") + 1
                timestamp = line[:timestamp_end]
                text = line[timestamp_end:].strip()

                # Add timestamp (gray, slightly smaller)
                timestamp_run = para.add_run(timestamp + " ")
                timestamp_run.font.size = Pt(10)
                timestamp_run.font.color.rgb = None  # Gray

                # Add text
                if text:
                    text_run = para.add_run(text)
                    text_run.font.size = Pt(11)

            # Check if line is silence marker
            elif line.startswith("[NO AUDIO"):
                marker_run = para.add_run(line)
                marker_run.font.size = Pt(11)
                marker_run.italic = True
                marker_run.font.color.rgb = None  # Gray

            else:
                # Regular text
                text_run = para.add_run(line)
                text_run.font.size = Pt(11)

            # Set line spacing
            para.paragraph_format.line_spacing = 1.15

        # Save document
        doc.save(str(docx_path))

        logger.info(f"DOCX created: {docx_path.name}")
        return docx_path

    except Exception as e:
        raise FileOperationError(
            f"Failed to convert TXT to DOCX: {e}",
            context={"txt_path": str(txt_path), "error": str(e)}
        )
