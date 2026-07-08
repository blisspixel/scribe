"""Tests for shared CLI error handling."""

from pathlib import PurePosixPath

import pytest
import typer

from scribe.cli.errors import exit_on_cli_error
from scribe.exceptions import ValidationError
from scribe.utils.logging import setup_logging


def test_exit_on_cli_error_scribe_error():
    with pytest.raises(typer.Exit) as exc:
        exit_on_cli_error(
            ValidationError("bad input", context={"field": "name"}),
            log_unexpected=False,
        )
    assert exc.value.exit_code == 1


def test_exit_on_cli_error_prints_recovery_hint(capsys):
    with pytest.raises(typer.Exit) as exc:
        exit_on_cli_error(RuntimeError("boom"), log_unexpected=False)
    assert exc.value.exit_code == 1

    out = capsys.readouterr().out
    assert "Unexpected error:" in out
    assert "scribe doctor" in out
    assert "scribe support-bundle" in out


def test_exit_on_cli_error_prints_active_log_file(tmp_path, capsys):
    logger = setup_logging("cli_error_test", tmp_path)

    try:
        with pytest.raises(typer.Exit) as exc:
            exit_on_cli_error(RuntimeError("boom"), log_unexpected=False)
    finally:
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)

    assert exc.value.exit_code == 1
    log_file = next(tmp_path.glob("scribe_cli_error_test_*.log"))
    out = capsys.readouterr().out
    assert "Log file:" in out
    assert log_file.name in out


def test_exit_on_cli_error_keeps_long_log_file_path_literal(monkeypatch, capsys):
    filename = "scribe_cli_error_test_20260708_013224.log"
    log_file = PurePosixPath(
        f"/tmp/pytest-of-runner/pytest-0/test_exit_on_cli_error_prints_0/{filename}"
    )
    monkeypatch.setattr("scribe.cli.errors.get_current_log_file", lambda: log_file)

    with pytest.raises(typer.Exit) as exc:
        exit_on_cli_error(RuntimeError("boom"), log_unexpected=False)

    assert exc.value.exit_code == 1
    out = capsys.readouterr().out
    assert f"Log file: {log_file}" in out
    assert filename in out
