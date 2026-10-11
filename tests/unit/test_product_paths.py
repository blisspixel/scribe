"""Linux storage conventions, compatibility reads and runtime failure contracts."""

from __future__ import annotations

import io
import logging
import os
import stat
import sys
import tomllib
from pathlib import Path
from unittest.mock import Mock

import pytest
from rich.console import Console
from typer.testing import CliRunner

from scribe import config_file, paths
from scribe.cli import init as init_wizard
from scribe.cli.system import run_doctor
from scribe.models.config import ScribeConfig
from scribe.utils.diagnostics import SystemDiagnostics
from scribe.utils.vocabulary import CustomVocabulary

_LINUX = sys.platform == "linux"


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(paths.sys, "platform", "linux")
    monkeypatch.setattr("scribe.utils.platform.get_platform", lambda: "linux")
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setattr(config_file, "CONFIG_DIR", tmp_path / ".config/scribe")
    monkeypatch.setattr(config_file, "CONFIG_PATH", tmp_path / ".config/scribe/config.toml")
    monkeypatch.setattr(config_file, "LEGACY_CONFIG_PATH", tmp_path / ".scribe/config.toml")
    monkeypatch.setattr(init_wizard, "CONFIG_PATH", config_file.CONFIG_PATH)
    monkeypatch.setattr(paths, "_RUNTIME_WARNING_SHOWN", False)
    monkeypatch.setattr("scribe.models.config._find_env_file", lambda: None)
    for variable in ("SCRIBE_OUTPUT_FOLDER", "SCRIBE_LOG_FOLDER", "SCRIBE_SKIP_INIT"):
        monkeypatch.delenv(variable, raising=False)


@pytest.mark.parametrize("current_exists", [False, True])
def test_doctor_explains_legacy_config_without_moving_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, current_exists: bool
) -> None:
    legacy = config_file.LEGACY_CONFIG_PATH
    legacy.parent.mkdir()
    legacy.write_text('[transcription]\nlanguage = "es"\n', encoding="utf-8")
    original = legacy.read_bytes()
    if current_exists:
        config_file.CONFIG_PATH.parent.mkdir(parents=True)
        config_file.CONFIG_PATH.write_text('[transcription]\nlanguage = "ja"\n')
    monkeypatch.setattr(SystemDiagnostics, "run_all_checks", lambda *_args, **_kwargs: [])
    output = io.StringIO()
    run_doctor(
        Console(file=output, width=240, color_system=None), "test", False, logging.getLogger()
    )
    text = output.getvalue()
    assert ("Using legacy config" in text) is not current_exists
    if not current_exists:
        assert str(legacy) in text
        assert str(config_file.CONFIG_PATH) in text
        assert "the legacy file is kept" in " ".join(text.split())
        assert not config_file.CONFIG_PATH.exists()
    assert legacy.read_bytes() == original


@pytest.mark.parametrize("value", [None, "", "relative/path", "~/not-expanded"])
def test_missing_empty_or_relative_xdg_homes_use_absolute_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str | None
) -> None:
    if value is not None:
        for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
            monkeypatch.setenv(variable, value)
    assert paths.config_dir() == tmp_path / ".config/scribe"
    assert paths.data_dir() == tmp_path / ".local/share/scribe"
    assert paths.state_dir() == tmp_path / ".local/state/scribe"
    assert paths.default_log_dir() == tmp_path / ".local/state/scribe/logs"
    assert not (tmp_path / ".config").exists()  # Resolution does not migrate or create files.


