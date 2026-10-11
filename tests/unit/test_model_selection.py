"""File accuracy policy, explicit overrides and decoding-resource choices."""

import pytest

from scribe.models.config import ScribeConfig
from scribe.utils.model_selection import resolve_local_batch_size, resolve_local_model


@pytest.mark.parametrize(
    ("profile", "model"),
    [("accurate", "large-v3"), ("balanced", "large-v3-turbo"), ("fast", "small")],
)
def test_profile_selects_model_without_hardware_downgrade(profile, model):
    assert resolve_local_model("large-v3", set(), profile) == (model, model != "large-v3")


@pytest.mark.parametrize("profile", ["accurate", "balanced", "fast"])
@pytest.mark.parametrize("model", ["tiny", "small", "large-v3"])
def test_explicit_model_wins_over_profile(profile, model):
    assert resolve_local_model(model, {"default_model"}, profile) == (model, False)


def test_other_explicit_fields_do_not_pin_model():
    assert resolve_local_model("large-v3", {"default_language"}, "fast") == ("small", True)


@pytest.mark.parametrize(
    ("profile", "configured", "expected"),
    [
        ("accurate", None, 0),
        ("balanced", None, None),
        ("fast", None, None),
        ("accurate", 8, 8),
        ("fast", 0, 0),
    ],
)
def test_explicit_batch_overrides_profile(profile, configured, expected):
    assert resolve_local_batch_size(profile, configured) == expected


def test_file_env_profile_and_explicit_model_precedence(monkeypatch, tmp_path):
    from scribe import config_file

    path = tmp_path / "config.toml"
    path.write_text('[transcription]\nquality = "fast"\n', encoding="utf-8")
    monkeypatch.setattr(config_file, "CONFIG_PATH", path)
    monkeypatch.delenv("SCRIBE_DEFAULT_MODEL", raising=False)
    monkeypatch.setenv("SCRIBE_TRANSCRIPTION_QUALITY", "balanced")
    config = ScribeConfig(_env_file=None)
    assert (
        resolve_local_model(
            config.default_model, config.model_fields_set, config.transcription_quality
        )[0]
        == "large-v3-turbo"
    )
    monkeypatch.setenv("SCRIBE_DEFAULT_MODEL", "medium")
    pinned = ScribeConfig(_env_file=None)
    assert (
        resolve_local_model(
            pinned.default_model, pinned.model_fields_set, pinned.transcription_quality
        )[0]
        == "medium"
    )
    monkeypatch.delenv("SCRIBE_TRANSCRIPTION_QUALITY")
    assert ScribeConfig(_env_file=None).transcription_quality == "fast"


@pytest.mark.parametrize("language", ["es", "ja"])
def test_primary_file_and_env_are_live_settings(language, monkeypatch, tmp_path):
    from scribe import config_file
    from scribe.utils.model_selection import resolve_local_language

    path = tmp_path / "config.toml"
    path.write_text(
        f'[transcription]\nprimary_language = "{language}"\nauto_detect_language = false\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_file, "CONFIG_PATH", path)
    monkeypatch.delenv("SCRIBE_DEFAULT_LANGUAGE", raising=False)
    monkeypatch.delenv("SCRIBE_AUTO_DETECT_LANGUAGE", raising=False)
    config = ScribeConfig(_env_file=None)
    assert (
        resolve_local_language(
            config.default_language, config.auto_detect_language, config.primary_language
        )
        == language
    )
    monkeypatch.setenv("SCRIBE_AUTO_DETECT_LANGUAGE", "true")
    config = ScribeConfig(_env_file=None)
    assert (
        resolve_local_language(
            config.default_language, config.auto_detect_language, config.primary_language
        )
        is None
    )
