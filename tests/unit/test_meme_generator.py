"""
Unit tests for meme generator.

Tests AI-generated meme creation from meeting transcripts.
"""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from scribe.utils.meme_generator import MemeConfig


class TestMemeConfig:
    """Test meme configuration."""

    def test_default_config(self):
        """Test default meme configuration."""
        config = MemeConfig()

        assert config.model == "gpt-5.5"
        assert config.image_model == "gpt-image-1"
        assert config.size == "1024x1024"
        assert config.quality == "high"
        assert config.output_format == "png"
        assert config.qa_enabled is True
        assert config.qa_threshold == 8.0
        assert config.max_retries == 3

    def test_custom_config(self):
        """Test custom meme configuration."""
        config = MemeConfig(qa_enabled=False, qa_threshold=8.0, max_retries=5)

        assert config.qa_enabled is False
        assert config.qa_threshold == 8.0
        assert config.max_retries == 5

    def test_from_env_defaults(self):
        """Test from_env with no environment variables set."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove any existing env vars
            os.environ.pop("SCRIBE_MEME_QA_THRESHOLD", None)
            os.environ.pop("SCRIBE_MEME_QA_ATTEMPTS", None)

            config = MemeConfig.from_env()

            assert config.qa_threshold == 8.0
            assert config.max_retries == 3

    def test_from_env_custom_threshold(self):
        """Test from_env with custom QA threshold."""
        with patch.dict(os.environ, {"SCRIBE_MEME_QA_THRESHOLD": "8.5"}):
            config = MemeConfig.from_env()

            assert config.qa_threshold == 8.5

    def test_from_env_custom_attempts(self):
        """Test from_env with custom max attempts."""
        with patch.dict(os.environ, {"SCRIBE_MEME_QA_ATTEMPTS": "5"}):
            config = MemeConfig.from_env()

            assert config.max_retries == 5

    def test_from_env_invalid_threshold_too_low(self):
        """Test from_env with invalid threshold (too low)."""
        with patch.dict(os.environ, {"SCRIBE_MEME_QA_THRESHOLD": "-1.0"}):
            config = MemeConfig.from_env()

            # Should use default
            assert config.qa_threshold == 8.0

    def test_from_env_invalid_threshold_too_high(self):
        """Test from_env with invalid threshold (too high)."""
        with patch.dict(os.environ, {"SCRIBE_MEME_QA_THRESHOLD": "11.0"}):
            config = MemeConfig.from_env()

            # Should use default
            assert config.qa_threshold == 8.0

    def test_from_env_invalid_threshold_not_number(self):
        """Test from_env with invalid threshold (not a number)."""
        with patch.dict(os.environ, {"SCRIBE_MEME_QA_THRESHOLD": "invalid"}):
            config = MemeConfig.from_env()

            # Should use default
            assert config.qa_threshold == 8.0

    def test_from_env_invalid_attempts_too_low(self):
        """Test from_env with invalid attempts (too low)."""
        with patch.dict(os.environ, {"SCRIBE_MEME_QA_ATTEMPTS": "0"}):
            config = MemeConfig.from_env()

            # Should use default
            assert config.max_retries == 3

    def test_from_env_invalid_attempts_too_high(self):
        """Test from_env with invalid attempts (too high)."""
        with patch.dict(os.environ, {"SCRIBE_MEME_QA_ATTEMPTS": "11"}):
            config = MemeConfig.from_env()

            # Should use default
            assert config.max_retries == 3

    def test_from_env_invalid_attempts_not_integer(self):
        """Test from_env with invalid attempts (not an integer)."""
        with patch.dict(os.environ, {"SCRIBE_MEME_QA_ATTEMPTS": "five"}):
            config = MemeConfig.from_env()

            # Should use default
            assert config.max_retries == 3

    def test_from_env_both_custom(self):
        """Test from_env with both threshold and attempts custom."""
        with patch.dict(
            os.environ, {"SCRIBE_MEME_QA_THRESHOLD": "7.5", "SCRIBE_MEME_QA_ATTEMPTS": "4"}
        ):
            config = MemeConfig.from_env()

            assert config.qa_threshold == 7.5
            assert config.max_retries == 4

    def test_from_env_custom_spice_level(self):
        """Test from_env with custom spice level."""
        with patch.dict(os.environ, {"SCRIBE_HUMOR_SPICE": "8"}):
            config = MemeConfig.from_env()

            assert config.spice_level == 8

    def test_from_env_invalid_spice_too_low(self):
        """Test from_env with invalid spice level (too low)."""
        with patch.dict(os.environ, {"SCRIBE_HUMOR_SPICE": "-1"}):
            config = MemeConfig.from_env()

            # Should use default
            assert config.spice_level == 5

    def test_from_env_invalid_spice_too_high(self):
        """Test from_env with invalid spice level (too high)."""
        with patch.dict(os.environ, {"SCRIBE_HUMOR_SPICE": "11"}):
            config = MemeConfig.from_env()

            # Should use default
            assert config.spice_level == 5

    def test_from_env_invalid_spice_not_integer(self):
        """Test from_env with invalid spice level (not an integer)."""
        with patch.dict(os.environ, {"SCRIBE_HUMOR_SPICE": "spicy"}):
            config = MemeConfig.from_env()

            # Should use default
            assert config.spice_level == 5

    def test_from_env_all_custom(self):
        """Test from_env with all settings custom."""
        with patch.dict(
            os.environ,
            {
                "SCRIBE_MEME_QA_THRESHOLD": "7.5",
                "SCRIBE_MEME_QA_ATTEMPTS": "4",
                "SCRIBE_HUMOR_SPICE": "8",
            },
        ):
            config = MemeConfig.from_env()

            assert config.qa_threshold == 7.5
            assert config.max_retries == 4
            assert config.spice_level == 8


# TODO: Add integration tests for meme generation with proper mocking
# The QA loop and refinement features need complex mocking that requires more setup


class TestMemeGeneratorSafetyHandling:
    """Test safety filter handling and retry logic."""

    def test_analyze_transcript_with_default_params(self):
        """Test _analyze_transcript_for_meme with default parameters."""
        from scribe.utils.meme_generator import _analyze_transcript_for_meme

        # Mock provider interface
        mock_provider = Mock()
        mock_provider.chat_completion.return_value = {
            "content": '{"template": "test", "concept": "test concept", "top_text": "TOP", "bottom_text": "BOTTOM", "image_prompt": "test prompt"}',
            "usage": {"total_tokens": 100},
        }

        config = MemeConfig()
        result = _analyze_transcript_for_meme(
            mock_provider, "Test transcript", config, show_reasoning=False
        )

        assert result is not None
        assert result["template"] == "test"
        assert result["concept"] == "test concept"

    def test_analyze_transcript_with_safety_params(self):
        """Test _analyze_transcript_for_meme with make_safer=True."""
        from scribe.utils.meme_generator import _analyze_transcript_for_meme

        # Mock provider interface
        mock_provider = Mock()
        mock_provider.chat_completion.return_value = {
            "content": '{"template": "safe", "concept": "safe concept", "top_text": "SAFE", "bottom_text": "HUMOR", "image_prompt": "safe prompt"}',
            "usage": {"total_tokens": 100},
        }

        config = MemeConfig(spice_level=7)
        previous_attempt = {"template": "edgy", "concept": "edgy concept"}

        result = _analyze_transcript_for_meme(
            mock_provider,
            "Test transcript",
            config,
            show_reasoning=False,
            previous_attempt=previous_attempt,
            make_safer=True,
        )

        assert result is not None
        # Spice level should be reduced by 2
        assert config.spice_level == 5

    def test_spice_level_reduction_respects_minimum(self):
        """Test that spice level reduction doesn't go below 1."""
        from scribe.utils.meme_generator import _analyze_transcript_for_meme

        mock_client = Mock()
        mock_response = Mock()
        mock_response.output_text = '{"template": "test", "concept": "test", "top_text": "A", "bottom_text": "B", "image_prompt": "test"}'
        mock_response.output = []
        mock_client.responses.create.return_value = mock_response

        config = MemeConfig(spice_level=2)

        _analyze_transcript_for_meme(mock_client, "Test transcript", config, make_safer=True)

        # Should be max(1, 2-2) = 1
        assert config.spice_level == 1

    def test_generate_meme_image_safety_block_detection(self):
        """Test that safety blocks are detected correctly."""
        from scribe.utils.meme_generator import _generate_meme_image

        # Mock provider interface
        mock_provider = Mock()
        mock_error = Exception(
            "Error code: 400 - {'error': {'message': 'Your request was rejected by the safety system.', 'code': 'moderation_blocked'}}"
        )
        mock_provider.generate_image.side_effect = mock_error

        config = MemeConfig()
        meme_concept = {
            "template": "test",
            "top_text": "TEST",
            "bottom_text": "MEME",
            "image_prompt": "test prompt",
            "optimal_size": "1024x1024",
        }

        result = _generate_meme_image(mock_provider, meme_concept, config, Path("test_meme.png"))

        # Should return special "SAFETY_BLOCKED" string
        assert result == "SAFETY_BLOCKED"


