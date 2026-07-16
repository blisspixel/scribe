"""Tests for resident voice tray settings and service-side pure logic."""

from __future__ import annotations

import importlib.machinery
import socket
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule
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
    resident_voice_advisories,
)
from scribe.voice.settings import (
    TraySettings,
    model_for_profile,
    normalize_hotkey,
    parse_hotkey,
    resolve_tray_activation,
    resolve_tray_settings,
)
from scribe.voice.tray import hotkey_hints


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

    # Latency-first dictation: even a 24GB GPU defaults balanced to the snappy
    # "small" model; "accurate" opts into large-v3-turbo (faster than large-v3).
    assert model_for_profile("fast", high_gpu) == "base"
    assert model_for_profile("balanced", high_gpu) == "small"
    assert model_for_profile("accurate", high_gpu) == "large-v3-turbo"
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


def test_dependency_report_handles_missing_parent_package(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_find_spec(module: str) -> importlib.machinery.ModuleSpec | None:
        if module == "PIL.Image":
            raise ModuleNotFoundError("No module named 'PIL'")
        return None

    monkeypatch.setattr("scribe.voice.service.importlib.util.find_spec", fake_find_spec)

    report = dependency_report(include_tray=True)

    pillow = next(status for status in report if status.dependency.package == "Pillow")
    assert pillow.available is False
    assert "Pillow" in missing_dependency_packages(include_tray=True)


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


class HotkeyStateMachine(RuleBasedStateMachine):
    """Stateful exploration of hotkey press/release invariants (Step 3)."""

    _KEYS = ("ctrl", "alt", "shift", "space", "f8", "f9")

    def __init__(self) -> None:
        super().__init__()
        self.hotkeys = HotkeyState(parse_hotkey("ctrl+alt+space"), parse_hotkey("f8"))

    @rule(key=st.sampled_from(_KEYS))
    def press_key(self, key: str) -> None:
        self.hotkeys.press(key)

    @rule(key=st.sampled_from(_KEYS))
    def release_key(self, key: str) -> None:
        self.hotkeys.release(key)

    @rule()
    def reset_keys(self) -> None:
        self.hotkeys.reset()

    @invariant()
    def pressed_keys_are_tracked_consistently(self) -> None:
        pressed = self.hotkeys.pressed
        assert all(isinstance(key, str) for key in pressed)
        assert pressed.issubset(frozenset(self._KEYS))


TestHotkeyStateMachine = HotkeyStateMachine.TestCase


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


def test_service_inject_falls_back_to_typing_when_clipboard_wedged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # When the clipboard is wedged (Windows OpenClipboard failures), dictation must
    # not be lost: _inject_text falls back to typing the text instead.
    typed: list[str] = []
    fake_clip = types.ModuleType("pyperclip")
    fake_clip.copy = lambda _v: (_ for _ in ()).throw(RuntimeError("wedged"))  # type: ignore[attr-defined]
    fake_clip.paste = lambda: ""  # type: ignore[attr-defined]

    keyboard = types.ModuleType("keyboard")

    class FakeKey:
        ctrl = object()
        cmd = object()

    class FakeController:
        def type(self, value: str) -> None:
            typed.append(value)

        def pressed(self, _modifier: object) -> _PressedContext:
            return _PressedContext()

        def press(self, _key: str) -> None:
            return None

        def release(self, _key: str) -> None:
            return None

    keyboard.Key = FakeKey  # type: ignore[attr-defined]
    keyboard.Controller = FakeController  # type: ignore[attr-defined]
    pynput = types.ModuleType("pynput")
    pynput.keyboard = keyboard  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "pyperclip", fake_clip)
    monkeypatch.setitem(sys.modules, "pynput", pynput)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    service = VoiceTrayService(TraySettings(inject="paste"), Console(record=True))
    service._inject_text("hello")

    assert typed == ["hello "]  # typed with the appended space, not silently dropped


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

    console = Console(record=True)
    assert tray.run_tray_check(console, TraySettings(), include_tray=True) == 1
    output = console.export_text()
    assert "Install missing tray packages with:" in output
    assert "[yellow]" not in output


