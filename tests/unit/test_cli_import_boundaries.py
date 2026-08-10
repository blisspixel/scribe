"""Regression tests for keeping trivial CLI commands lightweight."""

import subprocess
import sys


def test_cli_import_does_not_eagerly_load_optional_subsystems() -> None:
    forbidden = (
        "docx",
        "openai",
        "scribe.core.recorder",
        "scribe.core.transcriber",
        "scribe.utils.joke_generator",
    )
    script = (
        "import sys; import scribe.cli.main; "
        f"print(','.join(name for name in {forbidden!r} if name in sys.modules))"
    )

    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.stdout.strip() == ""
