"""Tests for resident voice tray settings and service-side pure logic."""

from __future__ import annotations

import importlib.machinery
import sys
import types
from dataclasses import replace

import pytest
from rich.console import Console
from typer.testing import CliRunner

from scribe.cli.main import app
from scribe.models.gpu import GPUConfig
from scribe.voice import settings as settings_mod
from scribe.voice.service import (
    Dependency,
    DependencyStatus,
    HotkeyState,
    VoiceTrayService,
    dependency_report,
    key_name_from_object,
    missing_dependency_packages,
)
from scribe.voice.settings import (
    TraySettings,
    model_for_profile,
    normalize_hotkey,
    parse_hotkey,
    resolve_tray_settings,
)


class _PressedContext:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> None:
        return None


def _install_fake_selection_modules(
    monkeypatch: pytest.MonkeyPatch,
    *,
    initial_clipboard: str = "old clipboard",
    copied_selection: str | None = None,
    controller_raises: bool = False,
    paste_raises: bool = False,
) -> types.SimpleNamespace:
    state = types.SimpleNamespace(value=initial_clipboard, copy_calls=[])
    pyperclip = types.ModuleType("pyperclip")

    def paste() -> str:
        return str(state.value)

    def copy(value: str) -> None:
        state.value = value
        state.copy_calls.append(value)

    pyperclip.paste = paste  # type: ignore[attr-defined]
    pyperclip.copy = copy  # type: ignore[attr-defined]

    keyboard = types.ModuleType("keyboard")

    class FakeKey:
        ctrl = object()
        cmd = object()

    class FakeController:
        def __init__(self) -> None:
            if controller_raises:
                raise RuntimeError("keyboard unavailable")

        def pressed(self, _modifier: object) -> _PressedContext:
            return _PressedContext()

        def press(self, _key: str) -> None:
            return None

        def release(self, key: str) -> None:
            if key == "v" and paste_raises:
                raise RuntimeError("paste failed")
            if key == "c" and copied_selection is not None:
                state.value = copied_selection

    keyboard.Key = FakeKey  # type: ignore[attr-defined]
    keyboard.Controller = FakeController  # type: ignore[attr-defined]

    pynput = types.ModuleType("pynput")
    pynput.keyboard = keyboard  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "pyperclip", pyperclip)
    monkeypatch.setitem(sys.modules, "pynput", pynput)
    monkeypatch.setattr("scribe.voice.service.time.sleep", lambda _seconds: None)
    return state


def test_parse_hotkey_normalizes_aliases_and_order() -> None:
    spec = parse_hotkey("Control + Shift + Spacebar")
    assert spec.canonical == "ctrl+shift+space"
    assert spec.parts == frozenset({"ctrl", "shift", "space"})
    assert normalize_hotkey("F9") == "f9"


def test_parse_hotkey_rejects_empty_and_unknown_keys() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_hotkey("   ")
    with pytest.raises(ValueError, match="Unsupported"):
        parse_hotkey("ctrl+hyper")


def test_resolve_tray_settings_reads_voice_tray_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_mod,
        "load_config_file",
        lambda: {
            "voice": {
                "tray": {
                    "profile": "accurate",
                    "dictate_hotkey": "ctrl+alt+space",
                    "read_hotkey": "f7",
                    "inject": "type",
                    "stt_model": "small",
                    "language": "en",
                    "tts_rate": 170,
                    "preload_model": True,
                }
            }
        },
    )

    settings = resolve_tray_settings()

    assert settings.profile == "accurate"
    assert settings.dictate_hotkey == "ctrl+alt+space"
    assert settings.read_hotkey == "f7"
    assert settings.inject == "type"
    assert settings.stt_model == "small"
    assert settings.language == "en"
    assert settings.tts_rate == 170
    assert settings.preload_model is True


def test_resolve_tray_settings_cli_overrides_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings_mod,
        "load_config_file",
        lambda: {"voice": {"tray": {"profile": "accurate", "inject": "type"}}},
    )

    settings = resolve_tray_settings(profile="fast", inject="paste", model="base")

    assert settings.profile == "fast"
    assert settings.inject == "paste"
    assert settings.stt_model == "base"


def test_resolve_tray_settings_rejects_same_hotkey(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_mod, "load_config_file", lambda: {})
    with pytest.raises(ValueError, match="must be different"):
        resolve_tray_settings(dictate_hotkey="f9", read_hotkey="F9")


def test_model_for_profile_uses_gpu_capacity() -> None:
    high_gpu = GPUConfig(
        has_gpu=True,
        cuda_available=True,
        gpu_memory_gb=24,
        gpu_name="NVIDIA GeForce RTX 4090",
    )
    cpu = GPUConfig(has_gpu=False, cuda_available=False)

    assert model_for_profile("fast", high_gpu) == "small"
    assert model_for_profile("balanced", high_gpu) == "medium"
    assert model_for_profile("accurate", high_gpu) == "large-v3"
    assert model_for_profile("accurate", high_gpu, explicit_model="base") == "base"
    assert model_for_profile("balanced", cpu) == "base"
    assert model_for_profile("accurate", cpu) == "small"


