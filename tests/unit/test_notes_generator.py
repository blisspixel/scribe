"""
Unit tests for NotesGenerator.

Tests the meeting notes generation functionality including:
- Transcript reading and validation
- GPT-5 API integration
- Notes formatting and output
"""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from src.scribe.utils.notes_generator import (
    NotesGenerationError,
    NotesGenerator,
    TranscriptTooShortError,
)


class TestNotesGeneratorInit:
    """Test NotesGenerator initialization."""

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test123"}, clear=False)
    def test_init_with_api_key(self):
        """Test initialization with API key."""
        generator = NotesGenerator(api_key="sk-test123")
        assert generator.api_key == "sk-test123"
        # Model may vary depending on the selected provider.
        assert generator.config.model in ["gpt-5.2", "grok-4.3"]

    def test_init_with_custom_model(self):
        """Test initialization with custom model."""
        generator = NotesGenerator(api_key="sk-test123", model="gpt-5-mini")
        assert generator.config.model == "gpt-5-mini"

    def test_init_without_api_key_raises_error(self):
        """Test that missing API key raises error."""
        with patch.dict(os.environ, {}, clear=True):
            # Clear all API keys
            with pytest.raises(NotesGenerationError, match="API key not found"):
                NotesGenerator()


class TestTranscriptValidation:
    """Test transcript validation logic."""

    def test_validate_transcript_too_short(self):
        """Test that short transcripts are rejected."""
        generator = NotesGenerator(api_key="sk-test123")
        short_content = "This is too short."

        with pytest.raises(TranscriptTooShortError, match="too short"):
            generator._validate_transcript(short_content)

    def test_validate_transcript_valid(self):
        """Test that valid transcripts pass validation."""
        generator = NotesGenerator(api_key="sk-test123")
        # Create content with 150 words
        valid_content = " ".join(["word"] * 150)

        # Should not raise
        generator._validate_transcript(valid_content)

    def test_validate_transcript_very_long_passes(self):
        """Test that very long transcripts pass (segmentation handles them)."""
        generator = NotesGenerator(api_key="sk-test123")
        # Create content with 150k words - should pass, segmentation will handle it
        long_content = " ".join(["word"] * 150000)

        # Should not raise - segmentation will handle long transcripts
        generator._validate_transcript(long_content)


class TestTranscriptReading:
    """Test transcript file reading."""

    def test_read_transcript_file_not_found(self, tmp_path):
        """Test reading non-existent file raises error."""
        generator = NotesGenerator(api_key="sk-test123")
        fake_path = tmp_path / "nonexistent.txt"

        with pytest.raises(NotesGenerationError, match="not found"):
            generator._read_transcript(fake_path)

    def test_read_transcript_with_metadata(self, tmp_path):
        """Test reading transcript with metadata extraction."""
        generator = NotesGenerator(api_key="sk-test123")

        # Create test transcript
        transcript_content = """Meeting: Test Meeting
Date: November 11, 2025
Duration: 30 minutes

────────────────────────────────────────────────────────────────────────────────

This is the transcript content with enough words to pass validation.
""" + " ".join(["word"] * 100)

        transcript_file = tmp_path / "test_transcript.txt"
        transcript_file.write_text(transcript_content, encoding="utf-8")

        # Read transcript
        result = generator._read_transcript(transcript_file)

        assert result["meeting_name"] == "Test Meeting"
        assert result["date"] == "November 11, 2025"
        assert result["duration"] == "30 minutes"
        assert "transcript content" in result["content"]


class TestMetadataExtraction:
    """Test metadata extraction from transcripts."""

    def test_extract_metadata_complete(self):
        """Test extracting all metadata fields."""
        generator = NotesGenerator(api_key="sk-test123")

        content = """Meeting: Board Meeting
Date: November 11, 2025
Duration: 45 minutes

Content here"""

        metadata = generator._extract_metadata(content)

        assert metadata["meeting_name"] == "Board Meeting"
        assert metadata["date"] == "November 11, 2025"
        assert metadata["duration"] == "45 minutes"

    def test_extract_metadata_partial(self):
        """Test extracting partial metadata."""
        generator = NotesGenerator(api_key="sk-test123")

        content = """Meeting: Quick Sync

Content here"""

        metadata = generator._extract_metadata(content)

        assert metadata["meeting_name"] == "Quick Sync"
        assert "date" not in metadata
        assert "duration" not in metadata