def test_absolute_xdg_overrides_and_real_state_consumers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scribe.utils.performance_tracker import PerformanceTracker
    from scribe.voice.tray import resident_log_path

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert paths.config_dir() == tmp_path / "cfg/scribe"
    assert paths.vocabulary_dirs()[0] == tmp_path / "data/scribe/vocab"
    assert resident_log_path() == tmp_path / "state/scribe/logs/resident-voice.log"
    tracker = PerformanceTracker("synthetic-machine")
    tracker.record_phase("preparing", 30.0, 1.0)
    assert tracker.metrics_file.is_file()
    assert tracker.metrics_file.parent == tmp_path / "state/scribe"
    explicit = PerformanceTracker("synthetic-machine", config_dir=tmp_path / "explicit")
    assert explicit.metrics_file.parent == tmp_path / "explicit"


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_non_linux_product_paths_keep_legacy_locations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str
) -> None:
    from scribe.voice.control import control_socket_path, control_token_path, write_token
    from scribe.voice.instance import tray_instance_lock_path
    from scribe.voice.tray import resident_log_path

    monkeypatch.setattr(paths.sys, "platform", platform)
    for variable in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR"):
        monkeypatch.setenv(variable, "relative-ignored-on-other-platforms")
    assert paths.config_dir() == tmp_path / ".scribe"
    assert paths.data_dir() == tmp_path / ".scribe"
    assert paths.state_dir() == tmp_path / ".scribe"
    assert paths.default_log_dir() == tmp_path / ".scribe/logs"
    assert resident_log_path() == tmp_path / ".scribe/logs/resident-voice.log"
    assert control_socket_path() == tmp_path / ".scribe/voice-control.sock"
    assert control_token_path() == tmp_path / ".scribe/voice-control.token"
    assert tray_instance_lock_path() == tmp_path / ".scribe/resident-voice.lock"
    write_token(control_token_path(), "synthetic-token")
    assert control_token_path().read_text(encoding="utf-8") == "synthetic-token\n"
    expected = "Movies" if platform == "darwin" else "Videos"
    assert paths.videos_dir() == tmp_path / expected


def _legacy_config(text: str) -> Path:
    path = config_file.LEGACY_CONFIG_PATH
    path.parent.mkdir(parents=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_legacy_config_read_and_first_run_do_not_migrate_or_overwrite() -> None:
    legacy = _legacy_config('[output]\nfolder = "/synthetic/output"\n[unknown]\nkeep = true\n')
    original = legacy.read_bytes()
    assert config_file.config_exists()
    assert config_file.config_read_path() == legacy
    assert config_file.load_config_file_strict()["unknown"] == {"keep": True}
    assert init_wizard._default_output_folder() == "/synthetic/output"
    assert init_wizard.maybe_prompt_first_run() is False
    result = init_wizard.run_wizard(Console(file=io.StringIO()))
    assert result == legacy
    assert legacy.read_bytes() == original
    assert not config_file.CONFIG_PATH.exists()


def test_current_config_wins_and_invalid_current_does_not_read_legacy() -> None:
    _legacy_config('[output]\nfolder = "legacy"\n')
    config_file.save_config_file({"output": {"folder": "current"}})
    assert config_file.config_read_path() == config_file.CONFIG_PATH
    assert config_file.load_config_file_strict()["output"]["folder"] == "current"
    config_file.CONFIG_PATH.write_text("[invalid", encoding="utf-8")
    with pytest.raises(tomllib.TOMLDecodeError):
        config_file.load_config_file_strict()
    assert config_file.load_config_file() == {}


def test_explicit_wizard_save_keeps_unknown_legacy_toml_and_legacy_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    legacy = _legacy_config(
        '[output]\nfolder = "synthetic"\ncustom = "keep"\n'
        '[transcription]\nmodel = "tiny"\n[unknown.nested]\nvalues = [1, 2]\n'
    )
    original = legacy.read_bytes()
    monkeypatch.setattr(init_wizard, "_detect_gpu_summary", lambda: (False, "synthetic CPU"))
    monkeypatch.setattr(init_wizard, "_detected_keys", lambda: {})
    monkeypatch.setattr(init_wizard, "_resolve_env_conflicts", Mock())
    monkeypatch.setattr(init_wizard, "_maybe_setup_voice", Mock())
    monkeypatch.setattr(
        init_wizard,
        "_default_obs_settings",
        lambda: {"host": "localhost", "port": "4455", "password": ""},
    )
    monkeypatch.setattr(init_wizard.Prompt, "ask", lambda _prompt, **kw: str(kw["default"]))
    monkeypatch.setattr(init_wizard.Confirm, "ask", lambda *_args, **_kw: False)
    result = init_wizard.run_wizard(Console(file=io.StringIO()), force=True)
    assert result == config_file.CONFIG_PATH
    saved = config_file.load_config_file_strict()
    assert saved["unknown"]["nested"]["values"] == [1, 2]
    assert saved["output"]["custom"] == "keep"
    assert saved["transcription"]["model"] == "tiny"
    assert legacy.read_bytes() == original


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('"$HOME/Vidéos"', "Vidéos"),
        ('"$HOME/Media/Films" # generated comment', "Media/Films"),
        ('"$HOME"', ""),
        ('"$HOME/Video \\"quoted\\" \\$literal"', 'Video "quoted" $literal'),
    ],
)
def test_localized_videos_quoted_format(tmp_path: Path, value: str, expected: str) -> None:
    user_dirs = tmp_path / ".config/user-dirs.dirs"
    user_dirs.parent.mkdir()
    user_dirs.write_text(f"# generated\nXDG_VIDEOS_DIR={value}\n", encoding="utf-8")
    assert paths.videos_dir() == tmp_path / expected


