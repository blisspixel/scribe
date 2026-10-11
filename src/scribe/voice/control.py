"""Short-lived control clients for the single resident voice owner.

The Go native tray keeps its one-shot localhost TCP socket. This channel is a
separate Unix-domain socket so Hyprland commands can reach the same
``VoiceTrayService`` without a second microphone owner or a second model.
"""

from __future__ import annotations

import hmac
import json
import os
import socket
import threading
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

SOCKET_NAME = "voice-control.sock"
TOKEN_NAME = "voice-control.token"  # noqa: S105
COMMANDS = frozenset({"PING", "STATUS", "DICTATE", "CANCEL", "COPY", "INSERT", "READ", "STOP"})

MAX_LINE_BYTES = 8192


class ControlError(RuntimeError):
    """The control channel could not complete one command."""


class VoiceControl(Protocol):
    """Methods the control server calls on the resident owner."""

    running: bool

    def snapshot(self) -> dict[str, object]: ...

    def request_dictation(self) -> str: ...

    def cancel_capture(self) -> str: ...

    def copy_last_transcript(self) -> bool: ...

    def insert_last_transcript(self) -> str: ...

    def read_last_transcript(self) -> str: ...

    def run_exclusive(self, action: Callable[[], str], *, timeout: float = 8.0) -> str: ...

    def stop(self) -> bool: ...


def control_socket_path(home: Path | None = None) -> Path:
    """Return the per-user control socket shared by voice clients."""
    from scribe.paths import runtime_dir

    return runtime_dir(home) / SOCKET_NAME


def control_token_path(home: Path | None = None) -> Path:
    """Return the per-user token file that authorizes one control command."""
    from scribe.paths import runtime_dir

    return runtime_dir(home) / TOKEN_NAME


def restrict_private(path: Path) -> None:
    """Best-effort owner-only mode for the socket, token, and parent directory."""
    with suppress(OSError):
        if path.parent.exists():
            os.chmod(path.parent, 0o700)
    with suppress(OSError):
        if path.is_dir():
            os.chmod(path, 0o700)
        elif path.exists():
            os.chmod(path, 0o600)


def tokens_match(provided: str, expected: str) -> bool:
    """Compare a control token without raising on a different length."""
    if not provided or not expected:
        return False
    provided_bytes = provided.encode("utf-8")
    expected_bytes = expected.encode("utf-8")
    if len(provided_bytes) != len(expected_bytes):
        return False
    return hmac.compare_digest(provided_bytes, expected_bytes)


def encode_request(token: str, command: str) -> bytes:
    """Encode one authenticated command as a single JSON line."""
    normalized = command.strip().upper()
    if normalized not in COMMANDS:
        raise ValueError(f"unknown voice command: {command}")
    payload = json.dumps({"token": token, "command": normalized}, separators=(",", ":"))
    return (payload + "\n").encode("utf-8")


def parse_request(line: str) -> tuple[str, str]:
    """Return ``(token, command)`` or raise ``ControlError`` for a bad line."""
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        raise ControlError("control request is too long")
    try:
        value = json.loads(line)
    except json.JSONDecodeError as error:
        raise ControlError("control request is not JSON") from error
    if not isinstance(value, dict):
        raise ControlError("control request must be an object")
    token = value.get("token")
    command = value.get("command")
    if not isinstance(token, str) or not isinstance(command, str):
        raise ControlError("control request needs a token and a command")
    normalized = command.strip().upper()
    if normalized not in COMMANDS:
        raise ControlError(f"unknown voice command: {command}")
    return token, normalized


def response(ok: bool, **fields: object) -> dict[str, object]:
    """Build one control response. ``validated`` stays false for every command."""
    body: dict[str, object] = {"ok": ok, "experimental": True, "validated": False}
    body.update(fields)
    return body


def apply_command(service: VoiceControl, command: str) -> dict[str, object]:
    """Run one command against the resident owner and return its response."""
    normalized = command.strip().upper()
    if normalized not in COMMANDS:
        return response(False, command=normalized, error=f"unknown voice command: {command}")
    if normalized == "PING":
        return response(True, command=normalized, state=service.snapshot().get("state"))
    if normalized == "STATUS":
        return response(True, command=normalized, **service.snapshot())
    if normalized == "STOP":
        service.stop()
        return response(True, command=normalized, state="stopped")
    if normalized == "DICTATE":
        outcome = service.request_dictation()
        return response(
            outcome in {"starting", "stopping"},
            command=normalized,
            outcome=outcome,
            **service.snapshot(),
        )
    if normalized == "CANCEL":
        outcome = service.run_exclusive(service.cancel_capture)
        return response(
            outcome in {"cancelled", "cancel_requested", "stopped_speaking", "idle"},
            command=normalized,
            outcome=outcome,
            **service.snapshot(),
        )
    if normalized == "COPY":

        def copy_action() -> str:
            return "copied" if service.copy_last_transcript() else "empty"

        copied = service.run_exclusive(copy_action)
        return response(
            copied == "copied",
            command=normalized,
            outcome=copied,
            **service.snapshot(),
        )
    if normalized == "INSERT":
        outcome = service.run_exclusive(service.insert_last_transcript)
        return response(
            outcome == "inserted",
            command=normalized,
            outcome=outcome,
            **service.snapshot(),
        )
    outcome = service.run_exclusive(service.read_last_transcript)
    return response(
        outcome in {"accepted", "stopped"},
        command=normalized,
        outcome=outcome,
        **service.snapshot(),
    )