class TestValidateOutput:
    """Test output validation and confidence scoring."""

    def test_validate_output_complete(self):
        """Test validation with complete breakdown."""
        generator = NotesGenerator(api_key="sk-test123")

        breakdown = {
            "current_state_business": [
                "Business context with specific details about Q4 revenue of $5M"
            ],
            "current_state_technical": ["Technical architecture using AWS Lambda and DynamoDB"],
            "drivers": ["Customer feedback requesting faster API response times under 100ms"],
            "blockers": ["Database performance bottleneck at 1000 queries per second"],
            "future_state_business": [
                "Target revenue of $10M by Q2 2026 with new enterprise clients"
            ],
            "future_state_technical": [
                "Migrate to Kubernetes for better scalability and auto-scaling"
            ],
            "next_steps": ["John to implement caching layer by November 20, 2025"],
        }

        confidence = generator._validate_output(breakdown)

        # Should have high confidence with complete, detailed breakdown
        assert confidence > 0.7

    def test_validate_output_missing_sections(self):
        """Test validation with missing sections."""
        generator = NotesGenerator(api_key="sk-test123")

        breakdown = {"current_state_business": ["Some content"], "drivers": ["Some drivers"]}

        confidence = generator._validate_output(breakdown)

        # Should have lower confidence with missing sections
        assert confidence < 0.5

    def test_validate_output_generic_content(self):
        """Test validation penalizes generic content."""
        generator = NotesGenerator(api_key="sk-test123")

        breakdown = {
            "current_state_business": ["We need to improve performance"],
            "current_state_technical": ["The system needs optimization"],
            "drivers": ["Business goals"],
            "blockers": ["Technical challenges"],
            "future_state_business": ["Better outcomes"],
            "future_state_technical": ["Enhanced system"],
            "next_steps": ["Follow up"],
        }

        confidence = generator._validate_output(breakdown)

        # Should have low confidence with generic content
        assert confidence < 0.6


class TestMarkdownFormatting:
    """Test Markdown output formatting."""

    def test_format_markdown_structure(self):
        """Test that Markdown has correct structure."""
        generator = NotesGenerator(api_key="sk-test123")

        summary = "This is a test summary of the meeting."
        breakdown = {
            "current_state_business": ["Business bullet 1", "Business bullet 2"],
            "current_state_technical": ["Technical bullet 1"],
            "drivers": ["Driver 1"],
            "blockers": ["Blocker 1"],
            "future_state_business": ["Future business 1"],
            "future_state_technical": ["Future technical 1"],
            "next_steps": ["Next step 1"],
        }
        metadata = {
            "meeting_name": "Test Meeting",
            "date": "November 11, 2025",
            "duration": "30 minutes",
        }

        markdown = generator._format_markdown(summary, breakdown, metadata)

        # Check structure
        assert "# Meeting Notes: Test Meeting" in markdown
        assert "**Date**: November 11, 2025" in markdown
        assert "**Duration**: 30 minutes" in markdown
        assert "## Detailed Summary" in markdown
        assert "## Current State" in markdown
        assert "**Business:**" in markdown
        assert "**Technical:**" in markdown
        assert "## Drivers" in markdown
        assert "## Blockers" in markdown
        assert "## Future State" in markdown
        assert "## Next Steps" in markdown

        # Check bullets are formatted correctly
        assert "- Business bullet 1" in markdown
        assert "- Technical bullet 1" in markdown


class TestFileWriting:
    """Test file writing functionality."""

    def test_write_notes_creates_file(self, tmp_path):
        """Test that notes are written to file."""
        generator = NotesGenerator(api_key="sk-test123")

        content = "# Test Notes\n\nThis is test content."
        output_path = tmp_path / "test_notes.md"

        result_path = generator._write_notes(content, output_path)

        assert result_path == output_path
        assert output_path.exists()
        assert output_path.read_text(encoding="utf-8") == content


