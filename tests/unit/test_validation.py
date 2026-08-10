"""
Unit tests for input validation utilities.

Tests validation functions for file paths, API keys, meeting names,
and other user inputs with defensive programming.
"""

from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from scribe.exceptions import ValidationError
from scribe.utils.validation import (
    sanitize_meeting_name,
    validate_api_key,
    validate_audio_file,
    validate_directory_path,
    validate_email,
    validate_file_path,
    validate_language_code,
    validate_model_name,
    validate_port,
    validate_positive_number,
    validate_url,
)


class TestValidateFilePath:
    """Test file path validation."""

    def test_validate_existing_file(self, sample_audio: Path):
        """Test validation of existing file."""
        result = validate_file_path(str(sample_audio))
        assert result == sample_audio
        assert result.is_absolute()

    def test_validate_file_with_quotes(self, sample_audio: Path):
        """Test validation removes quotes from path."""
        quoted_path = f'"{sample_audio}"'
        result = validate_file_path(quoted_path)
        assert result == sample_audio

    def test_validate_empty_path(self):
        """Test validation fails for empty path."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_file_path("")

        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_file_path("   ")

    def test_validate_nonexistent_file_must_exist(self, temp_dir: Path):
        """Test validation fails for non-existent file when must_exist=True."""
        fake_file = temp_dir / "nonexistent.txt"

        with pytest.raises(ValidationError, match="does not exist"):
            validate_file_path(str(fake_file), must_exist=True)

    def test_validate_nonexistent_file_optional(self, temp_dir: Path):
        """Test validation passes for non-existent file when must_exist=False."""
        fake_file = temp_dir / "nonexistent.txt"

        result = validate_file_path(str(fake_file), must_exist=False)
        assert result.name == "nonexistent.txt"


class TestValidateDirectoryPath:
    """Test directory path validation."""

    def test_validate_existing_directory(self, temp_dir: Path):
        """Test validation of existing directory."""
        result = validate_directory_path(str(temp_dir))
        assert result == temp_dir

    def test_validate_create_directory(self, temp_dir: Path):
        """Test validation creates directory if it doesn't exist."""
        new_dir = temp_dir / "new_directory"
        assert not new_dir.exists()

        result = validate_directory_path(str(new_dir), create=True)
        assert result == new_dir
        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_validate_empty_directory_path(self):
        """Test validation fails for empty directory path."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_directory_path("")


class TestValidateAudioFile:
    """Test audio file validation."""

    def test_validate_valid_audio(self, sample_audio: Path):
        """Test validation of valid audio file."""
        result = validate_audio_file(str(sample_audio))
        assert result == sample_audio

    def test_validate_unsupported_format(self, temp_dir: Path):
        """Test validation fails for unsupported format."""
        bad_file = temp_dir / "test.xyz"
        bad_file.write_text("content")

        with pytest.raises(ValidationError, match="Unsupported audio format"):
            validate_audio_file(str(bad_file))

    def test_validate_empty_audio_file(self, temp_dir: Path):
        """Test validation fails for empty file."""
        empty_file = temp_dir / "empty.wav"
        empty_file.write_bytes(b"")

        with pytest.raises(ValidationError, match="is empty"):
            validate_audio_file(str(empty_file))


class TestValidateAPIKey:
    """Test API key validation."""

    def test_validate_valid_api_key(self):
        """Test validation of valid API key."""
        valid_key = "sk-proj-1234567890abcdefghijklmnopqrstuvwxyz"
        result = validate_api_key(valid_key)
        assert result == valid_key

    def test_validate_empty_api_key(self):
        """Test validation fails for empty API key."""
        with pytest.raises(ValidationError, match="is required"):
            validate_api_key("")

        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_api_key("   ")

    def test_validate_short_api_key(self):
        """Test validation fails for too short API key."""
        with pytest.raises(ValidationError, match="too short"):
            validate_api_key("sk-123")

    def test_validate_invalid_prefix(self):
        """Test validation fails for invalid prefix."""
        with pytest.raises(ValidationError, match="should start with"):
            validate_api_key("invalid-1234567890abcdefghijklmnopqrstuvwxyz")


class TestSanitizeMeetingName:
    """Test meeting name sanitization."""

    def test_sanitize_basic_name(self):
        """Test sanitization of basic meeting name."""
        result = sanitize_meeting_name("Team Meeting")
        assert result == "Team_Meeting"

    def test_sanitize_special_characters(self):
        """Test sanitization removes special characters."""
        result = sanitize_meeting_name("Project: Q4 Review (2025)")
        assert result == "Project_Q4_Review_(2025)"

    def test_sanitize_multiple_spaces(self):
        """Test sanitization handles multiple spaces."""
        result = sanitize_meeting_name("Meeting   with    spaces")
        assert result == "Meeting_with_spaces"

    def test_sanitize_leading_trailing_spaces(self):
        """Test sanitization removes leading/trailing spaces."""
        result = sanitize_meeting_name("  Meeting Name  ")
        assert result == "Meeting_Name"

    def test_sanitize_empty_name(self):
        """Test sanitization of empty name raises error."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            sanitize_meeting_name("")

        with pytest.raises(ValidationError, match="cannot be empty"):
            sanitize_meeting_name("   ")


