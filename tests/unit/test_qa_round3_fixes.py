"""Tests for the QA round 3 fixes (wizard, support bundle, diagnostics, platform, files)."""

from pathlib import Path
from unittest.mock import patch

from scribe.utils.diagnostics import SystemDiagnostics
from scribe.utils.files import extract_date_from_filename, format_duration_minutes
from scribe.utils.platform import normalize_path
from scribe.utils.support_bundle import _redact_user


class TestDateValidation:
    def test_invalid_iso_date_is_rejected(self):
        # An impossible calendar date must not be echoed as a valid date.
        assert extract_date_from_filename("Meeting_2025-13-45.mp4") is None
        assert extract_date_from_filename("call_2025-02-30.mp4") is None

    def test_valid_iso_date_is_returned(self):
        assert extract_date_from_filename("Meeting_2025-11-07.mp4") == "2025-11-07"


class TestDurationClamp:
    def test_negative_seconds_clamped(self):
        assert format_duration_minutes(-5) == "0 minutes"

    def test_normal_duration(self):
        assert format_duration_minutes(3661) == "1 hour 1 minute"


class TestNormalizePathQuotes:
    def test_balanced_quotes_stripped(self):
        assert normalize_path('"x.txt"').name == "x.txt"
        assert normalize_path("'x.txt'").name == "x.txt"

    def test_unbalanced_quote_preserved(self):
        # A name that legitimately ends in a quote must not lose it.
        assert normalize_path('a"b.txt').name == 'a"b.txt'


class TestRedactUser:
    def test_home_and_user_redacted(self):
        home = str(Path.home())
        user = Path.home().name
        redacted = _redact_user(f"{home}/projects and {user} stuff")
        assert home not in redacted
        assert "~" in redacted
        if user:
            assert user not in redacted


class TestDiagnosticsIsolation:
    def test_one_failing_check_does_not_abort_run(self):
        diag = SystemDiagnostics()
        with patch.object(diag, "check_ffmpeg", side_effect=RuntimeError("boom")):
            results = diag.run_all_checks(live=False)
        # The run completed and recorded a failure for the broken check.
        assert any(r.status == "fail" and "unexpected error" in r.message for r in results)
        # Other checks still ran.
        assert len(results) > 5

    def test_live_false_skips_api_network_checks(self):
        diag = SystemDiagnostics()
        with patch.object(diag, "check_openai_api_key") as mock_key:
            diag.run_all_checks(live=False)
        mock_key.assert_not_called()

    def test_default_skips_api_network_checks(self):
        diag = SystemDiagnostics()
        with patch.object(diag, "check_openai_api_key") as mock_key:
            diag.run_all_checks()
        mock_key.assert_not_called()

    def test_live_true_runs_api_checks(self):
        diag = SystemDiagnostics()
        with patch.object(diag, "check_openai_api_key") as mock_key:
            with patch.object(diag, "check_additional_providers"):
                diag.run_all_checks(live=True)
        mock_key.assert_called_once()
