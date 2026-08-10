"""Tests for shared CLI error handling."""

from pathlib import PurePosixPath
from unittest.mock import patch

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


def test_exit_on_cli_error_renders_dynamic_markup_literally(capsys):
    with pytest.raises(typer.Exit):
        exit_on_cli_error(
            ValidationError("bad [/] input", context={"field": "value [/]"}),
            log_unexpected=False,
        )

    out = capsys.readouterr().out
    assert "bad [/] input" in out
    assert "value [/]" in out


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


@pytest.mark.parametrize(
    "terminal_error",
    [
        BrokenPipeError("closed terminal"),
        OSError("terminal unavailable"),
        UnicodeEncodeError("cp1252", "\u2500", 0, 1, "character maps to undefined"),
        ValueError("I/O operation on closed file"),
    ],
    ids=["broken-pipe", "os-error", "encoding", "closed-stream"],
)
def test_exit_on_cli_error_has_stable_exit_when_terminal_is_unavailable(terminal_error, capsys):
    original = RuntimeError("backend failed")

    with (
        patch("scribe.cli.errors.console.print", side_effect=terminal_error),
        patch("scribe.cli.errors.get_current_log_file", return_value=None),
        patch("scribe.cli.errors.logger.error") as unexpected_log,
        pytest.raises(typer.Exit) as raised,
    ):
        exit_on_cli_error(original)

    assert raised.value.exit_code == 1
    assert raised.value.__cause__ is original
    unexpected_log.assert_not_called()
    captured = capsys.readouterr()
    assert "Terminal output unavailable" in captured.err
    assert "See log:" not in captured.err
    assert "Logging error" not in captured.err


def test_exit_on_cli_error_fallback_cannot_replace_stable_exit(capsys):
    original = RuntimeError("backend failed")

    with (
        patch(
            "scribe.cli.errors.console.print",
            side_effect=BrokenPipeError("closed terminal"),
        ),
        patch("scribe.cli.errors.get_current_log_file", return_value=None),
        patch("scribe.cli.errors.sys.stderr.write", side_effect=RuntimeError("stderr wrapper")),
        pytest.raises(typer.Exit) as raised,
    ):
        exit_on_cli_error(original, log_unexpected=False)

    assert raised.value.exit_code == 1
    assert raised.value.__cause__ is original
    assert "Logging error" not in capsys.readouterr().err


@pytest.mark.parametrize(
    "terminal_error",
    [
        BrokenPipeError("closed terminal"),
        UnicodeEncodeError("cp1252", "\u2500", 0, 1, "character maps to undefined"),
    ],
    ids=["broken-pipe", "encoding"],
)
def test_exit_on_cli_error_preserves_file_log_without_recursive_traceback(
    tmp_path, capsys, terminal_error
):
    configured_logger = setup_logging("persistent_terminal", tmp_path)
    original = RuntimeError("backend failed")

    try:
        with (
            patch(
                "scribe.cli.errors.console.print",
                side_effect=terminal_error,
            ),
            pytest.raises(typer.Exit) as raised,
        ):
            try:
                raise original
            except RuntimeError as error:
                exit_on_cli_error(error)
    finally:
        for handler in configured_logger.handlers[:]:
            handler.close()
            configured_logger.removeHandler(handler)

    assert raised.value.exit_code == 1
    assert raised.value.__cause__ is original
    log_text = next(tmp_path.glob("scribe_persistent_terminal_*.log")).read_text(encoding="utf-8")
    assert "Unexpected CLI error" in log_text
    assert "backend failed" in log_text
    assert "Terminal output failed" in log_text
    captured = capsys.readouterr()
    assert "Terminal output unavailable" in captured.err
    assert "--- Logging error ---" not in captured.err


def test_exit_on_cli_error_logs_supplied_exception_outside_handler(tmp_path, capsys):
    configured_logger = setup_logging("outside_handler", tmp_path)
    original = RuntimeError("backend failed")

    try:
        with pytest.raises(typer.Exit):
            exit_on_cli_error(original)
    finally:
        for handler in configured_logger.handlers[:]:
            handler.close()
            configured_logger.removeHandler(handler)

    log_text = next(tmp_path.glob("scribe_outside_handler_*.log")).read_text(encoding="utf-8")
    assert "RuntimeError: backend failed" in log_text
    assert "NoneType: None" not in log_text
    capsys.readouterr()
