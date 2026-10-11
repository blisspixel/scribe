"""Omarchy voice control, explicit insert, overlay text, and Hyprland markers."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from rich.console import Console

from scribe.cli import voice_session
from scribe.cli.voice_session import (
    run_omarchy_install,
    run_omarchy_remove,
    run_serve,
    run_voice_check,
)
from scribe.voice.control import (
    ControlError,
    ControlServer,
    apply_command,
    encode_request,
    parse_request,
    send_command,
    tokens_match,
    transact,
    write_token,
)
from scribe.voice.omarchy import (
    AUTOSTART_BLOCK,
    BINDINGS_BLOCK,
    bindings_are_safe,
    build_voice_check,
    install_voice_files,
    remove_voice_files,
    upsert_marked_block,
)
from scribe.voice.overlay import overlay_plain_text, run_overlay
from scribe.voice.service import VoiceTrayService
from scribe.voice.settings import TraySettings
from scribe.voice.wayland_paste import (
    make_hyprland_inserter,
    paste_mods_for_class,
    read_hypr_window_class,
    send_key_state_expression,
)


class _Stream:
    def __init__(self) -> None:
        self.stopped = False
        self.closed = False

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class _Owner:
    def __init__(self) -> None:
        self.running = True
        self.calls: list[str] = []

    def snapshot(self) -> dict[str, object]:
        return {
            "state": "stopped" if not self.running else "idle",
            "status": "Ready",
            "recording": False,
            "paused": False,
            "transcript": "hello",
            "error": None,
            "model_loading": False,
            "explicit_insert": True,
        }

    def request_dictation(self) -> str:
        self.calls.append("dictate")
        return "starting"

    def cancel_capture(self) -> str:
        self.calls.append("cancel")
        return "cancelled"

    def copy_last_transcript(self) -> bool:
        self.calls.append("copy")
        return True

    def insert_last_transcript(self) -> str:
        self.calls.append("insert")
        return "inserted"

    def read_last_transcript(self) -> str:
        self.calls.append("read")
        return "accepted"

    def run_exclusive(self, action, timeout: float = 8.0) -> str:
        _ = timeout
        return str(action())

    def stop(self) -> bool:
        self.running = False
        self.calls.append("stop")
        return True


def _service(**kwargs: object) -> VoiceTrayService:
    explicit = bool(kwargs.get("explicit_insert", False))
    service = VoiceTrayService(TraySettings(), Console(), explicit_insert=explicit)
    service.running = True
    return service


@pytest.fixture(autouse=True)
def isolated_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))


def test_explicit_insert_stores_without_injection() -> None:
    service = _service(explicit_insert=True)
    injected: list[str] = []
    service._inject_text = injected.append  # type: ignore[method-assign]

    assert service.deliver_transcript("  hello   there ") == "stored"
    assert injected == []
    assert service.last_transcript == "hello there"


def test_default_delivery_still_inserts() -> None:
    service = _service()
    injected: list[str] = []
    service._inject_text = injected.append  # type: ignore[method-assign]

    assert service.deliver_transcript("hello") == "inserted"
    assert injected == ["hello"]


def test_cancel_flag_discards_transcript_before_insert() -> None:
    service = _service()
    injected: list[str] = []
    service._inject_text = injected.append  # type: ignore[method-assign]
    service._cancel_requested = True

    assert service.deliver_transcript("hello") == "cancelled"
    assert injected == []
    assert service.last_transcript == ""


def test_cancel_recording_discards_audio_without_transcription() -> None:
    service = _service(explicit_insert=True)
    stream = _Stream()
    service._stream = stream
    service.state = "recording"
    service._audio_buffer = [b"pcm"]
    service._audio_bytes = 3
    service._dictating = True

    assert service.cancel_capture() == "cancelled"
    assert stream.stopped and stream.closed
    assert service._audio_buffer == []
    assert service.state == "idle"
    assert service._dictating is False


def test_tokens_reject_a_different_length() -> None:
    assert tokens_match("a", "a")
    assert not tokens_match("a", "ab")
    assert not tokens_match("", "a")


def test_parse_request_rejects_unknown_commands() -> None:
    line = json.dumps({"token": "t", "command": "OPENAI"})
    with pytest.raises(Exception, match="unknown voice command"):
        parse_request(line)


def test_apply_command_never_reports_hardware_validation() -> None:
    owner = _Owner()
    result = apply_command(owner, "STATUS")
    assert result["validated"] is False
    assert result["experimental"] is True
    dictate = apply_command(owner, "DICTATE")
    assert dictate["outcome"] == "starting"
    assert "dictate" in owner.calls


def test_control_socket_authenticates_and_stops(tmp_path: Path) -> None:
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("Unix-domain sockets are unavailable")
    socket_path = tmp_path / "voice.sock"
    owner = _Owner()
    server = ControlServer(owner, socket_path, "secret-token")
    try:
        server.start()
    except OSError as error:
        pytest.skip(f"Unix-domain socket bind is unavailable here: {error}")
    try:
        rejected = send_command(socket_path, "wrong-token", "PING")
        assert rejected["ok"] is False
        assert rejected["validated"] is False
        accepted = send_command(socket_path, "secret-token", "STATUS")
        assert accepted["ok"] is True
        assert accepted["state"] == "idle"
        encode_request("secret-token", "PING")
        stopped = send_command(socket_path, "secret-token", "STOP")
        assert stopped["state"] == "stopped"
        assert owner.calls[-1] == "stop"
    finally:
        server.close()


def test_token_file_is_owner_only_on_posix(tmp_path: Path) -> None:
    path = tmp_path / "token"
    write_token(path, "secret")
    assert path.read_text(encoding="utf-8").strip() == "secret"
    if not hasattr(Path, "stat"):
        return
    if __import__("os").name != "posix":
        return
    assert path.stat().st_mode & 0o777 == 0o600


def test_binding_block_avoids_omarchy_dictation_keys() -> None:
    assert bindings_are_safe()
    assert "omarchy-launch-tui scribe voice overlay" in BINDINGS_BLOCK
    assert "{ tui =" not in BINDINGS_BLOCK
    assert 'o.launch_on_start("scribe voice serve")' in AUTOSTART_BLOCK
    for line in BINDINGS_BLOCK.splitlines():
        if "o.bind(" not in line:
            continue
        lowered = line.lower()
        assert "f9" not in lowered
        assert "alt_r" not in lowered
        assert "super + ctrl + x" not in lowered


def test_marker_install_is_idempotent_and_preserves_user_lines(tmp_path: Path) -> None:
    config = tmp_path / "hypr"
    bindings = config / "bindings.lua"
    autostart = config / "autostart.lua"
    config.mkdir()
    bindings.write_text(
        'o.bind("SUPER + K", "Keys", "omarchy-menu-keybindings")\n', encoding="utf-8"
    )
    autostart.write_text('o.launch_on_start("hypridle")\n', encoding="utf-8")

    install_voice_files(config)
    install_voice_files(config)
    binding_text = bindings.read_text(encoding="utf-8")
    autostart_text = autostart.read_text(encoding="utf-8")
    assert binding_text.count("scribe-omarchy-voice: start") == 1
    assert 'o.bind("SUPER + K"' in binding_text
    assert "scribe voice dictate" in binding_text
    assert 'o.launch_on_start("hypridle")' in autostart_text
    assert autostart_text.count("scribe voice serve") == 1

    remove_voice_files(config)
    removed = bindings.read_text(encoding="utf-8")
    assert "scribe voice dictate" not in removed
    assert 'o.bind("SUPER + K"' in removed
    assert bindings.exists() and autostart.exists()


def test_upsert_replaces_only_the_marked_region() -> None:
    original = "keep me\n-- start\nold\n-- end\nalso keep\n"
    updated = upsert_marked_block(original, "-- start", "-- end", "-- start\nnew\n-- end\n")
    assert updated.startswith("keep me\n")
    assert "also keep" in updated
    assert "old" not in updated
    assert "new" in updated


def test_voice_check_cannot_claim_validation() -> None:
    report = build_voice_check(
        python_version=(3, 12),
        sounddevice_available=True,
        omarchy_detected=True,
        bindings_text=BINDINGS_BLOCK,
        autostart_text=AUTOSTART_BLOCK,
    )
    assert report.experimental is True
    assert report.hardware_validated is False
    assert report.python_ok is True
    assert report.bindings_installed is True
    text = "\n".join(report.lines)
    assert "does not open the microphone" in text
    assert "does not validate hardware" in text
    assert "Cloud transcription stays opt-in" in text

    outside = build_voice_check(
        python_version=(3, 14),
        sounddevice_available=False,
        omarchy_detected=False,
        bindings_text="",
        autostart_text="",
    )
    assert outside.python_ok is False
    assert outside.hardware_validated is False
    assert "3.14" in "\n".join(outside.lines)


def test_overlay_makes_microphone_state_unmistakable() -> None:
    recording = overlay_plain_text(
        {
            "state": "recording",
            "recording": True,
            "status": "Recording",
            "transcript": "partial words",
            "error": None,
        }
    )
    processing = overlay_plain_text(
        {
            "state": "transcribing",
            "recording": False,
            "status": "Transcribing",
            "transcript": "finished words",
            "error": None,
        }
    )
    assert "MICROPHONE ON" in recording
    assert "partial words" in recording
    assert "hardware validation" in recording
    assert "Microphone is off" in processing
    assert "MICROPHONE ON" not in processing
    assert "finished words" in processing
    assert "Super+Alt+D" in processing
    assert "Super+Alt+Shift+D" in processing


def test_hyprland_paste_uses_send_key_state_and_not_wtype() -> None:
    assert paste_mods_for_class("foot") == "CTRL SHIFT"
    assert paste_mods_for_class("firefox") == "CTRL"
    assert "wtype" not in send_key_state_expression(mods="CTRL", key="V", state="down")
    commands: list[list[str]] = []

    def run(argv: list[str]) -> int:
        commands.append(argv)
        return 0

    copied: list[str] = []
    inserter = make_hyprland_inserter(
        copy=lambda text: copied.append(text) or True,
        run=run,
        read_class=lambda: "foot",
        sleep=lambda _seconds: None,
    )
    assert inserter("hello") == "inserted"
    assert copied == ["hello"]
    rendered = " ".join(" ".join(command) for command in commands)
    assert "hyprctl" in rendered
    assert "send_key_state" in rendered
    assert "CTRL SHIFT" in rendered
    assert "wtype" not in rendered
    assert "hello" not in rendered


def test_hyprland_paste_reports_clipboard_when_dispatch_fails() -> None:
    inserter = make_hyprland_inserter(
        copy=lambda _text: True,
        run=lambda _argv: 1,
        read_class=lambda: "",
        sleep=lambda _seconds: None,
    )
    assert inserter("hello") == "copied"


def test_active_window_class_reads_hyprctl_json() -> None:
    payload = json.dumps({"class": "foot", "title": "terminal"})

    def run_capture(argv: list[str]) -> tuple[int, str]:
        assert argv[:2] == ["hyprctl", "activewindow"]
        return 0, payload

    assert read_hypr_window_class(run_capture) == "foot"
    assert read_hypr_window_class(lambda _argv: (1, "")) == ""


def test_packaging_scripts_do_not_delete_user_data_or_publish() -> None:
    root = Path(__file__).resolve().parents[2]
    install = (root / "packaging" / "linux" / "omarchy" / "install.sh").read_text(encoding="utf-8")
    remove = (root / "packaging" / "linux" / "omarchy" / "uninstall.sh").read_text(encoding="utf-8")
    assert "uv tool install --python 3.12 --force" in install
    assert "scribe[tray] @" in install
    assert "scribe voice omarchy-install" in install
    assert "not a tested Omarchy install" in install
    assert "pypi" not in install.lower()
    assert "aur" not in install.lower()
    assert "scribe voice omarchy-remove" in remove
    assert "uv tool uninstall scribe" in remove
    assert "~/.scribe" in remove
    assert "left in place" in remove
    assert "rm -rf" not in remove


def test_explicit_insert_and_read_use_stored_text(monkeypatch: pytest.MonkeyPatch) -> None:
    service = _service(explicit_insert=True)
    service.last_transcript = "stored words"
    outcomes: list[str] = []
    service.set_text_inserter(lambda text: outcomes.append(text) or "inserted")
    monkeypatch.setattr("scribe.cli.voice.clipboard_copy", lambda text: text == "stored words")

    assert service.copy_last_transcript() is True
    assert service.insert_last_transcript() == "inserted"
    assert outcomes == ["stored words"]
    service._start_worker = lambda _action: True  # type: ignore[method-assign]
    assert service.read_last_transcript() == "accepted"


def test_insert_reports_unconfirmed_paste() -> None:
    service = _service(explicit_insert=True)
    service.last_transcript = "stored words"
    service.set_text_inserter(lambda _text: "copied")
    assert service.insert_last_transcript() == "copied"


def test_voice_check_command_refuses_python_314(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "version_info", (3, 14, 0, "final", 0))
    monkeypatch.delenv("OMARCHY_PATH", raising=False)
    monkeypatch.setattr(voice_session.importlib.util, "find_spec", lambda _name: object())
    printer = Console(record=True, width=100, force_terminal=False)
    assert run_voice_check(printer) == 1
    text = printer.export_text()
    assert "does not validate hardware" in text
    assert "outside" in text
    assert "not a tested Omarchy installation" in text


def test_omarchy_marker_commands_honor_force(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    printer = Console(record=True, width=100, force_terminal=False)
    if sys.platform != "linux":
        assert run_omarchy_install(printer, force=False) == 2
        assert run_omarchy_remove(printer, force=False) == 2
    assert run_omarchy_install(printer, force=True) == 0
    bindings = (tmp_path / "hypr" / "bindings.lua").read_text(encoding="utf-8")
    assert "scribe voice dictate" in bindings
    assert "omarchy-launch-tui scribe voice overlay" in bindings
    assert run_omarchy_remove(printer, force=True) == 0
    removed = (tmp_path / "hypr" / "bindings.lua").read_text(encoding="utf-8")
    assert "scribe voice dictate" not in removed
    assert "left in place" in printer.export_text()


def test_run_serve_exits_when_the_owner_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    class Lock:
        owner = SimpleNamespace(description="pid 9")

        def acquire(self) -> bool:
            return False

    monkeypatch.setattr("scribe.voice.instance.TrayInstanceLock", lambda: Lock())

    def fail_service(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a second owner must not be constructed")

    monkeypatch.setattr("scribe.voice.service.VoiceTrayService", fail_service)
    printer = Console(record=True, width=100, force_terminal=False)
    assert run_serve(printer, preload=False) == 0
    assert "already running" in printer.export_text()


def test_run_serve_stops_when_startup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    class Lock:
        def acquire(self) -> bool:
            return True

        def retain_until_process_exit(self) -> None:
            raise AssertionError("failed startup must not retain the lock")

    class Service:
        def __init__(self, _settings: object, _console: object, *, explicit_insert: bool) -> None:
            assert explicit_insert is True
            self.running = False

        def set_mic_announcer(self, _fn: object) -> None:
            return None

        def set_text_inserter(self, _fn: object) -> None:
            return None

        def start_session(self, *, preload_model: bool) -> bool:
            _ = preload_model
            return False

        def stop(self) -> bool:
            return True

    monkeypatch.setattr("scribe.voice.instance.TrayInstanceLock", lambda: Lock())
    monkeypatch.setattr("scribe.voice.tray._configure_resident_logging", lambda _console: None)
    monkeypatch.setattr(
        "scribe.voice.settings.resolve_tray_settings",
        lambda **_kwargs: SimpleNamespace(preload_model=False),
    )
    monkeypatch.setattr("scribe.voice.service.VoiceTrayService", Service)
    monkeypatch.setattr(voice_session, "_hyprland_inserter", lambda: lambda _text: "copied")
    assert run_serve(Console(), preload=False) == 1


def test_run_serve_listens_until_the_service_stops(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Lock:
        def __init__(self) -> None:
            self.retained = False

        def acquire(self) -> bool:
            return True

        def retain_until_process_exit(self) -> None:
            self.retained = True

    lock = Lock()

    class Service:
        def __init__(self, _settings: object, _console: object, *, explicit_insert: bool) -> None:
            assert explicit_insert is True
            self.running = True

        def set_mic_announcer(self, _fn: object) -> None:
            return None

        def set_text_inserter(self, _fn: object) -> None:
            return None

        def start_session(self, *, preload_model: bool) -> bool:
            _ = preload_model
            return True

        def stop(self) -> bool:
            self.running = False
            return True

    class Server:
        def __init__(self, service: Service, sock: Path, token: str) -> None:
            self.service = service
            self.sock = sock
            self.token = token
            self.closed = False

        def start(self) -> None:
            self.service.running = False

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr("scribe.voice.instance.TrayInstanceLock", lambda: lock)
    monkeypatch.setattr("scribe.voice.tray._configure_resident_logging", lambda _console: None)
    monkeypatch.setattr(
        "scribe.voice.settings.resolve_tray_settings",
        lambda **_kwargs: SimpleNamespace(preload_model=False),
    )
    monkeypatch.setattr("scribe.voice.service.VoiceTrayService", Service)
    monkeypatch.setattr(voice_session, "_hyprland_inserter", lambda: lambda _text: "copied")
    token_path = tmp_path / "voice-control.token"
    monkeypatch.setattr("scribe.voice.control.control_token_path", lambda: token_path)
    monkeypatch.setattr(
        "scribe.voice.control.write_token",
        lambda path, token: path.write_text(token, encoding="utf-8"),
    )
    monkeypatch.setattr("scribe.voice.control.ControlServer", Server)
    assert run_serve(Console(), preload=True) == 0
    assert lock.retained is True
    assert token_path.is_file()


def test_client_wrapper_exits_on_failed_command(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed(command: str, *, autostart: bool) -> dict[str, object]:
        assert command == "INSERT"
        assert autostart is True
        return {"ok": False, "outcome": "copied", "error": "paste unconfirmed"}

    monkeypatch.setattr(voice_session, "_transact", failed)
    with pytest.raises(typer.Exit) as caught:
        voice_session._run_client("INSERT", autostart=True)
    assert caught.value.exit_code == 1


def test_transact_starts_the_owner_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    starts: list[str] = []

    def send(socket_path: Path, token: str, command: str, *, timeout: float) -> dict[str, object]:
        _ = (socket_path, timeout)
        assert token == "secret"  # noqa: S105
        assert command == "PING"

        return {"ok": True, "experimental": True, "validated": False}

    def spawn() -> None:
        starts.append("once")
        from scribe.paths import runtime_dir

        scribe_dir = runtime_dir(tmp_path)
        scribe_dir.mkdir(parents=True, exist_ok=True)
        (scribe_dir / "voice-control.sock").write_text("", encoding="utf-8")
        write_token(scribe_dir / "voice-control.token", "secret")

    monkeypatch.setattr("scribe.voice.control.send_command", send)
    payload = transact("PING", home=tmp_path, spawn=spawn, timeout=1.0)
    assert payload["validated"] is False
    assert starts == ["once"]
    with pytest.raises(ControlError):
        monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "another-runtime"))
        (tmp_path / "another-runtime").mkdir(mode=0o700)
        transact("PING", home=tmp_path / "missing", spawn=None, timeout=0.1)


def test_overlay_once_and_local_keys_do_not_own_the_microphone() -> None:
    printer = Console(record=True, width=78, force_terminal=False, color_system=None)
    code = run_overlay(
        printer,
        lambda: {
            "state": "recording",
            "status": "listening",
            "recording": True,
            "transcript": "partial",
        },
        lambda _command: None,
        once=True,
    )
    assert code == 0
    assert "MICROPHONE ON" in printer.export_text()

    keys = iter(["d", "q"])
    sent: list[str] = []
    interactive = Console(record=True, width=78, force_terminal=True, color_system=None)
    code = run_overlay(
        interactive,
        lambda: {
            "state": "idle",
            "status": "idle",
            "recording": False,
            "transcript": "finished words",
        },
        sent.append,
        sleep=lambda _seconds: None,
        read_key=lambda: next(keys),
    )
    assert code == 0
    assert sent == ["DICTATE"]
    text = interactive.export_text()
    assert "microphone off" in text
    assert "MICROPHONE ON" not in text


def test_microphone_announcement_writes_exact_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(voice_session.Path, "home", lambda: tmp_path)
    calls: list[list[str]] = []

    class Result:
        returncode = 0

    def run(command: list[str], **_kwargs: object) -> Result:
        calls.append(command)
        return Result()

    monkeypatch.setattr(voice_session.subprocess, "run", run)
    voice_session._announce_microphone(True)
    from scribe.paths import state_dir

    status = (state_dir() / "voice-status.txt").read_text(encoding="utf-8")
    assert status == "MICROPHONE ON\n"
    assert calls[0][:3] == ["omarchy-notification-send", "-u", "critical"]