def test_absolute_relocated_videos_and_config_env_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    relocated = tmp_path / "media/recordings"
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    (cfg / "user-dirs.dirs").write_text(
        f'XDG_VIDEOS_DIR="{relocated.as_posix()}"\n', encoding="utf-8"
    )
    assert paths.videos_dir() == relocated
    settings = ScribeConfig(_env_file=None)
    assert settings.output_folder == relocated / "Transcriptions"
    config_file.save_config_file({"output": {"folder": str(tmp_path / "configured")}})
    assert ScribeConfig(_env_file=None).output_folder == tmp_path / "configured"
    monkeypatch.setenv("SCRIBE_OUTPUT_FOLDER", str(tmp_path / "environment"))
    assert ScribeConfig(_env_file=None).output_folder == tmp_path / "environment"
    assert (
        ScribeConfig(output_folder=tmp_path / "explicit", _env_file=None).output_folder
        == tmp_path / "explicit"
    )
    monkeypatch.setenv("SCRIBE_LOG_FOLDER", str(tmp_path / "custom-logs"))
    assert ScribeConfig(_env_file=None).log_folder == tmp_path / "custom-logs"


@pytest.mark.parametrize(
    "value",
    [
        '"relative"',
        '"${HOME}/other"',
        '"$HOME/$(touch marker)"',
        '"$HOME/`touch marker`"',
        '"/tmp"; touch marker',
    ],
)
def test_invalid_or_executable_user_dirs_text_is_not_evaluated(tmp_path: Path, value: str) -> None:
    user_dirs = tmp_path / ".config/user-dirs.dirs"
    user_dirs.parent.mkdir()
    user_dirs.write_text(f"XDG_VIDEOS_DIR={value}\n", encoding="utf-8")
    assert paths.videos_dir() == tmp_path / "Videos"
    assert not (tmp_path / "marker").exists()


def test_vocabulary_precedence_preserves_legacy_and_bundled_lookup(tmp_path: Path) -> None:
    legacy = tmp_path / ".scribe/vocab"
    legacy.mkdir(parents=True)
    (legacy / "synthetic.txt").write_text("legacy-term\n", encoding="utf-8")
    assert "legacy-term" in CustomVocabulary.load("synthetic").words
    current = paths.vocabulary_dirs()[0]
    current.mkdir(parents=True)
    (current / "synthetic.txt").write_text("current-term\n", encoding="utf-8")
    assert CustomVocabulary.load("synthetic").words == ["current-term"]
    assert (legacy / "synthetic.txt").read_text(encoding="utf-8") == "legacy-term\n"
    assert len(CustomVocabulary.load("tech")) > 0


