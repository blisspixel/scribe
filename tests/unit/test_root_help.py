"""Root help layout."""

from scribe.cli.root_help import root_help_text


def test_root_help_fits_and_groups_commands():
    text = root_help_text("2.13.0")
    lines = text.splitlines()
    assert len(lines) <= 25
    assert all(len(line) <= 80 for line in lines)
    assert lines[0] == "scribe 2.13.0"
    assert "Start here:" in lines
    start = [line for line in lines if line.startswith("  scribe ")]
    descriptions = [line[line.rindex("  ") + 2 :] for line in start]
    assert descriptions == [
        "first-run setup",
        "check models, cache and devices",
        "transcribe a file",
    ]
    assert "transcribe, url, batch, music, clean, query, vocab" in text
    assert "support-bundle" in text
    assert text.endswith("scribe <command> -h for options")


def _text_column(line: str) -> int:
    """Column where the description or command list starts."""
    return line.rindex("  ") + 2


def test_start_here_descriptions_share_a_column():
    lines = [line for line in root_help_text("2.13.0").splitlines() if line.startswith("  scribe ")]
    columns = [_text_column(line) for line in lines]
    assert len(set(columns)) == 1
    assert all(line[column] != " " for line, column in zip(lines, columns, strict=True))


def test_group_command_lists_share_a_column():
    groups = [
        line
        for line in root_help_text("2.13.0").splitlines()
        if line.endswith(("vocab", "shortcut", "health", "say", "meme", "help"))
    ]
    columns = [_text_column(line) for line in groups]
    assert len(groups) == 6
    assert len(set(columns)) == 1