class TestNotesGeneratorPipeline:
    """Test the higher-level orchestration paths."""

    def _make_generator(self) -> NotesGenerator:
        with patch(
            "scribe.providers.get_provider", side_effect=RuntimeError("provider unavailable")
        ):
            with patch("src.scribe.utils.notes_generator.OpenAI", return_value=Mock()):
                return NotesGenerator(api_key="sk-test123")

    def test_generate_notes_single_pass(self, tmp_path):
        generator = self._make_generator()
        transcript_path = tmp_path / "meeting.txt"
        transcript_path.write_text("content")
        output_path = tmp_path / "meeting_notes.md"

        with (
            patch.object(
                generator,
                "_read_transcript",
                return_value={
                    "content": "word " * 150,
                    "meeting_name": "Meeting",
                    "date": "Today",
                    "duration": "30 minutes",
                },
            ),
            patch.object(generator, "_validate_transcript"),
            patch.object(generator, "_segment_for_full_coverage", return_value=None),
            patch.object(generator, "_generate_detailed_summary", return_value="summary"),
            patch.object(
                generator,
                "_generate_analytical_breakdown",
                return_value={"current_state_business": ["A"]},
            ),
            patch.object(
                generator,
                "_refine_and_polish",
                return_value={"current_state_business": ["A"], "next_steps": ["Do thing"]},
            ),
            patch.object(generator, "_validate_output", return_value=0.91),
            patch.object(generator, "_format_markdown", return_value="# Notes"),
            patch.object(generator, "_write_notes", return_value=output_path) as mock_write,
        ):
            result = generator.generate_notes(transcript_path, output_path)

        assert result == output_path
        mock_write.assert_called_once_with("# Notes", output_path)

    def test_generate_notes_segmented_path(self, tmp_path):
        generator = self._make_generator()
        transcript_path = tmp_path / "meeting.txt"
        transcript_path.write_text("content")
        output_path = tmp_path / "meeting_notes.md"

        with (
            patch.object(
                generator,
                "_read_transcript",
                return_value={
                    "content": "word " * 500,
                    "meeting_name": "Meeting",
                    "date": "Today",
                    "duration": "30 minutes",
                },
            ),
            patch.object(generator, "_validate_transcript"),
            patch.object(generator, "_segment_for_full_coverage", return_value=["seg1", "seg2"]),
            patch.object(
                generator, "_generate_detailed_summary", side_effect=["summary1", "summary2"]
            ),
            patch.object(
                generator,
                "_generate_analytical_breakdown",
                side_effect=[
                    {"current_state_business": ["A"]},
                    {"current_state_business": ["B"]},
                ],
            ),
            patch.object(
                generator,
                "_merge_breakdowns",
                return_value={"current_state_business": ["A", "B"]},
            ) as mock_merge,
            patch.object(
                generator,
                "_refine_and_polish",
                return_value={"current_state_business": ["A", "B"], "next_steps": ["Ship it"]},
            ),
            patch.object(generator, "_validate_output", return_value=0.87),
            patch.object(generator, "_format_markdown", return_value="# Notes"),
            patch.object(generator, "_write_notes", return_value=output_path),
        ):
            result = generator.generate_notes(transcript_path, output_path)

        assert result == output_path
        mock_merge.assert_called_once()

    def test_call_gpt5_api_provider_mode(self):
        provider = Mock()
        provider.config = SimpleNamespace(
            provider_name="xai", model="grok-4.3", api_key="xai-test-key"
        )
        provider.chat_completion_with_json.return_value = {
            "content": '{"ok": true}',
            "usage": {"total_tokens": 321, "cost_usd": 0.12, "cost_source": "estimated"},
        }

        with patch("scribe.providers.get_provider", return_value=provider):
            with patch("src.scribe.utils.notes_generator.OpenAI", return_value=Mock()):
                generator = NotesGenerator(api_key="sk-test123", provider_name="xai")

        content, metrics = generator._call_gpt5_api(
            "hello", phase="summary", json_schema={"type": "object"}
        )

        assert content == '{"ok": true}'
        assert metrics["provider"] == "xai"
        assert metrics["tokens"] == 321

    def test_call_gpt5_api_openai_retry_on_incomplete(self):
        with patch(
            "scribe.providers.get_provider", side_effect=RuntimeError("provider unavailable")
        ):
            with patch("src.scribe.utils.notes_generator.OpenAI") as mock_openai:
                first_response = SimpleNamespace(
                    status="incomplete",
                    incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                    output_text="",
                    usage=None,
                )
                second_response = SimpleNamespace(
                    status="completed",
                    incomplete_details=None,
                    output_text="Final answer",
                    usage=SimpleNamespace(total_tokens=42),
                )
                client = Mock()
                client.responses.create.side_effect = [first_response, second_response]
                mock_openai.return_value = client
                generator = NotesGenerator(api_key="sk-test123")

        content, metrics = generator._call_gpt5_api("hello", phase="summary")

        assert content == "Final answer"
        assert metrics["tokens"] == 42

    def test_write_notes_creates_parent_dirs(self, tmp_path):
        """Test that parent directories are created."""
        generator = NotesGenerator(api_key="sk-test123")

        content = "# Test Notes"
        output_path = tmp_path / "subdir" / "notes" / "test_notes.md"

        result_path = generator._write_notes(content, output_path)

        assert result_path.exists()
        assert result_path.read_text(encoding="utf-8") == content