def test_legacy_consent_and_complete_voice_assets_remain_readable(tmp_path: Path) -> None:
    from scribe.cli.consent import ensure_recording_consent
    from scribe.voice.tts import KOKORO_MODEL_FILE, KOKORO_VOICES_FILE, kokoro_dir

    legacy = paths.legacy_dir()
    legacy.mkdir()
    (legacy / "recording_consent_ack").touch()
    assert ensure_recording_consent(Console(file=io.StringIO()))
    voices = legacy / "voices/kokoro"
    voices.mkdir(parents=True)
    for name, size in ((KOKORO_MODEL_FILE, 50_000_000), (KOKORO_VOICES_FILE, 1_000_000)):
        with (voices / name).open("wb") as handle:
            handle.truncate(size)  # Sparse synthetic files; nothing loads these assets.
    assert kokoro_dir() == voices
    current = paths.data_dir() / "voices/kokoro"
    current.mkdir(parents=True)
    assert kokoro_dir() == voices  # An empty or failed new download must not hide working assets.
    for name, size in ((KOKORO_MODEL_FILE, 50_000_000), (KOKORO_VOICES_FILE, 1_000_000)):
        with (current / name).open("wb") as handle:
            handle.truncate(size)
    assert kokoro_dir() == current


@pytest.mark.skipif(not _LINUX, reason="Linux runtime owner/mode contract")
def test_runtime_control_socket_token_and_lock_share_private_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scribe.voice.control import control_socket_path, control_token_path, write_token
    from scribe.voice.instance import TrayInstanceLock, tray_instance_lock_path

    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(base))
    expected = base / "scribe"
    assert (
        control_socket_path().parent
        == control_token_path().parent
        == tray_instance_lock_path().parent
        == expected
    )
    assert stat.S_IMODE(expected.stat().st_mode) == 0o700
    assert expected.stat().st_uid == os.getuid()
    write_token(control_token_path(), "synthetic-token")
    assert stat.S_IMODE(control_token_path().stat().st_mode) == 0o600
    lock = TrayInstanceLock()
    assert lock.acquire()
    try:
        assert not TrayInstanceLock().acquire()
    finally:
        lock.release()
    assert not paths.legacy_dir().exists()


@pytest.mark.skipif(not _LINUX, reason="Linux runtime owner/mode contract")
@pytest.mark.parametrize("empty", [False, True])
def test_unset_runtime_warns_once_and_keeps_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog, empty: bool
) -> None:
    from scribe.voice.control import control_socket_path, control_token_path
    from scribe.voice.instance import tray_instance_lock_path

    if empty:
        monkeypatch.setenv("XDG_RUNTIME_DIR", "")
    for resolver in (control_socket_path, control_token_path, tray_instance_lock_path):
        assert resolver().parent == tmp_path / ".scribe"
    assert stat.S_IMODE((tmp_path / ".scribe").stat().st_mode) == 0o700
    assert sum("XDG_RUNTIME_DIR is unset" in record.message for record in caplog.records) == 1


@pytest.mark.skipif(not _LINUX, reason="Linux runtime owner/mode contract")
@pytest.mark.parametrize(
    "problem",
    [
        "relative",
        "missing",
        "file",
        "symlink",
        "wide-base",
        "wide-child",
        "child-symlink",
        "wrong-owner",
    ],
)
def test_unsafe_explicit_runtime_fails_without_legacy_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, problem: str
) -> None:
    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    if problem == "relative":
        value = "relative/runtime"
    elif problem == "missing":
        value = str(base / "absent")
    elif problem == "file":
        file = tmp_path / "file"
        file.touch()
        value = str(file)
    elif problem == "symlink":
        link = tmp_path / "link"
        link.symlink_to(base, target_is_directory=True)
        value = str(link)
    else:
        value = str(base)
        if problem == "wide-base":
            base.chmod(0o755)
        elif problem == "wide-child":
            (base / "scribe").mkdir(mode=0o755)
        elif problem == "child-symlink":
            (base / "scribe").symlink_to(tmp_path, target_is_directory=True)
        else:
            monkeypatch.setattr(paths.os, "getuid", lambda: base.stat().st_uid + 1)
    monkeypatch.setenv("XDG_RUNTIME_DIR", value)
    with pytest.raises(OSError, match="Unsafe XDG_RUNTIME_DIR"):
        paths.runtime_dir()
    assert not paths.legacy_dir().exists()


