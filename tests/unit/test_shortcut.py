"""
Unit tests for the cross-platform Quick Record launcher (scribe shortcut).

Platform is mocked so all three OS code paths are exercised from any host; the
Windows .lnk creation (which shells out to PowerShell) is mocked to stay
OS-agnostic.
"""

import os
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from scribe.cli import shortcut as sc
from scribe.cli.main import app


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Point Path.home() at a temp dir for the duration of a test."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return tmp_path


def _set_platform(monkeypatch, name: str) -> None:
    monkeypatch.setattr("scribe.utils.platform.get_platform", lambda: name)


# ── resolve_scribe_command ────────────────────────────────────────────────────


def test_resolve_prefers_scribe_on_path(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda _: "/usr/local/bin/scribe")
    assert sc.resolve_scribe_command() == ["/usr/local/bin/scribe"]


def test_resolve_falls_back_to_python_module(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda _: None)
    monkeypatch.setattr(sc.sys, "argv", ["/tmp/not-scribe"])
    assert sc.resolve_scribe_command() == [sys.executable, "-m", "scribe"]


# ── per-OS install ────────────────────────────────────────────────────────────


def test_install_macos_writes_executable_command(monkeypatch, fake_home):
    _set_platform(monkeypatch, "macos")
    monkeypatch.setattr(sc, "resolve_scribe_command", lambda: ["/opt/scribe"])

    created = sc.install_quick_record_launcher(desktop=True)

    app_cmd = fake_home / "Applications" / "Scribe Quick Record.command"
    desk_cmd = fake_home / "Desktop" / "Scribe Quick Record.command"
    assert app_cmd in created and desk_cmd in created
    body = app_cmd.read_text()
    assert body.startswith("#!/bin/bash")
    assert "exec /opt/scribe rec" in body
    if os.name == "posix":  # Windows ignores Unix exec bits; chmod is a no-op there
        assert app_cmd.stat().st_mode & 0o111


def test_install_linux_writes_desktop_entry(monkeypatch, fake_home):
    _set_platform(monkeypatch, "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(sc, "resolve_scribe_command", lambda: ["/opt/scribe"])
    monkeypatch.setattr(sc.shutil, "which", lambda _: None)  # skip update-desktop-database

    created = sc.install_quick_record_launcher(desktop=False)

    entry = fake_home / ".local" / "share" / "applications" / "scribe-quick-record.desktop"
    assert created == [entry]
    text = entry.read_text()
    assert "Exec=/opt/scribe rec" in text
    assert "Terminal=true" in text
    assert "Type=Application" in text


def test_install_windows_quotes_spaced_path(monkeypatch, fake_home):
    _set_platform(monkeypatch, "windows")
    monkeypatch.setenv("APPDATA", str(fake_home / "AppData" / "Roaming"))
    monkeypatch.setattr(sc, "resolve_scribe_command", lambda: [r"C:\Program Files\scribe.exe"])

    lnk_calls: list[Path] = []

    def fake_lnk(lnk: Path, target: Path, workdir: Path) -> None:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        lnk.write_text("lnk")
        lnk_calls.append(lnk)

    monkeypatch.setattr(sc, "_create_windows_lnk", fake_lnk)

    created = sc.install_quick_record_launcher(desktop=False)

    cmd_path = fake_home / ".scribe" / "Scribe Quick Record.cmd"
    assert cmd_path in created
    content = cmd_path.read_text()
    # Spaced executable path must be quoted in the .cmd command line.
    assert '"C:\\Program Files\\scribe.exe" rec' in content
    assert "pause" in content
    assert any(p.name == "Scribe Quick Record.lnk" for p in lnk_calls)


def test_remove_deletes_installed_launchers(monkeypatch, fake_home):
    _set_platform(monkeypatch, "macos")
    monkeypatch.setattr(sc, "resolve_scribe_command", lambda: ["/opt/scribe"])
    sc.install_quick_record_launcher(desktop=True)

    removed = sc.remove_quick_record_launcher()

    assert removed
    assert not (fake_home / "Applications" / "Scribe Quick Record.command").exists()
    assert not (fake_home / "Desktop" / "Scribe Quick Record.command").exists()


# ── CLI command wiring ────────────────────────────────────────────────────────


def test_shortcut_command_installs(monkeypatch):
    seen: dict[str, bool] = {}

    def fake_install(desktop: bool):
        seen["desktop"] = desktop
        return [Path("/tmp/launcher")]

    monkeypatch.setattr("scribe.cli.shortcut.install_quick_record_launcher", fake_install)

    result = CliRunner().invoke(app, ["shortcut", "--no-desktop"])

    assert result.exit_code == 0
    assert seen["desktop"] is False


def test_shortcut_command_remove(monkeypatch):
    called = {"remove": False}

    def fake_remove():
        called["remove"] = True
        return [Path("/tmp/launcher")]

    monkeypatch.setattr("scribe.cli.shortcut.remove_quick_record_launcher", fake_remove)

    result = CliRunner().invoke(app, ["shortcut", "--remove"])

    assert result.exit_code == 0
    assert called["remove"] is True


# ── additional coverage: resolution fallback, run_shortcut paths, linux updater ──


def test_resolve_uses_running_entrypoint(monkeypatch, tmp_path):
    monkeypatch.setattr(sc.shutil, "which", lambda _: None)
    fake_exe = tmp_path / "scribe"
    fake_exe.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sc.sys, "argv", [str(fake_exe)])
    assert sc.resolve_scribe_command() == [str(fake_exe.resolve())]


def test_run_shortcut_reports_created_paths(monkeypatch):
    from unittest.mock import MagicMock

    def fake_install(desktop):
        return [Path("/tmp/a"), Path("/tmp/b")]

    monkeypatch.setattr(sc, "install_quick_record_launcher", fake_install)
    console = MagicMock()
    sc.run_shortcut(console=console, desktop=False, remove=False)
    printed = " ".join(str(c.args[0]) for c in console.print.call_args_list if c.args)
    assert "Installed" in printed


def test_run_shortcut_remove_when_none_installed(monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr(sc, "remove_quick_record_launcher", lambda: [])
    console = MagicMock()
    sc.run_shortcut(console=console, desktop=None, remove=True)
    printed = " ".join(str(c.args[0]) for c in console.print.call_args_list if c.args)
    assert "No installed launcher" in printed


def test_run_shortcut_install_failure_exits(monkeypatch):
    from unittest.mock import MagicMock

    def boom(desktop):
        raise OSError("denied")

    monkeypatch.setattr(sc, "install_quick_record_launcher", boom)
    with pytest.raises(SystemExit):
        sc.run_shortcut(console=MagicMock(), desktop=False, remove=False)


def test_linux_invokes_update_desktop_database(monkeypatch, fake_home):
    _set_platform(monkeypatch, "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(sc, "resolve_scribe_command", lambda: ["/opt/scribe"])
    monkeypatch.setattr(sc.shutil, "which", lambda _: "/usr/bin/update-desktop-database")

    runs: list[list[str]] = []

    def fake_run(args, **kwargs):
        runs.append(args)

    monkeypatch.setattr(sc.subprocess, "run", fake_run)
    sc.install_quick_record_launcher(desktop=False)
    assert any("update-desktop-database" in a[0] for a in runs)
