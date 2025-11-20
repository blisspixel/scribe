"""Tests for custom vocabulary support."""

import pytest
from pathlib import Path
import json
import tempfile

from scribe.utils.vocabulary import CustomVocabulary


class TestCustomVocabularyInit:
    """Test CustomVocabulary initialization."""
    
    def test_init_empty(self):
        """Test initialization with no words."""
        vocab = CustomVocabulary()
        assert len(vocab) == 0
        assert not bool(vocab)
        assert vocab.to_whisper_format() == ""
    
    def test_init_with_words(self):
        """Test initialization with word list."""
        words = ["Kubernetes", "PostgreSQL", "GraphQL"]
        vocab = CustomVocabulary(words)
        assert len(vocab) == 3
        assert bool(vocab)
        assert vocab.words == words


class TestCustomVocabularyFromFile:
    """Test loading vocabulary from files."""
    
    def test_load_from_txt_file(self, tmp_path):
        """Test loading from plain text file."""
        vocab_file = tmp_path / "vocab.txt"
        vocab_file.write_text("Kubernetes\nPostgreSQL\nGraphQL\n", encoding="utf-8")
        
        vocab = CustomVocabulary.from_file(vocab_file)
        assert len(vocab) == 3
        assert "Kubernetes" in vocab.words
        assert "PostgreSQL" in vocab.words
        assert "GraphQL" in vocab.words
    
    def test_load_from_txt_with_comments(self, tmp_path):
        """Test loading from text file with comments."""
        vocab_file = tmp_path / "vocab.txt"
        content = """# Cloud Services
Kubernetes
PostgreSQL

# Programming Languages
TypeScript
Python
"""
        vocab_file.write_text(content, encoding="utf-8")
        
        vocab = CustomVocabulary.from_file(vocab_file)
        assert len(vocab) == 4
        assert "Kubernetes" in vocab.words
        assert "TypeScript" in vocab.words
        # Comments should be excluded
        assert not any(word.startswith("#") for word in vocab.words)
    
    def test_load_from_txt_with_empty_lines(self, tmp_path):
        """Test loading from text file with empty lines."""
        vocab_file = tmp_path / "vocab.txt"
        content = "Kubernetes\n\nPostgreSQL\n\n\nGraphQL\n"
        vocab_file.write_text(content, encoding="utf-8")
        
        vocab = CustomVocabulary.from_file(vocab_file)
        assert len(vocab) == 3
    
    def test_load_from_json_file(self, tmp_path):
        """Test loading from JSON file."""
        vocab_file = tmp_path / "vocab.json"
        words = ["Kubernetes", "PostgreSQL", "GraphQL"]
        vocab_file.write_text(json.dumps(words), encoding="utf-8")
        
        vocab = CustomVocabulary.from_file(vocab_file)
        assert len(vocab) == 3
        assert vocab.words == words
    
    def test_load_from_json_with_whitespace(self, tmp_path):
        """Test loading from JSON with whitespace in words."""
        vocab_file = tmp_path / "vocab.json"
        words = ["  Kubernetes  ", "PostgreSQL", "  GraphQL"]
        vocab_file.write_text(json.dumps(words), encoding="utf-8")
        
        vocab = CustomVocabulary.from_file(vocab_file)
        assert len(vocab) == 3
        # Whitespace should be stripped
        assert "Kubernetes" in vocab.words
        assert "  Kubernetes  " not in vocab.words
    
    def test_load_from_nonexistent_file(self, tmp_path):
        """Test loading from nonexistent file raises error."""
        vocab_file = tmp_path / "nonexistent.txt"
        
        with pytest.raises(FileNotFoundError):
            CustomVocabulary.from_file(vocab_file)
    
    def test_load_from_unsupported_format(self, tmp_path):
        """Test loading from unsupported file format raises error."""
        vocab_file = tmp_path / "vocab.csv"
        vocab_file.write_text("word1,word2,word3", encoding="utf-8")
        
        with pytest.raises(ValueError, match="Unsupported vocabulary file format"):
            CustomVocabulary.from_file(vocab_file)
    
    def test_load_from_invalid_json(self, tmp_path):
        """Test loading from invalid JSON raises error."""
        vocab_file = tmp_path / "vocab.json"
        vocab_file.write_text("not valid json", encoding="utf-8")
        
        with pytest.raises(json.JSONDecodeError):
            CustomVocabulary.from_file(vocab_file)
    
    def test_load_from_json_non_array(self, tmp_path):
        """Test loading from JSON that's not an array raises error."""
        vocab_file = tmp_path / "vocab.json"
        vocab_file.write_text('{"words": ["test"]}', encoding="utf-8")
        
        with pytest.raises(ValueError, match="JSON file must contain an array"):
            CustomVocabulary.from_file(vocab_file)


