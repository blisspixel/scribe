"""Unit tests for single-accent header markup."""

from scribe.utils.branding import brand_header_markup


def test_header_is_one_accent_without_a_gradient():
    result = brand_header_markup("Scribe")
    assert result == "[bold blue]Scribe[/bold blue]"
    assert "rgb(" not in result


def test_header_escapes_markup():
    result = brand_header_markup("[read]")
    assert result == "[bold blue]\\[read][/bold blue]"
