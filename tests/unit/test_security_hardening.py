"""Tests for the security-hardening round (validation, traversal, DoS guards)."""

import math

import pytest

from scribe.exceptions import ValidationError
from scribe.models.transcript import TranscriptSegment
from scribe.utils.term_normalize import build_replacements
from scribe.utils.validation import sanitize_meeting_name, validate_media_url
from scribe.utils.vocabulary import MAX_GLOSSARY_BYTES, CustomVocabulary


class TestSsrfGuard:
    def test_normal_urls_pass(self):
        assert validate_media_url("https://youtube.com/watch?v=x").startswith("https://")
        assert validate_media_url("https://example.com/a.mp3")

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:8080/x",
            "http://127.0.0.1/admin",
            "http://169.254.169.254/latest/meta-data/",  # cloud metadata
            "http://10.0.0.5/x",
            "http://192.168.1.10/x",
            "http://[::1]/",
            "http://internal/x",  # bare hostname
        ],
    )
    def test_internal_targets_rejected(self, url, monkeypatch):
        monkeypatch.delenv("SCRIBE_ALLOW_LOCAL_URLS", raising=False)
        with pytest.raises(ValidationError):
            validate_media_url(url)

    def test_embedded_credentials_rejected(self, monkeypatch):
        monkeypatch.delenv("SCRIBE_ALLOW_LOCAL_URLS", raising=False)
        with pytest.raises(ValidationError):
            validate_media_url("https://user:pass@example.com/x")

    def test_local_allowed_with_optin(self, monkeypatch):
        monkeypatch.setenv("SCRIBE_ALLOW_LOCAL_URLS", "1")
        assert validate_media_url("http://localhost:8080/a.mp3").startswith("http://")


class TestReservedNames:
    @pytest.mark.parametrize("name", ["CON", "nul", "Aux", "COM1", "LPT9"])
    def test_reserved_device_names_are_prefixed(self, name):
        out = sanitize_meeting_name(name)
        assert out.split(".")[0].upper() not in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "LPT9",
        }
        assert out.startswith("_")

    def test_trailing_dots_and_spaces_stripped(self):
        assert sanitize_meeting_name("Meeting...  ") == "Meeting"


class TestTranscriptFiniteGuard:
    def test_nan_and_inf_rejected(self):
        with pytest.raises(ValueError):
            TranscriptSegment(start=math.nan, end=1.0, text="x")
        with pytest.raises(ValueError):
            TranscriptSegment(start=0.0, end=math.inf, text="x")

    def test_finite_still_ok(self):
        seg = TranscriptSegment(start=0.0, end=1.0, text="x")
        assert seg.end == 1.0


class TestGlossaryHardening:
    def test_named_glossary_rejects_unsafe_token(self, monkeypatch, tmp_path):
        monkeypatch.setattr("scribe.utils.vocabulary.Path.home", lambda: tmp_path)
        # Reaches the named branch (no separators, no .txt/.json, does not exist) but
        # is not a safe single token, so it is rejected rather than resolved.
        with pytest.raises(FileNotFoundError, match="Invalid glossary name"):
            CustomVocabulary.load("weird!name")

    def test_oversized_glossary_rejected(self, tmp_path):
        big = tmp_path / "big.txt"
        big.write_bytes(b"a\n" * (MAX_GLOSSARY_BYTES // 2 + 10))
        with pytest.raises(ValueError, match="too large"):
            CustomVocabulary.from_file(big)

    def test_single_char_aliases_dropped(self):
        # A 1-char alias matches everywhere; it must be dropped from the rule set.
        reps = build_replacements({"PostgreSQL": ["a", "post gray sequel"]})
        # Only the multi-char variant (plus the canonical self-map) survive.
        assert all(p.pattern for p, _ in reps)
        assert len(reps) == 2  # "PostgreSQL" self + "post gray sequel"