class TestMemeGeneratorOrchestration:
    """Test the end-to-end meme orchestration logic with mocked providers."""

    def test_generate_meeting_meme_without_qa(self, tmp_path):
        from scribe.utils.meme_generator import generate_meeting_meme

        transcript_path = tmp_path / "meeting.txt"
        transcript_path.write_text("meeting transcript")
        config = MemeConfig(qa_enabled=False, max_retries=1)
        concept_provider = Mock(
            config=SimpleNamespace(provider_name="xai", model="grok", api_key="xai")
        )
        image_provider = Mock(
            config=SimpleNamespace(provider_name="openai", model="gpt-image-1", api_key="openai")
        )
        generated_attempt = tmp_path / "meeting_meme_attempt1.png"

        def generate_image(*args, **kwargs):
            generated_attempt.write_text("image")
            return generated_attempt

        with (
            patch("scribe.providers.get_provider", side_effect=[concept_provider, image_provider]),
            patch(
                "scribe.utils.meme_generator.load_transcript_text",
                return_value="meeting transcript",
            ),
            patch(
                "scribe.utils.meme_generator._analyze_transcript_for_meme",
                return_value={
                    "template": "drake",
                    "top_text": "No",
                    "bottom_text": "Yes",
                    "image_prompt": "prompt",
                },
            ),
            patch("scribe.utils.safe_write.atomic_write_json"),
            patch("scribe.utils.meme_generator._generate_meme_image", side_effect=generate_image),
        ):
            result = generate_meeting_meme(transcript_path, output_dir=tmp_path, config=config)

        assert result is not None
        assert result["final_path"].exists()
        assert result["attempts"][0]["score"] is None

    def test_generate_meeting_meme_accepts_high_qa_score(self, tmp_path):
        from scribe.utils.meme_generator import generate_meeting_meme

        transcript_path = tmp_path / "meeting.txt"
        transcript_path.write_text("meeting transcript")
        config = MemeConfig(qa_enabled=True, qa_threshold=8.0, max_retries=1)
        provider = Mock(config=SimpleNamespace(provider_name="xai", model="grok", api_key="xai"))
        progress_updates = []
        generated_attempt = tmp_path / "meeting_meme_attempt1.png"

        def progress_callback(attempt: int, max_attempts: int, score: float | None) -> None:
            progress_updates.append((attempt, max_attempts, score))

        def generate_image(*args, **kwargs):
            generated_attempt.write_text("image")
            return generated_attempt

        with (
            patch("scribe.providers.get_provider", side_effect=[provider, provider]),
            patch(
                "scribe.utils.meme_generator.load_transcript_text",
                return_value="meeting transcript",
            ),
            patch(
                "scribe.utils.meme_generator._analyze_transcript_for_meme",
                return_value={
                    "template": "drake",
                    "top_text": "No",
                    "bottom_text": "Yes",
                    "image_prompt": "prompt",
                },
            ),
            patch("scribe.utils.safe_write.atomic_write_json"),
            patch(
                "scribe.utils.meme_generator._qa_grade_meme",
                return_value=(9.1, {"overall": "great", "critical_fixes": []}),
            ),
            patch("scribe.utils.meme_generator._generate_meme_image", side_effect=generate_image),
        ):
            result = generate_meeting_meme(
                transcript_path,
                output_dir=tmp_path,
                config=config,
                progress_callback=progress_callback,
            )

        assert result is not None
        assert result["best_score"] == 9.1
        assert progress_updates[-1] == (1, 1, 9.1)

    def test_generate_meeting_meme_uses_best_attempt_after_failed_qa(self, tmp_path):
        from scribe.utils.meme_generator import generate_meeting_meme

        transcript_path = tmp_path / "meeting.txt"
        transcript_path.write_text("meeting transcript")
        config = MemeConfig(qa_enabled=True, qa_threshold=8.0, max_retries=2)
        provider = Mock(config=SimpleNamespace(provider_name="xai", model="grok", api_key="xai"))

        def generate_image(*args, **kwargs):
            target = kwargs.get("output_path") or args[-1]
            target.write_text("image")
            return target

        def refine_prompt(_provider, meme_concept, _qa_feedback, _attempt, _config):
            return meme_concept

        with (
            patch("scribe.providers.get_provider", side_effect=[provider, provider]),
            patch(
                "scribe.utils.meme_generator.load_transcript_text",
                return_value="meeting transcript",
            ),
            patch(
                "scribe.utils.meme_generator._analyze_transcript_for_meme",
                return_value={
                    "template": "drake",
                    "top_text": "No",
                    "bottom_text": "Yes",
                    "image_prompt": "prompt",
                },
            ),
            patch("scribe.utils.safe_write.atomic_write_json"),
            patch(
                "scribe.utils.meme_generator._qa_grade_meme",
                side_effect=[
                    (6.0, {"overall": "weak", "critical_fixes": ["contrast"]}),
                    (7.5, {"overall": "better", "critical_fixes": []}),
                ],
            ),
            patch(
                "scribe.utils.meme_generator._refine_prompt_from_feedback",
                side_effect=refine_prompt,
            ),
            patch("scribe.utils.meme_generator._generate_meme_image", side_effect=generate_image),
        ):
            result = generate_meeting_meme(transcript_path, output_dir=tmp_path, config=config)

        assert result is not None
        assert result["best_score"] == 7.5
        assert result["final_path"].exists()

    def test_generate_meeting_meme_handles_safety_block_with_retry(self, tmp_path):
        from scribe.utils.meme_generator import generate_meeting_meme

        transcript_path = tmp_path / "meeting.txt"
        transcript_path.write_text("meeting transcript")
        config = MemeConfig(qa_enabled=False, max_retries=2)
        provider = Mock(config=SimpleNamespace(provider_name="xai", model="grok", api_key="xai"))

        first_concept = {
            "template": "drake",
            "top_text": "No",
            "bottom_text": "Yes",
            "image_prompt": "unsafe prompt",
        }
        second_concept = {
            "template": "drake",
            "top_text": "Still no",
            "bottom_text": "Safer yes",
            "image_prompt": "safe prompt",
        }
        generated_attempt = tmp_path / "meeting_meme_attempt1.png"

        def generate_image(*args, **kwargs):
            target = kwargs.get("output_path") or args[-1]
            if isinstance(target, Path):
                target.write_text("image")
            return target

        with (
            patch("scribe.providers.get_provider", side_effect=[provider, provider]),
            patch(
                "scribe.utils.meme_generator.load_transcript_text",
                return_value="meeting transcript",
            ),
            patch(
                "scribe.utils.meme_generator._analyze_transcript_for_meme",
                side_effect=[first_concept, second_concept],
            ),
            patch("scribe.utils.safe_write.atomic_write_json"),
            patch(
                "scribe.utils.meme_generator._generate_meme_image",
                side_effect=[
                    "SAFETY_BLOCKED",
                    generate_image(output_path=generated_attempt),
                ],
            ),
        ):
            result = generate_meeting_meme(transcript_path, output_dir=tmp_path, config=config)

        assert result is not None
        assert result["final_path"].exists()

    def test_generate_meme_image_other_errors_return_none(self):
        """Test that non-safety errors return None."""
        from openai import OpenAI

        from scribe.utils.meme_generator import _generate_meme_image

        mock_client = Mock(spec=OpenAI)
        mock_error = Exception("Network error")
        mock_client.images.generate.side_effect = mock_error

        config = MemeConfig()
        meme_concept = {
            "template": "test",
            "top_text": "TEST",
            "bottom_text": "MEME",
            "image_prompt": "test prompt",
            "optimal_size": "1024x1024",
        }

        result = _generate_meme_image(mock_client, meme_concept, config, Path("test_meme.png"))

        # Should return None for non-safety errors
        assert result is None


