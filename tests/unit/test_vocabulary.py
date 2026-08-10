"""Tests for custom vocabulary support."""

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scribe.utils.vocabulary import CustomVocabulary, build_deduped_prompt


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
            "CI/CD",
        ]
        vocab = CustomVocabulary(words)

        assert len(vocab) == 8
        prompt = vocab.to_whisper_format()
        assert "Kubernetes" in prompt
        assert "CI/CD" in prompt

    def test_company_names(self):
        """Test with company names."""
        words = ["Example Company", "Sample Organization", "Example Product", "Demo API"]
        vocab = CustomVocabulary(words)

        assert len(vocab) == 4
        prompt = vocab.to_whisper_format()
        assert "Example Company" in prompt

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


class TestGlossaryExtensions:
    """Aliases, budgeted prompt, and name resolution."""

    def test_txt_alias_syntax(self, tmp_path):
        f = tmp_path / "g.txt"
        f.write_text(
            "# domain\nPostgreSQL = post gray sequel, postgres sql\nKubernetes\n",
            encoding="utf-8",
        )
        vocab = CustomVocabulary.from_file(f)
        assert "PostgreSQL" in vocab.words
        assert "Kubernetes" in vocab.words
        assert vocab.aliases["PostgreSQL"] == ["post gray sequel", "postgres sql"]
        assert "Kubernetes" not in vocab.aliases

    def test_json_terms_and_aliases_object(self, tmp_path):
        f = tmp_path / "g.json"
        f.write_text(
            json.dumps({"terms": ["EBITDA"], "aliases": {"EBITDA": ["e bit duh"]}}),
            encoding="utf-8",
        )
        vocab = CustomVocabulary.from_file(f)
        assert "EBITDA" in vocab.words
        assert vocab.aliases["EBITDA"] == ["e bit duh"]

    def test_json_non_terms_object_still_raises(self, tmp_path):
        f = tmp_path / "g.json"
        f.write_text('{"words": ["x"]}', encoding="utf-8")
        with pytest.raises(ValueError, match="JSON file must contain an array"):
            CustomVocabulary.from_file(f)

    @pytest.mark.parametrize(
        "payload",
        [
            {"terms": "Alpha"},
            {"terms": ["Alpha"], "aliases": {"Alpha": "ale fah"}},
            {"terms": ["Alpha", 7]},
            ["Alpha", 7],
        ],
    )
    def test_json_rejects_non_string_collection_shapes(self, tmp_path, payload):
        f = tmp_path / "invalid.json"
        f.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError, match=r"strings|string"):
            CustomVocabulary.from_file(f)

    def test_to_prompt_dedups_and_budgets(self):
        vocab = CustomVocabulary(["Alpha", "alpha", "Beta"])
        # Case-insensitive dedup keeps the first form.
        assert vocab.to_prompt() == "Alpha, Beta"
        many = CustomVocabulary([f"term{i}" for i in range(500)])
        prompt = many.to_prompt(max_chars=50)
        assert len(prompt) <= 50
        assert prompt.startswith("term0")

    def test_load_resolves_user_glossary(self, tmp_path, monkeypatch):
        vocab_dir = tmp_path / ".scribe" / "vocab"
        vocab_dir.mkdir(parents=True)
        (vocab_dir / "mine.txt").write_text("ExampleTerm\n", encoding="utf-8")
        monkeypatch.setattr("scribe.utils.vocabulary.Path.home", lambda: tmp_path)
        vocab = CustomVocabulary.load("mine")
        assert "ExampleTerm" in vocab.words

    def test_load_resolves_bundled_preset(self):
        # The shipped presets resolve by bare name.
        tech = CustomVocabulary.load("tech")
        assert "PostgreSQL" in tech.words
        assert tech.aliases  # presets carry aliases

    def test_load_unknown_name_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("scribe.utils.vocabulary.Path.home", lambda: tmp_path)
        with pytest.raises(FileNotFoundError, match="No glossary named"):
            CustomVocabulary.load("does-not-exist")

    def test_load_path_still_works(self, tmp_path):
        f = tmp_path / "terms.txt"
        f.write_text("ExampleTerm\n", encoding="utf-8")
        vocab = CustomVocabulary.load(str(f))
        assert "ExampleTerm" in vocab.words

    def test_normalize_transcript_via_vocab(self):
        from scribe.models.transcript import Transcript, TranscriptSegment

        vocab = CustomVocabulary(["PostgreSQL"], {"PostgreSQL": ["post gray sequel"]})
        t = Transcript(segments=[TranscriptSegment(0.0, 1.0, "post gray sequel")], backend="x")
        out = vocab.normalize_transcript(t)
        assert out.segments[0].text == "PostgreSQL"


class TestVocabCommand:
    """The `scribe vocab` listing/show command."""

    def test_vocab_list_shows_presets(self):
        from typer.testing import CliRunner

        from scribe.cli.main import app

        result = CliRunner().invoke(app, ["vocab"])
        assert result.exit_code == 0
        assert "tech" in result.output and "finance" in result.output

    def test_vocab_show_lists_terms_and_aliases(self):
        from typer.testing import CliRunner

        from scribe.cli.main import app

        result = CliRunner().invoke(app, ["vocab", "tech"])
        assert result.exit_code == 0
        assert "PostgreSQL" in result.output

    def test_vocab_show_unknown_exits_nonzero(self):
        from typer.testing import CliRunner

        from scribe.cli.main import app

        result = CliRunner().invoke(app, ["vocab", "definitely-not-a-glossary-xyz"])
        assert result.exit_code == 1


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


class TestVocabularyProperties:
    """Property-based invariants for vocabulary formatting."""

    @given(
        st.lists(
            st.text(
                alphabet=st.characters(blacklist_characters=",\n\r"),
                min_size=1,
                max_size=30,
            )
            .map(str.strip)
            .filter(bool),
            max_size=25,
        )
    )
    def test_to_whisper_format_is_comma_join_or_empty(self, words: list[str]) -> None:
        vocab = CustomVocabulary(words)
        result = vocab.to_whisper_format()
        if not words:
            assert result == ""
        else:
            assert result == ", ".join(words)
            assert all(part in result for part in words)

    @given(
        st.lists(
            st.text(
                alphabet=st.characters(blacklist_characters=",\n\r"),
                min_size=1,
                max_size=20,
            )
            .map(str.strip)
            .filter(bool),
            max_size=30,
        ),
        st.integers(min_value=1, max_value=200),
    )
    def test_build_deduped_prompt_is_str_within_budget(
        self, words: list[str], max_chars: int
    ) -> None:
        result = build_deduped_prompt(words, max_chars)
        assert isinstance(result, str)
        if not words:
            assert result == ""
            return

        # Case-insensitive duplicates collapse to the first spelling.
        seen: set[str] = set()
        expected_unique: list[str] = []
        for word in words:
            key = word.lower()
            if key not in seen:
                seen.add(key)
                expected_unique.append(word)

        kept: list[str] = []
        for word in expected_unique:
            candidate = ", ".join([*kept, word])
            if kept and len(candidate) > max_chars:
                break
            kept.append(word)
        assert result == ", ".join(kept)
        if len(kept) > 1:
            assert len(result) <= max_chars