@pytest.mark.skipif(not _LINUX, reason="Linux runtime owner/mode contract")
@pytest.mark.parametrize("kind", ["symlink", "wide", "directory", "wrong-owner"])
def test_token_write_rejects_unsafe_existing_leaf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    from scribe.voice.control import write_token

    token = tmp_path / "token"
    target = tmp_path / "untouched"
    target.write_text("original", encoding="utf-8")
    if kind == "symlink":
        token.symlink_to(target)
    elif kind == "directory":
        token.mkdir()
    else:
        token.write_text("original token", encoding="utf-8")
        token.chmod(0o644 if kind == "wide" else 0o600)
        if kind == "wrong-owner":
            monkeypatch.setattr(paths.os, "getuid", lambda: token.stat().st_uid + 1)
    with pytest.raises(OSError, match="expected type"):
        write_token(token, "replacement")
    assert target.read_text(encoding="utf-8") == "original"


@pytest.mark.skipif(not _LINUX, reason="Linux runtime owner/mode contract")
def test_unsafe_runtime_cli_status_and_serve_fail_before_model_start(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scribe.cli.main import app

    monkeypatch.setenv("XDG_RUNTIME_DIR", "relative/unsafe")
    start = Mock(side_effect=AssertionError("a model-owning service must not start"))
    monkeypatch.setattr("scribe.voice.service.VoiceTrayService", start)
    for args in (["voice", "status"], ["voice", "serve", "--no-preload"]):
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 1, result.output
        assert "Unsafe XDG_RUNTIME_DIR" in result.output
        assert "did not fall back" in result.output
    start.assert_not_called()
    assert not paths.legacy_dir().exists()


@pytest.mark.skipif(not _LINUX, reason="Linux Unix-domain control socket contract")
def test_real_control_uses_xdg_token_socket_and_cleanup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scribe.voice.control import (
        ControlServer,
        control_socket_path,
        control_token_path,
        transact,
        write_token,
    )

    base = tmp_path / "runtime"
    base.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(base))
    owner = Mock()
    owner.snapshot.return_value = {"state": "idle"}
    path = control_socket_path()
    write_token(control_token_path(), "synthetic-token")
    server = ControlServer(owner, path, "synthetic-token")
    server.start()
    try:
        assert path.is_socket()
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        result = transact("STATUS", timeout=1.0)
        assert result["ok"] is True
        assert result["state"] == "idle"
    finally:
        server.close()
    assert not path.exists()
    assert control_token_path().is_file()


@pytest.mark.skipif(not _LINUX, reason="Linux runtime leaf type contract")
def test_control_rejects_regular_file_socket_without_deleting_it(tmp_path: Path) -> None:
    from scribe.voice.control import ControlServer

    path = tmp_path / "socket"
    path.write_text("preserve", encoding="utf-8")
    path.chmod(0o600)
    server = ControlServer(Mock(), path, "synthetic-token")
    with pytest.raises(OSError, match="expected type"):
        server.start()
    server.close()
    assert path.read_text(encoding="utf-8") == "preserve"


@pytest.mark.skipif(not _LINUX, reason="Linux runtime leaf permission contract")
def test_lock_rejects_nonprivate_existing_file_without_modification(tmp_path: Path) -> None:
    from scribe.voice.instance import TrayInstanceLock

    path = tmp_path / "lock"
    path.write_bytes(b"preserve")
    path.chmod(0o644)
    with pytest.raises(OSError, match="expected type"):
        TrayInstanceLock(path).acquire()
    assert path.read_bytes() == b"preserve"
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


@pytest.mark.skipif(not _LINUX, reason="Linux runtime directory ownership contract")
def test_runtime_rejects_symlink_ancestor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "runtime").mkdir(mode=0o700)
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(link / "runtime"))
    with pytest.raises(OSError, match="symbolic link"):
        paths.runtime_dir()
    assert not (real / "runtime/scribe").exists()