class TestMemeConfigSpiceLevel:
    """Test spice level configuration and validation."""

    def test_spice_level_default(self):
        """Test default spice level is 5."""
        config = MemeConfig()
        assert config.spice_level == 5

    def test_spice_level_custom(self):
        """Test custom spice level."""
        config = MemeConfig(spice_level=8)
        assert config.spice_level == 8

    def test_spice_level_minimum(self):
        """Test spice level can be 0."""
        config = MemeConfig(spice_level=0)
        assert config.spice_level == 0

    def test_spice_level_maximum(self):
        """Test spice level can be 10."""
        config = MemeConfig(spice_level=10)
        assert config.spice_level == 10

    def test_spice_level_from_env(self):
        """Test spice level from environment variable."""
        with patch.dict(os.environ, {"SCRIBE_HUMOR_SPICE": "7"}):
            config = MemeConfig.from_env()
            assert config.spice_level == 7

    def test_spice_level_type_is_int(self):
        """Test that spice_level is always an int, not a slice."""
        config = MemeConfig()
        assert isinstance(config.spice_level, int)
        assert not isinstance(config.spice_level, slice)

    def test_spice_descriptions_access(self):
        """Test that spice_descriptions can be accessed with int keys."""
        spice_descriptions = {0: "DISABLED", 1: "MILD", 5: "HONEST", 10: "SPICY"}

        config = MemeConfig(spice_level=5)

        # This should not raise "unhashable type: 'slice'" error
        desc = spice_descriptions.get(config.spice_level, "DEFAULT")
        assert desc == "HONEST"

    def test_spice_level_not_slice_object(self):
        """Test that spice_level is never a slice object."""
        config = MemeConfig()

        # Ensure it's not a slice
        assert not isinstance(config.spice_level, slice)

        # Ensure it can be used as a dict key
        test_dict = {5: "value"}
        result = test_dict.get(config.spice_level)
        assert result == "value"