class TestNotesGeneratorHelpers:
    def _make_generator(self) -> NotesGenerator:
        with patch(
            "scribe.providers.get_provider", side_effect=RuntimeError("provider unavailable")
        ):
            with patch("src.scribe.utils.notes_generator.OpenAI", return_value=Mock()):
                return NotesGenerator(api_key="sk-test123")

    def test_extract_output_text_and_repair_json_helpers(self):
        generator = self._make_generator()
        response = SimpleNamespace(
            output=[
                {"type": "message", "content": [{"type": "output_text", "text": "First"}]},
                SimpleNamespace(type="output_text", content="Second"),
            ]
        )

        assert generator._extract_output_text(response) == "First\nSecond"

        repaired = generator._repair_json_lenient(
            '```json\n{"items": ["alpha" "beta"], "count": 2,}\n``` trailing text'
        )
        assert '"alpha", "beta"' in repaired
        assert repaired.endswith("}")

    def test_read_transcript_and_summary_errors_are_wrapped(self, tmp_path):
        generator = self._make_generator()
        directory = tmp_path / "folder"
        directory.mkdir()

        with pytest.raises(NotesGenerationError, match="Path is not a file"):
            generator._read_transcript(directory)

        transcript_path = tmp_path / "meeting.txt"
        transcript_path.write_text("content", encoding="utf-8")
        with patch(
            "src.scribe.utils.notes_generator.load_transcript_text",
            side_effect=OSError("decode failed"),
        ):
            with pytest.raises(NotesGenerationError, match="Failed to read transcript"):
                generator._read_transcript(transcript_path)

        with patch.object(generator, "_call_gpt5_api", side_effect=RuntimeError("api down")):
            with pytest.raises(NotesGenerationError, match="Failed to generate summary"):
                generator._generate_detailed_summary("word " * 200)

    def test_breakdown_generation_and_refinement_cover_repair_paths(self, tmp_path):
        generator = self._make_generator()
        repaired_breakdown = {
            "current_state_business": ["Alpha", "Beta"],
            "current_state_technical": [],
            "drivers": [],
            "blockers": [],
            "future_state_business": [],
            "future_state_technical": [],
            "next_steps": [],
        }

        response_text = (
            '{"current_state_business": ["Alpha" "Beta"], '
            '"current_state_technical": [], "drivers": [], "blockers": [], '
            '"future_state_business": [], "future_state_technical": [], "next_steps": []}'
        )
        with patch.object(generator, "_call_gpt5_api", return_value=(response_text, {})):
            breakdown = generator._generate_analytical_breakdown("transcript", "summary")

        assert breakdown == repaired_breakdown

        monkeypatch_dir = tmp_path / "debug"
        monkeypatch_dir.mkdir()
        current_dir = os.getcwd()
        os.chdir(monkeypatch_dir)
        try:
            with patch.object(generator, "_call_gpt5_api", return_value=("{bad json", {})):
                with pytest.raises(
                    NotesGenerationError, match="Failed to generate analytical breakdown"
                ):
                    generator._generate_analytical_breakdown("transcript", "summary")
            assert (monkeypatch_dir / "debug_json_response.txt").exists()
        finally:
            os.chdir(current_dir)

        original_breakdown = {
            "current_state_business": ["Business"],
            "current_state_technical": ["Technical"],
            "drivers": ["Driver"],
            "blockers": ["Blocker"],
            "future_state_business": ["Future business"],
            "future_state_technical": ["Future technical"],
            "next_steps": ["Next step"],
        }
        refined_json = '{"current_state_business": ["Refined business"]}'
        with patch.object(generator, "_call_gpt5_api", return_value=(refined_json, {})):
            refined = generator._refine_and_polish("transcript", original_breakdown)

        assert refined["current_state_business"] == ["Refined business"]
        assert refined["blockers"] == ["Blocker"]

        with patch.object(generator, "_call_gpt5_api", return_value=("{bad json", {})):
            assert (
                generator._refine_and_polish("transcript", original_breakdown) == original_breakdown
            )

    def test_segmentation_merge_and_breakdown_validation(self):
        generator = self._make_generator()
        short_text = "word " * 100
        long_text = "A" * (220_000 * 4 + 100)

        assert generator._segment_for_full_coverage(short_text) is None
        chunks = generator._segment_for_full_coverage(long_text)
        assert chunks is not None
        assert len(chunks) >= 2

        merged = generator._merge_breakdowns(
            [
                {"drivers": ["Alpha"], "next_steps": ["Ship"], "blockers": ["Risk"]},
                {"drivers": ["Alpha", "Beta"], "next_steps": ["Ship"], "blockers": ["Risk 2"]},
            ]
        )
        assert merged["drivers"] == ["Alpha", "Beta"]
        assert merged["blockers"] == ["Risk", "Risk 2"]

        generator._validate_breakdown_keys(
            {
                "current_state_business": [],
                "current_state_technical": [],
                "drivers": [],
                "blockers": [],
                "future_state_business": [],
                "future_state_technical": [],
                "next_steps": [],
            }
        )

        with pytest.raises(Exception, match="Missing required section"):
            generator._validate_breakdown_keys({"drivers": []})

        with pytest.raises(Exception, match="must be a list of strings"):
            generator._validate_breakdown_keys(
                {
                    "current_state_business": "bad",
                    "current_state_technical": [],
                    "drivers": [],
                    "blockers": [],
                    "future_state_business": [],
                    "future_state_technical": [],
                    "next_steps": [],
                }
            )