class TestWhisperFormatConversion:
    """Test conversion to Whisper prompt format."""
    
    def test_to_whisper_format_empty(self):
        """Test conversion with empty vocabulary."""
        vocab = CustomVocabulary()
        assert vocab.to_whisper_format() == ""
    
    def test_to_whisper_format_single_word(self):
        """Test conversion with single word."""
        vocab = CustomVocabulary(["Kubernetes"])
        assert vocab.to_whisper_format() == "Kubernetes"
    
    def test_to_whisper_format_multiple_words(self):
        """Test conversion with multiple words."""
        vocab = CustomVocabulary(["Kubernetes", "PostgreSQL", "GraphQL"])
        result = vocab.to_whisper_format()
        assert result == "Kubernetes, PostgreSQL, GraphQL"
    
    def test_to_whisper_format_preserves_capitalization(self):
        """Test that capitalization is preserved."""
        vocab = CustomVocabulary(["PostgreSQL", "GraphQL", "OAuth"])
        result = vocab.to_whisper_format()
        assert "PostgreSQL" in result
        assert "GraphQL" in result
        assert "OAuth" in result


class TestVocabularyOperations:
    """Test vocabulary operations."""
    
    def test_len_operator(self):
        """Test __len__ operator."""
        vocab = CustomVocabulary(["word1", "word2", "word3"])
        assert len(vocab) == 3
    
    def test_bool_operator_empty(self):
        """Test __bool__ operator with empty vocabulary."""
        vocab = CustomVocabulary()
        assert not bool(vocab)
    
    def test_bool_operator_with_words(self):
        """Test __bool__ operator with words."""
        vocab = CustomVocabulary(["word1"])
        assert bool(vocab)


class TestRealWorldExamples:
    """Test with real-world vocabulary examples."""
    
    def test_technical_terms(self):
        """Test with technical terms."""
        words = [
            "Kubernetes",
            "PostgreSQL",
            "GraphQL",
            "TypeScript",
            "WebSocket",
            "OAuth",
            "JWT",
            "CI/CD"
        ]
        vocab = CustomVocabulary(words)
        
        assert len(vocab) == 8
        prompt = vocab.to_whisper_format()
        assert "Kubernetes" in prompt
        assert "CI/CD" in prompt
    
    def test_company_names(self):
        """Test with company names."""
        words = [
            "Acme Corporation",
            "TechStart Inc",
            "DataSync Pro",
            "CloudHub API"
        ]
        vocab = CustomVocabulary(words)
        
        assert len(vocab) == 4
        prompt = vocab.to_whisper_format()
        assert "Acme Corporation" in prompt
    
    def test_mixed_case_preservation(self):
        """Test that mixed case is preserved."""
        words = ["iPhone", "macOS", "iOS", "iPadOS"]
        vocab = CustomVocabulary(words)
        
        prompt = vocab.to_whisper_format()
        assert "iPhone" in prompt
        assert "macOS" in prompt
        assert "iOS" in prompt


class TestExampleFiles:
    """Test with actual example files from the project."""
    
    def test_example_vocabulary_txt_exists(self):
        """Test that example vocabulary.txt exists and loads."""
        example_file = Path("examples/vocabulary.txt")
        if example_file.exists():
            vocab = CustomVocabulary.from_file(example_file)
            assert len(vocab) > 0
            assert bool(vocab)
    
    def test_example_vocabulary_json_exists(self):
        """Test that example vocabulary.json exists and loads."""
        example_file = Path("examples/vocabulary.json")
        if example_file.exists():
            vocab = CustomVocabulary.from_file(example_file)
            assert len(vocab) > 0
            assert bool(vocab)


class TestEdgeCases:
    """Test edge cases and error conditions."""
    
    def test_unicode_characters(self, tmp_path):
        """Test handling of unicode characters."""
        vocab_file = tmp_path / "vocab.txt"
        content = "Café\nNaïve\n日本語\n"
        vocab_file.write_text(content, encoding="utf-8")
        
        vocab = CustomVocabulary.from_file(vocab_file)
        assert len(vocab) == 3
        assert "Café" in vocab.words
        assert "日本語" in vocab.words
    
    def test_very_long_word_list(self):
        """Test with very long word list."""
        words = [f"word{i}" for i in range(1000)]
        vocab = CustomVocabulary(words)
        
        assert len(vocab) == 1000
        prompt = vocab.to_whisper_format()
        assert "word0" in prompt
        assert "word999" in prompt
    
    def test_duplicate_words(self):
        """Test that duplicate words are kept (user's choice)."""
        words = ["Kubernetes", "PostgreSQL", "Kubernetes"]
        vocab = CustomVocabulary(words)
        
        # We keep duplicates as-is (user might want emphasis)
        assert len(vocab) == 3
    
    def test_empty_strings_filtered(self, tmp_path):
        """Test that empty strings are filtered out."""
        vocab_file = tmp_path / "vocab.txt"
        content = "Kubernetes\n\n  \n\t\nPostgreSQL\n"
        vocab_file.write_text(content, encoding="utf-8")
        
        vocab = CustomVocabulary.from_file(vocab_file)
        assert len(vocab) == 2
        assert "" not in vocab.words
