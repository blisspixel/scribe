"""
Unit tests for meme generator.

Tests AI-generated meme creation from meeting transcripts.
"""

import os
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from scribe.utils.meme_generator import MemeConfig


class TestMemeConfig:
    """Test meme configuration."""
    
    def test_default_config(self):
        """Test default meme configuration."""
        config = MemeConfig()
        
        assert config.model == "gpt-5"
        assert config.image_model == "gpt-image-1"
        assert config.size == "1024x1024"
        assert config.quality == "high"
        assert config.output_format == "png"
        assert config.qa_enabled is True
        assert config.qa_threshold == 8.0
        assert config.max_retries == 3
    
    def test_custom_config(self):
        """Test custom meme configuration."""
        config = MemeConfig(
            qa_enabled=False,
            qa_threshold=8.0,
            max_retries=5
        )
        
        assert config.qa_enabled is False
        assert config.qa_threshold == 8.0
        assert config.max_retries == 5
    
    def test_from_env_defaults(self):
        """Test from_env with no environment variables set."""
        with patch.dict(os.environ, {}, clear=False):
            # Remove any existing env vars
            os.environ.pop('SCRIBE_MEME_QA_THRESHOLD', None)
            os.environ.pop('SCRIBE_MEME_QA_ATTEMPTS', None)
            
            config = MemeConfig.from_env()
            
            assert config.qa_threshold == 8.0
            assert config.max_retries == 3
    
    def test_from_env_custom_threshold(self):
        """Test from_env with custom QA threshold."""
        with patch.dict(os.environ, {'SCRIBE_MEME_QA_THRESHOLD': '8.5'}):
            config = MemeConfig.from_env()
            
            assert config.qa_threshold == 8.5
    
    def test_from_env_custom_attempts(self):
        """Test from_env with custom max attempts."""
        with patch.dict(os.environ, {'SCRIBE_MEME_QA_ATTEMPTS': '5'}):
            config = MemeConfig.from_env()
            
            assert config.max_retries == 5
    
    def test_from_env_invalid_threshold_too_low(self):
        """Test from_env with invalid threshold (too low)."""
        with patch.dict(os.environ, {'SCRIBE_MEME_QA_THRESHOLD': '-1.0'}):
            config = MemeConfig.from_env()
            
            # Should use default
            assert config.qa_threshold == 8.0
    
    def test_from_env_invalid_threshold_too_high(self):
        """Test from_env with invalid threshold (too high)."""
        with patch.dict(os.environ, {'SCRIBE_MEME_QA_THRESHOLD': '11.0'}):
            config = MemeConfig.from_env()
            
            # Should use default
            assert config.qa_threshold == 8.0
    
    def test_from_env_invalid_threshold_not_number(self):
        """Test from_env with invalid threshold (not a number)."""
        with patch.dict(os.environ, {'SCRIBE_MEME_QA_THRESHOLD': 'invalid'}):
            config = MemeConfig.from_env()
            
            # Should use default
            assert config.qa_threshold == 8.0
    
    def test_from_env_invalid_attempts_too_low(self):
        """Test from_env with invalid attempts (too low)."""
        with patch.dict(os.environ, {'SCRIBE_MEME_QA_ATTEMPTS': '0'}):
            config = MemeConfig.from_env()
            
            # Should use default
            assert config.max_retries == 3
    
    def test_from_env_invalid_attempts_too_high(self):
        """Test from_env with invalid attempts (too high)."""
        with patch.dict(os.environ, {'SCRIBE_MEME_QA_ATTEMPTS': '11'}):
            config = MemeConfig.from_env()
            
            # Should use default
            assert config.max_retries == 3
    
    def test_from_env_invalid_attempts_not_integer(self):
        """Test from_env with invalid attempts (not an integer)."""
        with patch.dict(os.environ, {'SCRIBE_MEME_QA_ATTEMPTS': 'five'}):
            config = MemeConfig.from_env()
            
            # Should use default
            assert config.max_retries == 3
    
    def test_from_env_both_custom(self):
        """Test from_env with both threshold and attempts custom."""
        with patch.dict(os.environ, {
            'SCRIBE_MEME_QA_THRESHOLD': '7.5',
            'SCRIBE_MEME_QA_ATTEMPTS': '4'
        }):
            config = MemeConfig.from_env()
            
            assert config.qa_threshold == 7.5
            assert config.max_retries == 4
    
    def test_from_env_custom_spice_level(self):
        """Test from_env with custom spice level."""
        with patch.dict(os.environ, {'SCRIBE_HUMOR_SPICE': '8'}):
            config = MemeConfig.from_env()
            
            assert config.spice_level == 8
    
    def test_from_env_invalid_spice_too_low(self):
        """Test from_env with invalid spice level (too low)."""
        with patch.dict(os.environ, {'SCRIBE_HUMOR_SPICE': '-1'}):
            config = MemeConfig.from_env()
            
            # Should use default
            assert config.spice_level == 5
    
    def test_from_env_invalid_spice_too_high(self):
        """Test from_env with invalid spice level (too high)."""
        with patch.dict(os.environ, {'SCRIBE_HUMOR_SPICE': '11'}):
            config = MemeConfig.from_env()
            
            # Should use default
            assert config.spice_level == 5
    
    def test_from_env_invalid_spice_not_integer(self):
        """Test from_env with invalid spice level (not an integer)."""
        with patch.dict(os.environ, {'SCRIBE_HUMOR_SPICE': 'spicy'}):
            config = MemeConfig.from_env()
            
            # Should use default
            assert config.spice_level == 5
    
    def test_from_env_all_custom(self):
        """Test from_env with all settings custom."""
        with patch.dict(os.environ, {
            'SCRIBE_MEME_QA_THRESHOLD': '7.5',
            'SCRIBE_MEME_QA_ATTEMPTS': '4',
            'SCRIBE_HUMOR_SPICE': '8'
        }):
            config = MemeConfig.from_env()
            
            assert config.qa_threshold == 7.5
            assert config.max_retries == 4
            assert config.spice_level == 8


# TODO: Add integration tests for meme generation with proper mocking
# The QA loop and refinement features need complex mocking that requires more setup
