"""Tests for the one-time recording-consent gate (cli/consent.py)."""

import io
from unittest.mock import patch

from rich.console import Console

from scribe.cli import consent


def _console() -> Console:
    return Console(file=io.StringIO())


def test_assume_consent_env_skips_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("SCRIBE_ASSUME_CONSENT", "1")
    monkeypatch.setattr(consent.Path, "home", lambda: tmp_path)
    assert consent.ensure_recording_consent(_console()) is True


def test_existing_marker_skips_prompt(monkeypatch, tmp_path):
    monkeypatch.delenv("SCRIBE_ASSUME_CONSENT", raising=False)
    monkeypatch.setattr(consent.Path, "home", lambda: tmp_path)
    marker = tmp_path / ".scribe" / "recording_consent_ack"
    marker.parent.mkdir(parents=True)
    marker.write_text("acknowledged\n", encoding="utf-8")
    assert consent.ensure_recording_consent(_console()) is True


def test_non_interactive_proceeds_without_prompt(monkeypatch, tmp_path):
    monkeypatch.delenv("SCRIBE_ASSUME_CONSENT", raising=False)
    monkeypatch.setattr(consent.Path, "home", lambda: tmp_path)
    # Non-tty stdin simulates piping/CI: cannot prompt, so it proceeds.
    monkeypatch.setattr(consent.sys.stdin, "isatty", lambda: False)
    assert consent.ensure_recording_consent(_console()) is True
    # No marker written on the non-interactive path.
    assert not (tmp_path / ".scribe" / "recording_consent_ack").exists()


def test_interactive_yes_writes_marker(monkeypatch, tmp_path):
    monkeypatch.delenv("SCRIBE_ASSUME_CONSENT", raising=False)
    monkeypatch.setattr(consent.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(consent.sys.stdin, "isatty", lambda: True)
    with patch("scribe.cli.consent.typer.confirm", return_value=True):
        assert consent.ensure_recording_consent(_console()) is True
    assert (tmp_path / ".scribe" / "recording_consent_ack").exists()


def test_interactive_no_blocks_and_no_marker(monkeypatch, tmp_path):
    monkeypatch.delenv("SCRIBE_ASSUME_CONSENT", raising=False)
    monkeypatch.setattr(consent.Path, "home", lambda: tmp_path)
    monkeypatch.setattr(consent.sys.stdin, "isatty", lambda: True)
    with patch("scribe.cli.consent.typer.confirm", return_value=False):
        assert consent.ensure_recording_consent(_console()) is False
    assert not (tmp_path / ".scribe" / "recording_consent_ack").exists()
