"""Tests for shared CLI error handling."""

import pytest
import typer

from scribe.cli.errors import exit_on_cli_error
from scribe.exceptions import ValidationError


def test_exit_on_cli_error_scribe_error():
    with pytest.raises(typer.Exit) as exc:
        exit_on_cli_error(
            ValidationError("bad input", context={"field": "name"}),
            log_unexpected=False,
        )
    assert exc.value.exit_code == 1


def test_exit_on_cli_error_unexpected():
    with pytest.raises(typer.Exit) as exc:
        exit_on_cli_error(RuntimeError("boom"), log_unexpected=False)
    assert exc.value.exit_code == 1