def test_native_tray_selection_does_not_implicitly_use_source_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scribe.voice import tray

    monkeypatch.delenv("SCRIBE_TRAY_NATIVE_BIN", raising=False)
    monkeypatch.setattr(tray, "files", lambda _package: tmp_path)

    selection = tray._resolve_native_tray()

    assert selection.path is None
    assert selection.source == "python"
    assert "opt-in" in selection.reason


def test_native_tray_selection_labels_developer_override_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scribe.voice import tray

    explicit = tmp_path / "custom-tray.exe"
    explicit.touch()
    monkeypatch.setenv("SCRIBE_TRAY_NATIVE_BIN", str(explicit))

    selection = tray._resolve_native_tray()

    assert selection.path == explicit
    assert selection.source == "explicit"
    assert "unverified developer override" in selection.reason
    assert str(explicit) in selection.reason


def test_native_tray_selection_reports_missing_explicit_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scribe.voice import tray

    missing = tmp_path / "missing-tray.exe"
    monkeypatch.setenv("SCRIBE_TRAY_NATIVE_BIN", str(missing))

    selection = tray._resolve_native_tray()

    assert selection.path is None
    assert selection.source == "python"
    assert str(missing) in selection.reason


def test_native_tray_compatibility_requires_toggle_function_keys() -> None:
    from scribe.voice import tray

    assert tray._native_compatibility_issue(TraySettings()) is None
    assert "toggle" in str(tray._native_compatibility_issue(TraySettings(activation="hold")))
    assert "F6-F12" in str(
        tray._native_compatibility_issue(
            TraySettings(dictate_hotkey="ctrl+alt+space", read_hotkey="f8")
        )
    )


def test_tray_check_reports_backend_and_selection_state(monkeypatch: pytest.MonkeyPatch) -> None:
    from scribe.voice import tray

    monkeypatch.setattr(tray, "dependency_report", lambda **_kwargs: [])
    monkeypatch.setattr(tray, "missing_dependency_packages", lambda **_kwargs: [])
    monkeypatch.setattr(
        tray,
        "_resolve_native_tray",
        lambda: tray.NativeTraySelection(
            None,
            "python",
            "native daemon is opt-in via SCRIBE_TRAY_NATIVE_BIN",
        ),
    )
    console = Console(record=True)

    assert tray.run_tray_check(console, TraySettings(), include_tray=True) == 0
    output = console.export_text()
    assert "platform" in output
    assert "backend" in output
    assert "startup" in output
    assert "Python tray" in output
    assert "opt-in via SCRIBE_TRAY_NATIVE_BIN" in output


