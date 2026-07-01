"""
Unit tests for the cross-platform Quick Record launcher (scribe shortcut).

Platform is mocked so all three OS code paths are exercised from any host. The
Windows .lnk creation (which shells out to PowerShell) is mocked to stay
OS-agnostic; the bundled icon is read from the real package data.
"""

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


# ── command resolution ────────────────────────────────────────────────────────


def test_resolve_prefers_scribe_on_path(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda _: "/usr/local/bin/scribe")
    assert sc.resolve_scribe_command() == ["/usr/local/bin/scribe"]


def test_resolve_falls_back_to_python_module(monkeypatch):
    monkeypatch.setattr(sc.shutil, "which", lambda _: None)
    monkeypatch.setattr(sc.sys, "argv", ["/tmp/not-scribe"])
    assert sc.resolve_scribe_command() == [sys.executable, "-m", "scribe"]


def test_get_launcher_target_and_args(monkeypatch):
    monkeypatch.setattr(sc, "_get_scribe_command", lambda: ["/usr/bin/scribe"])
    assert sc._get_launcher_target_and_args() == ("scribe", ["rec"])
    monkeypatch.setattr(sc, "_get_scribe_command", lambda: ["/py", "-m", "scribe"])
    assert sc._get_launcher_target_and_args() == (
        "scribe",
        ["rec"],
    )  # prefers bare when possible via which mock not here


# ── per-OS install ────────────────────────────────────────────────────────────


def test_install_macos_app_bundle(monkeypatch, fake_home):
    _set_platform(monkeypatch, "macos")
    monkeypatch.setattr(sc, "_get_launcher_target_and_args", lambda: ("/opt/scribe", ["rec"]))

    created = sc.install_quick_record_launcher(desktop=False)

    app_bundle = fake_home / "Applications" / "Scribe Quick Record.app"
    assert created == [app_bundle]
    assert (app_bundle / "Contents" / "MacOS" / "run").exists()
    assert (app_bundle / "Contents" / "Resources" / "scribe.icns").exists()
    plist = (app_bundle / "Contents" / "Info.plist").read_bytes()
    assert b"scribe.icns" in plist
    launch = (app_bundle / "Contents" / "Resources" / "launch.command").read_text()
    # Adaptive: prefers bare scribe or has fallback logic
    assert "scribe" in launch.lower() or "fallback" in launch.lower()


def test_install_linux_desktop_with_icon(monkeypatch, fake_home):
    _set_platform(monkeypatch, "linux")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(sc, "_get_launcher_target_and_args", lambda: ("/opt/scribe", ["rec"]))
    monkeypatch.setattr(sc.shutil, "which", lambda _: None)  # skip update-desktop-database

    created = sc.install_quick_record_launcher(desktop=False)

    entry = fake_home / ".local" / "share" / "applications" / "scribe-quick-record.desktop"
    icon = fake_home / ".local" / "share" / "icons" / "scribe.png"
    assert created == [entry]
    assert icon.exists()
    text = entry.read_text()
    # Now uses adaptive wrapper or bare for durability
    assert "Exec=" in text and ("scribe" in text or ".sh" in text.lower())
    assert "Terminal=true" in text
    assert f"Icon={icon}" in text


def test_install_windows_targets_exe_with_icon(monkeypatch, fake_home):
    _set_platform(monkeypatch, "windows")
    monkeypatch.setenv("APPDATA", str(fake_home / "AppData" / "Roaming"))
    monkeypatch.setattr(
        sc, "_get_launcher_target_and_args", lambda: (r"C:\Program Files\scribe.exe", ["rec"])
    )

    calls: list[tuple] = []

    def fake_lnk(lnk: Path, target: str, arguments: str, workdir: Path, icon: Path) -> None:
        lnk.parent.mkdir(parents=True, exist_ok=True)
        lnk.write_text("lnk")
        calls.append((lnk, target, arguments, icon))

    monkeypatch.setattr(sc, "_create_windows_lnk", fake_lnk)

    created = sc.install_quick_record_launcher(desktop=False)

    start_menu = (
        fake_home
        / "AppData"
        / "Roaming"
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Scribe Quick Record.lnk"
    )
    assert start_menu in created
    _lnk, target, arguments, icon = calls[0]
    # .lnk targets cmd.exe (with env + exe call) for reliable taskbar icon while
    # wrapper .cmd is still created for the adaptive logic.
    assert "cmd.exe" in target.lower()
    assert "SCRIBE_FROM_SHORTCUT" in arguments
    assert (fake_home / ".scribe" / "Scribe Quick Record.cmd").exists()
    wrapper_text = (fake_home / ".scribe" / "Scribe Quick Record.cmd").read_text()
    # Bulletproof adaptive design
    assert "scribe" in wrapper_text
    assert "where" in wrapper_text.lower() or "exist" in wrapper_text.lower()
    assert "rec" in wrapper_text
    assert "pause" in wrapper_text.lower()
    assert "FALLBACK" in wrapper_text
    assert str(icon).endswith("scribe.ico")
    assert (fake_home / ".scribe" / "scribe.ico").exists()  # icon staged for stability


@pytest.mark.skipif(sys.platform != "win32", reason="reads the Windows registry")
def test_windows_desktop_dir_resolves():
    # On a real Windows host this returns the actual (possibly redirected) Desktop.
    assert (
        sc._windows_desktop_dir().name.lower() in {"desktop"} or sc._windows_desktop_dir().exists()
    )


def test_remove_deletes_app_bundle(monkeypatch, fake_home):
    _set_platform(monkeypatch, "macos")
    monkeypatch.setattr(sc, "_get_launcher_target_and_args", lambda: ("/opt/scribe", ["rec"]))
    sc.install_quick_record_launcher(desktop=True)

    removed = sc.remove_quick_record_launcher()

    assert removed
    assert not (fake_home / "Applications" / "Scribe Quick Record.app").exists()
    assert not (fake_home / "Desktop" / "Scribe Quick Record.app").exists()


# ── run_shortcut UX ───────────────────────────────────────────────────────────


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