class TestCLIParameterPassing:
    """Test that CLI commands pass parameters correctly."""

    def test_rec_shortcut_passes_humor_flags(self):
        """Test that rec shortcut passes no_joke and no_meme flags."""
        from scribe.cli.main import rec_shortcut

        with patch("scribe.cli.main.record") as mock_record:
            rec_shortcut(name="Test Meeting")

            # Verify record was called with correct parameters
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args.kwargs

            assert call_kwargs["name"] == "Test Meeting"
            assert call_kwargs["auto_transcribe"] is True
            assert call_kwargs["method"] == "auto"
            assert call_kwargs["no_joke"] is False
            assert call_kwargs["no_meme"] is False

    def test_rec_shortcut_without_name(self):
        """Test that rec shortcut works without name."""
        from scribe.cli.main import rec_shortcut

        with patch("scribe.cli.main.record") as mock_record:
            rec_shortcut(name=None)

            # Verify record was called with correct parameters
            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args.kwargs

            assert call_kwargs["name"] is None
            assert call_kwargs["no_joke"] is False
            assert call_kwargs["no_meme"] is False


class TestMemeGeneratorHelpers:
    def test_analyze_transcript_openai_path_captures_reasoning(self, capsys):
        from scribe.utils.meme_generator import _analyze_transcript_for_meme

        response = SimpleNamespace(
            output_text='{"template": "drake", "concept": "idea", "top_text": "TOP", "bottom_text": "BOTTOM", "image_prompt": "prompt", "summary": "Summary", "opportunities": ["Opportunity"], "selected_idea": "Chosen", "template_myth": "Myth", "match_type": "Exact", "judgment": "Works"}',
            output=[
                SimpleNamespace(type="reasoning", summary=[SimpleNamespace(text="reasoning item")])
            ],
        )
        client = SimpleNamespace(responses=Mock())
        client.responses.create.return_value = response

        result = _analyze_transcript_for_meme(
            client, "meeting transcript", MemeConfig(), show_reasoning=True
        )

        assert result is not None
        assert result["api_reasoning"] == ["reasoning item"]
        assert result["transcript_length"] == len("meeting transcript")
        assert "GPT-5 MEMETIC ANALYSIS" in capsys.readouterr().out

    def test_analyze_transcript_provider_repairs_json_and_handles_missing_json(self):
        from scribe.utils.meme_generator import _analyze_transcript_for_meme

        provider = Mock()
        provider.chat_completion.return_value = {
            "content": '{"template": "drake", "concept": "idea", "top_text": "TOP", "bottom_text": "BOTTOM", "image_prompt": "prompt",}',
        }

        repaired = _analyze_transcript_for_meme(provider, "meeting transcript", MemeConfig())
        assert repaired is not None
        assert repaired["template"] == "drake"

        provider.chat_completion.return_value = {"content": "no json here"}
        assert _analyze_transcript_for_meme(provider, "meeting transcript", MemeConfig()) is None

    def test_refine_prompt_and_qa_grade_cover_success_and_fallbacks(self, tmp_path):
        from scribe.utils.meme_generator import _qa_grade_meme, _refine_prompt_from_feedback

        provider = Mock()
        provider.chat_completion.return_value = {
            "content": '{"analysis": "Need better framing", "key_fixes": ["contrast"], "refined_prompt": "better prompt"}'
        }
        concept = {
            "template": "drake",
            "top_text": "No",
            "bottom_text": "Yes",
            "image_prompt": "original prompt",
            "concept": "funny",
        }
        feedback = {"score": 6.0, "overall": "Too dark", "issues": ["dark"]}

        refined = _refine_prompt_from_feedback(provider, concept.copy(), feedback, 1, MemeConfig())
        assert refined["image_prompt"] == "better prompt"
        assert refined["qa_refinement_1"]["analysis"] == "Need better framing"

        provider.chat_completion.side_effect = RuntimeError("provider down")
        fallback = _refine_prompt_from_feedback(provider, concept.copy(), feedback, 2, MemeConfig())
        assert "IMPROVEMENT NEEDED (Attempt 2)" in fallback["image_prompt"]

        meme_path = tmp_path / "meme.png"
        meme_path.write_bytes(b"png")
        provider = Mock()
        provider.analyze_image.return_value = (
            '{"score": 8.5, "overall": "good", "issues": [], "critical_fixes": []}'
        )
        score, qa_feedback = _qa_grade_meme(provider, meme_path, concept, MemeConfig())
        assert score == 8.5
        assert qa_feedback["overall"] == "good"

        provider.analyze_image.return_value = "plain text feedback"
        score, qa_feedback = _qa_grade_meme(provider, meme_path, concept, MemeConfig())
        assert score == 5.0
        assert qa_feedback["overall"] == "plain text feedback"

        provider.analyze_image.side_effect = RuntimeError("vision down")
        score, qa_feedback = _qa_grade_meme(provider, meme_path, concept, MemeConfig())
        assert score == 5.0
        assert "QA failed" in qa_feedback["overall"]

    @pytest.mark.requires_pillow
    def test_generate_meme_image_covers_local_overlay_and_openai_fallback(self, tmp_path):
        from scribe.utils.meme_generator import _generate_meme_image

        output_path = tmp_path / "meme.png"
        concept = {
            "template": "drake",
            "top_text": "TOP",
            "bottom_text": "BOTTOM",
            "image_prompt": "base prompt",
            "optimal_size": "1024x1024",
        }

        image_provider = Mock(config=SimpleNamespace(provider_name="openai"))
        image_provider.generate_image.return_value = b"image-bytes"
        final_image = Mock()

        with (
            patch.dict(os.environ, {"SCRIBE_MEME_TEXT_METHOD": "local"}, clear=False),
            patch("PIL.Image.open", return_value=Mock()),
            patch(
                "scribe.utils.meme_compositor.MemeCompositor.overlay_text", return_value=final_image
            ),
        ):
            result = _generate_meme_image(image_provider, concept.copy(), MemeConfig(), output_path)

        assert result == output_path
        final_image.save.assert_called_once()

        xai_provider = Mock(config=SimpleNamespace(provider_name="xai"))
        xai_provider.generate_image.side_effect = Exception("Invalid URL 'None'")
        openai_provider = Mock()
        openai_provider.generate_image.return_value = b"fallback-image"
        long_concept = {
            "template": "drake",
            "top_text": "TOP",
            "bottom_text": "BOTTOM",
            "image_prompt": "x" * 1200,
            "optimal_size": "not-a-size",
        }

        with (
            patch.dict(os.environ, {"SCRIBE_MEME_TEXT_METHOD": "ai"}, clear=False),
            patch("scribe.providers.get_provider", return_value=openai_provider),
        ):
            result = _generate_meme_image(
                xai_provider, long_concept, MemeConfig(), tmp_path / "fallback.png"
            )

        assert result == tmp_path / "fallback.png"
        assert result.exists()
        openai_provider.generate_image.assert_called_once()

    def test_generate_meeting_meme_fallback_paths_and_text_entrypoint(self, tmp_path):
        from scribe.utils.meme_generator import generate_meeting_meme, generate_meme_from_text

        transcript_path = tmp_path / "meeting.txt"
        transcript_path.write_text("meeting transcript", encoding="utf-8")
        provider = Mock(
            config=SimpleNamespace(provider_name="openai", model="gpt-5.5", api_key="key")
        )

        with (
            patch(
                "scribe.providers.get_provider",
                side_effect=[RuntimeError("bad provider"), provider, provider],
            ),
            patch(
                "scribe.utils.meme_generator.load_transcript_text",
                return_value="meeting transcript",
            ),
            patch(
                "scribe.utils.meme_generator._analyze_transcript_for_meme",
                return_value={
                    "template": "drake",
                    "top_text": "No",
                    "bottom_text": "Yes",
                    "image_prompt": "prompt",
                },
            ),
            patch("scribe.utils.safe_write.atomic_write_json"),
            patch(
                "scribe.utils.meme_generator._generate_meme_image",
                return_value=(tmp_path / "attempt.png"),
            ),
        ):
            (tmp_path / "attempt.png").write_text("image", encoding="utf-8")
            result = generate_meeting_meme(
                transcript_path, output_dir=tmp_path, config=MemeConfig(qa_enabled=False)
            )

        assert result is not None
        assert result["final_path"].exists()

        with patch(
            "scribe.utils.meme_generator.load_transcript_text", side_effect=OSError("bad file")
        ):
            assert (
                generate_meeting_meme(transcript_path, output_dir=tmp_path, config=MemeConfig())
                is None
            )

        with patch.dict(os.environ, {}, clear=True):
            assert generate_meme_from_text("hello", tmp_path / "out.png") is None

        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=True),
            patch("scribe.utils.meme_generator.OpenAI", return_value=Mock()),
            patch(
                "scribe.utils.meme_generator._analyze_transcript_for_meme",
                return_value={
                    "template": "drake",
                    "top_text": "No",
                    "bottom_text": "Yes",
                    "image_prompt": "prompt",
                },
            ),
            patch(
                "scribe.utils.meme_generator._generate_meme_image",
                return_value=tmp_path / "text_meme.png",
            ),
        ):
            assert (
                generate_meme_from_text("transcript", tmp_path / "text_meme.png")
                == tmp_path / "text_meme.png"
            )