class TestValidateModelName:
    """Test model name validation."""

    def test_validate_valid_whisper_models(self):
        """Test validation of valid Whisper model names."""
        valid_models = [
            "tiny",
            "base",
            "small",
            "medium",
            "large",
            "large-v2",
            "large-v3",
            "large-v3-turbo",
            "turbo",
        ]

        for model in valid_models:
            result = validate_model_name(model, valid_models)
            assert result == model

    def test_validate_invalid_model(self):
        """Test validation fails for invalid model name."""
        valid_models = ["tiny", "base", "small"]
        with pytest.raises(ValidationError, match="Invalid model"):
            validate_model_name("invalid-model", valid_models)

    def test_validate_empty_model(self):
        """Test validation fails for empty model name."""
        valid_models = ["tiny", "base"]
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_model_name("", valid_models)


class TestValidateLanguageCode:
    """Test language code validation."""

    def test_validate_valid_language_codes(self):
        """Test validation of valid language codes."""
        valid_codes = ["en", "es", "fr", "de", "zh", "ja", "ko"]

        for code in valid_codes:
            result = validate_language_code(code)
            assert result == code

    def test_validate_language_names(self):
        """Test validation accepts full language names."""
        assert validate_language_code("english") == "en"
        assert validate_language_code("spanish") == "es"
        assert validate_language_code("french") == "fr"
        assert validate_language_code("german") == "de"
        assert validate_language_code("japanese") == "ja"
        assert validate_language_code("chinese") == "zh"

    def test_validate_native_script_names_resolve_to_iso(self):
        """Non-ASCII 2-char native names must resolve via aliases, not pass through.

        Regression: the 2-letter shortcut used only len()==2 and .isalpha(), so a
        CJK name like the native word for Chinese (2 chars, alphabetic) was returned
        verbatim as a bogus 'code' instead of resolving to its ISO 639-1 value.
        """
        assert validate_language_code("中文") == "zh"  # Chinese (Zhōngwén)

    def test_validate_auto_language(self):
        """Test validation rejects 'auto' (not a valid language)."""
        with pytest.raises(ValidationError, match="Unknown language"):
            validate_language_code("auto")

    def test_validate_invalid_language_code(self):
        """Test validation fails for invalid language code."""
        with pytest.raises(ValidationError, match="Unknown language"):
            validate_language_code("invalid")

    def test_validate_empty_language_code(self):
        """Test validation fails for empty language code."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_language_code("")


class TestValidatePort:
    """Test port number validation."""

    def test_validate_valid_ports(self):
        """Test validation of valid port numbers."""
        valid_ports = [80, 443, 8080, 3000, 5000]

        for port in valid_ports:
            result = validate_port(port)
            assert result == port

    def test_validate_port_too_low(self):
        """Test validation fails for port below 1."""
        with pytest.raises(ValidationError, match="must be between"):
            validate_port(0)

        with pytest.raises(ValidationError, match="must be between"):
            validate_port(-1)

    def test_validate_port_too_high(self):
        """Test validation fails for port above 65535."""
        with pytest.raises(ValidationError, match="must be between"):
            validate_port(65536)

        with pytest.raises(ValidationError, match="must be between"):
            validate_port(100000)


class TestValidatePositiveNumber:
    """Test positive number validation."""

    def test_validate_positive_integers(self):
        """Test validation of positive integers."""
        assert validate_positive_number(1) == 1
        assert validate_positive_number(100) == 100
        assert validate_positive_number(999999) == 999999

    def test_validate_positive_floats(self):
        """Test validation of positive floats."""
        assert validate_positive_number(0.1) == 0.1
        assert validate_positive_number(3.14) == 3.14
        assert validate_positive_number(99.99) == 99.99

    def test_validate_zero(self):
        """Test validation allows zero by default (min_value=0.0)."""
        # Zero is allowed by default
        assert validate_positive_number(0) == 0.0

        # But can be rejected with min_value > 0
        with pytest.raises(ValidationError, match=r"must be >= 0.1"):
            validate_positive_number(0, min_value=0.1)

    def test_validate_negative_number(self):
        """Test validation fails for negative numbers."""
        with pytest.raises(ValidationError, match=r"must be >= 0.0"):
            validate_positive_number(-1)

        with pytest.raises(ValidationError, match=r"must be >= 0.0"):
            validate_positive_number(-3.14)


class TestValidateEmail:
    """Test email validation."""

    def test_validate_valid_emails(self):
        """Test validation of valid email addresses."""
        valid_emails = [
            "user@example.com",
            "test.user@example.co.uk",
            "user+tag@example.com",
            "user_name@example-domain.com",
        ]

        for email in valid_emails:
            result = validate_email(email)
            assert result == email

    def test_validate_invalid_emails(self):
        """Test validation fails for invalid email addresses."""
        invalid_emails = [
            "not-an-email",
            "@example.com",
            "user@",
            "user @example.com",
            "user@example",
        ]

        for email in invalid_emails:
            with pytest.raises(ValidationError, match="Invalid email"):
                validate_email(email)

    def test_validate_empty_email(self):
        """Test validation fails for empty email."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_email("")


