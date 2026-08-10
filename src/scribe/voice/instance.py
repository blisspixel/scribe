"""Cross-process ownership for Scribe's resident voice process.

The lock path is deliberately stable across virtual environments, editable
installs, and future Scribe upgrades. Operating-system file locks are released
when a process exits, so a crash cannot leave a stale lock that blocks the next
launch.
"""

from __future__ import annotations

import errno
import json
import os
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, BinaryIO

LOCK_FILE_NAME = "resident-voice.lock"
_MAX_OWNER_BYTES = 4096


@dataclass(frozen=True)
class TrayInstanceOwner:
    """Best-effort identity read from the process that owns the voice lock."""

    pid: int | None
    version: str | None
    started_at: str | None

    @property
    def description(self) -> str:
        """Return a concise description suitable for terminal output."""
        parts: list[str] = []
        if self.pid is not None:
            parts.append(f"PID {self.pid}")
        if self.version:
            parts.append(f"Scribe {self.version}")
        return ", ".join(parts) if parts else "another process"


def tray_instance_lock_path(home: Path | None = None) -> Path:
    """Return the per-user lock shared by all resident voice entry points."""
    base = Path.home() if home is None else home
    return base / ".scribe" / LOCK_FILE_NAME


class TrayInstanceLock:
    """Own the single resident voice slot for the current operating-system user."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = tray_instance_lock_path() if path is None else path
        self.owner: TrayInstanceOwner | None = None
        self._handle: BinaryIO | None = None

    @property
    def acquired(self) -> bool:
        """Whether this object currently owns the operating-system lock."""
        return self._handle is not None

    def acquire(self) -> bool:
        """Try to become the tray owner without waiting.

        Returns ``False`` when another process already owns resident voice. Other I/O
        failures are raised so callers do not silently run without protection.
        """
        if self._handle is not None:
            return True

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with suppress(OSError):
            os.chmod(self.path.parent, 0o700)

        if self.path.is_symlink():
            raise OSError(f"resident voice lock path must not be a symbolic link: {self.path}")
        open_flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(self.path, open_flags, 0o600)
        try:
            handle = os.fdopen(descriptor, "r+b")
        except BaseException:
            os.close(descriptor)
            raise
        with suppress(OSError):
            os.chmod(self.path, 0o600)
        try:
            _ensure_lock_byte(handle)
            if not _try_lock(handle):
                self.owner = _read_owner(handle)
                handle.close()
                return False
            owner = _current_owner()
            _write_owner(handle, owner)
            self._handle = handle
            self.owner = owner
            return True
        except BaseException:
            self._handle = None
            self.owner = None
            handle.close()
            raise

    def release(self) -> None:
        """Release ownership while leaving the stable lock inode in place."""
        with _RETAINED_LOCKS_GUARD:
            with suppress(ValueError):
                _RETAINED_LOCKS.remove(self)
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        self.owner = None
        try:
            with suppress(OSError):
                handle.seek(0)
                handle.write(b"\0")
                handle.truncate()
                handle.flush()
            _unlock(handle)
        finally:
            handle.close()

    def retain_until_process_exit(self) -> None:
        """Keep ownership until interpreter shutdown.

        Resident commands are process-lifetime workflows. Retaining their lock
        through the final interpreter teardown closes the small but important
        window where a slow daemon worker could still own GPU resources after the
        command returned but before the process exited.
        """
        if self._handle is None:
            raise RuntimeError("cannot retain a resident voice lock that is not acquired")
        with _RETAINED_LOCKS_GUARD:
            if self not in _RETAINED_LOCKS:
                _RETAINED_LOCKS.append(self)


def _ensure_lock_byte(handle: BinaryIO) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def _try_lock(handle: BinaryIO) -> bool:
    """Acquire one non-blocking exclusive lock using the native OS primitive."""
    if os.name == "nt":
        msvcrt: Any = __import__("msvcrt")

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                return False
            raise

    fcntl: Any = __import__("fcntl")

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as error:
        if error.errno in {errno.EACCES, errno.EAGAIN}:
            return False
        raise


def _unlock(handle: BinaryIO) -> None:
    handle.seek(0)
    if os.name == "nt":
        msvcrt: Any = __import__("msvcrt")

        with suppress(OSError):
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    fcntl: Any = __import__("fcntl")

    with suppress(OSError):
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _current_owner() -> TrayInstanceOwner:
    try:
        package_version = version("scribe")
    except PackageNotFoundError:
        package_version = None
    return TrayInstanceOwner(
        pid=os.getpid(),
        version=package_version,
        started_at=datetime.now(UTC).isoformat(),
    )


def _write_owner(handle: BinaryIO, owner: TrayInstanceOwner) -> None:
    payload = json.dumps(
        {
            "pid": owner.pid,
            "version": owner.version,
            "started_at": owner.started_at,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    handle.seek(0)
    handle.write(b"\0" + payload)
    handle.truncate()
    handle.flush()


def _read_owner(handle: BinaryIO) -> TrayInstanceOwner | None:
    try:
        handle.seek(1)
        payload = handle.read(_MAX_OWNER_BYTES + 1)
        if len(payload) > _MAX_OWNER_BYTES:
            return None
        value: Any = json.loads(payload.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    pid_value = value.get("pid")
    version_value = value.get("version")
    started_value = value.get("started_at")
    return TrayInstanceOwner(
        pid=pid_value if isinstance(pid_value, int) and not isinstance(pid_value, bool) else None,
        version=version_value if isinstance(version_value, str) else None,
        started_at=started_value if isinstance(started_value, str) else None,
    )


_RETAINED_LOCKS: list[TrayInstanceLock] = []
_RETAINED_LOCKS_GUARD = threading.Lock()


def _release_retained_locks() -> None:
    """Release retained locks explicitly in tests or controlled non-resident use."""
    while True:
        with _RETAINED_LOCKS_GUARD:
            if not _RETAINED_LOCKS:
                return
            instance_lock = _RETAINED_LOCKS.pop()
        with suppress(Exception):
            instance_lock.release()


# Do not register an atexit release. Python runs atexit handlers before final
# interpreter and daemon-thread teardown, which would reopen the duplicate-launch
# window while the old process could still own CUDA or hotkey resources. Retained
# locks deliberately stay open for the operating system to release at process exit.