def test_tray_check_darwin_emits_permission_advisories(monkeypatch: pytest.MonkeyPatch) -> None:
    from scribe.voice import tray

    monkeypatch.setattr(tray.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(tray, "dependency_report", lambda **_kwargs: [])
    monkeypatch.setattr(tray, "missing_dependency_packages", lambda **_kwargs: [])
    monkeypatch.setattr(
        tray,
        "_resolve_native_tray",
        lambda: tray.NativeTraySelection(
            None,
            "python",
            "native daemon is opt-in via SCRIBE_TRAY_NATIVE_BIN",
        ),
    )
    console = Console(record=True)

    assert tray.run_tray_check(console, TraySettings(), include_tray=True) == 0
    output = console.export_text()
    assert "experimental" in output.lower()
    assert "Input Monitoring" in output
    assert "LaunchAgent" in output


def test_tray_check_linux_headless_warns_without_x11_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scribe.voice import tray

    monkeypatch.setattr(tray.platform, "system", lambda: "Linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("XDG_SESSION_TYPE", raising=False)
    monkeypatch.setattr(tray, "dependency_report", lambda **_kwargs: [])
    monkeypatch.setattr(tray, "missing_dependency_packages", lambda **_kwargs: [])
    monkeypatch.setattr(
        tray,
        "_resolve_native_tray",
        lambda: tray.NativeTraySelection(
            None,
            "python",
            "native daemon is opt-in via SCRIBE_TRAY_NATIVE_BIN",
        ),
    )
    console = Console(record=True)

    assert tray.run_tray_check(console, TraySettings(), include_tray=True) == 0
    output = console.export_text()
    assert "DISPLAY" in output or "WAYLAND_DISPLAY" in output
    assert "global hotkeys via pynput are expected to work" not in output


def test_tray_check_labels_explicit_native_override_unverified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scribe.voice import tray

    monkeypatch.setattr(tray, "dependency_report", lambda **_kwargs: [])
    monkeypatch.setattr(tray, "missing_dependency_packages", lambda **_kwargs: [])
    monkeypatch.setattr(
        tray,
        "_resolve_native_tray",
        lambda: tray.NativeTraySelection(
            Path("developer-tray.exe"),
            "explicit",
            "unverified developer override at developer-tray.exe",
        ),
    )
    console = Console(record=True)

    assert tray.run_tray_check(console, TraySettings(), include_tray=True) == 0
    output = console.export_text()
    assert "native tray" in output
    assert "unverified developer override at developer-tray.exe" in output


def test_run_tray_falls_back_to_python_after_native_startup_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scribe.voice import tray

    native = tmp_path / "scribe-tray.exe"
    native.touch()
    selection = tray.NativeTraySelection(native, "explicit", f"explicit path {native}")
    calls: list[str] = []
    monkeypatch.setattr(tray, "_resolve_native_tray", lambda: selection)
    monkeypatch.setattr(
        tray,
        "_run_native_tray",
        lambda *_args: calls.append("native") or None,
    )
    monkeypatch.setattr(
        tray,
        "_run_python_tray",
        lambda *_args: calls.append("python") or 0,
    )

    assert tray.run_tray(Console(record=True), TraySettings(), no_tray=False) == 0
    assert calls == ["native", "python"]


def test_native_runner_keeps_capability_out_of_arguments_and_preloads_after_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scribe.voice import tray

    captured: dict[str, object] = {}
    capability_value = "process-capability"

    class FakeService:
        def __init__(self, *_args: object) -> None:
            self.preload_calls = 0
            self.stopped = False
            captured["service"] = self

        @property
        def ipc_token(self) -> str:
            return capability_value

        def start_ipc_server(self, *, preload_model: bool) -> int:
            assert preload_model is False
            return 32123

        def wait_for_ipc_ready(self, *, timeout: float) -> bool:
            assert timeout > 0
            return True

        def start_model_preload(self) -> None:
            self.preload_calls += 1

        def stop(self) -> None:
            self.stopped = True

    class FakeProcess:
        def poll(self) -> None:
            return None

        def wait(self, *, timeout: float | None = None) -> int:
            assert timeout is None
            return 0

    def fake_popen(arguments: list[str], *, env: dict[str, str]) -> FakeProcess:
        captured["arguments"] = arguments
        captured["environment"] = env
        return FakeProcess()

    native = tmp_path / "scribe-tray.exe"
    native.touch()
    monkeypatch.setattr(tray, "VoiceTrayService", FakeService)
    monkeypatch.setattr("subprocess.Popen", fake_popen)
    monkeypatch.setattr(tray, "_await_model_ready", lambda *_args: True)
    monkeypatch.setattr(tray, "packaged_native_icon_path", lambda: tmp_path / "scribe.ico")

    selection = tray.NativeTraySelection(native, "explicit", f"explicit path {native}")
    result = tray._run_native_tray(Console(record=True), TraySettings(), selection)

    arguments = captured["arguments"]
    environment = captured["environment"]
    service = captured["service"]
    assert isinstance(arguments, list)
    assert isinstance(environment, dict)
    assert capability_value not in arguments
    assert environment["SCRIBE_TRAY_IPC_TOKEN"] == capability_value
    assert isinstance(service, FakeService)
    assert service.preload_calls == 1
    assert service.stopped is True
    assert result == 0


def test_native_runner_does_not_preload_before_failed_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scribe.voice import tray

    capability_value = "process-capability"

    class FakeService:
        def __init__(self, *_args: object) -> None:
            self.preload_calls = 0

        @property
        def ipc_token(self) -> str:
            return capability_value

        def start_ipc_server(self, *, preload_model: bool) -> int:
            assert preload_model is False
            return 32123

        def wait_for_ipc_ready(self, *, timeout: float) -> bool:
            raise AssertionError(f"exited process should not wait {timeout}")

        def start_model_preload(self) -> None:
            self.preload_calls += 1

        def stop(self) -> None:
            return None

    class FailedProcess:
        def poll(self) -> int:
            return 7

    service = FakeService()
    monkeypatch.setattr(tray, "VoiceTrayService", lambda *_args: service)
    monkeypatch.setattr("subprocess.Popen", lambda *_args, **_kwargs: FailedProcess())
    monkeypatch.setattr(tray, "packaged_native_icon_path", lambda: tmp_path / "scribe.ico")
    native = tmp_path / "scribe-tray.exe"
    native.touch()

    result = tray._run_native_tray(
        Console(record=True),
        TraySettings(),
        tray.NativeTraySelection(native, "explicit", f"explicit path {native}"),
    )

    assert result is None
    assert service.preload_calls == 0


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


def test_tray_platform_matrix_tiers() -> None:
    from scribe.voice.service import graphical_session_detected, tray_platform_matrix

    assert tray_platform_matrix("Windows").tier == "validated"
    assert "live-validated" in tray_platform_matrix("Windows").headline
    assert tray_platform_matrix("Darwin").tier == "experimental"
    assert tray_platform_matrix("Linux").tier == "experimental"
    assert tray_platform_matrix("FreeBSD").tier == "unsupported"
    assert graphical_session_detected(display=":0")
    assert graphical_session_detected(wayland_display="wayland-0")
    # Stale XDG_SESSION_TYPE without a display socket is not a graphical proof.
    assert not graphical_session_detected(session_type="x11")
    assert not graphical_session_detected(session_type="wayland")
    assert not graphical_session_detected()


def test_tray_environment_advisories_linux_headless_warns() -> None:
    from scribe.voice.service import tray_environment_advisories

    advisories = tray_environment_advisories("Linux")
    assert any("DISPLAY" in a.message for a in advisories)
    assert not tray_environment_advisories("Windows")


def test_resident_voice_advisories_macos_warns_about_permissions() -> None:
    advisories = resident_voice_advisories("Darwin")
    assert any(a.level == "warning" and "Input Monitoring" in a.message for a in advisories)
    assert any(a.level == "warning" and "experimental" in a.message.lower() for a in advisories)
    assert any(a.level == "info" and "LaunchAgent" in a.message for a in advisories)


def test_resident_voice_advisories_macos_type_mentions_accessibility() -> None:
    advisories = resident_voice_advisories("Darwin", inject="type")
    assert any(a.level == "warning" and "Accessibility" in a.message for a in advisories)
    assert any(a.level == "warning" and "keyboard layout" in a.message for a in advisories)


def test_resident_voice_advisories_linux_wayland_warns() -> None:
    # WAYLAND_DISPLAY proves a graphical Wayland session. Session type alone does not.
    by_display = resident_voice_advisories("Linux", wayland_display="wayland-0")
    by_both = resident_voice_advisories(
        "Linux", session_type="wayland", wayland_display="wayland-0"
    )
    assert any(a.level == "warning" and "Wayland" in a.message for a in by_display)
    assert any(a.level == "warning" and "Wayland" in a.message for a in by_both)
    assert any("GlobalShortcuts" in a.message for a in by_display)
    assert any(a.level == "info" and "autostart" in a.message for a in by_display)


def test_resident_voice_advisories_linux_x11_includes_matrix_and_session_notes() -> None:
    advisories = resident_voice_advisories("Linux", session_type="x11", display=":0")
    assert any(a.level == "info" and "X11" in a.message for a in advisories)
    assert any(a.level == "info" and "AppIndicator" in a.message for a in advisories)
    assert any(a.level == "warning" and "experimental" in a.message.lower() for a in advisories)
    assert any(a.level == "info" and "autostart" in a.message for a in advisories)


def test_resident_voice_advisories_linux_headless_does_not_claim_x11_support() -> None:
    advisories = resident_voice_advisories("Linux")
    joined = " ".join(a.message for a in advisories)
    assert "DISPLAY" in joined or "WAYLAND_DISPLAY" in joined
    assert "pynput global hotkeys may work" not in joined
    assert "Linux/X11" not in joined


def test_resident_voice_advisories_linux_stale_session_type_without_display() -> None:
    advisories = resident_voice_advisories("Linux", session_type="x11")
    joined = " ".join(a.message for a in advisories)
    assert "DISPLAY" in joined or "WAYLAND_DISPLAY" in joined
    assert "pynput global hotkeys may work" not in joined


def test_resident_voice_advisories_windows_paste_is_clean() -> None:
    # Windows with the default paste injection needs no permission/layout caveat.
    assert resident_voice_advisories("Windows") == []


def test_resident_voice_advisories_type_mode_warns_any_os() -> None:
    advisories = resident_voice_advisories("Windows", inject="type")
    assert any(a.level == "warning" and "keyboard layout" in a.message for a in advisories)


def test_resolve_tray_activation() -> None:
    assert resolve_tray_activation(None) == "toggle"  # default: tap on/off
    assert resolve_tray_activation("HOLD") == "hold"
    assert resolve_tray_activation("Toggle") == "toggle"
    with pytest.raises(ValueError, match="--activation"):
        resolve_tray_activation("doubletap")


def test_hotkey_hints_word_for_activation_mode() -> None:
    toggle_dictate, toggle_read = hotkey_hints(TraySettings(activation="toggle"))
    assert "Tap F9 to start" in toggle_dictate and "tap again" in toggle_dictate
    assert "Tap F8" in toggle_read and "tap again to stop" in toggle_read

    hold_dictate, _ = hotkey_hints(TraySettings(activation="hold"))
    assert "Hold F9" in hold_dictate


def _drain_actions(service: VoiceTrayService) -> None:
    """Run queued hotkey actions, as the dispatcher thread does in the live app."""
    import queue

    while True:
        try:
            action = service._actions.get_nowait()
        except queue.Empty:
            return
        if action is not None:
            action()


def test_native_ipc_requires_capability_and_readiness(monkeypatch: pytest.MonkeyPatch) -> None:
    service = VoiceTrayService(TraySettings(preload_model=False), Console(record=True))
    calls: list[str] = []
    monkeypatch.setattr(service, "_begin_recording", lambda: calls.append("dictate"))
    monkeypatch.setattr(service, "read_selection_now", lambda: calls.append("read") or True)
    monkeypatch.setattr(service, "stop_speaking", lambda: calls.append("stop"))
    port = service.start_ipc_server()

    try:
        # Wrong-length AUTH must reject without killing the accept loop.
        with socket.create_connection(("127.0.0.1", port), timeout=1.0) as rejected:
            rejected.sendall(b"AUTH wrong\nDICTATE\n")
            rejected.settimeout(1.0)
            assert rejected.recv(64) == b""

        # Equal-length wrong token must also reject cleanly.
        with socket.create_connection(("127.0.0.1", port), timeout=1.0) as rejected_equal:
            token = service.ipc_token or ""
            wrong = ("x" * len(token)).encode()
            rejected_equal.sendall(b"AUTH " + wrong + b"\n")
            rejected_equal.settimeout(1.0)
            assert rejected_equal.recv(64) == b""

        with socket.create_connection(("127.0.0.1", port), timeout=1.0) as accepted:
            stream = accepted.makefile("rwb")
            stream.write(f"AUTH {service.ipc_token}\n".encode())
            stream.flush()
            assert stream.readline() == b"AUTH OK\n"
            assert not service.wait_for_ipc_ready(timeout=0.01)

            stream.write(b"READY\n")
            stream.flush()
            assert service.wait_for_ipc_ready(timeout=1.0)
            assert stream.readline() == b"STATE:idle\n"

            stream.write(b"DICTATE\n")
            stream.flush()
            for _ in range(100):
                if calls:
                    break
                import time

                time.sleep(0.01)
            assert calls == ["dictate"]

            service._dictating = False
            stream.write(b"READ\n")
            stream.flush()
            for _ in range(100):
                if len(calls) == 2:
                    break
                import time

                time.sleep(0.01)
            assert calls == ["dictate", "read"]

            service.state = "speaking"
            stream.write(b"READ\n")
            stream.flush()
            for _ in range(100):
                if len(calls) == 3:
                    break
                import time

                time.sleep(0.01)
            assert calls == ["dictate", "read", "stop"]
    finally:
        service.stop()

    assert service._ipc_socket is None
    assert service._ipc_conn is None


def test_on_press_enqueues_action_off_the_hook_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    # The fix: the keyboard-hook callback must NOT run device work inline (opening
    # the mic on the hook thread breaks key capture on Windows). It enqueues.
    service = VoiceTrayService(TraySettings(activation="toggle"), Console(record=True))
    calls: list[str] = []
    monkeypatch.setattr(service, "_begin_recording", lambda: calls.append("begin"))

    service._on_press(_NamedKey("f9"))
    assert calls == []  # not run inline
    assert service._dictating is True  # intent flag set synchronously
    _drain_actions(service)
    assert calls == ["begin"]  # the dispatcher runs it


def test_service_toggle_dictation_starts_then_stops_on_taps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = VoiceTrayService(TraySettings(activation="toggle"), Console(record=True))
    calls: list[str] = []
    monkeypatch.setattr(service, "_begin_recording", lambda: calls.append("begin"))
    monkeypatch.setattr(service, "_finish_recording", lambda: calls.append("finish"))

    f9 = _NamedKey("f9")
    service._on_press(f9)  # tap 1 -> enqueue start
    service._on_release(f9)  # release is ignored in toggle mode
    service._on_press(f9)  # tap 2 -> enqueue stop + transcribe
    service._on_release(f9)

    _drain_actions(service)
    assert calls == ["begin", "finish"]


def test_service_hold_dictation_starts_on_press_stops_on_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = VoiceTrayService(TraySettings(activation="hold"), Console(record=True))
    calls: list[str] = []
    monkeypatch.setattr(service, "_begin_recording", lambda: calls.append("begin"))
    monkeypatch.setattr(service, "_finish_recording", lambda: calls.append("finish"))

    f9 = _NamedKey("f9")
    service._on_press(f9)  # press -> enqueue start
    service._on_release(f9)  # release -> enqueue stop (push-to-talk)

    _drain_actions(service)
    assert calls == ["begin", "finish"]


def test_service_read_hotkey_toggles_start_and_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    service = VoiceTrayService(TraySettings(activation="toggle"), Console(record=True))
    calls: list[str] = []
    monkeypatch.setattr(service, "read_selection_now", lambda: calls.append("read") or True)
    monkeypatch.setattr(service, "stop_speaking", lambda: calls.append("stop"))

    f8 = _NamedKey("f8")
    service._on_press(f8)  # idle -> enqueue read selection
    service._on_release(f8)
    _drain_actions(service)
    service.state = "speaking"
    service._on_press(f8)  # speaking -> stop playback (inline, instant)
    service._on_release(f8)

    assert calls == ["read", "stop"]


def test_finish_recording_resets_state_when_worker_is_busy() -> None:
    # Regression: with --preload, a dictation finishing while the model is still
    # loading must not get stuck in "recording" - it resets to idle instead.
    import threading

    service = VoiceTrayService(TraySettings(), Console(record=True))
    service.running = True  # a real running service finishing a recording
    service._set_state("recording")
    service._audio_buffer = [b"\x00" * 9000]  # above the min-audio floor

    busy = threading.Event()
    worker = threading.Thread(target=busy.wait, daemon=True)
    worker.start()
    service._worker = worker  # occupy the single worker slot
    try:
        service._finish_recording()
        assert service.state == "idle"
    finally:
        busy.set()
        worker.join(timeout=1)


def test_finish_recording_does_not_clobber_error_state() -> None:
    # A stale/duplicate finish (e.g. after a mic error) must not flip error -> idle.
    service = VoiceTrayService(TraySettings(), Console(record=True))
    service.running = True
    service._set_state("error", "microphone unavailable")
    service._audio_buffer = [b"\x00" * 9000]

    service._finish_recording()

    assert service.state == "error"
    assert service._audio_buffer == []


def test_return_to_idle_after_stop_does_not_revive_service() -> None:
    # A worker finishing after stop() must not clobber the terminal "stopped".
    service = VoiceTrayService(TraySettings(), Console(record=True))
    service.running = False
    service.state = "stopped"

    service._return_to_idle()

    assert service.state == "stopped"


def test_set_paused_discards_recording_and_resets_intent() -> None:
    # Pause mid-recording discards the capture and clears the toggle intent
    # (without holding the state lock across stream teardown).
    service = VoiceTrayService(TraySettings(), Console(record=True))
    service.running = True
    service._dictating = True
    service._set_state("recording")
    service._audio_buffer = [b"\x00" * 200]

    service.set_paused(True)

    assert service.paused is True
    assert service._dictating is False
    assert service.state == "idle"
    assert service._audio_buffer == []


def test_speak_text_falls_back_to_system_voice_on_kokoro_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A runtime Kokoro synth/playback failure must not permanently break read-aloud:
    # it falls back to the pyttsx3 system voice for this read.
    from scribe.voice import tts

    spoken: list[str] = []

    class FailingSpeaker:
        def speak(self, _text: str) -> None:
            raise RuntimeError("onnx inference failed")

        def close(self) -> None:
            return None

    class OkSpeaker:
        def speak(self, text: str) -> None:
            spoken.append(text)

        def close(self) -> None:
            return None

    def fake_make_speaker(backend: str, **_kwargs: object) -> object:
        return FailingSpeaker() if backend == "kokoro" else OkSpeaker()

    monkeypatch.setattr(tts, "resolve_tts_backend", lambda *_a, **_k: "kokoro")
    monkeypatch.setattr(tts, "kokoro_installed", lambda: True)
    monkeypatch.setattr(tts, "kokoro_assets_ready", lambda: True)
    monkeypatch.setattr(tts, "make_speaker", fake_make_speaker)

    service = VoiceTrayService(TraySettings(), Console(record=True))
    service._speak_text("hello world")

    assert spoken == ["hello world"]  # fell back to the system voice, did not crash


def test_load_model_returns_cached_without_reloading() -> None:
    # Double-checked cache: a warmed model is returned without re-importing or
    # reconstructing (a preload thread + first dictation must not double-load).
    service = VoiceTrayService(TraySettings(), Console(record=True))
    sentinel = object()
    service._model = sentinel
    assert service._load_model() is sentinel


def test_status_text_shows_loading_while_model_warms() -> None:
    # The tray must report "Loading model..." (not "Ready") while preloading, so it
    # never claims readiness before the model is warm.
    service = VoiceTrayService(TraySettings(), Console(record=True))
    assert service.status_text == "Ready"
    service.model_loading = True
    assert service.status_text == "Loading model..."
    service.model_loading = False
    assert service.status_text == "Ready"


def test_tray_preloads_by_default() -> None:
    # A resident tray keeps a model warm unless explicitly told not to.
    assert TraySettings().preload_model is True


def test_tray_startup_install_remove_roundtrip(
    tmp_path: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    from scribe.voice import startup

    home = Path(str(tmp_path))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    # Avoid launching PowerShell (Windows) / launchctl (macOS) in the test.
    monkeypatch.setattr(
        "scribe.cli.shortcut._create_windows_lnk",
        lambda path, *_a, **_k: Path(path).write_text("lnk", encoding="utf-8"),
    )
    monkeypatch.setattr("subprocess.run", lambda *_a, **_k: None)

    assert startup.is_startup_enabled() is False
    created = startup.install_startup()
    assert created.exists()
    assert startup.is_startup_enabled() is True
    removed = startup.remove_startup()
    assert removed == created
    assert startup.is_startup_enabled() is False


def test_run_tray_startup_install_macos_mentions_permissions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scribe.voice import startup

    created = tmp_path / "io.pueo.scribe.tray.plist"
    created.write_text("plist", encoding="utf-8")
    monkeypatch.setattr(startup, "install_startup", lambda: created)
    monkeypatch.setattr(startup, "is_windows", lambda: False)
    monkeypatch.setattr(startup, "is_macos", lambda: True)
    console = Console(record=True)

    assert startup.run_tray_startup(console, "install") == 0
    text = console.export_text()
    assert "LaunchAgent" in text
    assert "Input Monitoring" in text


def test_run_tray_startup_install_linux_mentions_wayland_caveat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scribe.voice import startup

    created = tmp_path / "scribe-voice-tray.desktop"
    created.write_text("desktop", encoding="utf-8")
    monkeypatch.setattr(startup, "install_startup", lambda: created)
    monkeypatch.setattr(startup, "is_windows", lambda: False)
    monkeypatch.setattr(startup, "is_macos", lambda: False)
    console = Console(record=True)

    assert startup.run_tray_startup(console, "install") == 0
    text = console.export_text()
    assert "XDG autostart" in text
    assert "Wayland" in text


def test_startup_path_rejects_unsupported_os(monkeypatch: pytest.MonkeyPatch) -> None:
    from scribe.voice import startup

    monkeypatch.setattr(startup, "is_windows", lambda: False)
    monkeypatch.setattr(startup, "is_macos", lambda: False)
    monkeypatch.setattr(startup, "is_linux", lambda: False)
    monkeypatch.setattr(startup.platform, "system", lambda: "FreeBSD")
    with pytest.raises(OSError, match="not supported"):
        startup.startup_path()
    assert startup.is_startup_enabled() is False


def test_set_hotkey_changes_live_and_rejects_collisions(monkeypatch: pytest.MonkeyPatch) -> None:
    import scribe.config_file as cf

    # Don't touch the real config file when persisting.
    monkeypatch.setattr(cf, "load_config_file", lambda: {})
    monkeypatch.setattr(cf, "save_config_file", lambda _data: cf.CONFIG_PATH)

    service = VoiceTrayService(TraySettings(dictate_hotkey="f9", read_hotkey="f8"), Console())

    # Change the read key live; the chord state updates to match.
    assert service.set_hotkey("read", "f7") is True
    assert service.read_hotkey == "f7"
    assert service.hotkeys._read.parts == frozenset({"f7"})

    # Collisions are rejected (read can't become the dictate key).
    assert service.set_hotkey("read", "f9") is False
    assert service.read_hotkey == "f7"  # unchanged