class TestValidateURL:
    """Test URL validation."""

    def test_validate_valid_urls(self):
        """Test validation of valid URLs."""
        valid_urls = [
            "http://example.com",
            "https://example.com",
            "https://www.example.com/path",
            "http://localhost:8080",
            "https://example.com:443/path?query=value",
        ]

        for url in valid_urls:
            result = validate_url(url)
            assert result == url

    def test_validate_invalid_urls(self):
        """Test validation fails for invalid URLs."""
        invalid_urls = [
            "not-a-url",
            "ftp://example.com",  # Only http/https allowed
            "example.com",  # Missing scheme
            "http://",  # Missing domain
        ]

        for url in invalid_urls:
            with pytest.raises(ValidationError, match="Invalid URL"):
                validate_url(url)

    def test_validate_empty_url(self):
        """Test validation fails for empty URL."""
        with pytest.raises(ValidationError, match="cannot be empty"):
            validate_url("")


class TestValidationProperties:
    """Property-based invariants for pure validation helpers."""

    @given(st.integers(min_value=1, max_value=65535))
    def test_validate_port_roundtrip(self, port: int):
        """Valid ports pass through unchanged."""
        assert validate_port(port) == port

    @given(
        st.text(
            alphabet=st.characters(blacklist_categories=("Cs",), blacklist_characters='<>:"/\\|?*'),
            min_size=1,
            max_size=50,
        ).filter(lambda s: s.strip() and any(ch.isalnum() for ch in s))
    )
    def test_sanitize_meeting_name_produces_safe_filename(self, name: str):
        """Sanitized names stay within length bounds and avoid Windows reserved stems."""
        result = sanitize_meeting_name(name)
        assert result
        assert len(result) <= 100
        assert not any(ch in result for ch in '<>:"/\\|?*')
        assert result.split(".")[0].upper() not in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }

    @given(st.floats(min_value=0.0, max_value=1_000_000, allow_nan=False, allow_infinity=False))
    def test_validate_positive_number_respects_minimum(self, value: float):
        """Non-negative values return a float >= the configured minimum."""
        assert validate_positive_number(value) >= 0.0
