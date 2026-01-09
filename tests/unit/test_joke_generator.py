"""
Unit tests for agentic AI joke generator.

Tests joke generation system including metadata extraction,
archetype selection, and GPT-5 integration.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from scribe.utils.joke_generator import (
    _extract_meeting_metadata,
    _select_archetype_heuristic,
    _mine_safe_entities,
    _word_len_ok,
    _clip_to_words,
    _build_instruction,
    generate_transcript_joke,
    ARCHETYPE_DISPLAY_NAMES,
    COMEDY_STYLES,
    HumorConfig,
)


class TestMetadataExtraction:
    """Test transcript metadata extraction for context-aware humor."""
    
    def test_extract_basic_metadata(self):
        """Test extraction of basic transcript metadata."""
        transcript = "This is a short meeting transcript with some words."
        metadata = _extract_meeting_metadata(transcript)
        
        assert 'word_count' in metadata
        assert 'is_short' in metadata
        assert 'is_long' in metadata
        assert metadata['word_count'] > 0
    
    def test_detect_jargon(self):
        """Test detection of corporate jargon."""
        transcript = "We need to leverage synergy and circle back on bandwidth alignment."
        metadata = _extract_meeting_metadata(transcript)
        
        assert metadata['has_jargon'] is True
    
    def test_detect_technical_content(self):
        """Test detection of technical terminology."""
        transcript = "The API deployment to the database infrastructure failed."
        metadata = _extract_meeting_metadata(transcript)
        
        assert metadata['has_technical'] is True
    
    def test_detect_intent_drift(self):
        """Test detection of intent drift (decisions deferred)."""
        transcript = """
        We need to decide on the budget. Let's circle back later.
        We should agree on the timeline. Let's follow up next week.
        """
        metadata = _extract_meeting_metadata(transcript)
        
        # Should detect more deferrals than decisions
        assert 'intent_drift' in metadata
    
    def test_detect_circular_discussion(self):
        """Test detection of circular/repetitive discussions."""
        transcript = "budget " * 10 + "timeline " * 10
        metadata = _extract_meeting_metadata(transcript)
        
        assert metadata['has_repetition'] is True
    
    def test_detect_exhaustion_tone(self):
        """Test detection of exhaustion markers."""
        transcript = "This is taking long. Finally we can move on. Anyway, last thing..."
        metadata = _extract_meeting_metadata(transcript)
        
        assert 'dominant_tone' in metadata
    
    def test_short_meeting_classification(self):
        """Test classification of short meetings."""
        transcript = "Quick sync. " * 30  # ~60 words
        metadata = _extract_meeting_metadata(transcript)
        
        assert metadata['is_short'] is True
        assert metadata['is_long'] is False
    
    def test_long_meeting_classification(self):
        """Test classification of long meetings."""
        transcript = "Long discussion. " * 2000  # ~4000 words
        metadata = _extract_meeting_metadata(transcript)
        
        assert metadata['is_short'] is False
        assert metadata['is_long'] is True
    
    def test_high_jargon_low_decision_detection(self):
        """Test detection of jargon-heavy meetings with few decisions."""
        transcript = "synergy leverage bandwidth alignment circle back touch base deep dive"
        metadata = _extract_meeting_metadata(transcript)
        
        assert metadata['high_jargon_low_decision'] is True


class TestArchetypeSelection:
    """Test comedy archetype selection based on context."""
    
    def test_select_translator_for_high_jargon(self):
        """Test Jargon Translator selected for jargon-heavy meetings."""
        metadata = {
            'has_jargon': True,
            'has_technical': False,
            'is_long': False,
            'is_short': False,
            'high_jargon_low_decision': True,
            'intent_drift': False,
            'circular_discussion': False,
            'dominant_tone': 'neutral',
            'decision_ratio': 1.0
        }
        
        # Run multiple times to check weighting
        selections = [_select_archetype_heuristic(metadata, seed=i) for i in range(20)]
        
        # Translator should be heavily weighted (4x)
        assert 'translator' in selections
        assert selections.count('translator') > 5  # Should appear frequently
    
    def test_select_empathic_for_long_exhausting_meeting(self):
        """Test Empathic Realist selected for long, exhausting meetings."""
        metadata = {
            'has_jargon': False,
            'has_technical': False,
            'is_long': True,
            'is_short': False,
            'dominant_tone': 'exhaustion',
            'intent_drift': False,
            'circular_discussion': False,
            'high_jargon_low_decision': False,
            'decision_ratio': 1.0
        }
        
        selections = [_select_archetype_heuristic(metadata, seed=i) for i in range(20)]
        
        # Empathic or Time Alchemist should be weighted (at least 25% of selections)
        empathic_or_time = [s for s in selections if s in ['empathic', 'time_alchemist']]
        assert len(empathic_or_time) >= 5  # At least 25% should be empathic or time_alchemist
    
    def test_select_trickster_for_intent_drift(self):
        """Test Trickster selected when goals diverge from outcomes."""
        metadata = {
            'has_jargon': False,
            'has_technical': False,
            'is_long': False,
            'is_short': False,
            'intent_drift': True,
            'circular_discussion': False,
            'high_jargon_low_decision': False,
            'dominant_tone': 'neutral',
            'decision_ratio': 1.0
        }
        
        selections = [_select_archetype_heuristic(metadata, seed=i) for i in range(20)]
        
        # Trickster should be heavily weighted (3.5x), but with 10 archetypes now, adjust threshold
        assert 'trickster' in selections
        assert selections.count('trickster') >= 4  # Adjusted for more archetypes
    
    def test_select_fool_scholar_for_circular_discussion(self):
        """Test Fool-Scholar selected for circular discussions."""
        metadata = {
            'has_jargon': False,
            'has_technical': False,
            'is_long': False,
            'is_short': False,
            'intent_drift': False,
            'circular_discussion': True,
            'high_jargon_low_decision': False,
            'dominant_tone': 'confusion',
            'decision_ratio': 1.0
        }
        
        selections = [_select_archetype_heuristic(metadata, seed=i) for i in range(20)]
        
        # Fool-Scholar should be heavily weighted (3x)
        assert 'fool_scholar' in selections
    
    def test_all_archetypes_available(self):
        """Test all archetypes can be selected."""
        metadata = {
            'has_jargon': False,
            'has_technical': False,
            'is_long': False,
            'is_short': False,
            'intent_drift': False,
            'circular_discussion': False,
            'high_jargon_low_decision': False,
            'dominant_tone': 'neutral',
            'decision_ratio': 1.0
        }
        
        # With neutral metadata, all should be possible
        selections = set(_select_archetype_heuristic(metadata, seed=i) for i in range(100))
        
        # Should see variety
        assert len(selections) >= 4
    
    def test_seeded_selection_is_deterministic(self):
        """Test archetype selection is deterministic with seed."""
        metadata = {
            'has_jargon': True,
            'has_technical': False,
            'is_long': False,
            'is_short': False,
            'intent_drift': False,
            'circular_discussion': False,
            'high_jargon_low_decision': False,
            'dominant_tone': 'neutral',
            'decision_ratio': 1.0
        }
        
        # Same seed should give same result
        result1 = _select_archetype_heuristic(metadata, seed=42)
        result2 = _select_archetype_heuristic(metadata, seed=42)
        
        assert result1 == result2


class TestEntityMining:
    """Test safe entity extraction from transcripts."""
    
    def test_mine_project_names(self):
        """Test extraction of project names."""
        transcript = "We discussed Project Alpha and Project Beta today."
        entities = _mine_safe_entities(transcript)
        
        assert "Project Alpha" in entities or "Project Beta" in entities
    
    def test_mine_acronyms(self):
        """Test extraction of acronyms."""
        transcript = "The API and SDK need updates. Also check the UI."
        entities = _mine_safe_entities(transcript)
        
        # Should extract some acronyms
        assert any(e.isupper() for e in entities)
    
    def test_mine_camel_case(self):
        """Test extraction of CamelCase identifiers."""
        transcript = "We need to update UserProfile and DataModel classes."
        entities = _mine_safe_entities(transcript)
        
        # Should extract CamelCase
        assert any("Profile" in e or "Model" in e for e in entities)
    
    def test_filter_speaker_names(self):
        """Test that speaker names are filtered out."""
        transcript = """
        John: We should discuss the API.
        Sarah: I agree about the API.
        """
        entities = _mine_safe_entities(transcript)
        
        # Should not include speaker names
        assert "John" not in entities
        assert "Sarah" not in entities
    
    def test_limit_entity_count(self):
        """Test entity count is limited."""
        transcript = "Project A Project B Project C " * 20
        entities = _mine_safe_entities(transcript, top_k=5)
        
        assert len(entities) <= 5


class TestUtilityFunctions:
    """Test utility helper functions."""
    
    def test_word_len_ok_within_range(self):
        """Test word length check for valid range."""
        assert _word_len_ok("This is a test", 3, 5) is True
        assert _word_len_ok("This is a test", 5, 10) is False
        assert _word_len_ok("This is a test", 1, 3) is False
    
    def test_clip_to_words(self):
        """Test clipping text to word limit."""
        text = "This is a long sentence that needs to be clipped"
        clipped = _clip_to_words(text, 5)
        
        assert len(clipped.split()) == 5
        assert clipped == "This is a long sentence"
    
    def test_clip_to_words_removes_punctuation(self):
        """Test clipping removes trailing punctuation."""
        text = "This is a test, with punctuation."
        clipped = _clip_to_words(text, 4)
        
        # Should remove trailing comma
        assert not clipped.endswith(",")
    
    def test_clip_to_words_no_change_if_short(self):
        """Test clipping doesn't change short text."""
        text = "Short text"
        clipped = _clip_to_words(text, 10)
        
        assert clipped == text


