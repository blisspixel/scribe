"""Tests for cross-process resident voice ownership."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scribe.voice import instance
from scribe.voice.instance import (
    TrayInstanceLock,
    TrayInstanceOwner,
    _read_owner,
    tray_instance_lock_path,
)


def test_tray_instance_lock_path_is_stable_per_user(tmp_path: Path) -> None:
    assert tray_instance_lock_path(tmp_path) == tmp_path / ".scribe" / "resident-voice.lock"


def test_owner_description_uses_available_identity() -> None:
    assert TrayInstanceOwner(42, "2.8.1", None).description == "PID 42, Scribe 2.8.1"
    assert TrayInstanceOwner(None, None, None).description == "another process"


def test_instance_lock_rejects_duplicate_and_recovers_after_release(tmp_path: Path) -> None:
    path = tray_instance_lock_path(tmp_path)
    first = TrayInstanceLock(path)
    second = TrayInstanceLock(path)

    assert first.acquire() is True
    assert first.acquire() is True
    assert first.acquired is True
    assert second.acquire() is False
    assert second.owner is not None
    assert second.owner.pid == os.getpid()

    first.release()
    first.release()
    assert first.acquired is False
    assert second.acquire() is True
    second.release()


def test_read_owner_tolerates_invalid_or_partially_typed_metadata(tmp_path: Path) -> None:
    path = tmp_path / "owner"
    path.write_bytes(b"\0not-json")
    with path.open("rb") as handle:
        assert _read_owner(handle) is None

    path.write_bytes(
        b"\0" + json.dumps({"pid": "bad", "version": 123, "started_at": []}).encode("utf-8")
    )
    with path.open("rb") as handle:
        owner = _read_owner(handle)
    assert owner == TrayInstanceOwner(None, None, None)

    path.write_bytes(b"\0" + json.dumps({"pid": True}).encode("utf-8"))
    with path.open("rb") as handle:
        owner = _read_owner(handle)
    assert owner == TrayInstanceOwner(None, None, None)

    path.write_bytes(b"\0" + b"x" * 5000)
    with path.open("rb") as handle:
        assert _read_owner(handle) is None


def test_instance_lock_rejects_symbolic_link(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("do not overwrite", encoding="utf-8")
    link = tmp_path / "lock-link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symbolic links are unavailable for this user")

    with pytest.raises(OSError, match="symbolic link"):
        TrayInstanceLock(link).acquire()
    assert target.read_text(encoding="utf-8") == "do not overwrite"


def test_metadata_write_failure_does_not_leave_false_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = TrayInstanceLock(tmp_path / "resident.lock")

    def fail_write(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(instance, "_write_owner", fail_write)

    with pytest.raises(OSError, match="disk full"):
        lock.acquire()

    assert lock.acquired is False
    assert lock.owner is None

    monkeypatch.undo()
    replacement = TrayInstanceLock(lock.path)
    assert replacement.acquire() is True
    replacement.release()


def test_retained_instance_lock_blocks_relaunch_until_process_cleanup(tmp_path: Path) -> None:
    path = tray_instance_lock_path(tmp_path)
    owner = TrayInstanceLock(path)
    contender = TrayInstanceLock(path)

    assert owner.acquire() is True
    owner.retain_until_process_exit()
    assert contender.acquire() is False

    instance._release_retained_locks()
    assert owner.acquired is False
    assert contender.acquire() is True
    contender.release()


def test_retained_instance_lock_stays_held_during_atexit(tmp_path: Path) -> None:
    path = tray_instance_lock_path(tmp_path)
    atexit_started = tmp_path / "atexit-started"
    script = """
import atexit
import sys
import time
from pathlib import Path

lock_path = Path(sys.argv[1])
signal_path = Path(sys.argv[2])

def linger_during_atexit():
    signal_path.write_text("running", encoding="utf-8")
    time.sleep(1.0)

atexit.register(linger_during_atexit)
from scribe.voice.instance import TrayInstanceLock

lock = TrayInstanceLock(lock_path)
assert lock.acquire()
lock.retain_until_process_exit()
"""
    process = subprocess.Popen([sys.executable, "-c", script, str(path), str(atexit_started)])
    try:
        deadline = time.monotonic() + 5.0
        while not atexit_started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert atexit_started.exists(), "child process did not enter its atexit handler"

        contender = TrayInstanceLock(path)
        assert contender.acquire() is False

        assert process.wait(timeout=5.0) == 0
        assert contender.acquire() is True
        contender.release()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5.0)