class ControlServer:
    """Serve one JSON line per connection on the resident voice socket."""

    def __init__(self, service: VoiceControl, socket_path: Path, token: str) -> None:
        self.service = service
        self.socket_path = socket_path
        self.token = token
        self._socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        """Bind the socket and start accepting. Raises if the socket cannot be created."""
        if not hasattr(socket, "AF_UNIX"):
            raise ControlError("this Python build has no Unix-domain sockets")
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        restrict_private(self.socket_path.parent)
        from scribe.paths import validate_runtime_file

        validate_runtime_file(self.socket_path, socket_file=True)
        if self.socket_path.exists() or self.socket_path.is_socket():
            self.socket_path.unlink()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(os.fspath(self.socket_path))
        except OSError:
            server.close()
            raise
        restrict_private(self.socket_path)
        server.listen(8)
        server.settimeout(0.2)
        self._socket = server
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="scribe-voice-control",
        )
        self._thread.start()

    def close(self) -> None:
        """Stop accepting and remove the socket file."""
        self._stop.set()
        server = self._socket
        self._socket = None
        if server is not None:
            with suppress(OSError):
                server.close()
        with suppress(OSError):
            from scribe.paths import validate_runtime_file

            validate_runtime_file(self.socket_path, socket_file=True)
            if self.socket_path.exists() or self.socket_path.is_socket():
                self.socket_path.unlink()

    def _loop(self) -> None:
        server = self._socket
        if server is None:
            return
        while not self._stop.is_set() and self.service.running:
            try:
                connection, _address = server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            try:
                self._handle(connection)
            finally:
                with suppress(OSError):
                    connection.close()

    def _handle(self, connection: socket.socket) -> None:
        connection.settimeout(2.0)
        try:
            raw = _read_line(connection)
            token, command = parse_request(raw)
        except (OSError, UnicodeError, ControlError) as error:
            _send(connection, response(False, error=str(error)))
            return
        if not tokens_match(token, self.token):
            _send(connection, response(False, error="authentication failed"))
            return
        try:
            result = apply_command(self.service, command)
        except Exception as error:
            result = response(False, command=command, error=str(error))
        if command == "STOP":
            self._stop.set()
        _send(connection, result)


def send_command(
    socket_path: Path,
    token: str,
    command: str,
    *,
    timeout: float = 2.0,
) -> dict[str, Any]:
    """Send one command and return the decoded response object."""
    if not hasattr(socket, "AF_UNIX"):
        raise ControlError("this Python build has no Unix-domain sockets")
    from scribe.paths import validate_runtime_file

    validate_runtime_file(socket_path, socket_file=True)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(os.fspath(socket_path))
        client.sendall(encode_request(token, command))
        line = _read_line(client)
    except OSError as error:
        raise ControlError(f"voice control is not reachable: {error}") from error
    finally:
        with suppress(OSError):
            client.close()
    try:
        value = json.loads(line)
    except json.JSONDecodeError as error:
        raise ControlError("voice control returned invalid JSON") from error
    if not isinstance(value, dict):
        raise ControlError("voice control returned an unexpected response")
    return value


def transact(
    command: str,
    *,
    home: Path | None = None,
    spawn: Callable[[], None] | None = None,
    timeout: float = 8.0,
) -> dict[str, Any]:
    """Send one command, starting the owner once when the socket is absent."""
    import time

    socket_path = control_socket_path(home)
    token_path = control_token_path(home)
    deadline = time.monotonic() + timeout
    started = False
    last_error = "resident voice is not running"
    while time.monotonic() < deadline:
        if socket_path.exists() and token_path.is_file():
            from scribe.paths import validate_runtime_file

            validate_runtime_file(token_path)
            token = token_path.read_text(encoding="utf-8").strip()
            try:
                return send_command(socket_path, token, command, timeout=min(2.0, timeout))
            except ControlError as error:
                last_error = str(error)
        elif spawn is not None and not started:
            spawn()
            started = True
        elif spawn is None:
            break
        time.sleep(0.05)
    raise ControlError(last_error)


def write_token(path: Path, token: str) -> None:
    """Write the control token so only the current user can read it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    restrict_private(path.parent)
    from scribe.paths import validate_runtime_file

    validate_runtime_file(path)
    import sys

    if sys.platform == "linux":
        descriptor = os.open(
            path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(token + "\n")
    else:
        path.write_text(token + "\n", encoding="utf-8")
    restrict_private(path)


def _read_line(connection: socket.socket) -> str:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = connection.recv(1024)
        if not chunk:
            break
        size += len(chunk)
        if size > MAX_LINE_BYTES:
            raise ControlError("control line is too long")
        chunks.append(chunk)
        if b"\n" in chunk:
            break
    raw = b"".join(chunks)
    line, _separator, _rest = raw.partition(b"\n")
    return line.decode("utf-8")


def _send(connection: socket.socket, payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    with suppress(OSError):
        connection.sendall(encoded)
