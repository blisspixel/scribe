"""Tests for voice setup download hygiene."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest
from rich.console import Console

from scribe.voice.setup import _download_file


def test_download_file_rejects_incomplete_payload(tmp_path: Path) -> None:
    """Truncated HTTP bodies must not be promoted to the final asset path."""
    dest = tmp_path / "model.bin"
    console = Console(record=True)

    class FakeResponse:
        def __init__(self) -> None:
            self.headers = {"Content-Length": "100"}

        def raise_for_status(self) -> None:
            return None

        def iter_bytes(self, chunk_size: int = 0):
            yield b"short"

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    with patch("httpx.stream", return_value=FakeResponse()):
        with pytest.raises(OSError, match="incomplete download"):
            _download_file("https://example.com/model.bin", dest, console, "model.bin")

    assert not dest.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_download_file_wraps_http_errors(tmp_path: Path) -> None:
    dest = tmp_path / "voices.bin"
    console = Console(record=True)

    def raise_http_error(*_args: object, **_kwargs: object):
        raise httpx.ConnectError("offline", request=MagicMock())

    with patch("httpx.stream", side_effect=raise_http_error):
        with pytest.raises(OSError, match="download failed"):
            _download_file("https://example.com/voices.bin", dest, console, "voices.bin")

    assert not dest.exists()
    assert list(tmp_path.glob("*.part")) == []


def test_setup_verification_model_is_explicitly_unloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    from scribe.voice.setup import download_stt_model

    unloaded: list[bool] = []

    class WhisperModel:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            self.model = types.SimpleNamespace(unload_model=lambda: unloaded.append(True))

    faster_whisper = types.ModuleType("faster_whisper")
    faster_whisper.WhisperModel = WhisperModel  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "faster_whisper", faster_whisper)

    result = download_stt_model(Console(record=True), "base")

    assert result.ok is True
    assert unloaded == [True]


def test_voice_setup_refuses_to_overwrite_invalid_existing_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tomllib

    import scribe.config_file as config_file
    from scribe.voice import setup

    monkeypatch.setattr("scribe.voice.service.missing_dependency_packages", lambda **_kwargs: [])
    monkeypatch.setattr(
        config_file,
        "load_config_file_strict",
        lambda: (_ for _ in ()).throw(tomllib.TOMLDecodeError("bad table", "[bad", 0)),
    )
    console = Console(record=True)

    assert setup.run_voice_setup(console, interactive=False) == 1
    assert "Could not read existing config safely" in console.export_text()


def test_voice_setup_returns_failure_when_settings_cannot_be_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import types

    import scribe.config_file as config_file
    from scribe.voice import setup

    monkeypatch.setattr("scribe.voice.service.missing_dependency_packages", lambda **_kwargs: [])
    monkeypatch.setattr(config_file, "load_config_file_strict", lambda: {})
    monkeypatch.setattr(
        config_file,
        "save_config_file",
        lambda _config: (_ for _ in ()).throw(PermissionError("config is locked")),
    )
    monkeypatch.setattr(
        "scribe.models.gpu.GPUConfig.detect",
        lambda: types.SimpleNamespace(
            has_gpu=False,
            cuda_available=False,
            gpu_name=None,
            gpu_memory_gb=0,
        ),
    )
    monkeypatch.setattr(
        setup,
        "download_stt_model",
        lambda *_args, **_kwargs: setup.SetupStepResult("STT model", True, "ready"),
    )
    monkeypatch.setattr(setup, "kokoro_installed", lambda: False)
    console = Console(record=True)

    assert setup.run_voice_setup(console, interactive=False) == 1
    output = console.export_text()
    assert "Could not save voice settings" in output
    assert "setup is incomplete" in output
