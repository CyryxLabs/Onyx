"""Authenticated, cooperative lifecycle channel for installer maintenance.

The installed executable is both server and client.  A resident Onyx process
publishes a short-lived capability record below its fixed private runtime
directory and listens on a local-only Windows named pipe.  A second invocation
of the *same executable* consumes that capability, asks the live runtime to
perform its governed cleanup, verifies the signed cleanup receipt, and then
waits for the original process identity to disappear.

This module never terminates another process.  A timeout or incomplete cleanup
is an explicit refusal so packaging can stop before replacing live files.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import stat
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping

from core.paths import private_control_plane_runtime_dir


SCHEMA = "onyx.installer-lifecycle.v1"
CHALLENGE_SCHEMA = "onyx.installer-lifecycle-challenge.v1"
REQUEST_SCHEMA = "onyx.installer-lifecycle-request.v1"
RECEIPT_SCHEMA = "onyx.installer-lifecycle-receipt.v1"
RECORD_NAME = "resident.json"
MAX_FRAME = 16 * 1024
EXIT_OK = 0
EXIT_REFUSED = 20
EXIT_TIMEOUT = 21
EXIT_SECURITY = 22
EXIT_PROTOCOL = 23


class InstallerLifecycleError(RuntimeError):
    """Base error for a fail-closed lifecycle transaction."""


class InstallerLifecycleSecurityError(InstallerLifecycleError):
    """A filesystem, identity, ACL, or authentication check failed."""


class InstallerLifecycleProtocolError(InstallerLifecycleError):
    """A peer sent data outside the exact lifecycle schema."""


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    started: str
    executable: str
    executable_sha256: str
    version: str


@dataclass(frozen=True, slots=True)
class ClientResult:
    exit_code: int
    status: str
    detail: str
    receipt: Mapping[str, object] | None = None


def lifecycle_dir() -> Path:
    return private_control_plane_runtime_dir() / "installer-lifecycle-v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _process_started(pid: int) -> str:
    try:
        import psutil

        return f"{psutil.Process(pid).create_time():.6f}"
    except Exception as exc:
        raise InstallerLifecycleSecurityError(
            "process start identity is unavailable"
        ) from exc


def _process_executable(pid: int) -> Path:
    try:
        import psutil

        return Path(psutil.Process(pid).exe()).resolve(strict=True)
    except Exception as exc:
        raise InstallerLifecycleSecurityError(
            "process executable identity is unavailable"
        ) from exc


def _same_process(identity: ProcessIdentity) -> bool:
    try:
        return _process_started(
            identity.pid
        ) == identity.started and _process_executable(identity.pid) == Path(
            identity.executable
        ).resolve(strict=True)
    except InstallerLifecycleSecurityError:
        return False


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(os.fspath(left))) == os.path.normcase(
        os.path.abspath(os.fspath(right))
    )


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _mac(token: bytes, payload: Mapping[str, object]) -> str:
    return hmac.new(token, _canonical(payload), hashlib.sha256).hexdigest()


def _reject_reparse(path: Path) -> None:
    if os.name != "nt":
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise InstallerLifecycleSecurityError("lifecycle path is linked")
        return
    import win32con
    import win32file

    try:
        attributes = win32file.GetFileAttributes(str(path))
    except Exception as exc:
        if getattr(exc, "winerror", None) in {2, 3}:
            raise FileNotFoundError(os.fspath(path)) from exc
        raise InstallerLifecycleSecurityError(
            "lifecycle path attributes are unavailable"
        ) from exc
    # GetFileAttributes may return INVALID_FILE_ATTRIBUTES instead of raising.
    # Never bit-test 0xFFFFFFFF: every attribute bit is set, including REPARSE.
    if attributes in {-1, 0xFFFFFFFF}:
        import win32api

        error = int(win32api.GetLastError())
        if error in {2, 3}:
            raise FileNotFoundError(os.fspath(path))
        raise InstallerLifecycleSecurityError(
            f"lifecycle path attributes are unavailable ({error})"
        )
    if attributes & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
        raise InstallerLifecycleSecurityError("lifecycle path is a reparse point")


def _reject_reparse_ancestors(path: Path) -> None:
    current = Path(os.path.abspath(os.fspath(path)))
    while True:
        _reject_reparse(current)
        parent = current.parent
        if parent == current:
            return
        current = parent


def _current_windows_sid():
    import win32api
    import win32con
    import win32security

    token = win32security.OpenProcessToken(
        win32api.GetCurrentProcess(), win32con.TOKEN_QUERY
    )
    return win32security.GetTokenInformation(token, win32security.TokenUser)[0]


def _secure_windows_directory(path: Path) -> None:
    import ntsecuritycon
    import win32security

    sid = _current_windows_sid()
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAce(
        win32security.ACL_REVISION,
        ntsecuritycon.FILE_ALL_ACCESS,
        sid,
    )
    win32security.SetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.DACL_SECURITY_INFORMATION
        | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
        None,
        None,
        dacl,
        None,
    )
    security = win32security.GetNamedSecurityInfo(
        str(path),
        win32security.SE_FILE_OBJECT,
        win32security.OWNER_SECURITY_INFORMATION
        | win32security.DACL_SECURITY_INFORMATION,
    )
    owner = security.GetSecurityDescriptorOwner()
    actual = security.GetSecurityDescriptorDacl()
    if owner != sid or actual is None or actual.GetAceCount() != 1:
        raise InstallerLifecycleSecurityError("lifecycle directory ACL is not private")
    ace = actual.GetAce(0)
    if ace[2] != sid or ace[0][0] != win32security.ACCESS_ALLOWED_ACE_TYPE:
        raise InstallerLifecycleSecurityError("lifecycle directory ACL drifted")


def _ensure_private_root(root: Path, *, enforce_security: bool) -> Path:
    candidate = Path(os.path.abspath(os.fspath(root)))
    if not candidate.is_absolute() or candidate.name != "installer-lifecycle-v1":
        raise InstallerLifecycleSecurityError("invalid lifecycle directory")
    candidate.mkdir(parents=True, exist_ok=True)
    _reject_reparse_ancestors(candidate)
    if enforce_security:
        if os.name == "nt":
            _secure_windows_directory(candidate)
        else:
            candidate.chmod(0o700)
            info = candidate.stat()
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                raise InstallerLifecycleSecurityError(
                    "lifecycle directory is not owner-only"
                )
    return candidate


def _atomic_write(root: Path, name: str, payload: Mapping[str, object]) -> Path:
    if name != RECORD_NAME:
        raise InstallerLifecycleSecurityError("unexpected lifecycle record name")
    target = root / name
    if target.exists() or target.is_symlink():
        _reject_reparse(target)
        if not target.is_file():
            raise InstallerLifecycleSecurityError("lifecycle record is not a file")
    temporary = root / f".{name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(temporary, flags, 0o600)
    try:
        encoded = _canonical(payload) + b"\n"
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, target)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    _reject_reparse(target)
    return target


def _windows_read_no_follow(path: Path) -> bytes:
    import win32con
    import win32file

    try:
        handle = win32file.CreateFile(
            str(path),
            win32con.GENERIC_READ,
            win32con.FILE_SHARE_READ
            | win32con.FILE_SHARE_WRITE
            | win32con.FILE_SHARE_DELETE,
            None,
            win32con.OPEN_EXISTING,
            getattr(win32file, "FILE_FLAG_OPEN_REPARSE_POINT", 0x00200000)
            | win32con.FILE_FLAG_SEQUENTIAL_SCAN,
            None,
        )
    except Exception as exc:
        if getattr(exc, "winerror", None) in {2, 3}:
            raise FileNotFoundError(os.fspath(path)) from exc
        raise InstallerLifecycleSecurityError(
            "lifecycle record could not be opened safely"
        ) from exc
    try:
        before = win32file.GetFileInformationByHandle(handle)
        if int(before[0]) & win32con.FILE_ATTRIBUTE_REPARSE_POINT:
            raise InstallerLifecycleSecurityError("lifecycle record is a reparse point")
        final = win32file.GetFinalPathNameByHandle(handle, 0)
        if final.startswith("\\\\?\\"):
            final = final[4:]
        if not _same_path(Path(final), path):
            raise InstallerLifecycleSecurityError(
                "lifecycle record path identity drifted"
            )
        chunks = bytearray()
        while len(chunks) <= MAX_FRAME:
            _status, block = win32file.ReadFile(
                handle, min(4096, MAX_FRAME + 1 - len(chunks))
            )
            if not block:
                break
            chunks.extend(block)
        after = win32file.GetFileInformationByHandle(handle)
        identity_fields = (4, 8, 9)
        if any(before[index] != after[index] for index in identity_fields):
            raise InstallerLifecycleSecurityError(
                "lifecycle record changed identity while read"
            )
        return bytes(chunks)
    finally:
        handle.Close()


def _posix_read_no_follow(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise InstallerLifecycleSecurityError(
            "lifecycle record could not be opened safely"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise InstallerLifecycleSecurityError("lifecycle record is not a file")
        raw = os.read(descriptor, MAX_FRAME + 1)
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise InstallerLifecycleSecurityError(
                "lifecycle record changed identity while read"
            )
        return raw
    finally:
        os.close(descriptor)


def _read_record(root: Path) -> dict[str, object] | None:
    target = root / RECORD_NAME
    try:
        raw = (
            _windows_read_no_follow(target)
            if os.name == "nt"
            else _posix_read_no_follow(target)
        )
    except FileNotFoundError:
        return None
    if len(raw) > MAX_FRAME:
        raise InstallerLifecycleSecurityError("lifecycle record is oversized")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallerLifecycleSecurityError("lifecycle record is invalid") from exc
    required = {
        "schema",
        "state",
        "generation",
        "pipe",
        "pid",
        "started",
        "executable",
        "executable_sha256",
        "version",
        "issued_at_ns",
    }
    if type(value) is not dict or set(value) != required:
        raise InstallerLifecycleSecurityError("lifecycle record schema drifted")
    if value["schema"] != SCHEMA or value["state"] != "listening":
        raise InstallerLifecycleSecurityError("lifecycle record is not live")
    if not isinstance(value["pid"], int) or value["pid"] <= 0:
        raise InstallerLifecycleSecurityError("lifecycle pid is invalid")
    for key in ("generation", "started", "executable", "executable_sha256", "version"):
        if not isinstance(value[key], str) or not value[key]:
            raise InstallerLifecycleSecurityError(f"lifecycle {key} is invalid")
    if len(value["generation"]) != 32:
        raise InstallerLifecycleSecurityError("lifecycle capability is invalid")
    if len(value["executable_sha256"]) != 64:
        raise InstallerLifecycleSecurityError("lifecycle executable digest is invalid")
    pipe = value["pipe"]
    if not isinstance(pipe, str) or not pipe.startswith(r"\\.\pipe\CyryxLabs-Onyx-"):
        raise InstallerLifecycleSecurityError("lifecycle pipe is invalid")
    return value


def _identity_from_record(record: Mapping[str, object]) -> ProcessIdentity:
    return ProcessIdentity(
        pid=int(record["pid"]),
        started=str(record["started"]),
        executable=str(record["executable"]),
        executable_sha256=str(record["executable_sha256"]),
        version=str(record["version"]),
    )


def _security_attributes():
    import ntsecuritycon
    import pywintypes
    import win32security

    sid = _current_windows_sid()
    dacl = win32security.ACL()
    dacl.AddAccessAllowedAce(win32security.ACL_REVISION, ntsecuritycon.GENERIC_ALL, sid)
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorDacl(1, dacl, 0)
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    attributes.bInheritHandle = 0
    return attributes


def _read_exact(handle, size: int) -> bytes:
    import win32file

    chunks = bytearray()
    while len(chunks) < size:
        _status, data = win32file.ReadFile(handle, size - len(chunks))
        if not data:
            raise InstallerLifecycleProtocolError("lifecycle frame ended early")
        chunks.extend(data)
    return bytes(chunks)


def _read_frame(handle) -> dict[str, object]:
    length = int.from_bytes(_read_exact(handle, 4), "big")
    if length <= 0 or length > MAX_FRAME:
        raise InstallerLifecycleProtocolError("lifecycle frame length is invalid")
    try:
        value = json.loads(_read_exact(handle, length))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallerLifecycleProtocolError("lifecycle frame is invalid") from exc
    if type(value) is not dict:
        raise InstallerLifecycleProtocolError("lifecycle frame must be an object")
    return value


def _write_frame(handle, payload: Mapping[str, object]) -> None:
    import win32file

    encoded = _canonical(payload)
    if len(encoded) > MAX_FRAME:
        raise InstallerLifecycleProtocolError("lifecycle response is oversized")
    win32file.WriteFile(handle, len(encoded).to_bytes(4, "big") + encoded)
    win32file.FlushFileBuffers(handle)


def _connected_client_identity(handle, *, version: str) -> ProcessIdentity:
    import win32pipe

    try:
        pid = int(win32pipe.GetNamedPipeClientProcessId(handle))
    except Exception as exc:
        raise InstallerLifecycleSecurityError(
            "named-pipe client process identity is unavailable"
        ) from exc
    if pid <= 0:
        raise InstallerLifecycleSecurityError("named-pipe client pid is invalid")
    executable = _process_executable(pid)
    _reject_reparse_ancestors(executable)
    return ProcessIdentity(
        pid=pid,
        started=_process_started(pid),
        executable=str(executable),
        executable_sha256=_sha256_file(executable),
        version=version,
    )


class InstallerLifecycleServer:
    """One resident same-user maintenance endpoint with rotating capabilities."""

    def __init__(
        self,
        *,
        begin_shutdown: Callable[[str], bool],
        shutdown_status: Callable[[], tuple[str, str]],
        exit_after_receipt: Callable[[], bool],
        version: str,
        root: Path | None = None,
        executable: Path | None = None,
        cleanup_timeout: float = 60.0,
        enforce_security: bool = True,
    ) -> None:
        if os.name != "nt":
            raise InstallerLifecycleError(
                "installer lifecycle named pipe requires Windows"
            )
        self.root = _ensure_private_root(
            root or lifecycle_dir(), enforce_security=enforce_security
        )
        self.executable = (executable or Path(sys.executable)).resolve(strict=True)
        _reject_reparse_ancestors(self.executable)
        self.identity = ProcessIdentity(
            pid=os.getpid(),
            started=_process_started(os.getpid()),
            executable=str(self.executable),
            executable_sha256=_sha256_file(self.executable),
            version=str(version),
        )
        self.begin_shutdown = begin_shutdown
        self.shutdown_status = shutdown_status
        self.exit_after_receipt = exit_after_receipt
        self.cleanup_timeout = max(1.0, min(float(cleanup_timeout), 180.0))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pipe = None

    def start(self) -> bool:
        if self._thread is not None and self._thread.is_alive():
            return False
        self._thread = threading.Thread(
            target=self._serve, name="onyx-installer-lifecycle", daemon=True
        )
        self._thread.start()
        return True

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        # Wake ConnectNamedPipe without killing or touching the live runtime.
        try:
            record = _read_record(self.root)
        except InstallerLifecycleSecurityError:
            record = None
        if record is not None:
            try:
                self._connect(str(record["pipe"]), timeout=0.2).Close()
            except Exception:
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=max(0.0, timeout))
        try:
            (self.root / RECORD_NAME).unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _connect(pipe: str, *, timeout: float):
        import win32con
        import win32file
        import win32pipe

        win32pipe.WaitNamedPipe(pipe, max(1, int(timeout * 1000)))
        return win32file.CreateFile(
            pipe,
            win32con.GENERIC_READ | win32con.GENERIC_WRITE,
            0,
            None,
            win32con.OPEN_EXISTING,
            0,
            None,
        )

    def _serve(self) -> None:
        import win32pipe

        while not self._stop.is_set():
            generation = secrets.token_hex(16)
            token = secrets.token_bytes(32)
            pipe_name = rf"\\.\pipe\CyryxLabs-Onyx-{generation}"
            record = {
                "schema": SCHEMA,
                "state": "listening",
                "generation": generation,
                "pipe": pipe_name,
                "pid": self.identity.pid,
                "started": self.identity.started,
                "executable": self.identity.executable,
                "executable_sha256": self.identity.executable_sha256,
                "version": self.identity.version,
                "issued_at_ns": time.time_ns(),
            }
            handle = win32pipe.CreateNamedPipe(
                pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX
                | getattr(win32pipe, "FILE_FLAG_FIRST_PIPE_INSTANCE", 0x00080000),
                win32pipe.PIPE_TYPE_BYTE
                | win32pipe.PIPE_READMODE_BYTE
                | win32pipe.PIPE_WAIT
                | getattr(win32pipe, "PIPE_REJECT_REMOTE_CLIENTS", 0x8),
                1,
                MAX_FRAME,
                MAX_FRAME,
                5000,
                _security_attributes(),
            )
            self._pipe = handle
            try:
                _atomic_write(self.root, RECORD_NAME, record)
                try:
                    win32pipe.ConnectNamedPipe(handle, None)
                except Exception as exc:
                    # ERROR_PIPE_CONNECTED is a successful client race.
                    if getattr(exc, "winerror", None) != 535:
                        raise
                if self._stop.is_set():
                    return
                peer = _connected_client_identity(handle, version=self.identity.version)
                if not _same_path(Path(peer.executable), self.executable):
                    raise InstallerLifecycleSecurityError(
                        "named-pipe client executable path does not match installed Onyx"
                    )
                if peer.executable_sha256 != self.identity.executable_sha256:
                    raise InstallerLifecycleSecurityError(
                        "named-pipe client executable hash does not match installed Onyx"
                    )
                challenge_core = {
                    "schema": CHALLENGE_SCHEMA,
                    "generation": generation,
                    "token": token.hex(),
                    "client": {
                        "pid": peer.pid,
                        "started": peer.started,
                        "executable": peer.executable,
                        "executable_sha256": peer.executable_sha256,
                        "version": peer.version,
                    },
                    "target": {
                        "pid": self.identity.pid,
                        "started": self.identity.started,
                        "executable_sha256": self.identity.executable_sha256,
                        "version": self.identity.version,
                    },
                }
                challenge = dict(challenge_core)
                challenge["mac"] = _mac(token, challenge_core)
                _write_frame(handle, challenge)
                request = _read_frame(handle)
                required = {
                    "schema",
                    "operation",
                    "reason",
                    "request_id",
                    "generation",
                    "client",
                    "target",
                    "mac",
                }
                if set(request) != required or request.get("schema") != REQUEST_SCHEMA:
                    raise InstallerLifecycleProtocolError(
                        "lifecycle request schema drifted"
                    )
                if request.get("operation") != "maintenance-shutdown":
                    raise InstallerLifecycleProtocolError(
                        "unsupported lifecycle operation"
                    )
                request_mac = request.pop("mac", None)
                if (
                    request.get("generation") != generation
                    or not isinstance(request_mac, str)
                    or not hmac.compare_digest(request_mac, _mac(token, request))
                ):
                    raise InstallerLifecycleSecurityError(
                        "lifecycle capability rejected"
                    )
                if request.get("client") != challenge_core["client"]:
                    raise InstallerLifecycleSecurityError(
                        "lifecycle client identity drifted"
                    )
                if request.get("target") != {
                    "pid": self.identity.pid,
                    "started": self.identity.started,
                    "executable_sha256": self.identity.executable_sha256,
                    "version": self.identity.version,
                }:
                    raise InstallerLifecycleSecurityError(
                        "lifecycle target identity drifted"
                    )
                request_id = request.get("request_id")
                if not isinstance(request_id, str) or len(request_id) != 32:
                    raise InstallerLifecycleProtocolError(
                        "lifecycle request id is invalid"
                    )
                consumed = dict(record)
                consumed["state"] = "consumed"
                _atomic_write(self.root, RECORD_NAME, consumed)
                accepted = self.begin_shutdown(
                    str(request.get("reason", "installer"))[:80]
                )
                status = "refused"
                detail = "runtime refused maintenance shutdown"
                if not accepted:
                    # A fail-closed runtime may already know the exact boundary
                    # that prevents maintenance (for example, construction or
                    # cleanup recovery). Preserve that bounded diagnosis in the
                    # authenticated receipt instead of replacing it with a
                    # generic refusal that the installer cannot act on.
                    state, state_detail = self.shutdown_status()
                    if state == "refused":
                        detail = state_detail
                else:
                    deadline = time.monotonic() + self.cleanup_timeout
                    while time.monotonic() < deadline:
                        state, state_detail = self.shutdown_status()
                        if state in {"complete", "refused"}:
                            status, detail = state, state_detail
                            break
                        time.sleep(0.05)
                    else:
                        detail = "governed cleanup exceeded the installer timeout"
                core = {
                    "schema": RECEIPT_SCHEMA,
                    "request_id": request_id,
                    "status": status,
                    "detail": detail[:240],
                    "receipt_nonce": secrets.token_hex(16),
                    "server": {
                        "pid": self.identity.pid,
                        "started": self.identity.started,
                        "executable_sha256": self.identity.executable_sha256,
                        "version": self.identity.version,
                    },
                }
                response = dict(core)
                response["mac"] = _mac(token, core)
                _write_frame(handle, response)
                if status == "complete":
                    try:
                        (self.root / RECORD_NAME).unlink()
                    except FileNotFoundError:
                        pass
                    self.exit_after_receipt()
                    return
            except (InstallerLifecycleError, OSError):
                # A malformed or unauthorized connection grants no authority.
                # Rotate the capability and keep the resident runtime available.
                pass
            finally:
                try:
                    win32pipe.DisconnectNamedPipe(handle)
                except Exception:
                    pass
                handle.Close()
                self._pipe = None


def request_installer_shutdown(
    *,
    reason: str,
    timeout: float = 75.0,
    root: Path | None = None,
    executable: Path | None = None,
    enforce_security: bool = True,
) -> ClientResult:
    """Request cleanup from the bound resident and wait for that PID to exit."""

    if os.name != "nt":
        return ClientResult(
            EXIT_REFUSED, "unsupported", "Windows lifecycle channel unavailable"
        )
    private = _ensure_private_root(
        root or lifecycle_dir(), enforce_security=enforce_security
    )
    record = _read_record(private)
    if record is None:
        return ClientResult(EXIT_OK, "not-running", "no resident lifecycle record")
    identity = _identity_from_record(record)
    if not _same_process(identity):
        try:
            (private / RECORD_NAME).unlink()
        except FileNotFoundError:
            pass
        return ClientResult(
            EXIT_OK, "not-running", "stale resident lifecycle record removed"
        )
    caller = (executable or Path(sys.executable)).resolve(strict=True)
    _reject_reparse_ancestors(caller)
    if not _same_path(caller, Path(identity.executable).resolve(strict=True)):
        return ClientResult(
            EXIT_SECURITY, "refused", "client executable path does not match resident"
        )
    if _sha256_file(caller) != identity.executable_sha256:
        return ClientResult(
            EXIT_SECURITY, "refused", "client executable hash does not match resident"
        )
    request_id = secrets.token_hex(16)
    expected_target = {
        "pid": identity.pid,
        "started": identity.started,
        "executable_sha256": identity.executable_sha256,
        "version": identity.version,
    }
    deadline = time.monotonic() + max(1.0, min(float(timeout), 180.0))
    try:
        handle = InstallerLifecycleServer._connect(
            str(record["pipe"]), timeout=min(5.0, max(0.1, deadline - time.monotonic()))
        )
        try:
            challenge = _read_frame(handle)
            challenge_mac = challenge.pop("mac", None)
            token_hex = challenge.get("token")
            if not isinstance(token_hex, str) or len(token_hex) != 64:
                raise InstallerLifecycleSecurityError(
                    "lifecycle challenge capability is invalid"
                )
            token = bytes.fromhex(token_hex)
            if (
                not isinstance(challenge_mac, str)
                or not hmac.compare_digest(challenge_mac, _mac(token, challenge))
                or challenge.get("schema") != CHALLENGE_SCHEMA
                or challenge.get("generation") != record["generation"]
                or challenge.get("target") != expected_target
            ):
                raise InstallerLifecycleSecurityError(
                    "lifecycle challenge authentication failed"
                )
            client = challenge.get("client")
            if not isinstance(client, dict) or client != {
                "pid": os.getpid(),
                "started": _process_started(os.getpid()),
                "executable": str(caller),
                "executable_sha256": _sha256_file(caller),
                "version": identity.version,
            }:
                raise InstallerLifecycleSecurityError(
                    "lifecycle challenge client identity drifted"
                )
            request = {
                "schema": REQUEST_SCHEMA,
                "operation": "maintenance-shutdown",
                "reason": str(reason)[:80],
                "request_id": request_id,
                "generation": record["generation"],
                "client": client,
                "target": expected_target,
            }
            request["mac"] = _mac(token, request)
            _write_frame(handle, request)
            response = _read_frame(handle)
        finally:
            handle.Close()
    except Exception as exc:
        return ClientResult(
            EXIT_PROTOCOL,
            "refused",
            f"lifecycle transport failed: {type(exc).__name__}",
        )
    mac = response.pop("mac", None)
    if not isinstance(mac, str) or not hmac.compare_digest(mac, _mac(token, response)):
        return ClientResult(
            EXIT_SECURITY, "refused", "server receipt authentication failed"
        )
    expected_server = expected_target
    if (
        response.get("schema") != RECEIPT_SCHEMA
        or response.get("request_id") != request_id
        or response.get("server") != expected_server
    ):
        return ClientResult(EXIT_PROTOCOL, "refused", "server receipt identity drifted")
    if response.get("status") != "complete":
        return ClientResult(
            EXIT_REFUSED,
            "refused",
            str(response.get("detail", "governed cleanup refused")),
            response,
        )
    while time.monotonic() < deadline:
        if not _same_process(identity):
            return ClientResult(
                EXIT_OK,
                "complete",
                "governed cleanup and process exit verified",
                response,
            )
        time.sleep(0.05)
    return ClientResult(
        EXIT_TIMEOUT,
        "refused",
        "resident did not exit after authenticated cleanup",
        response,
    )


def installer_client_main(argv: list[str]) -> int:
    reason = "installer-maintenance"
    timeout = 75.0
    for argument in argv:
        if argument.startswith("--maintenance-reason="):
            reason = argument.partition("=")[2]
        elif argument.startswith("--timeout-seconds="):
            try:
                timeout = float(argument.partition("=")[2])
            except ValueError:
                return EXIT_PROTOCOL
    result = request_installer_shutdown(reason=reason, timeout=timeout)
    stream = sys.stdout if result.exit_code == EXIT_OK else sys.stderr
    if stream is not None:
        print(
            json.dumps(
                {"schema": SCHEMA, "status": result.status, "detail": result.detail},
                sort_keys=True,
            ),
            file=stream,
            flush=True,
        )
    return result.exit_code