def test_videos_home_expansion_preserves_literal_home_characters(tmp_path: Path) -> None:
    home = tmp_path / "home$with`literal"
    user_dirs = home / ".config/user-dirs.dirs"
    user_dirs.parent.mkdir(parents=True)
    user_dirs.write_text('XDG_VIDEOS_DIR="$HOME/Vidéos"\n', encoding="utf-8")
    assert paths.videos_dir(home) == home / "Vidéos"


def test_videos_uses_last_usable_assignment_like_generated_shell_format(tmp_path: Path) -> None:
    user_dirs = tmp_path / ".config/user-dirs.dirs"
    user_dirs.parent.mkdir()
    user_dirs.write_text(
        'XDG_VIDEOS_DIR="$HOME/Old"\nXDG_VIDEOS_DIR="$HOME/Current"\n', encoding="utf-8"
    )
    assert paths.videos_dir() == tmp_path / "Current"


@pytest.mark.skipif(not _LINUX, reason="Linux config module import-time defaults")
@pytest.mark.parametrize("override", ["absolute", "relative", "empty"])
def test_fresh_process_config_constants_follow_xdg_environment(
    tmp_path: Path, override: str
) -> None:
    import json
    import subprocess

    environment = os.environ.copy()
    environment["HOME"] = str(tmp_path)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")
    value = (
        str(tmp_path / "cfg")
        if override == "absolute"
        else "relative"
        if override == "relative"
        else ""
    )
    environment["XDG_CONFIG_HOME"] = value
    environment["XDG_DATA_HOME"] = value
    environment["XDG_STATE_HOME"] = value
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; from scribe.config_file import CONFIG_PATH; from scribe.paths import data_dir, state_dir; print(json.dumps([str(CONFIG_PATH), str(data_dir()), str(state_dir())]))",
        ],
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    actual = json.loads(result.stdout)
    expected = (
        [tmp_path / "cfg/scribe/config.toml", tmp_path / "cfg/scribe", tmp_path / "cfg/scribe"]
        if override == "absolute"
        else [
            tmp_path / ".config/scribe/config.toml",
            tmp_path / ".local/share/scribe",
            tmp_path / ".local/state/scribe",
        ]
    )
    assert actual == [str(path) for path in expected]


def test_relative_desktop_and_obs_xdg_overrides_never_use_cwd(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from scribe.cli.shortcut import _linux_applications_dir, _linux_icon_path
    from scribe.cli.voice_session import _hypr_config_dir
    from scribe.utils.obs_config import obs_config_dir
    from scribe.voice.startup import LINUX_AUTOSTART_ID, _linux_autostart_path

    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/config")
    monkeypatch.setenv("XDG_DATA_HOME", "relative/data")
    monkeypatch.setattr("scribe.utils.obs_config.get_platform", lambda: "linux")
    assert _hypr_config_dir() == tmp_path / ".config/hypr"
    assert _linux_autostart_path() == tmp_path / ".config/autostart" / LINUX_AUTOSTART_ID
    assert obs_config_dir() == tmp_path / ".config/obs-studio"
    assert _linux_applications_dir() == tmp_path / ".local/share/applications"
    assert _linux_icon_path() == tmp_path / ".local/share/icons/scribe.png"


def test_recording_search_keeps_legacy_videos_after_localized_destination(tmp_path: Path) -> None:
    from scribe.core.recording_policy import recording_media_candidate_dirs

    user_dirs = tmp_path / ".config/user-dirs.dirs"
    user_dirs.parent.mkdir()
    user_dirs.write_text('XDG_VIDEOS_DIR="$HOME/Vidéos"\n', encoding="utf-8")
    primary = tmp_path / "configured"
    candidates = recording_media_candidate_dirs(primary)
    assert candidates == (
        primary,
        tmp_path / "Vidéos",
        tmp_path / "Vidéos/OBS",
        tmp_path / "Videos",
        tmp_path / "Videos/OBS",
    )