# Integration test (requires API key)
@pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"), reason="Requires OPENAI_API_KEY environment variable"
)
class TestNotesGeneratorIntegration:
    """Integration tests with real API calls."""

    @pytest.mark.slow
    @pytest.mark.skipif(not os.getenv("OPENAI_API_KEY"), reason="OpenAI API key not configured")
    def test_generate_notes_from_real_transcript(self, tmp_path):
        """Test generating notes from a real transcript file (slow, makes real API call)."""
        # Find a real transcript
        transcript_path = Path(
            "output/Rawlings_Internal_11-11_2025-11-11_07-33-07_transcription.txt"
        )

        if not transcript_path.exists():
            pytest.skip("Test transcript not found")

        # Skip if no valid API key
        api_key = os.getenv("XAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key or api_key.startswith("sk-proj-"):
            pytest.skip("No valid API key available for integration test")

        # Initialize generator
        generator = NotesGenerator(api_key=api_key, model="gpt-5")

        # Generate notes
        output_path = tmp_path / "test_notes.md"
        notes_path = generator.generate_notes(transcript_path, output_path)

        # Verify output
        assert notes_path.exists()
        content = notes_path.read_text(encoding="utf-8")

        # Check for required sections
        assert "# Meeting Notes:" in content
        assert "## Detailed Summary" in content
        assert "## Current State" in content
        assert "## Drivers" in content
        assert "## Blockers" in content
        assert "## Future State" in content
        assert "## Next Steps" in content

        # Check for proper formatting
        assert "**Business:**" in content
        assert "**Technical:**" in content

        print(f"\n✅ Successfully generated notes: {notes_path}")
        print(f"📄 Content length: {len(content)} characters")