def test_dependency_report_deduplicates_missing_packages(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_find_spec(module: str) -> importlib.machinery.ModuleSpec | None:
        if module in {"sounddevice", "pynput"}:
            return importlib.machinery.ModuleSpec(module, loader=None)
        return None

    monkeypatch.setattr("scribe.voice.service.importlib.util.find_spec", fake_find_spec)

    report = dependency_report(include_tray=True)
    missing = missing_dependency_packages(include_tray=True)

    assert any(status.available for status in report)
    assert "pyperclip" in missing
    assert "Pillow" in missing
    assert missing == sorted(set(missing))


class _CharKey:
    char = "A"
    name = None


class _NamedKey:
    char = None

    def __init__(self, name: str) -> None:
        self.name = name


def test_key_name_from_object_matches_pynput_shapes() -> None:
    assert key_name_from_object(_CharKey()) == "a"
    assert key_name_from_object(_NamedKey("ctrl_l")) == "ctrl"
    assert key_name_from_object(_NamedKey("f9")) == "f9"
    assert key_name_from_object(_NamedKey("unknown_key")) is None


def test_hotkey_state_reports_activation_edges() -> None:
    hotkeys = HotkeyState(parse_hotkey("ctrl+alt+space"), parse_hotkey("f8"))

    assert hotkeys.press("ctrl") == (False, False)
    assert hotkeys.press("alt") == (False, False)
    assert hotkeys.press("space") == (True, False)
    assert hotkeys.press("space") == (False, False)
    assert hotkeys.release("alt") is True
    assert hotkeys.press("f8") == (False, True)
    assert hotkeys.press("f8") == (False, False)
    assert hotkeys.release("f8") is False


def test_service_status_and_pause_callbacks() -> None:
    service = VoiceTrayService(TraySettings(), Console(record=True))
    seen: list[str] = []
    service.add_status_callback(lambda _state: seen.append(service.status_text))

    service.set_paused(True)
    assert service.status_text == "Paused"
    assert service.toggle_pause() is False
    service._set_state("error", "microphone unavailable")

    assert "Paused" in seen
    assert service.status_text == "Error: microphone unavailable"


def test_service_ignores_hotkey_presses_while_paused() -> None:
    service = VoiceTrayService(TraySettings(), Console(record=True))
    service.set_paused(True)

    service._on_press(_NamedKey("f9"))

    assert service.hotkeys.pressed == frozenset()
    assert service.state == "idle"


def test_service_start_hotkeys_handles_listener_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = VoiceTrayService(TraySettings(), Console(record=True))

    def no_missing(**_kwargs: object) -> list[str]:
        return []

    monkeypatch.setattr(
        "scribe.voice.service.missing_dependency_packages",
        no_missing,
    )

    keyboard = types.ModuleType("keyboard")

    class FailingListener:
        def __init__(self, **_kwargs: object) -> None:
            return None

        def start(self) -> None:
            raise RuntimeError("permission denied")

    keyboard.Listener = FailingListener  # type: ignore[attr-defined]
    pynput = types.ModuleType("pynput")
    pynput.keyboard = keyboard  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pynput", pynput)

    assert service.start_hotkeys() is False
    assert service.running is False
    assert service.state == "error"
    assert "hotkey listener unavailable" in str(service.error_message)


def test_service_read_selection_does_not_read_stale_clipboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _install_fake_selection_modules(monkeypatch, copied_selection=None)
    service = VoiceTrayService(TraySettings(), Console(record=True))

    assert service._read_selection_text() == ""
    assert state.value == "old clipboard"


def test_service_read_selection_restores_clipboard_after_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _install_fake_selection_modules(monkeypatch, copied_selection="selected text")
    service = VoiceTrayService(TraySettings(), Console(record=True))

    assert service._read_selection_text() == "selected text"
    assert state.value == "old clipboard"


def test_service_read_selection_restores_clipboard_when_keyboard_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _install_fake_selection_modules(monkeypatch, controller_raises=True)
    service = VoiceTrayService(TraySettings(), Console(record=True))

    with pytest.raises(RuntimeError, match="keyboard unavailable"):
        service._read_selection_text()

    assert state.value == "old clipboard"


def test_service_inject_restores_clipboard_when_paste_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _install_fake_selection_modules(monkeypatch, paste_raises=True)
    service = VoiceTrayService(TraySettings(), Console(record=True))

    with pytest.raises(RuntimeError, match="paste failed"):
        service._inject_text("dictated text")

    assert state.value == "old clipboard"


def test_cli_read_selection_does_not_read_stale_clipboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scribe.cli import voice

    state = _install_fake_selection_modules(monkeypatch, copied_selection=None)

    assert voice._read_selection(Console(record=True)) == ""
    assert state.value == "old clipboard"


def test_cli_read_selection_restores_clipboard_when_keyboard_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scribe.cli import voice

    state = _install_fake_selection_modules(monkeypatch, controller_raises=True)

    assert voice._read_selection(Console(record=True)) == ""
    assert state.value == "old clipboard"


def test_tray_check_reports_missing_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    from scribe.voice import tray

    dep = Dependency("pystray", "pystray", "tray icon", required_for_tray=True)

    def fake_report(*, include_tray: bool) -> list[DependencyStatus]:
        assert include_tray is True
        return [DependencyStatus(dep, available=False)]

    def fake_missing(*, include_tray: bool) -> list[str]:
        assert include_tray is True
        return ["pystray"]

    monkeypatch.setattr(
        tray,
        "dependency_report",
        fake_report,
    )
    monkeypatch.setattr(tray, "missing_dependency_packages", fake_missing)

    assert tray.run_tray_check(Console(record=True), TraySettings(), include_tray=True) == 1


def test_tray_command_check_uses_no_tray_dependency_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scribe.voice import tray

    seen: dict[str, object] = {}

    def fake_check(console: Console, settings: TraySettings, *, include_tray: bool) -> int:
        seen["settings"] = settings
        seen["include_tray"] = include_tray
        return 0

    monkeypatch.setattr(tray, "run_tray_check", fake_check)
    result = CliRunner().invoke(app, ["tray", "--check", "--no-tray", "--profile", "fast"])

    assert result.exit_code == 0
    assert seen["include_tray"] is False
    assert isinstance(seen["settings"], TraySettings)
    assert seen["settings"] == replace(seen["settings"], profile="fast")