class TestInstructionBuilding:
    """Test instruction generation for GPT-5."""
    
    def test_build_instruction_basic(self):
        """Test basic instruction building."""
        cfg = HumorConfig()
        instruction = _build_instruction([], cfg)
        
        assert "meeting transcript" in instruction.lower()
        assert "joke" in instruction.lower()
        assert str(cfg.min_words) in instruction
        assert str(cfg.max_words) in instruction
    
    def test_build_instruction_with_entities(self):
        """Test instruction includes entities."""
        cfg = HumorConfig()
        entities = ["Project Alpha", "API"]
        instruction = _build_instruction(entities, cfg)
        
        assert "Project Alpha" in instruction
        assert "API" in instruction
    
    def test_build_instruction_safety_guidelines(self):
        """Test instruction includes safety guidelines."""
        cfg = HumorConfig()
        instruction = _build_instruction([], cfg)
        
        assert "avoid individuals" in instruction.lower() or "protected groups" in instruction.lower()


class TestHumorConfig:
    """Test HumorConfig dataclass."""
    
    def test_default_config(self):
        """Test default configuration values."""
        cfg = HumorConfig()
        
        assert cfg.model == "gpt-5.2"
        assert cfg.min_words == 10
        assert cfg.max_words == 18
        assert cfg.reasoning_effort == "minimal"
        assert cfg.verbosity == "low"
        assert cfg.spice_level == 5
    
    def test_custom_config(self):
        """Test custom configuration values."""
        cfg = HumorConfig(
            model="gpt-4",
            min_words=5,
            max_words=10,
            api_key="test-key",
            spice_level=8
        )
        
        assert cfg.model == "gpt-4"
        assert cfg.min_words == 5
        assert cfg.max_words == 10
        assert cfg.api_key == "test-key"
        assert cfg.spice_level == 8
    
    def test_from_env_default_spice(self):
        """Test from_env with default spice level."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('SCRIBE_HUMOR_SPICE', None)
            cfg = HumorConfig.from_env()
            
            assert cfg.spice_level == 5
    
    def test_from_env_custom_spice(self):
        """Test from_env with custom spice level."""
        with patch.dict(os.environ, {'SCRIBE_HUMOR_SPICE': '7'}):
            cfg = HumorConfig.from_env()
            
            assert cfg.spice_level == 7
    
    def test_from_env_invalid_spice_too_low(self):
        """Test from_env with invalid spice level (too low)."""
        with patch.dict(os.environ, {'SCRIBE_HUMOR_SPICE': '-1'}):
            cfg = HumorConfig.from_env()
            
            # Should use default
            assert cfg.spice_level == 5
    
    def test_from_env_invalid_spice_too_high(self):
        """Test from_env with invalid spice level (too high)."""
        with patch.dict(os.environ, {'SCRIBE_HUMOR_SPICE': '11'}):
            cfg = HumorConfig.from_env()
            
            # Should use default
            assert cfg.spice_level == 5
    
    def test_from_env_invalid_spice_not_integer(self):
        """Test from_env with invalid spice level (not an integer)."""
        with patch.dict(os.environ, {'SCRIBE_HUMOR_SPICE': 'very_spicy'}):
            cfg = HumorConfig.from_env()
            
            # Should use default
            assert cfg.spice_level == 5


class TestJokeGeneration:
    """Test end-to-end joke generation."""
    
    @patch('scribe.utils.joke_generator.OpenAI')
    def test_generate_joke_success(self, mock_openai_class, tmp_path):
        """Test successful joke generation."""
        # Create test transcript
        transcript_path = tmp_path / "test_transcript.txt"
        transcript_path.write_text("We had a meeting about synergy and alignment.")
        
        # Mock OpenAI response
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        
        mock_response = Mock()
        mock_response.output_text = "We synergized until the buzzwords achieved sentience."
        mock_client.responses.create.return_value = mock_response
        
        # Generate joke
        result = generate_transcript_joke(transcript_path, "test-api-key")
        
        assert result is not None
        joke_text, comedy_style = result
        assert isinstance(joke_text, str)
        assert len(joke_text) > 0
        # comedy_style is the display name, not the key
        assert isinstance(comedy_style, str)
        assert len(comedy_style) > 0
    
    @patch('scribe.utils.joke_generator.OpenAI')
    def test_generate_joke_uses_responses_api(self, mock_openai_class, tmp_path):
        """Test that Responses API is used (not Chat Completions)."""
        transcript_path = tmp_path / "test_transcript.txt"
        transcript_path.write_text("Meeting content.")
        
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        
        mock_response = Mock()
        mock_response.output_text = "Joke text"
        mock_client.responses.create.return_value = mock_response
        
        generate_transcript_joke(transcript_path, "test-api-key")
        
        # Verify Responses API was called (may be called multiple times for retries)
        assert mock_client.responses.create.called
        call_args = mock_client.responses.create.call_args
        
        # Check it uses GPT-5.2
        assert call_args[1]['model'] == 'gpt-5.2'
    
    @patch('scribe.utils.joke_generator.OpenAI')
    def test_generate_joke_handles_api_error(self, mock_openai_class, tmp_path):
        """Test graceful handling of API errors."""
        transcript_path = tmp_path / "test_transcript.txt"
        transcript_path.write_text("Meeting content.")
        
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        mock_client.responses.create.side_effect = Exception("API Error")
        
        result = generate_transcript_joke(transcript_path, "test-api-key")
        
        # Should return None on error, not crash
        assert result is None
    
    @patch('scribe.utils.joke_generator.OpenAI')
    def test_generate_joke_handles_empty_response(self, mock_openai_class, tmp_path):
        """Test handling of empty joke response."""
        transcript_path = tmp_path / "test_transcript.txt"
        transcript_path.write_text("Meeting content.")
        
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        
        mock_response = Mock()
        mock_response.output_text = ""  # Empty response
        mock_client.responses.create.return_value = mock_response
        
        result = generate_transcript_joke(transcript_path, "test-api-key")
        
        # Should return None for empty joke
        assert result is None
    
    def test_generate_joke_missing_api_key(self, tmp_path):
        """Test error when API key is missing."""
        transcript_path = tmp_path / "test_transcript.txt"
        transcript_path.write_text("Meeting content.")
        
        with patch.dict('os.environ', {}, clear=True):
            # Should raise RuntimeError for missing API key
            with pytest.raises(RuntimeError, match="Missing OpenAI API key"):
                generate_transcript_joke(transcript_path, None)
    
    @patch('scribe.utils.joke_generator.OpenAI')
    def test_generate_joke_with_config(self, mock_openai_class, tmp_path):
        """Test joke generation with custom config."""
        transcript_path = tmp_path / "test_transcript.txt"
        transcript_path.write_text("Meeting content.")
        
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        
        mock_response = Mock()
        mock_response.output_text = "Custom joke"
        mock_client.responses.create.return_value = mock_response
        
        # Create custom config
        config = HumorConfig(
            model="gpt-5",
            min_words=5,
            max_words=10,
            api_key="test-key"
        )
        
        result = generate_transcript_joke(transcript_path, config)
        
        assert result is not None


class TestArchetypeDisplayNames:
    """Test archetype display name mappings."""
    
    def test_all_archetypes_have_display_names(self):
        """Test all archetypes have human-readable display names."""
        for archetype_key in COMEDY_STYLES.keys():
            assert archetype_key in ARCHETYPE_DISPLAY_NAMES
            display_name = ARCHETYPE_DISPLAY_NAMES[archetype_key]
            assert isinstance(display_name, str)
            assert len(display_name) > 0
    
    def test_display_names_are_formatted(self):
        """Test display names are properly formatted."""
        for display_name in ARCHETYPE_DISPLAY_NAMES.values():
            # Should start with "The"
            assert display_name.startswith("The ")
            # Should be title case
            assert display_name[0].isupper()


class TestArchetypePrompts:
    """Test archetype system prompts."""
    
    def test_all_archetypes_have_prompts(self):
        """Test all archetypes have system prompts."""
        assert len(COMEDY_STYLES) == 10  # Updated for based and gen_z archetypes
        
        for archetype_key, prompt in COMEDY_STYLES.items():
            assert isinstance(prompt, str)
            assert len(prompt) > 50  # Should be substantial
    
    def test_prompts_contain_key_elements(self):
        """Test prompts contain required elements."""
        for archetype_key, prompt in COMEDY_STYLES.items():
            # Each prompt should mention the archetype
            assert "You are" in prompt
            # Should specify word count
            assert "words" in prompt.lower()
            # Should specify one line
            assert "One line" in prompt or "one line" in prompt.lower()
    
    def test_prompts_specify_word_limit(self):
        """Test prompts specify word limits."""
        for archetype_key, prompt in COMEDY_STYLES.items():
            # Should mention word limit
            assert any(str(n) in prompt for n in range(10, 20))


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_empty_transcript(self):
        """Test handling of empty transcript."""
        metadata = _extract_meeting_metadata("")
        
        assert metadata['word_count'] == 0
        assert metadata['is_short'] is True
    
    def test_very_long_transcript(self):
        """Test handling of very long transcript."""
        transcript = "word " * 10000
        metadata = _extract_meeting_metadata(transcript)
        
        assert metadata['word_count'] == 10000
        assert metadata['is_long'] is True
    
    def test_transcript_with_special_characters(self):
        """Test handling of special characters."""
        transcript = "Meeting about @#$% and &*()!"
        metadata = _extract_meeting_metadata(transcript)
        
        # Should not crash
        assert 'word_count' in metadata
    
    def test_transcript_with_unicode(self):
        """Test handling of unicode characters."""
        transcript = "Meeting about café and naïve approaches 中文"
        metadata = _extract_meeting_metadata(transcript)
        
        # Should handle unicode
        assert 'word_count' in metadata
        assert metadata['word_count'] > 0


class TestIntegration:
    """Test integration scenarios."""
    
    @patch('scribe.utils.joke_generator.OpenAI')
    def test_full_pipeline_with_jargon_heavy_meeting(self, mock_openai_class, tmp_path):
        """Test full pipeline with jargon-heavy meeting."""
        transcript = """
        Meeting: Q4 Strategy Session
        Duration: 45 minutes
        
        We need to leverage our synergy to circle back on bandwidth alignment.
        Let's touch base on the action items and move the needle on our deep dive.
        We should table this discussion and revisit the parking lot items later.
        """
        
        transcript_path = tmp_path / "jargon_meeting.txt"
        transcript_path.write_text(transcript)
        
        mock_client = Mock()
        mock_openai_class.return_value = mock_client
        
        mock_response = Mock()
        mock_response.output_text = "We leveraged synergy until it filed for workers' comp."
        mock_client.responses.create.return_value = mock_response
        
        result = generate_transcript_joke(transcript_path, "test-key")
        
        assert result is not None
        joke_text, archetype = result
        
        # archetype is the display name (e.g., "The Trickster-Employee")
        # Just verify it's a valid string
        assert isinstance(archetype, str)
        assert len(archetype) > 0
        assert archetype.startswith("The ")
