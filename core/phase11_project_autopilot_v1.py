"""Default-off Phase 11 patch isolation with non-executable static gates."""

from __future__ import annotations

import ast
import ctypes
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator, Mapping, Protocol, Sequence, cast
from ctypes import wintypes

from core import native_vault
from core.phase11_executable_sandbox_v1 import (
    ExecutableSandboxHostV1,
    ExecutableTestSandboxV1,
)
from core.phase11_execution_ledger_v1 import Phase11ExecutionLedgerV1
from core.missions import MissionError
from memory.store import _harden_mode, _is_reparse

if os.name == "nt":
    import msvcrt
else:  # pragma: no cover - enabled constructor refuses non-Windows
    msvcrt = None  # type: ignore[assignment]


FEATURE_FLAG = "ONYX_PHASE11_PROJECT_AUTOPILOT_V1"
MISSION_TYPE = "project_autopilot_v1"
TOOL_NAME = "phase11_project_autopilot_v1"
SCHEMA = "onyx.phase11.project_autopilot.v2"
CHECKPOINT_SCHEMA = "onyx.phase11.project_autopilot.checkpoint.v2"
EXECUTABLE_PLAN_SCHEMA = "onyx.phase11.project_autopilot.executable_plan.v1"
ANCHOR_SCHEMA = "onyx.phase11.project_autopilot.anchor.v1"
TRANSACTION_SCHEMA = "onyx.phase11.project_autopilot.transaction.v1"
MAX_PATCH_BYTES = 256 * 1024
MAX_GATE_COUNT = 8
MAX_GATE_ARG_COUNT = 32
MAX_GIT_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_EXECUTABLE_TIMEOUT_SECONDS = 300.0
MAX_DIRTY_BYTES = 16 * 1024 * 1024
MAX_DIRTY_FILES = 2_000
MAX_OWNER_GIT_BYTES = 512 * 1024 * 1024
MAX_OWNER_GIT_FILES = 25_000
MAX_OWNER_GIT_DIRS = 10_000
MAX_STATIC_FILE_BYTES = 2 * 1024 * 1024
MAX_CLONE_BYTES = 768 * 1024 * 1024
MAX_CLONE_FILES = 50_000
MAX_CLONE_DIRS = 20_000
CLONE_FREE_SPACE_MARGIN = 64 * 1024 * 1024
MAX_MONITOR_FILES = 60_000
MAX_MONITOR_DIRS = 25_000
MAX_MONITOR_DEPTH = 64
MAX_MONITOR_SECONDS = 2.0
MAX_MISSION_LOCK_ENTRIES = 4_096
MAX_PROCESS_HIGH_WATER_ENTRIES = 4_096
_BOUND_GIT_RETRY_DELAYS_SECONDS = (0.05, 0.15)
_CLONE_TREE_RETRY_DELAYS_SECONDS = (0.01, 0.05)
_CHECKPOINT_DOMAIN = b"ONYX/PHASE11/PROJECT-AUTOPILOT/CHECKPOINT/V2\0"
_ANCHOR_DOMAIN = b"ONYX/PHASE11/PROJECT-AUTOPILOT/ANCHOR/V1\0"
_TRANSACTION_DOMAIN = b"ONYX/PHASE11/PROJECT-AUTOPILOT/TRANSACTION/V1\0"
_RECEIPT_DOMAIN = b"ONYX/PHASE11/PROJECT-AUTOPILOT/RECEIPT/V2\0"
_EXECUTABLE_AUTH_DOMAIN = b"ONYX/PHASE11/PROJECT-AUTOPILOT/EXECUTABLE-AUTH/V1\0"
_SANDBOX_SUBKEY_DOMAIN = b"ONYX/PHASE11/PROJECT-AUTOPILOT/SANDBOX-SUBKEY/V1\0"
_EXECUTION_ID_DOMAIN = b"ONYX/PHASE11/PROJECT-AUTOPILOT/EXECUTION-ID/V1\0"
_DIFF_HEADER = re.compile(r"^diff --git a/([^\s]+) b/([^\s]+)$")
_HUNK_HEADER = re.compile(
    r"^@@ -([0-9]+)(?:,([0-9]+))? \+([0-9]+)(?:,([0-9]+))? @@(?: .*)?$"
)
_GIT_CONFIG_SECTION = re.compile(
    r"^\[\s*(?P<section>[A-Za-z0-9][A-Za-z0-9.-]*)"
    r'(?:\s+"(?:[^"\\\r\n]|\\[^\r\n])*")?\s*\]'
    r"\s*(?:[#;].*)?$"
)
_GIT_CONFIG_KEY = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9-]*)(?:\s*=|\s*$)")
_SAFE_MISSION_ID = re.compile(r"^mis_[0-9a-f]{32}$")
_PROCESS_HIGH_WATER_LOCK = threading.RLock()
_PROCESS_HIGH_WATER: dict[str, tuple[int, str]] = {}


if os.name == "nt":

    class _JobBasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JobExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JobBasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    class _ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]


class _WindowsKillJob:
    def __init__(
        self,
        process: subprocess.Popen[bytes],
        *,
        before_resume: Callable[[], None] | None = None,
    ) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows Job Objects are unavailable")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.SetInformationJobObject.restype = wintypes.BOOL
        kernel32.AssignProcessToJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.HANDLE,
        ]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel32.CreateToolhelp32Snapshot.argtypes = [
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Thread32First.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ThreadEntry32),
        ]
        kernel32.Thread32First.restype = wintypes.BOOL
        kernel32.Thread32Next.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(_ThreadEntry32),
        ]
        kernel32.Thread32Next.restype = wintypes.BOOL
        kernel32.OpenThread.argtypes = [
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        ]
        kernel32.OpenThread.restype = wintypes.HANDLE
        kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
        kernel32.ResumeThread.restype = wintypes.DWORD
        kernel32.TerminateJobObject.argtypes = [
            wintypes.HANDLE,
            wintypes.UINT,
        ]
        kernel32.TerminateJobObject.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32 = kernel32
        self.handle = None
        snapshot = None
        thread_handle = None
        try:
            self.handle = kernel32.CreateJobObjectW(None, None)
            if not self.handle:
                raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
            information = _JobExtendedLimitInformation()
            information.BasicLimitInformation.LimitFlags = 0x00002000
            if not kernel32.SetInformationJobObject(
                self.handle,
                9,
                ctypes.byref(information),
                ctypes.sizeof(information),
            ):
                raise OSError(
                    ctypes.get_last_error(),
                    "SetInformationJobObject failed",
                )
            if not kernel32.AssignProcessToJobObject(
                self.handle, int(getattr(process, "_handle"))
            ):
                raise OSError(
                    ctypes.get_last_error(),
                    "AssignProcessToJobObject failed",
                )
            if before_resume is not None:
                before_resume()
            snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
            invalid = ctypes.c_void_p(-1).value
            if snapshot == invalid:
                snapshot = None
                raise OSError(ctypes.get_last_error(), "thread snapshot failed")
            try:
                entry = _ThreadEntry32()
                entry.dwSize = ctypes.sizeof(entry)
                found = kernel32.Thread32First(snapshot, ctypes.byref(entry))
                while found:
                    if entry.th32OwnerProcessID == process.pid:
                        thread_handle = kernel32.OpenThread(
                            0x0002, False, entry.th32ThreadID
                        )
                        break
                    found = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
                if not thread_handle:
                    raise OSError(
                        ctypes.get_last_error(),
                        "suspended thread unavailable",
                    )
                if kernel32.ResumeThread(thread_handle) == 0xFFFFFFFF:
                    raise OSError(ctypes.get_last_error(), "ResumeThread failed")
            finally:
                if thread_handle:
                    kernel32.CloseHandle(thread_handle)
                    thread_handle = None
                if snapshot:
                    kernel32.CloseHandle(snapshot)
                    snapshot = None
        except BaseException:
            try:
                self.terminate()
            except BaseException:
                pass
            try:
                _close_process_resources(process, terminate=True)
            except BaseException:
                pass
            try:
                self.close()
            except BaseException:
                pass
            raise
        finally:
            if thread_handle:
                kernel32.CloseHandle(thread_handle)
            if snapshot:
                kernel32.CloseHandle(snapshot)

    def terminate(self) -> None:
        if self.handle:
            self._kernel32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self._kernel32.CloseHandle(self.handle)
            self.handle = None


def _close_process_resources(
    process: subprocess.Popen[bytes],
    *,
    terminate: bool,
) -> None:
    if getattr(process, "_onyx_resources_closed", False):
        return
    setattr(process, "_onyx_resources_closed", True)
    failures: list[BaseException] = []
    if terminate:
        try:
            process.terminate()
        except BaseException as exc:
            failures.append(exc)
        try:
            process.wait(timeout=0.5)
        except BaseException:
            try:
                process.kill()
            except BaseException as exc:
                failures.append(exc)
            try:
                process.wait(timeout=0.5)
            except BaseException as exc:
                failures.append(exc)
    else:
        try:
            process.wait(timeout=0.5)
        except BaseException as exc:
            failures.append(exc)
    for stream in (
        getattr(process, "stdin", None),
        getattr(process, "stdout", None),
        getattr(process, "stderr", None),
    ):
        close = getattr(stream, "close", None)
        if close is not None:
            try:
                close()
            except BaseException as exc:
                failures.append(exc)
    native = getattr(process, "_handle", None)
    close_native = getattr(native, "Close", None)
    if close_native is None:
        close_native = getattr(native, "close", None)
    if close_native is not None:
        try:
            close_native()
        except BaseException as exc:
            failures.append(exc)
    if failures and sys.exc_info()[0] is None:
        raise ProjectAutopilotWaiting(
            "trusted_git_resource_cleanup_failed"
        ) from failures[0]


class ProjectAutopilotError(MissionError):
    pass


class ProjectAutopilotContractError(ProjectAutopilotError):
    pass


class ProjectAutopilotWaiting(ProjectAutopilotError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(slots=True)
class _MissionLockEntry:
    lock: threading.RLock
    references: int = 0


class CheckpointVault(Protocol):
    def get_bytes(self) -> bytes | None: ...
    def set_bytes(self, secret: bytes | bytearray) -> None: ...


CheckpointVaultFactory = Callable[[native_vault.SecretReference], CheckpointVault]
TerminalStateResolver = Callable[[str], str]
CancelCheck = Callable[[], bool]
ProcessFactory = Callable[..., subprocess.Popen[bytes]]


def feature_enabled(environment: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environment is None else environment
    return source.get(FEATURE_FLAG) == "true"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _path_identity(path: Path) -> tuple[int, int]:
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode):
        raise ProjectAutopilotContractError("trusted_directory_invalid")
    return info.st_dev, info.st_ino


def _extended_length_path(path: Path) -> Path:
    """Return an absolute Win32 extended-length path for local syscalls."""

    if os.name != "nt":
        return path
    value = os.path.abspath(os.fspath(path))
    if value.startswith("\\\\?\\"):
        return Path(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def _reject_linked_ancestors(path: Path) -> None:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        if not current.exists():
            continue
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or _is_reparse(current):
            raise ProjectAutopilotContractError("linked_or_reparse_path_forbidden")


def _safe_relative(value: str) -> str:
    if (
        not value
        or "\\" in value
        or "\x00" in value
        or ":" in value
        or any(ord(char) < 32 for char in value)
    ):
        raise ProjectAutopilotContractError("unsafe_patch_path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} for part in path.parts)
        or any(part.casefold() == ".git" for part in path.parts)
    ):
        raise ProjectAutopilotContractError("unsafe_patch_path")
    return path.as_posix()


def _resolve_trusted_git() -> Path:
    candidates: tuple[Path, ...]
    if os.name == "nt":
        candidates = (
            Path(r"C:\Program Files\Git\cmd\git.exe"),
            Path(r"C:\Program Files\Git\bin\git.exe"),
            Path(r"C:\Program Files (x86)\Git\cmd\git.exe"),
        )
    else:
        candidates = (Path("/usr/bin/git"), Path("/usr/local/bin/git"))
    for candidate in candidates:
        try:
            path = candidate.resolve(strict=True)
            info = path.lstat()
        except OSError:
            continue
        if (
            path.is_absolute()
            and stat.S_ISREG(info.st_mode)
            and not stat.S_ISLNK(info.st_mode)
            and not _is_reparse(path)
            and path.name.casefold() in {"git", "git.exe"}
        ):
            return path
    raise ProjectAutopilotContractError("trusted_system_git_unavailable")


def _patch_paths(patch: str) -> tuple[str, ...]:
    encoded = patch.encode("utf-8", errors="strict")
    if not encoded or len(encoded) > MAX_PATCH_BYTES or "\x00" in patch:
        raise ProjectAutopilotContractError("patch_byte_budget_invalid")
    paths: set[str] = set()
    current: str | None = None
    old_seen = new_seen = False
    hunk_seen = False
    old_remaining = new_remaining = 0

    def finish_block() -> None:
        if current is not None and (
            not (old_seen and new_seen and hunk_seen) or old_remaining or new_remaining
        ):
            raise ProjectAutopilotContractError("noncanonical_patch_block")

    for line in patch.splitlines():
        if old_remaining or new_remaining:
            if not line:
                raise ProjectAutopilotContractError("malformed_patch_hunk")
            marker = line[0]
            if marker == " ":
                old_remaining -= 1
                new_remaining -= 1
            elif marker == "-":
                old_remaining -= 1
            elif marker == "+":
                new_remaining -= 1
            elif marker == "\\" and line == r"\ No newline at end of file":
                continue
            else:
                raise ProjectAutopilotContractError("malformed_patch_hunk")
            if old_remaining < 0 or new_remaining < 0:
                raise ProjectAutopilotContractError("malformed_patch_hunk")
            continue
        if line.startswith("diff --git "):
            finish_block()
            match = _DIFF_HEADER.fullmatch(line)
            if match is None:
                raise ProjectAutopilotContractError("unsupported_diff_header")
            left = _safe_relative(match.group(1))
            right = _safe_relative(match.group(2))
            if left != right or left in paths:
                raise ProjectAutopilotContractError(
                    "rename_or_duplicate_patch_block_refused"
                )
            current = left
            paths.add(left)
            old_seen = new_seen = False
            hunk_seen = False
            old_remaining = new_remaining = 0
            continue
        if line.startswith("--- "):
            if current is None or old_seen:
                raise ProjectAutopilotContractError("noncanonical_patch_block")
            marker = line[4:]
            if marker != "/dev/null" and marker != f"a/{current}":
                raise ProjectAutopilotContractError("patch_old_path_mismatch")
            old_seen = True
            continue
        if line.startswith("+++ "):
            if current is None or not old_seen or new_seen:
                raise ProjectAutopilotContractError("noncanonical_patch_block")
            marker = line[4:]
            if marker != "/dev/null" and marker != f"b/{current}":
                raise ProjectAutopilotContractError("patch_new_path_mismatch")
            new_seen = True
            continue
        if line.startswith("@@ "):
            if current is None or not (old_seen and new_seen):
                raise ProjectAutopilotContractError("noncanonical_patch_block")
            match = _HUNK_HEADER.fullmatch(line)
            if match is None:
                raise ProjectAutopilotContractError("malformed_patch_hunk_header")
            old_remaining = int(match.group(2) or "1")
            new_remaining = int(match.group(4) or "1")
            hunk_seen = True
            if old_remaining == 0 and new_remaining == 0:
                raise ProjectAutopilotContractError("empty_patch_hunk_refused")
            continue
        if line.startswith("Index: ") or line.startswith("*** "):
            raise ProjectAutopilotContractError("alternate_patch_format_refused")
    finish_block()
    if not paths:
        raise ProjectAutopilotContractError("unified_patch_required")
    return tuple(sorted(paths))


def _validate_gate_argv(value: object, patch_paths: tuple[str, ...]) -> tuple[str, ...]:
    if (
        not isinstance(value, (list, tuple))
        or not 2 <= len(value) <= MAX_GATE_ARG_COUNT
        or any(not isinstance(item, str) for item in value)
    ):
        raise ProjectAutopilotContractError("static_gate_argv_invalid")
    argv = tuple(value)
    if any(
        not item or len(item) > 256 or "\x00" in item or "\r" in item or "\n" in item
        for item in argv
    ):
        raise ProjectAutopilotContractError("static_gate_argv_invalid")
    if argv[0] != "onyx-static":
        raise ProjectAutopilotContractError("executable_gate_refused")
    if argv[1] == "diff-check" and len(argv) == 2:
        return argv
    if argv[1] == "python-ast" and len(argv) >= 3:
        selected = tuple(_safe_relative(item) for item in argv[2:])
        if (
            len(set(selected)) != len(selected)
            or any(item not in patch_paths for item in selected)
            or any(PurePosixPath(item).suffix.casefold() != ".py" for item in selected)
        ):
            raise ProjectAutopilotContractError("static_ast_scope_invalid")
        return argv
    raise ProjectAutopilotContractError("static_gate_forbidden")


def _descriptor_read(
    path: Path,
    *,
    max_bytes: int,
    missing_ok: bool = False,
) -> bytes | None:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        if missing_ok:
            return None
        raise
    try:
        held = os.fstat(descriptor)
        if not stat.S_ISREG(held.st_mode) or held.st_size > max_bytes:
            raise ProjectAutopilotContractError("descriptor_file_invalid_or_oversized")
        chunks: list[bytes] = []
        remaining = held.st_size + 1
        while remaining:
            block = os.read(descriptor, min(65_536, remaining))
            if not block:
                break
            chunks.append(block)
            remaining -= len(block)
        content = b"".join(chunks)
        try:
            visible = path.lstat()
        except FileNotFoundError as exc:
            raise ProjectAutopilotContractError("descriptor_path_replaced") from exc
        if (
            len(content) != held.st_size
            or not stat.S_ISREG(visible.st_mode)
            or stat.S_ISLNK(visible.st_mode)
            or _is_reparse(path)
            or (visible.st_dev, visible.st_ino) != (held.st_dev, held.st_ino)
            or visible.st_size != held.st_size
            or visible.st_mtime_ns != held.st_mtime_ns
        ):
            raise ProjectAutopilotContractError("descriptor_path_replaced")
        return content
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, content: bytes) -> None:
    parent_identity = _path_identity(path.parent)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags, 0o600)
    try:
        held = os.fstat(descriptor)
        if not stat.S_ISREG(held.st_mode):
            raise ProjectAutopilotContractError("exclusive_file_invalid")
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset : offset + 65_536])
            if written <= 0:
                raise ProjectAutopilotContractError("exclusive_file_write_failed")
            offset += written
        os.fsync(descriptor)
        after = os.fstat(descriptor)
        if after.st_size != len(content):
            raise ProjectAutopilotContractError("exclusive_file_write_failed")
    finally:
        os.close(descriptor)
    if _path_identity(path.parent) != parent_identity:
        raise ProjectAutopilotContractError("trusted_directory_replaced")
    _descriptor_read(path, max_bytes=len(content))


def _atomic_descriptor_write(path: Path, content: bytes) -> None:
    parent_identity = _path_identity(path.parent)
    temporary = path.parent / f".a-{secrets.token_hex(12)}.tmp"
    _write_exclusive(temporary, content)
    if _path_identity(path.parent) != parent_identity:
        raise ProjectAutopilotContractError("trusted_directory_replaced")
    if path.exists():
        current = _descriptor_read(path, max_bytes=2_000_000)
        if current is None:
            raise ProjectAutopilotContractError("checkpoint_replaced")
    os.replace(temporary, path)
    if _path_identity(path.parent) != parent_identity:
        raise ProjectAutopilotContractError("trusted_directory_replaced")
    _descriptor_read(path, max_bytes=len(content))


def _secure_scrub_regular(path: Path, max_bytes: int) -> None:
    if not path.exists():
        return
    held_path = path.lstat()
    if (
        not stat.S_ISREG(held_path.st_mode)
        or stat.S_ISLNK(held_path.st_mode)
        or _is_reparse(path)
        or held_path.st_nlink != 1
    ):
        raise ProjectAutopilotContractError("controlled_scrub_target_invalid")
    tombstone = path.parent / f".scrub-{secrets.token_hex(16)}"
    os.replace(path, tombstone)
    moved = tombstone.lstat()
    if (moved.st_dev, moved.st_ino) != (
        held_path.st_dev,
        held_path.st_ino,
    ) or moved.st_nlink != 1:
        raise ProjectAutopilotContractError("controlled_scrub_target_replaced")
    path = tombstone
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    except OSError as exc:
        raise ProjectAutopilotContractError("controlled_scrub_chmod_failed") from exc
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        held = os.fstat(descriptor)
        if (
            not stat.S_ISREG(held.st_mode)
            or held.st_nlink != 1
            or held.st_size > max_bytes
        ):
            raise ProjectAutopilotContractError("controlled_scrub_target_invalid")
        remaining = held.st_size
        zeros = b"\0" * 65_536
        os.lseek(descriptor, 0, os.SEEK_SET)
        while remaining:
            written = os.write(descriptor, zeros[: min(len(zeros), remaining)])
            if written <= 0:
                raise ProjectAutopilotContractError("controlled_scrub_failed")
            remaining -= written
        os.ftruncate(descriptor, 0)
        os.fsync(descriptor)
        visible = path.lstat()
        if (
            stat.S_ISLNK(visible.st_mode)
            or _is_reparse(path)
            or (visible.st_dev, visible.st_ino) != (held.st_dev, held.st_ino)
        ):
            raise ProjectAutopilotContractError("controlled_scrub_target_replaced")
    finally:
        os.close(descriptor)
    os.unlink(path)


def _bounded_tree_usage_once(root: Path) -> tuple[int, int, int]:
    files = directories = total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        directories += 1
        if directories > MAX_CLONE_DIRS:
            raise ProjectAutopilotWaiting("controlled_clone_directory_budget_exhausted")
        held = directory.lstat()
        if (
            not stat.S_ISDIR(held.st_mode)
            or stat.S_ISLNK(held.st_mode)
            or _is_reparse(directory)
        ):
            raise ProjectAutopilotWaiting("controlled_clone_entry_invalid")
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                info = path.lstat()
                if stat.S_ISDIR(info.st_mode) and not _is_reparse(path):
                    pending.append(path)
                    continue
                if (
                    not stat.S_ISREG(info.st_mode)
                    or stat.S_ISLNK(info.st_mode)
                    or _is_reparse(path)
                ):
                    raise ProjectAutopilotWaiting("controlled_clone_entry_invalid")
                files += 1
                total += info.st_size
                if files > MAX_CLONE_FILES:
                    raise ProjectAutopilotWaiting(
                        "controlled_clone_file_budget_exhausted"
                    )
                if total > MAX_CLONE_BYTES:
                    raise ProjectAutopilotWaiting(
                        "controlled_clone_disk_budget_exhausted"
                    )
    return files, directories, total


def _bounded_tree_usage(root: Path) -> tuple[int, int, int]:
    """Measure a stable clone tree without accepting partial enumeration.

    Git may atomically replace a pack file after ``scandir`` has yielded its
    former name, especially on Windows.  A missing entry therefore restarts
    the complete bounded walk; it is never ignored or subtracted from the
    quota.  Repeated churn remains fail-closed as an explicit waiting state.
    """

    scan_root = _extended_length_path(root)
    for retry, delay in enumerate((*_CLONE_TREE_RETRY_DELAYS_SECONDS, None)):
        try:
            return _bounded_tree_usage_once(scan_root)
        except FileNotFoundError as exc:
            if delay is None:
                raise ProjectAutopilotWaiting(
                    "controlled_clone_tree_unstable"
                ) from exc
            time.sleep(delay)
    raise AssertionError(f"unreachable clone tree retry index: {retry}")


def _logical_tree_bytes(root: Path, hard_limit: int) -> int:
    if not root.exists():
        return 0
    total = 0
    files = 0
    directories = 1
    deadline = time.monotonic() + MAX_MONITOR_SECONDS
    pending = [(root, 0)]
    while pending:
        if time.monotonic() >= deadline:
            raise ProjectAutopilotWaiting(
                "controlled_disk_monitor_time_budget_exhausted"
            )
        directory, depth = pending.pop()
        if directories > MAX_MONITOR_DIRS:
            raise ProjectAutopilotWaiting(
                "controlled_disk_monitor_directory_budget_exhausted"
            )
        if depth > MAX_MONITOR_DEPTH:
            raise ProjectAutopilotWaiting(
                "controlled_disk_monitor_depth_budget_exhausted"
            )
        try:
            info = directory.lstat()
        except FileNotFoundError:
            continue
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or _is_reparse(directory)
        ):
            raise ProjectAutopilotWaiting("controlled_disk_entry_invalid")
        try:
            entries = os.scandir(directory)
            with entries:
                while True:
                    if time.monotonic() >= deadline:
                        raise ProjectAutopilotWaiting(
                            "controlled_disk_monitor_time_budget_exhausted"
                        )
                    try:
                        entry = next(entries)
                    except StopIteration:
                        break
                    if time.monotonic() >= deadline:
                        raise ProjectAutopilotWaiting(
                            "controlled_disk_monitor_time_budget_exhausted"
                        )
                    path = Path(entry.path)
                    try:
                        child = path.lstat()
                    except FileNotFoundError:
                        continue
                    if stat.S_ISDIR(child.st_mode) and not _is_reparse(path):
                        directories += 1
                        if directories > MAX_MONITOR_DIRS:
                            raise ProjectAutopilotWaiting(
                                "controlled_disk_monitor_directory_budget_exhausted"
                            )
                        if depth + 1 > MAX_MONITOR_DEPTH:
                            raise ProjectAutopilotWaiting(
                                "controlled_disk_monitor_depth_budget_exhausted"
                            )
                        pending.append((path, depth + 1))
                    elif (
                        stat.S_ISREG(child.st_mode)
                        and not stat.S_ISLNK(child.st_mode)
                        and not _is_reparse(path)
                    ):
                        files += 1
                        if files > MAX_MONITOR_FILES:
                            raise ProjectAutopilotWaiting(
                                "controlled_disk_monitor_file_budget_exhausted"
                            )
                        total += child.st_size
                        if total > hard_limit:
                            return total
                    else:
                        raise ProjectAutopilotWaiting("controlled_disk_entry_invalid")
        except FileNotFoundError:
            continue
    return total


@dataclass(frozen=True)
class GateSpecV1:
    argv: tuple[str, ...]
    timeout_seconds: float


@dataclass(frozen=True)
class ExecutableGateSpecV1:
    argv: tuple[str, ...]
    timeout_seconds: float
    max_output_bytes: int


def _validate_executable_argv(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple) or not 1 <= len(value) <= MAX_GATE_ARG_COUNT:
        raise ProjectAutopilotContractError("executable_gate_argv_must_be_tuple")
    total = 0
    parsed: list[str] = []
    for argument in value:
        if not isinstance(argument, str) or not argument:
            raise ProjectAutopilotContractError("executable_gate_argument_invalid")
        encoded = argument.encode("utf-8")
        if len(encoded) > 16 * 1024 or any(
            character in argument for character in ("\x00", "\r", "\n")
        ):
            raise ProjectAutopilotContractError("executable_gate_argument_invalid")
        total += len(encoded)
        parsed.append(argument)
    if total > 64 * 1024:
        raise ProjectAutopilotContractError("executable_gate_arguments_too_large")
    try:
        from core.phase11_executable_sandbox_v1 import (
            SandboxContractError,
            validate_executable_command_v1,
        )

        return validate_executable_command_v1(tuple(parsed))
    except SandboxContractError as exc:
        reason = str(exc)
        if reason in {
            "sandbox_command_wrapper_refused",
            "sandbox_executable_not_approved",
        }:
            reason = "executable_gate_shell_refused"
        elif reason == "sandbox_secret_shaped_argument_refused":
            reason = "executable_gate_secret_shaped_argument_refused"
        elif reason in {
            "sandbox_inline_code_refused",
            "sandbox_python_module_refused",
            "sandbox_package_command_refused",
        }:
            reason = f"executable_gate_{reason.removeprefix('sandbox_')}"
        else:
            reason = "executable_gate_argument_invalid"
        raise ProjectAutopilotContractError(reason) from exc


@dataclass(frozen=True)
class ExecutableGatePlanV1:
    schema: str
    image_id: str
    platform: str
    gates: tuple[ExecutableGateSpecV1, ...]
    plan_digest: str

    @classmethod
    def build(
        cls,
        *,
        image_id: object,
        platform: object,
        gates: object,
        approved_image_ids: Iterable[str],
    ) -> "ExecutableGatePlanV1":
        approved = frozenset(approved_image_ids)
        if (
            not isinstance(image_id, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
            or image_id not in approved
        ):
            raise ProjectAutopilotContractError("executable_gate_image_not_approved")
        if platform not in {"linux/amd64", "linux/arm64"}:
            raise ProjectAutopilotContractError("executable_gate_platform_invalid")
        if (
            not isinstance(gates, (list, tuple))
            or not 1 <= len(gates) <= MAX_GATE_COUNT
        ):
            raise ProjectAutopilotContractError("executable_gate_count_invalid")
        parsed: list[ExecutableGateSpecV1] = []
        for item in gates:
            if not isinstance(item, Mapping) or set(item) != {
                "argv",
                "timeout_seconds",
                "max_output_bytes",
            }:
                raise ProjectAutopilotContractError("executable_gate_contract_invalid")
            timeout = item["timeout_seconds"]
            output = item["max_output_bytes"]
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or not 1 <= float(timeout) <= MAX_EXECUTABLE_TIMEOUT_SECONDS
            ):
                raise ProjectAutopilotContractError("executable_gate_timeout_invalid")
            if (
                isinstance(output, bool)
                or not isinstance(output, int)
                or not 1 <= output <= MAX_GIT_OUTPUT_BYTES
            ):
                raise ProjectAutopilotContractError(
                    "executable_gate_output_budget_invalid"
                )
            parsed.append(
                ExecutableGateSpecV1(
                    argv=_validate_executable_argv(item["argv"]),
                    timeout_seconds=float(timeout),
                    max_output_bytes=output,
                )
            )
        unsigned = {
            "schema": EXECUTABLE_PLAN_SCHEMA,
            "image_id": image_id,
            "platform": platform,
            "gates": [asdict(gate) for gate in parsed],
        }
        return cls(
            schema=EXECUTABLE_PLAN_SCHEMA,
            image_id=image_id,
            platform=str(platform),
            gates=tuple(parsed),
            plan_digest=_digest(unsigned),
        )

    def verify(self, approved_image_ids: Iterable[str]) -> None:
        rebuilt = self.build(
            image_id=self.image_id,
            platform=self.platform,
            gates=[
                {
                    "argv": gate.argv,
                    "timeout_seconds": gate.timeout_seconds,
                    "max_output_bytes": gate.max_output_bytes,
                }
                for gate in self.gates
            ],
            approved_image_ids=approved_image_ids,
        )
        if (
            self.schema != EXECUTABLE_PLAN_SCHEMA
            or not hmac.compare_digest(self.plan_digest, rebuilt.plan_digest)
            or self != rebuilt
        ):
            raise ProjectAutopilotContractError("executable_gate_plan_invalid")


@dataclass(frozen=True)
class ExecutableGateEnvelopeV1:
    schema: str
    plan: ExecutableGatePlanV1
    mission_id: str
    gate_index: int
    primary_input_digest: str
    binding_digest: str
    plan_digest: str
    authorization_hmac_sha256: str

    @classmethod
    def build(
        cls,
        *,
        image_id: object,
        platform: object,
        gates: object,
        approved_image_ids: Iterable[str],
        mission_id: str,
        gate_index: int,
        primary_envelope: AutopilotEnvelopeV1,
        binding_digest: str,
        signing_key: bytes,
    ) -> "ExecutableGateEnvelopeV1":
        if (
            not isinstance(primary_envelope, AutopilotEnvelopeV1)
            or not re.fullmatch(r"[0-9a-f]{64}", primary_envelope.input_digest)
            or not isinstance(mission_id, str)
            or not _SAFE_MISSION_ID.fullmatch(mission_id)
            or type(gate_index) is not int
            or gate_index != 0
            or not isinstance(binding_digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", binding_digest)
            or not isinstance(signing_key, bytes)
            or len(signing_key) < 32
        ):
            raise ProjectAutopilotContractError("executable_gate_authority_invalid")
        plan = ExecutableGatePlanV1.build(
            image_id=image_id,
            platform=platform,
            gates=gates,
            approved_image_ids=approved_image_ids,
        )
        unsigned = {
            "schema": EXECUTABLE_PLAN_SCHEMA,
            "mission_id": mission_id,
            "gate_index": gate_index,
            "primary_input_digest": primary_envelope.input_digest,
            "binding_digest": binding_digest,
            "plan_digest": plan.plan_digest,
        }
        authorization = hmac.new(
            signing_key,
            _EXECUTABLE_AUTH_DOMAIN + _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        return cls(
            schema=EXECUTABLE_PLAN_SCHEMA,
            plan=plan,
            mission_id=mission_id,
            gate_index=gate_index,
            primary_input_digest=primary_envelope.input_digest,
            binding_digest=binding_digest,
            plan_digest=plan.plan_digest,
            authorization_hmac_sha256=authorization,
        )

    def verify(
        self,
        *,
        approved_image_ids: Iterable[str],
        mission_id: str,
        gate_index: int,
        primary_envelope: AutopilotEnvelopeV1,
        binding_digest: str,
        signing_key: bytes,
    ) -> None:
        self.plan.verify(approved_image_ids)
        unsigned = {
            "schema": EXECUTABLE_PLAN_SCHEMA,
            "mission_id": mission_id,
            "gate_index": gate_index,
            "primary_input_digest": primary_envelope.input_digest,
            "binding_digest": binding_digest,
            "plan_digest": self.plan.plan_digest,
        }
        expected = hmac.new(
            signing_key,
            _EXECUTABLE_AUTH_DOMAIN + _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        if (
            self.schema != EXECUTABLE_PLAN_SCHEMA
            or self.mission_id != mission_id
            or self.gate_index != gate_index
            or self.primary_input_digest != primary_envelope.input_digest
            or self.binding_digest != binding_digest
            or self.plan_digest != self.plan.plan_digest
            or not hmac.compare_digest(self.authorization_hmac_sha256, expected)
        ):
            raise ProjectAutopilotContractError("executable_gate_envelope_invalid")


@dataclass(frozen=True)
class AutopilotEnvelopeV1:
    schema: str
    root: str
    base_head: str
    owner_git_sha256: str
    patch_sha256: str
    patch_bytes: int
    patch_paths: tuple[str, ...]
    gates: tuple[GateSpecV1, ...]
    max_seconds: float
    max_output_bytes: int
    input_digest: str

    @classmethod
    def build(
        cls,
        *,
        root: str,
        base_head: str,
        owner_git_sha256: str,
        patch: object,
        gates: object,
        max_seconds: object,
        max_output_bytes: object = MAX_GIT_OUTPUT_BYTES,
    ) -> "AutopilotEnvelopeV1":
        if not isinstance(owner_git_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", owner_git_sha256
        ):
            raise ProjectAutopilotContractError("owner_git_digest_invalid")
        if not isinstance(patch, str):
            raise ProjectAutopilotContractError("patch_must_be_text")
        paths = _patch_paths(patch)
        if (
            not isinstance(gates, (list, tuple))
            or not 1 <= len(gates) <= MAX_GATE_COUNT
        ):
            raise ProjectAutopilotContractError("gate_count_invalid")
        parsed: list[GateSpecV1] = []
        for item in gates:
            if not isinstance(item, Mapping) or set(item) != {
                "argv",
                "timeout_seconds",
            }:
                raise ProjectAutopilotContractError("gate_contract_invalid")
            timeout = item["timeout_seconds"]
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout)
                or not 1 <= float(timeout) <= 60
            ):
                raise ProjectAutopilotContractError("static_gate_timeout_invalid")
            parsed.append(
                GateSpecV1(_validate_gate_argv(item["argv"], paths), float(timeout))
            )
        if (
            isinstance(max_seconds, bool)
            or not isinstance(max_seconds, (int, float))
            or not math.isfinite(max_seconds)
            or not 10 <= float(max_seconds) <= 900
        ):
            raise ProjectAutopilotContractError("mission_time_budget_invalid")
        if (
            isinstance(max_output_bytes, bool)
            or not isinstance(max_output_bytes, int)
            or not 1 <= max_output_bytes <= MAX_GIT_OUTPUT_BYTES
        ):
            raise ProjectAutopilotContractError("output_budget_invalid")
        patch_bytes = patch.encode("utf-8")
        unsigned = {
            "schema": SCHEMA,
            "root": root,
            "base_head": base_head.lower(),
            "owner_git_sha256": owner_git_sha256,
            "patch_sha256": hashlib.sha256(patch_bytes).hexdigest(),
            "patch_bytes": len(patch_bytes),
            "patch_paths": list(paths),
            "gates": [asdict(item) for item in parsed],
            "max_seconds": float(max_seconds),
            "max_output_bytes": max_output_bytes,
        }
        return cls(
            schema=SCHEMA,
            root=root,
            base_head=base_head.lower(),
            owner_git_sha256=owner_git_sha256,
            patch_sha256=str(unsigned["patch_sha256"]),
            patch_bytes=len(patch_bytes),
            patch_paths=paths,
            gates=tuple(parsed),
            max_seconds=float(max_seconds),
            max_output_bytes=max_output_bytes,
            input_digest=_digest(unsigned),
        )


class ProjectAutopilotV1:
    """Apply a patch in a standalone clone and run trusted static checks only."""

    def __init__(
        self,
        *,
        worktree_root: str | os.PathLike[str],
        signing_key: bytes,
        enabled: bool = False,
        process_factory: ProcessFactory = subprocess.Popen,
        checkpoint_vault_factory: CheckpointVaultFactory | None = None,
        terminal_state_resolver: TerminalStateResolver | None = None,
        executable_sandbox_enabled: bool = False,
        executable_sandbox_host: ExecutableSandboxHostV1 | None = None,
        approved_executable_image_ids: Iterable[str] = (),
        execution_ledger: Phase11ExecutionLedgerV1 | None = None,
        require_execution_ledger: bool = False,
    ) -> None:
        self.enabled = enabled is True
        self.worktree_root = Path(worktree_root)
        self._key = bytes(signing_key)
        self._process_factory = process_factory
        self._checkpoint_vault_factory = checkpoint_vault_factory or (
            lambda reference: native_vault.NativeSecretVault(reference)
        )
        self._terminal_state_resolver = terminal_state_resolver
        self._executable_sandbox_enabled = executable_sandbox_enabled is True
        if (
            executable_sandbox_host is not None
            and type(executable_sandbox_host) is not ExecutableSandboxHostV1
        ):
            raise ProjectAutopilotContractError(
                "executable_sandbox_host_binding_invalid"
            )
        self._executable_sandbox_host = executable_sandbox_host
        self._approved_executable_image_ids = frozenset(approved_executable_image_ids)
        self._execution_ledger = execution_ledger
        self._require_execution_ledger = require_execution_ledger is True
        self._validated_execution_ledger()
        self._executable_control_root = (
            self.worktree_root / ".executable-sandbox-control"
        )
        self._clone_cleanup: Any | None = None
        self._clone_cleanup_errors: tuple[type[BaseException], ...] = ()
        self._clone_cleanup_waiting: type[BaseException] | None = None
        self._namespace: Any | None = None
        self._namespace_sessions: dict[str, Any] = {}
        self._clone_operations: dict[str, Any] = {}
        self.git_executable: Path | None = None
        self._process_lock = threading.RLock()
        self._active: dict[str, subprocess.Popen[bytes]] = {}
        self._mission_locks_lock = threading.RLock()
        self._mission_locks: dict[str, _MissionLockEntry] = {}
        if not self.enabled:
            return
        if len(self._key) < 16:
            raise ValueError("autopilot signing key must contain at least 16 bytes")
        if self._executable_sandbox_enabled:
            if any(
                not isinstance(image_id, str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id)
                for image_id in self._approved_executable_image_ids
            ):
                raise ProjectAutopilotContractError(
                    "approved_executable_image_ids_invalid"
                )
        if os.name != "nt":
            raise ProjectAutopilotContractError(
                "project_autopilot_v1 requires the Windows Job Object boundary"
            )
        self.git_executable = _resolve_trusted_git()
        _reject_linked_ancestors(self.worktree_root.parent)
        self.worktree_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _reject_linked_ancestors(self.worktree_root)
        if not stat.S_ISDIR(self.worktree_root.lstat().st_mode):
            raise ProjectAutopilotContractError("worktree_root_invalid")
        if os.name == "posix":
            os.chmod(self.worktree_root, 0o700)
        else:
            _harden_mode(self.worktree_root)
        if (
            os.name == "nt"
            and os.environ.get("ONYX_PHASE11_HANDLE_SAFE_CLONE_CLEANUP_V1") == "true"
        ):
            from core.phase11_windows_clone_cleanup_v1 import (
                CloneCleanupContractError,
                CloneCleanupWaiting,
                WindowsCloneCleanupV1,
            )
            from core.phase11_windows_namespace_v1 import (
                WindowsNamespaceV1,
            )

            self._clone_cleanup = WindowsCloneCleanupV1(
                worktree_root=self.worktree_root,
                signing_key=self._key,
                vault_factory=self._checkpoint_vault_factory,
                enabled=True,
            )
            self._clone_cleanup_errors = (
                CloneCleanupContractError,
                CloneCleanupWaiting,
            )
            self._clone_cleanup_waiting = CloneCleanupWaiting
            self._namespace = WindowsNamespaceV1(
                worktree_root=self.worktree_root,
                enabled=True,
            )
        self._git_home = self.worktree_root / ".git-home"
        self._git_home.mkdir(mode=0o700, exist_ok=True)
        _reject_linked_ancestors(self._git_home)

    def _environment(self) -> dict[str, str]:
        inherited = ("SystemRoot", "WINDIR", "PATHEXT", "TEMP", "TMP")
        environment = {key: os.environ[key] for key in inherited if key in os.environ}
        null_hooks = "NUL" if os.name == "nt" else "/dev/null"
        system_path = (
            str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
            if os.name == "nt"
            else "/usr/bin:/bin"
        )
        assert self.git_executable is not None
        environment.update(
            PATH=os.pathsep.join((str(self.git_executable.parent), system_path)),
            HOME=str(self._git_home),
            USERPROFILE=str(self._git_home),
            XDG_CONFIG_HOME=str(self._git_home),
            GIT_OPTIONAL_LOCKS="0",
            GIT_TERMINAL_PROMPT="0",
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=null_hooks,
            GIT_CONFIG_SYSTEM=null_hooks,
            GIT_CONFIG_COUNT="5",
            GIT_CONFIG_KEY_0="core.autocrlf",
            GIT_CONFIG_VALUE_0="false",
            GIT_CONFIG_KEY_1="core.hooksPath",
            GIT_CONFIG_VALUE_1=null_hooks,
            GIT_CONFIG_KEY_2="protocol.file.allow",
            GIT_CONFIG_VALUE_2="always",
            GIT_CONFIG_KEY_3="core.fsmonitor",
            GIT_CONFIG_VALUE_3="false",
            GIT_CONFIG_KEY_4="core.longpaths",
            GIT_CONFIG_VALUE_4="true",
            LC_ALL="C",
            NO_COLOR="1",
        )
        return environment

    def _map_clone_cleanup_error(self, exc: BaseException) -> None:
        waiting = self._clone_cleanup_waiting
        reason = str(exc) or type(exc).__name__
        if waiting is not None and isinstance(exc, waiting):
            raise ProjectAutopilotWaiting(reason) from exc
        raise ProjectAutopilotContractError(reason) from exc

    @staticmethod
    def _stop(process: subprocess.Popen[bytes]) -> None:
        job = getattr(process, "_onyx_kill_job", None)
        if job is not None:
            try:
                job.terminate()
                process.wait(timeout=0.5)
            except (OSError, subprocess.TimeoutExpired):
                pass
            return
        try:
            process.terminate()
            process.wait(timeout=0.5)
            return
        except (OSError, subprocess.TimeoutExpired):
            pass
        try:
            process.kill()
            process.wait(timeout=0.5)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def kill(self, mission_id: str) -> None:
        with self._process_lock:
            process = self._active.get(mission_id)
        if process is not None:
            self._stop(process)

    def has_active_processes(self) -> bool:
        """Read-only lifecycle projection for the owning Live bridge."""
        with self._process_lock:
            return bool(self._active)

    def checkpoint_status(self, mission_id: str) -> dict[str, Any] | None:
        """Authenticated, locked checkpoint projection for status callers."""
        return self._read_checkpoint(mission_id)

    def checkpoint_status_for_fresh_reapproval(
        self, mission_id: str
    ) -> dict[str, Any] | None:
        """Validate a cold checkpoint solely to decide fresh reapproval.

        A normal status/read must retain the in-process high-water requirement
        so a cold runtime can never resume an old mission.  The reseed path is
        different: it must inspect the authenticated checkpoint to refuse a
        replacement after attempted-unknown executable work, while still
        creating a new mission/envelope/nonce for explicit owner approval.
        This read does not seed high-water state and therefore cannot resume
        execution of the old mission.
        """
        with self._mission_lock(mission_id):
            with self._mission_process_lock(mission_id):
                return self._read_checkpoint_locked(
                    mission_id,
                    allow_missing_process_high_water=True,
                )

    def _run(
        self,
        mission_id: str,
        argv: Sequence[str],
        *,
        cwd: Path,
        timeout_seconds: float,
        output_limit: int,
        cancel: CancelCheck,
        disk_root: Path | None = None,
        disk_limit: int | None = None,
        input_bytes: bytes | None = None,
        stdout_sink: Callable[[bytes], None] | None = None,
        stdout_limit: int | None = None,
    ) -> tuple[bytes, bytes, int]:
        if cancel():
            raise ProjectAutopilotWaiting("kill_requested")
        with self._process_lock:
            if mission_id in self._active:
                raise ProjectAutopilotWaiting("trusted_git_mission_active")
        if input_bytes is not None and len(input_bytes) > MAX_PATCH_BYTES:
            raise ProjectAutopilotContractError("trusted_git_input_budget_exceeded")
        if (
            self.git_executable is None
            or not argv
            or Path(argv[0]) != self.git_executable
        ):
            raise ProjectAutopilotContractError("unpinned_external_process_refused")
        creationflags = 0
        if os.name == "nt":
            creationflags = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | 0x00000004  # CREATE_SUSPENDED
            )
        try:
            process = self._process_factory(
                list(argv),
                cwd=str(cwd),
                stdin=subprocess.PIPE
                if input_bytes is not None
                else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                env=self._environment(),
                creationflags=creationflags,
            )
        except (FileNotFoundError, OSError) as exc:
            raise ProjectAutopilotWaiting("trusted_git_start_failed") from exc
        if (
            process.stdout is None
            or process.stderr is None
            or (input_bytes is not None and process.stdin is None)
        ):
            _close_process_resources(process, terminate=True)
            raise ProjectAutopilotWaiting("trusted_git_pipe_failed")
        if os.name == "nt":
            try:
                process._onyx_kill_job = _WindowsKillJob(process)  # type: ignore[attr-defined]
            except BaseException as exc:
                try:
                    _close_process_resources(process, terminate=True)
                except BaseException:
                    pass
                if isinstance(exc, (OSError, RuntimeError)):
                    raise ProjectAutopilotWaiting(
                        "trusted_git_job_boundary_failed"
                    ) from exc
                raise
        with self._process_lock:
            collision = mission_id in self._active
            if not collision:
                self._active[mission_id] = process
        if collision:
            self._stop(process)
            job = getattr(process, "_onyx_kill_job", None)
            if job is not None:
                job.close()
            _close_process_resources(process, terminate=True)
            raise ProjectAutopilotWaiting("trusted_git_mission_active")
        chunks: dict[str, list[bytes]] = {"stdout": [], "stderr": []}
        consumed = 0
        stdout_consumed = 0
        lock = threading.Lock()
        exceeded = threading.Event()
        failures: list[BaseException] = []
        input_failures: list[BaseException] = []

        def drain(name: str, stream: object) -> None:
            nonlocal consumed, stdout_consumed
            try:
                while True:
                    chunk = stream.read(65_536)  # type: ignore[attr-defined]
                    if not chunk:
                        return
                    if name == "stdout" and stdout_sink is not None:
                        if (
                            stdout_limit is None
                            or stdout_consumed + len(chunk) > stdout_limit
                        ):
                            exceeded.set()
                            self._stop(process)
                            return
                        stdout_sink(chunk)
                        stdout_consumed += len(chunk)
                        continue
                    with lock:
                        if consumed + len(chunk) > output_limit:
                            exceeded.set()
                        else:
                            consumed += len(chunk)
                            chunks[name].append(chunk)
                    if exceeded.is_set():
                        self._stop(process)
                        return
            except BaseException as exc:
                failures.append(exc)
                self._stop(process)

        readers = [
            threading.Thread(
                target=drain, args=("stdout", process.stdout), daemon=True
            ),
            threading.Thread(
                target=drain, args=("stderr", process.stderr), daemon=True
            ),
        ]
        for reader in readers:
            reader.start()
        writer: threading.Thread | None = None
        if input_bytes is not None:

            def feed_input() -> None:
                try:
                    assert process.stdin is not None
                    for offset in range(0, len(input_bytes), 65_536):
                        process.stdin.write(input_bytes[offset : offset + 65_536])
                        process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
                except BaseException as exc:
                    input_failures.append(exc)
                    self._stop(process)
                finally:
                    try:
                        assert process.stdin is not None
                        process.stdin.close()
                    except OSError:
                        pass

            writer = threading.Thread(target=feed_input, daemon=True)
            writer.start()
        deadline = time.monotonic() + timeout_seconds
        reason = ""
        try:
            while process.poll() is None:
                if cancel():
                    reason = "kill_requested"
                    self._stop(process)
                    break
                if exceeded.is_set():
                    reason = "trusted_git_output_budget_exhausted"
                    self._stop(process)
                    break
                if disk_root is not None and disk_limit is not None:
                    try:
                        usage = _logical_tree_bytes(disk_root, disk_limit)
                    except ProjectAutopilotWaiting as exc:
                        reason = exc.reason
                        self._stop(process)
                        break
                    if usage > disk_limit:
                        reason = "controlled_disk_budget_exhausted"
                        self._stop(process)
                        break
                if time.monotonic() >= deadline:
                    reason = "trusted_git_timeout"
                    self._stop(process)
                    break
                time.sleep(0.025)
            for reader in readers:
                reader.join(timeout=1.0)
            if writer is not None:
                writer.join(timeout=1.0)
                if writer.is_alive():
                    self._stop(process)
                    writer.join(timeout=1.0)
                    raise ProjectAutopilotWaiting("trusted_git_input_drain_failed")
            if any(reader.is_alive() for reader in readers):
                raise ProjectAutopilotWaiting("trusted_git_drain_failed")
            if failures:
                raise ProjectAutopilotWaiting(
                    "trusted_git_stdout_sink_failed"
                ) from failures[0]
            if input_failures:
                raise ProjectAutopilotWaiting("trusted_git_input_failed")
            if exceeded.is_set():
                raise ProjectAutopilotWaiting("trusted_git_output_budget_exhausted")
            if reason:
                raise ProjectAutopilotWaiting(reason)
            return (
                b"".join(chunks["stdout"]),
                b"".join(chunks["stderr"]),
                int(process.returncode or 0),
            )
        finally:
            job = getattr(process, "_onyx_kill_job", None)
            if job is not None:
                job.close()
            with self._process_lock:
                if self._active.get(mission_id) is process:
                    self._active.pop(mission_id, None)
            _close_process_resources(process, terminate=False)

    def _git(
        self,
        mission_id: str,
        cwd: Path,
        arguments: Sequence[str],
        *,
        timeout: float,
        output_limit: int,
        cancel: CancelCheck,
        disk_root: Path | None = None,
        disk_limit: int | None = None,
        input_bytes: bytes | None = None,
        stdout_sink: Callable[[bytes], None] | None = None,
        stdout_limit: int | None = None,
    ) -> bytes:
        stdout, _stderr, code = self._run(
            mission_id,
            (str(self.git_executable), *arguments),
            cwd=cwd,
            timeout_seconds=timeout,
            output_limit=output_limit,
            cancel=cancel,
            disk_root=disk_root,
            disk_limit=disk_limit,
            input_bytes=input_bytes,
            stdout_sink=stdout_sink,
            stdout_limit=stdout_limit,
        )
        if code != 0:
            raise ProjectAutopilotWaiting("trusted_git_command_failed")
        return stdout

    def _mission_dir(self, mission_id: str) -> Path:
        if not _SAFE_MISSION_ID.fullmatch(mission_id):
            raise ProjectAutopilotContractError("mission_id_invalid")
        return self.worktree_root / mission_id

    def _checkpoint_path(self, mission_id: str) -> Path:
        return self._mission_dir(mission_id) / "checkpoint.json"

    def _transaction_path(self, mission_id: str) -> Path:
        return self._mission_dir(mission_id) / "checkpoint.transaction.json"

    def _clone_path(self, mission_id: str) -> Path:
        return self._mission_dir(mission_id) / "clone"

    def _patch_path(self, mission_id: str) -> Path:
        return self._mission_dir(mission_id) / "patch.diff"

    def _bundle_path(self, mission_id: str) -> Path:
        return self._mission_dir(mission_id) / "source.bundle"

    @contextmanager
    def _mission_lock(self, mission_id: str) -> Iterator[None]:
        if not _SAFE_MISSION_ID.fullmatch(mission_id):
            raise ProjectAutopilotContractError("mission_id_invalid")
        with self._mission_locks_lock:
            entry = self._mission_locks.get(mission_id)
            if entry is None:
                if len(self._mission_locks) >= MAX_MISSION_LOCK_ENTRIES:
                    raise ProjectAutopilotWaiting("mission_lock_capacity_exhausted")
                entry = _MissionLockEntry(threading.RLock())
                self._mission_locks[mission_id] = entry
            entry.references += 1
        try:
            with entry.lock:
                yield
        finally:
            with self._mission_locks_lock:
                current = self._mission_locks.get(mission_id)
                if current is not entry or entry.references <= 0:
                    raise ProjectAutopilotContractError(
                        "mission_lock_registry_diverged"
                    )
                entry.references -= 1
                if entry.references == 0:
                    self._mission_locks.pop(mission_id)

    @contextmanager
    def _mission_process_lock(self, mission_id: str) -> Iterator[None]:
        if msvcrt is None:
            raise ProjectAutopilotContractError(
                "mission interprocess lock requires Windows"
            )
        mission_dir = self._mission_dir(mission_id)
        mission_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        _reject_linked_ancestors(mission_dir)
        if self._namespace is not None:
            try:
                with self._namespace.mission(mission_id) as session:
                    with session.lock():
                        if mission_id in self._namespace_sessions:
                            raise ProjectAutopilotContractError(
                                "mission_namespace_session_already_active"
                            )
                        self._namespace_sessions[mission_id] = session
                        try:
                            yield
                        finally:
                            if self._namespace_sessions.get(mission_id) is session:
                                self._namespace_sessions.pop(mission_id, None)
            except self._clone_cleanup_errors as exc:
                self._map_clone_cleanup_error(exc)
            return
        path = mission_dir / "mission.lock"
        flags = (
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_BINARY", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(path, flags, 0o600)
        locked = False
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode):
                raise ProjectAutopilotContractError("mission_interprocess_lock_invalid")
            if opened.st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                locked = True
            except OSError as exc:
                raise ProjectAutopilotWaiting("mission_interprocess_lock_busy") from exc
            yield
        finally:
            if locked:
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            os.close(descriptor)

    def _borrowed_containment_handles(self, mission_id: str) -> tuple[Any, Any] | None:
        if self._namespace is None:
            return None
        session = self._namespace_sessions.get(mission_id)
        if session is None:
            raise ProjectAutopilotContractError("mission_namespace_session_missing")
        return session.borrowed_containment_handles

    def _scrub_mission_artifact(
        self, mission_id: str, name: str, max_bytes: int
    ) -> None:
        if self._namespace is None:
            _secure_scrub_regular(self._mission_dir(mission_id) / name, max_bytes)
            return
        session = self._namespace_sessions.get(mission_id)
        if session is None:
            raise ProjectAutopilotContractError("mission_namespace_session_missing")
        try:
            session.scrub_artifact(name, max_bytes=max_bytes)
        except self._clone_cleanup_errors as exc:
            self._map_clone_cleanup_error(exc)

    def _anchor_vault(self, mission_id: str) -> CheckpointVault:
        return self._checkpoint_vault_factory(
            native_vault.SecretReference(
                "Onyx.Phase11AutopilotCheckpoint",
                f"cp-{mission_id}",
                "Onyx Phase 11 autopilot checkpoint high-water",
            )
        )

    def _anchor_document(
        self, mission_id: str, sequence: int, checkpoint_digest: str
    ) -> dict[str, Any]:
        payload = {
            "schema": ANCHOR_SCHEMA,
            "mission_id": mission_id,
            "sequence": sequence,
            "checkpoint_digest": checkpoint_digest,
        }
        payload["signature"] = hmac.new(
            self._key, _ANCHOR_DOMAIN + _canonical(payload), hashlib.sha256
        ).hexdigest()
        return payload

    def _read_anchor(self, mission_id: str) -> dict[str, Any] | None:
        raw = self._anchor_vault(mission_id).get_bytes()
        if raw is None:
            return None
        if len(raw) > 2_000:
            raise ProjectAutopilotContractError("checkpoint_anchor_invalid")
        try:
            document = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProjectAutopilotContractError("checkpoint_anchor_invalid") from exc
        if not isinstance(document, dict):
            raise ProjectAutopilotContractError("checkpoint_anchor_invalid")
        unsigned = {key: value for key, value in document.items() if key != "signature"}
        expected = hmac.new(
            self._key, _ANCHOR_DOMAIN + _canonical(unsigned), hashlib.sha256
        ).hexdigest()
        if (
            document.get("schema") != ANCHOR_SCHEMA
            or document.get("mission_id") != mission_id
            or isinstance(document.get("sequence"), bool)
            or not isinstance(document.get("sequence"), int)
            or int(document["sequence"]) <= 0
            or not isinstance(document.get("checkpoint_digest"), str)
            or not hmac.compare_digest(str(document.get("signature", "")), expected)
        ):
            raise ProjectAutopilotContractError("checkpoint_anchor_invalid")
        return document

    def _sign_checkpoint(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        digest = _digest(payload)
        signature = hmac.new(
            self._key, _CHECKPOINT_DOMAIN + digest.encode("ascii"), hashlib.sha256
        ).hexdigest()
        return {**payload, "checkpoint_digest": digest, "signature": signature}

    def _transaction_document(
        self,
        mission_id: str,
        checkpoint: Mapping[str, Any],
        anchor: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = {
            "schema": TRANSACTION_SCHEMA,
            "mission_id": mission_id,
            "checkpoint": dict(checkpoint),
            "anchor": dict(anchor),
        }
        payload["signature"] = hmac.new(
            self._key,
            _TRANSACTION_DOMAIN + _canonical(payload),
            hashlib.sha256,
        ).hexdigest()
        return payload

    def _recover_checkpoint_transaction(self, mission_id: str) -> None:
        path = self._transaction_path(mission_id)
        raw = _descriptor_read(path, max_bytes=2_000_000, missing_ok=True)
        if raw is None:
            return
        try:
            transaction = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProjectAutopilotWaiting(
                "checkpoint_transaction_recovery_required"
            ) from exc
        if not isinstance(transaction, dict):
            raise ProjectAutopilotWaiting("checkpoint_transaction_recovery_required")
        unsigned = {
            key: value for key, value in transaction.items() if key != "signature"
        }
        expected = hmac.new(
            self._key,
            _TRANSACTION_DOMAIN + _canonical(unsigned),
            hashlib.sha256,
        ).hexdigest()
        checkpoint = transaction.get("checkpoint")
        anchor = transaction.get("anchor")
        if (
            transaction.get("schema") != TRANSACTION_SCHEMA
            or transaction.get("mission_id") != mission_id
            or not isinstance(checkpoint, dict)
            or not isinstance(anchor, dict)
            or not hmac.compare_digest(str(transaction.get("signature", "")), expected)
            or checkpoint.get("mission_id") != mission_id
            or anchor.get("mission_id") != mission_id
            or checkpoint.get("checkpoint_digest") != anchor.get("checkpoint_digest")
            or checkpoint.get("sequence") != anchor.get("sequence")
        ):
            raise ProjectAutopilotWaiting("checkpoint_transaction_recovery_required")
        _atomic_descriptor_write(
            self._checkpoint_path(mission_id), _canonical(checkpoint)
        )
        vault = self._anchor_vault(mission_id)
        vault.set_bytes(_canonical(anchor))
        if self._read_anchor(mission_id) != anchor:
            raise ProjectAutopilotWaiting("checkpoint_transaction_recovery_required")
        _secure_scrub_regular(path, 2_000_000)

    def _read_checkpoint(self, mission_id: str) -> dict[str, Any] | None:
        with self._mission_lock(mission_id):
            with self._mission_process_lock(mission_id):
                return self._read_checkpoint_locked(mission_id)

    def _read_checkpoint_locked(
        self,
        mission_id: str,
        *,
        allow_missing_process_high_water: bool = False,
    ) -> dict[str, Any] | None:
        self._recover_checkpoint_transaction(mission_id)
        path = self._checkpoint_path(mission_id)
        try:
            raw = _descriptor_read(path, max_bytes=2_000_000, missing_ok=True)
        except OSError as exc:
            raise ProjectAutopilotContractError("checkpoint_read_failed") from exc
        anchor = self._read_anchor(mission_id)
        if raw is None:
            if anchor is not None:
                raise ProjectAutopilotContractError("checkpoint_rollback_detected")
            return None
        if anchor is None:
            raise ProjectAutopilotContractError("checkpoint_anchor_missing")
        try:
            document = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProjectAutopilotContractError("checkpoint_invalid") from exc
        if not isinstance(document, dict):
            raise ProjectAutopilotContractError("checkpoint_invalid")
        payload = {
            key: value
            for key, value in document.items()
            if key not in {"checkpoint_digest", "signature"}
        }
        digest = _digest(payload)
        expected = hmac.new(
            self._key, _CHECKPOINT_DOMAIN + digest.encode("ascii"), hashlib.sha256
        ).hexdigest()
        if (
            document.get("schema") != CHECKPOINT_SCHEMA
            or document.get("mission_id") != mission_id
            or not hmac.compare_digest(
                str(document.get("checkpoint_digest", "")), digest
            )
            or not hmac.compare_digest(str(document.get("signature", "")), expected)
            or anchor.get("sequence") != document.get("sequence")
            or anchor.get("checkpoint_digest") != digest
        ):
            raise ProjectAutopilotContractError("checkpoint_replay_or_tamper_detected")
        sequence = int(document["sequence"])
        with _PROCESS_HIGH_WATER_LOCK:
            previous = _PROCESS_HIGH_WATER.get(mission_id)
            if previous is None and not allow_missing_process_high_water:
                raise ProjectAutopilotWaiting("fresh_owner_reapproval_required")
            if previous is not None:
                if sequence < previous[0] or (
                    sequence == previous[0]
                    and not hmac.compare_digest(digest, previous[1])
                ):
                    raise ProjectAutopilotContractError(
                        "checkpoint_process_rollback_detected"
                    )
                if sequence > previous[0]:
                    _PROCESS_HIGH_WATER[mission_id] = (sequence, digest)
        return document

    def _write_checkpoint(self, mission_id: str, payload: Mapping[str, Any]) -> None:
        with _PROCESS_HIGH_WATER_LOCK:
            if (
                mission_id not in _PROCESS_HIGH_WATER
                and len(_PROCESS_HIGH_WATER) >= MAX_PROCESS_HIGH_WATER_ENTRIES
            ):
                raise ProjectAutopilotWaiting(
                    "checkpoint_high_water_capacity_exhausted"
                )
        path = self._checkpoint_path(mission_id)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _reject_linked_ancestors(path.parent)
        current = self._read_checkpoint_locked(mission_id)
        sequence = 1 if current is None else int(current["sequence"]) + 1
        document = self._sign_checkpoint({**payload, "sequence": sequence})
        anchor = self._anchor_document(
            mission_id, sequence, str(document["checkpoint_digest"])
        )
        transaction = self._transaction_document(mission_id, document, anchor)
        _atomic_descriptor_write(
            self._transaction_path(mission_id), _canonical(transaction)
        )
        _atomic_descriptor_write(path, _canonical(document))
        vault = self._anchor_vault(mission_id)
        vault.set_bytes(_canonical(anchor))
        observed = self._read_anchor(mission_id)
        if observed != anchor:
            raise ProjectAutopilotContractError("checkpoint_anchor_write_failed")
        _secure_scrub_regular(self._transaction_path(mission_id), 2_000_000)
        with _PROCESS_HIGH_WATER_LOCK:
            if (
                mission_id not in _PROCESS_HIGH_WATER
                and len(_PROCESS_HIGH_WATER) >= MAX_PROCESS_HIGH_WATER_ENTRIES
            ):
                raise ProjectAutopilotWaiting(
                    "checkpoint_high_water_capacity_exhausted"
                )
            _PROCESS_HIGH_WATER[mission_id] = (
                sequence,
                str(document["checkpoint_digest"]),
            )

    @staticmethod
    def _assert_patch_targets(root: Path, paths: Iterable[str]) -> None:
        for relative in paths:
            target = root.joinpath(*PurePosixPath(relative).parts)
            _reject_linked_ancestors(target.parent)
            if target.exists() or target.is_symlink():
                info = target.lstat()
                if stat.S_ISLNK(info.st_mode) or _is_reparse(target):
                    raise ProjectAutopilotWaiting("patch_target_link_forbidden")

    @staticmethod
    def capture_owner_git_state(
        root: str | os.PathLike[str],
        *,
        cancel: CancelCheck | None = None,
        max_seconds: float = 30.0,
    ) -> str:
        if (
            not isinstance(max_seconds, (int, float))
            or isinstance(max_seconds, bool)
            or not 0 < float(max_seconds) <= 60
        ):
            raise ValueError("owner metadata timeout is invalid")
        deadline = time.monotonic() + float(max_seconds)
        owner = Path(root)
        git_dir = owner / ".git"
        _reject_linked_ancestors(git_dir)
        if not git_dir.is_dir() or git_dir.is_symlink() or _is_reparse(git_dir):
            raise ProjectAutopilotContractError(
                "owner_repo_must_have_regular_dot_git_directory"
            )
        rows: list[dict[str, Any]] = []
        total = files = 0
        directories = 1
        pending = [git_dir]

        def capture_guard() -> None:
            if (cancel is not None and cancel()) or time.monotonic() >= deadline:
                raise ProjectAutopilotWaiting("owner_git_capture_timeout_or_cancel")
            if files > MAX_OWNER_GIT_FILES:
                raise ProjectAutopilotContractError("owner_git_file_budget_exhausted")
            if directories > MAX_OWNER_GIT_DIRS:
                raise ProjectAutopilotContractError(
                    "owner_git_directory_budget_exhausted"
                )

        while pending:
            capture_guard()
            directory = pending.pop()
            candidates: list[tuple[str, dict[str, Any], Path | None]] = []
            with os.scandir(directory) as iterator:
                while True:
                    capture_guard()
                    try:
                        entry = next(iterator)
                    except StopIteration:
                        break
                    capture_guard()
                    path = Path(entry.path)
                    relative = path.relative_to(git_dir).as_posix()
                    info = path.lstat()
                    if stat.S_ISDIR(info.st_mode) and not _is_reparse(path):
                        if directories >= MAX_OWNER_GIT_DIRS:
                            raise ProjectAutopilotContractError(
                                "owner_git_directory_budget_exhausted"
                            )
                        directories += 1
                        candidates.append(
                            (
                                entry.name,
                                {
                                    "path": relative,
                                    "kind": "dir",
                                    "mode": stat.S_IMODE(info.st_mode),
                                },
                                path,
                            )
                        )
                        continue
                    if (
                        not stat.S_ISREG(info.st_mode)
                        or stat.S_ISLNK(info.st_mode)
                        or _is_reparse(path)
                    ):
                        raise ProjectAutopilotContractError(
                            "owner_git_entry_not_regular"
                        )
                    if files >= MAX_OWNER_GIT_FILES:
                        raise ProjectAutopilotContractError(
                            "owner_git_file_budget_exhausted"
                        )
                    files += 1
                    content = _descriptor_read(
                        path,
                        max_bytes=MAX_OWNER_GIT_BYTES - total,
                    )
                    assert content is not None
                    total += len(content)
                    candidates.append(
                        (
                            entry.name,
                            {
                                "path": relative,
                                "kind": "file",
                                "mode": stat.S_IMODE(info.st_mode),
                                "size": len(content),
                                "sha256": hashlib.sha256(content).hexdigest(),
                            },
                            None,
                        )
                    )
            candidates.sort(key=lambda item: item[0])
            child_dirs: list[Path] = []
            for _name, row, child in candidates:
                capture_guard()
                rows.append(row)
                if child is not None:
                    child_dirs.append(child)
            pending.extend(reversed(child_dirs))
        return _digest({"entries": rows, "bytes": total})

    def _owner_state(
        self, mission_id: str, root: Path, cancel: CancelCheck
    ) -> tuple[str, bytes]:
        top = self._git(
            mission_id,
            root,
            ("rev-parse", "--show-toplevel"),
            timeout=10,
            output_limit=65_536,
            cancel=cancel,
        )
        try:
            if Path(top.decode("utf-8").strip()).resolve() != root:
                raise ProjectAutopilotWaiting("repo_root_drift")
        except (OSError, UnicodeError) as exc:
            raise ProjectAutopilotWaiting("repo_root_invalid") from exc
        head = (
            self._git(
                mission_id,
                root,
                ("rev-parse", "--verify", "HEAD"),
                timeout=10,
                output_limit=65_536,
                cancel=cancel,
            )
            .decode("ascii", errors="strict")
            .strip()
            .lower()
        )
        status = self._git(
            mission_id,
            root,
            ("status", "--porcelain=v2", "-z", "--untracked-files=all"),
            timeout=15,
            output_limit=MAX_GIT_OUTPUT_BYTES,
            cancel=cancel,
        )
        return head, status

    @staticmethod
    def _assert_owner_git_config_nonexecuting(root: Path) -> None:
        config_paths = (
            (root / ".git" / "config", False),
            (root / ".git" / "config.worktree", True),
        )
        for config_path, missing_ok in config_paths:
            try:
                raw = _descriptor_read(
                    config_path,
                    max_bytes=2_000_000,
                    missing_ok=missing_ok,
                )
                if raw is None:
                    continue
                text = raw.decode("utf-8", errors="strict")
            except (OSError, UnicodeError) as exc:
                raise ProjectAutopilotContractError("owner_git_config_invalid") from exc
            if any(
                ord(character) < 32 and character not in {"\t", "\r", "\n"}
                for character in text
            ):
                raise ProjectAutopilotContractError("owner_git_config_invalid")
            section = ""
            continuation = False
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if continuation:
                    continuation = (len(raw_line) - len(raw_line.rstrip("\\"))) % 2 == 1
                    continue
                if not line or line.startswith(("#", ";")):
                    continue
                if line.startswith("["):
                    match = _GIT_CONFIG_SECTION.fullmatch(line)
                    if match is None:
                        raise ProjectAutopilotContractError("owner_git_config_invalid")
                    section = match.group("section").split(".", 1)[0].casefold()
                    if section in {
                        "filter",
                        "diff",
                        "merge",
                        "include",
                        "includeif",
                    }:
                        raise ProjectAutopilotContractError(
                            "owner_git_executable_config_refused"
                        )
                    continue
                key_match = _GIT_CONFIG_KEY.match(line)
                if key_match is None:
                    raise ProjectAutopilotContractError("owner_git_config_invalid")
                key = key_match.group("key").casefold()
                if section == "core" and key in {
                    "hookspath",
                    "fsmonitor",
                    "sshcommand",
                }:
                    raise ProjectAutopilotContractError(
                        "owner_git_executable_config_refused"
                    )
                continuation = (len(raw_line) - len(raw_line.rstrip("\\"))) % 2 == 1

    def _assert_owner_immutable(
        self,
        mission_id: str,
        envelope: AutopilotEnvelopeV1,
        cancel: CancelCheck,
    ) -> Path:
        root = Path(envelope.root)
        if not root.is_absolute() or not root.is_dir():
            raise ProjectAutopilotWaiting("repo_unavailable")
        _reject_linked_ancestors(root)
        resolved = root.resolve()
        if str(resolved) != envelope.root:
            raise ProjectAutopilotWaiting("repo_root_drift")
        self._assert_owner_git_config_nonexecuting(resolved)
        head, status = self._owner_state(mission_id, resolved, cancel)
        if not hmac.compare_digest(head, envelope.base_head):
            raise ProjectAutopilotWaiting("base_head_drift")
        if status:
            raise ProjectAutopilotWaiting("owner_worktree_not_clean")
        if not hmac.compare_digest(
            self.capture_owner_git_state(resolved, cancel=cancel, max_seconds=30),
            envelope.owner_git_sha256,
        ):
            raise ProjectAutopilotWaiting("owner_git_metadata_drift")
        self._assert_patch_targets(resolved, envelope.patch_paths)
        return resolved

    def _preflight_clone_budget(
        self,
        mission_id: str,
        owner: Path,
        mission_dir: Path,
        envelope: AutopilotEnvelopeV1,
        cancel: CancelCheck,
    ) -> None:
        if cancel():
            raise ProjectAutopilotWaiting("kill_requested")
        git_bytes = _logical_tree_bytes(owner / ".git", MAX_OWNER_GIT_BYTES)
        if git_bytes > MAX_OWNER_GIT_BYTES:
            raise ProjectAutopilotWaiting(
                "controlled_clone_preflight_disk_budget_exhausted"
            )
        listing = self._git(
            mission_id,
            owner,
            ("ls-tree", "-r", "-l", "-z", envelope.base_head),
            timeout=30,
            output_limit=envelope.max_output_bytes,
            cancel=cancel,
        )
        checkout_bytes = 0
        for record in listing.split(b"\0"):
            if not record:
                continue
            try:
                metadata, _name = record.split(b"\t", 1)
                fields = metadata.split()
                if len(fields) != 4:
                    raise ValueError
                mode, kind, _object_id, size = fields
                if kind != b"blob" or mode == b"120000" or not size.isdigit():
                    raise ValueError
                checkout_bytes += int(size)
            except (ValueError, OverflowError) as exc:
                raise ProjectAutopilotWaiting(
                    "controlled_clone_preflight_entry_refused"
                ) from exc
            if checkout_bytes > MAX_CLONE_BYTES:
                raise ProjectAutopilotWaiting(
                    "controlled_clone_preflight_disk_budget_exhausted"
                )
        estimated_peak = (
            (git_bytes * 2)
            + checkout_bytes
            + envelope.patch_bytes
            + CLONE_FREE_SPACE_MARGIN
        )
        if estimated_peak > MAX_CLONE_BYTES:
            raise ProjectAutopilotWaiting(
                "controlled_clone_preflight_disk_budget_exhausted"
            )
        if shutil.disk_usage(mission_dir).free < estimated_peak:
            raise ProjectAutopilotWaiting("controlled_clone_free_space_insufficient")

    def _materialize_clone(
        self,
        mission_id: str,
        owner: Path,
        envelope: AutopilotEnvelopeV1,
        cancel: CancelCheck,
        allow_existing: bool,
    ) -> Path:
        clone = self._clone_path(mission_id)
        mission_dir = self._mission_dir(mission_id)
        mission_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        _reject_linked_ancestors(mission_dir)
        if clone.exists() and not allow_existing:
            raise ProjectAutopilotContractError("controlled_clone_preseeded")
        if not clone.exists() and allow_existing:
            raise ProjectAutopilotContractError("controlled_clone_missing_on_resume")
        if not clone.exists():
            bundle = self._bundle_path(mission_id)
            if bundle.exists():
                raise ProjectAutopilotContractError("controlled_bundle_preseeded")
            self._preflight_clone_budget(
                mission_id, owner, mission_dir, envelope, cancel
            )
            try:
                self._git(
                    mission_id,
                    owner,
                    ("bundle", "create", str(bundle), "HEAD"),
                    timeout=120,
                    output_limit=envelope.max_output_bytes,
                    cancel=cancel,
                    disk_root=mission_dir,
                    disk_limit=MAX_CLONE_BYTES,
                )
                _descriptor_read(bundle, max_bytes=MAX_OWNER_GIT_BYTES)
                self._git(
                    mission_id,
                    mission_dir,
                    ("clone", "--no-checkout", str(bundle), str(clone)),
                    timeout=120,
                    output_limit=envelope.max_output_bytes,
                    cancel=cancel,
                    disk_root=mission_dir,
                    disk_limit=MAX_CLONE_BYTES,
                )
                self._git(
                    mission_id,
                    clone,
                    ("checkout", "--detach", envelope.base_head),
                    timeout=60,
                    output_limit=envelope.max_output_bytes,
                    cancel=cancel,
                    disk_root=mission_dir,
                    disk_limit=MAX_CLONE_BYTES,
                )
            except BaseException:
                _secure_scrub_regular(bundle, MAX_CLONE_BYTES + CLONE_FREE_SPACE_MARGIN)
                raise
        _reject_linked_ancestors(clone)
        if not clone.is_dir() or clone.is_symlink() or _is_reparse(clone):
            raise ProjectAutopilotWaiting("controlled_clone_invalid")
        top = self._git(
            mission_id,
            clone,
            ("rev-parse", "--show-toplevel"),
            timeout=10,
            output_limit=65_536,
            cancel=cancel,
        )
        common = self._git(
            mission_id,
            clone,
            ("rev-parse", "--git-common-dir"),
            timeout=10,
            output_limit=65_536,
            cancel=cancel,
        )
        origin = (
            self._git(
                mission_id,
                clone,
                ("remote", "get-url", "origin"),
                timeout=10,
                output_limit=65_536,
                cancel=cancel,
            )
            if self._clone_cleanup is None
            else None
        )
        try:
            top_path = Path(top.decode("utf-8", errors="strict").strip()).resolve()
            common_raw = Path(common.decode("utf-8", errors="strict").strip())
            common_path = (
                common_raw if common_raw.is_absolute() else (clone / common_raw)
            ).resolve()
            origin_path = (
                None
                if origin is None
                else Path(origin.decode("utf-8", errors="strict").strip()).resolve()
            )
        except (UnicodeError, OSError) as exc:
            raise ProjectAutopilotWaiting("controlled_clone_identity_invalid") from exc
        if (
            top_path != clone.resolve()
            or common_path != (clone / ".git").resolve()
            or (
                origin_path is not None
                and origin_path != self._bundle_path(mission_id).resolve()
            )
        ):
            raise ProjectAutopilotWaiting("controlled_clone_identity_invalid")
        head = (
            self._git(
                mission_id,
                clone,
                ("rev-parse", "--verify", "HEAD"),
                timeout=10,
                output_limit=65_536,
                cancel=cancel,
            )
            .decode("ascii", errors="strict")
            .strip()
            .lower()
        )
        if not hmac.compare_digest(head, envelope.base_head):
            raise ProjectAutopilotWaiting("controlled_clone_head_drift")
        self._assert_patch_targets(clone, envelope.patch_paths)
        _bounded_tree_usage(clone)
        self._assert_owner_immutable(mission_id, envelope, cancel)
        return clone

    @contextmanager
    def _protected_bundle(
        self,
        mission_id: str,
        owner: Path,
        envelope: AutopilotEnvelopeV1,
        cancel: CancelCheck,
    ) -> Iterator[tuple[Path, int, str]]:
        session = self._namespace_sessions.get(mission_id)
        if session is None:
            raise ProjectAutopilotContractError("mission_namespace_session_missing")
        self._scrub_mission_artifact(mission_id, "source.bundle", MAX_OWNER_GIT_BYTES)
        bundle: Path
        _bundle_size: int
        _bundle_digest: str
        try:
            with session.artifact_writer(
                "source.bundle", max_bytes=MAX_OWNER_GIT_BYTES
            ) as writer:
                self._git(
                    mission_id,
                    owner,
                    ("bundle", "create", "-", "--all"),
                    timeout=120,
                    output_limit=envelope.max_output_bytes,
                    cancel=cancel,
                    stdout_sink=writer.write,
                    stdout_limit=MAX_OWNER_GIT_BYTES,
                )
                size, digest = writer.finish()
                if size <= 0:
                    raise ProjectAutopilotContractError("controlled_bundle_empty")
                bundle = self._bundle_path(mission_id)
                self._git(
                    mission_id,
                    owner,
                    ("bundle", "verify", str(bundle)),
                    timeout=30,
                    output_limit=envelope.max_output_bytes,
                    cancel=cancel,
                )
                yield bundle, size, digest
        except BaseException:
            self._scrub_mission_artifact(
                mission_id, "source.bundle", MAX_OWNER_GIT_BYTES
            )
            raise

    def _populate_prepared_clone(
        self,
        mission_id: str,
        owner: Path,
        envelope: AutopilotEnvelopeV1,
        cancel: CancelCheck,
    ) -> None:
        """Populate the exact empty directory bound by the cleanup backend."""
        clone = self._clone_path(mission_id)
        mission_dir = self._mission_dir(mission_id)
        if self._clone_cleanup is None:
            raise ProjectAutopilotContractError(
                "handle_safe_clone_cleanup_not_configured"
            )
        try:
            entries = tuple(clone.iterdir())
        except OSError as exc:
            raise ProjectAutopilotWaiting(
                "controlled_clone_prepared_directory_unavailable"
            ) from exc
        if entries:
            return
        self._preflight_clone_budget(mission_id, owner, mission_dir, envelope, cancel)
        try:
            with self._protected_bundle(mission_id, owner, envelope, cancel) as (
                bundle,
                _bundle_size,
                _bundle_digest,
            ):
                self._git(
                    mission_id,
                    clone,
                    ("init",),
                    timeout=30,
                    output_limit=envelope.max_output_bytes,
                    cancel=cancel,
                    disk_root=mission_dir,
                    disk_limit=MAX_CLONE_BYTES,
                )
                clone_files = self._clone_operations.get(mission_id)
                if clone_files is None:
                    raise ProjectAutopilotContractError(
                        "controlled_clone_operation_missing"
                    )
                with (
                    clone_files.hold_file(".git/config"),
                    clone_files.parent(".git/hooks/probe"),
                ):
                    self._git(
                        mission_id,
                        clone,
                        (
                            "fetch",
                            "--no-tags",
                            str(bundle),
                            envelope.base_head,
                        ),
                        timeout=120,
                        output_limit=envelope.max_output_bytes,
                        cancel=cancel,
                        disk_root=mission_dir,
                        disk_limit=MAX_CLONE_BYTES,
                    )
                    self._git(
                        mission_id,
                        clone,
                        (
                            "checkout",
                            "--detach",
                            envelope.base_head,
                        ),
                        timeout=60,
                        output_limit=envelope.max_output_bytes,
                        cancel=cancel,
                        disk_root=mission_dir,
                        disk_limit=MAX_CLONE_BYTES,
                    )
        except BaseException:
            self._scrub_mission_artifact(
                mission_id, "source.bundle", MAX_OWNER_GIT_BYTES
            )
            raise

    @staticmethod
    def _status_paths(status: bytes) -> tuple[str, ...]:
        from core.phase11_local_project_audit_v1 import LocalProjectAuditV1

        return tuple(path for path, _state in LocalProjectAuditV1._status_paths(status))

    def _state_receipt(
        self,
        mission_id: str,
        root: Path,
        envelope: AutopilotEnvelopeV1,
        cancel: CancelCheck,
        clone_files: Any | None = None,
    ) -> dict[str, Any]:
        _bounded_tree_usage(root)
        status = self._git(
            mission_id,
            root,
            ("status", "--porcelain=v2", "-z", "--untracked-files=all"),
            timeout=20,
            output_limit=envelope.max_output_bytes,
            cancel=cancel,
        )
        paths = self._status_paths(status)
        if set(paths) != set(envelope.patch_paths):
            raise ProjectAutopilotWaiting("dirty_paths_diverge_from_signed_patch")
        if len(paths) > MAX_DIRTY_FILES:
            raise ProjectAutopilotWaiting("dirty_file_budget_exhausted")
        files: list[dict[str, Any]] = []
        total = 0
        for relative in paths:
            path = root.joinpath(*PurePosixPath(relative).parts)
            if clone_files is None:
                _reject_linked_ancestors(path.parent)
            try:
                content = (
                    clone_files.read_file_optional(
                        relative,
                        max_bytes=MAX_DIRTY_BYTES - total,
                    )
                    if clone_files is not None
                    else _descriptor_read(
                        path,
                        max_bytes=MAX_DIRTY_BYTES - total,
                        missing_ok=True,
                    )
                )
            except self._clone_cleanup_errors as exc:
                self._map_clone_cleanup_error(exc)
            except OSError as exc:
                raise ProjectAutopilotWaiting("dirty_file_read_failed") from exc
            if content is None:
                files.append(
                    {"path": relative, "size": -1, "sha256": _digest("<missing>")}
                )
                continue
            total += len(content)
            files.append(
                {
                    "path": relative,
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        diff = self._git(
            mission_id,
            root,
            ("diff", "--binary", "--no-ext-diff", "--no-renames", "HEAD", "--"),
            timeout=30,
            output_limit=envelope.max_output_bytes,
            cancel=cancel,
        )
        payload = {
            "patch_sha256": envelope.patch_sha256,
            "status_sha256": hashlib.sha256(status).hexdigest(),
            "diff_sha256": hashlib.sha256(diff).hexdigest(),
            "dirty_files": files,
            "dirty_bytes": total,
        }
        payload["state_sha256"] = _digest(payload)
        return payload

    def _receipt_signature(self, value: Mapping[str, Any]) -> str:
        return hmac.new(
            self._key, _RECEIPT_DOMAIN + _canonical(value), hashlib.sha256
        ).hexdigest()

    def _normalize_executable_plan(
        self,
        value: ExecutableGatePlanV1 | ExecutableGateEnvelopeV1 | None,
        *,
        mission_id: str,
        primary_envelope: AutopilotEnvelopeV1,
        binding_digest: str,
    ) -> ExecutableGatePlanV1 | None:
        if value is None:
            return None
        if isinstance(value, ExecutableGateEnvelopeV1):
            value.verify(
                approved_image_ids=self._approved_executable_image_ids,
                mission_id=mission_id,
                gate_index=0,
                primary_envelope=primary_envelope,
                binding_digest=binding_digest,
                signing_key=self._key,
            )
            return value.plan
        raise ProjectAutopilotContractError(
            "executable_gate_authorized_envelope_required"
        )

    def _validated_execution_ledger(
        self,
    ) -> Phase11ExecutionLedgerV1 | None:
        ledger = self._execution_ledger
        if ledger is None:
            if self._require_execution_ledger:
                raise ProjectAutopilotContractError(
                    "executable_execution_ledger_required"
                )
            return None
        if type(ledger) is not Phase11ExecutionLedgerV1 or ledger.enabled is not True:
            raise ProjectAutopilotContractError(
                "executable_execution_ledger_binding_invalid"
            )
        return ledger

    def _sandbox_subkey(self) -> bytes:
        return derive_executable_sandbox_subkey_v1(self._key)

    def _execution_id(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        primary_input_digest: str,
        plan: ExecutableGatePlanV1,
        index: int,
    ) -> str:
        gate = plan.gates[index]
        payload = {
            "mission_id": mission_id,
            "binding_digest": binding_digest,
            "primary_input_digest": primary_input_digest,
            "plan_digest": plan.plan_digest,
            "index": index,
            "image_id": plan.image_id,
            "platform": plan.platform,
            "argv": list(gate.argv),
            "timeout_seconds": gate.timeout_seconds,
            "max_output_bytes": gate.max_output_bytes,
        }
        return hmac.new(
            self._sandbox_subkey(),
            _EXECUTION_ID_DOMAIN + _canonical(payload),
            hashlib.sha256,
        ).hexdigest()

    def _executable_sandbox(
        self,
        *,
        clone: Path,
        plan: ExecutableGatePlanV1,
    ) -> Any:
        if (
            not self._executable_sandbox_enabled
            or self._executable_sandbox_host is None
        ):
            raise ProjectAutopilotContractError(
                "executable_sandbox_not_explicitly_enabled"
            )
        if len(self._key) < 32:
            raise ProjectAutopilotContractError(
                "executable_sandbox_signing_key_too_short"
            )
        control_root = self._executable_control_root
        control_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        _reject_linked_ancestors(control_root)
        if os.name == "posix":
            os.chmod(control_root, 0o700)
        else:
            _harden_mode(control_root)
        control_root_value = str(control_root.resolve(strict=True))
        clone_parent_value = str(clone.parent.resolve(strict=True))
        expected: dict[str, object] = {
            "enabled": True,
            "control_root": control_root_value,
            "clone_parent": clone_parent_value,
            "container_platform": plan.platform,
        }
        assert self._executable_sandbox_host is not None
        execution_ledger = self._validated_execution_ledger()
        sandbox = self._executable_sandbox_host.instantiate(
            container_platform=plan.platform,
            control_root=control_root_value,
            clone_parent=clone_parent_value,
            signing_key=self._sandbox_subkey(),
            execution_ledger=execution_ledger,
        )
        if type(sandbox) is not ExecutableTestSandboxV1:
            raise ProjectAutopilotContractError(
                "executable_sandbox_host_type_drift"
            )
        try:
            observed = sandbox.integration_binding()
        except BaseException as exc:
            raise ProjectAutopilotContractError(
                "executable_sandbox_host_binding_failed"
            ) from exc
        if not isinstance(observed, Mapping) or dict(observed) != expected:
            raise ProjectAutopilotContractError(
                "executable_sandbox_host_binding_mismatch"
            )
        return sandbox

    def _executable_receipt(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        primary_input_digest: str,
        plan: ExecutableGatePlanV1,
        gate: ExecutableGateSpecV1,
        index: int,
        sandbox_receipt: object,
    ) -> dict[str, Any]:
        from core.phase11_executable_sandbox_v1 import (
            ExecutableSandboxReceiptV1,
            verify_executable_sandbox_receipt_v1,
        )

        if not isinstance(sandbox_receipt, ExecutableSandboxReceiptV1):
            raise ProjectAutopilotContractError(
                "executable_sandbox_receipt_type_invalid"
            )
        if not verify_executable_sandbox_receipt_v1(
            sandbox_receipt,
            signing_key=self._sandbox_subkey(),
            mission_id=mission_id,
            execution_id=self._execution_id(
                mission_id=mission_id,
                binding_digest=binding_digest,
                primary_input_digest=primary_input_digest,
                plan=plan,
                index=index,
            ),
            image_id=plan.image_id,
            argv=gate.argv,
        ):
            raise ProjectAutopilotContractError("executable_sandbox_receipt_invalid")
        execution_ledger = self._validated_execution_ledger()
        if execution_ledger is not None:
            if execution_ledger.authenticated_receipt(
                mission_id=mission_id,
                execution_id=sandbox_receipt.execution_id,
                attempt=sandbox_receipt.attempt,
            ) != asdict(sandbox_receipt):
                raise ProjectAutopilotContractError(
                    "executable_ledger_receipt_binding_invalid"
                )
        receipt = {
            "index": index,
            "execution_id": sandbox_receipt.execution_id,
            "plan_digest": plan.plan_digest,
            "image_id": plan.image_id,
            "platform": plan.platform,
            "argv_sha256": _digest(list(gate.argv)),
            "verdict": sandbox_receipt.verdict,
            "repository_code_executed": True,
            "sandbox_receipt": asdict(sandbox_receipt),
        }
        receipt["signature"] = self._receipt_signature(receipt)
        return receipt

    def _verify_executable_receipt(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        primary_input_digest: str,
        plan: ExecutableGatePlanV1,
        index: int,
        receipt: object,
    ) -> None:
        from core.phase11_executable_sandbox_v1 import (
            verify_executable_sandbox_receipt_v1,
        )

        if not isinstance(receipt, Mapping) or set(receipt) != {
            "index",
            "execution_id",
            "plan_digest",
            "image_id",
            "platform",
            "argv_sha256",
            "verdict",
            "repository_code_executed",
            "sandbox_receipt",
            "signature",
        }:
            raise ProjectAutopilotContractError("executable_gate_receipt_invalid")
        gate = plan.gates[index]
        unsigned = {key: value for key, value in receipt.items() if key != "signature"}
        expected = self._receipt_signature(unsigned)
        execution_id = self._execution_id(
            mission_id=mission_id,
            binding_digest=binding_digest,
            primary_input_digest=primary_input_digest,
            plan=plan,
            index=index,
        )
        if (
            receipt.get("index") != index
            or receipt.get("execution_id") != execution_id
            or receipt.get("plan_digest") != plan.plan_digest
            or receipt.get("image_id") != plan.image_id
            or receipt.get("platform") != plan.platform
            or receipt.get("argv_sha256") != _digest(list(gate.argv))
            or receipt.get("repository_code_executed") is not True
            or not hmac.compare_digest(str(receipt.get("signature", "")), expected)
            or not verify_executable_sandbox_receipt_v1(
                receipt.get("sandbox_receipt", {}),
                signing_key=self._sandbox_subkey(),
                mission_id=mission_id,
                execution_id=execution_id,
                image_id=plan.image_id,
                argv=gate.argv,
            )
        ):
            raise ProjectAutopilotContractError("executable_gate_receipt_invalid")

    def _static_gate(
        self,
        clone: Path,
        patch: str,
        envelope: AutopilotEnvelopeV1,
        gate: GateSpecV1,
        cancel: CancelCheck,
        clone_files: Any | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        gate_deadline = started + gate.timeout_seconds

        def check_boundary() -> None:
            if cancel():
                raise ProjectAutopilotWaiting("kill_requested")
            if time.monotonic() >= gate_deadline:
                raise ProjectAutopilotWaiting("static_gate_timeout")

        if gate.argv == ("onyx-static", "diff-check"):
            for index, line in enumerate(patch.splitlines()):
                if index % 128 == 0:
                    check_boundary()
                if (
                    line.startswith("+")
                    and not line.startswith("+++")
                    and line.rstrip(" \t") != line
                ):
                    raise ProjectAutopilotWaiting("static_diff_check_failed")
                if line[1:] in {"<<<<<<<", "=======", ">>>>>>>"}:
                    raise ProjectAutopilotWaiting("static_diff_check_failed")
            checked = len(patch.encode("utf-8"))
        elif gate.argv[1] == "python-ast":
            checked = 0
            for relative in gate.argv[2:]:
                check_boundary()
                path = clone.joinpath(*PurePosixPath(relative).parts)
                if clone_files is None:
                    _reject_linked_ancestors(path.parent)
                try:
                    content = (
                        clone_files.read_file(
                            relative,
                            max_bytes=MAX_STATIC_FILE_BYTES,
                        )
                        if clone_files is not None
                        else _descriptor_read(
                            path,
                            max_bytes=MAX_STATIC_FILE_BYTES,
                        )
                    )
                    assert content is not None
                    source = content.decode("utf-8", errors="strict")
                    ast.parse(source, filename=relative, mode="exec")
                except self._clone_cleanup_errors as exc:
                    self._map_clone_cleanup_error(exc)
                except (
                    OSError,
                    UnicodeError,
                    SyntaxError,
                    ProjectAutopilotContractError,
                ) as exc:
                    raise ProjectAutopilotWaiting("static_python_ast_failed") from exc
                checked += len(cast(bytes, content))
                check_boundary()
        else:
            raise ProjectAutopilotContractError("static_gate_forbidden")
        check_boundary()
        receipt = {
            "argv_sha256": _digest(list(gate.argv)),
            "verdict": "PASS",
            "checked_bytes": checked,
            "executor": "trusted_onyx_static_v1",
            "repository_code_executed": False,
        }
        receipt["signature"] = self._receipt_signature(receipt)
        return receipt

    def _checkpoint_payload(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        envelope: AutopilotEnvelopeV1,
        stage: str,
        gate_index: int,
        gate_receipts: list[dict[str, Any]],
        state_receipt: dict[str, Any] | None,
        waiting_reason: str | None,
        executable_plan_digest: str | None = None,
        executable_gate_index: int = 0,
        executable_gate_receipts: list[dict[str, Any]] | None = None,
        executable_gate_intent: dict[str, Any] | None = None,
        executable_terminal_outcome: dict[str, Any] | None = None,
        repository_code_execution_state: str = "not_started",
    ) -> dict[str, Any]:
        payload = {
            "schema": CHECKPOINT_SCHEMA,
            "mission_id": mission_id,
            "binding_digest": binding_digest,
            "input_digest": envelope.input_digest,
            "base_head": envelope.base_head,
            "owner_git_sha256": envelope.owner_git_sha256,
            "clone": str(self._clone_path(mission_id)),
            "stage": stage,
            "gate_index": gate_index,
            "gate_receipts": gate_receipts,
            "state_receipt": state_receipt,
            "waiting_reason": waiting_reason,
        }
        if executable_plan_digest is not None:
            payload.update(
                executable_plan_digest=executable_plan_digest,
                executable_gate_index=executable_gate_index,
                executable_gate_receipts=(
                    [] if executable_gate_receipts is None else executable_gate_receipts
                ),
                executable_gate_intent=executable_gate_intent,
                executable_terminal_outcome=executable_terminal_outcome,
                repository_code_execution_state=repository_code_execution_state,
            )
        return payload

    def execute(
        self,
        **arguments: Any,
    ) -> dict[str, Any]:
        mission_id = str(arguments.get("mission_id", ""))
        with self._mission_lock(mission_id):
            with self._mission_process_lock(mission_id):
                result = self._execute_locked(**arguments)
                for delay in _BOUND_GIT_RETRY_DELAYS_SECONDS:
                    data = result.get("data")
                    if (
                        result.get("status") != "waiting"
                        or result.get("waiting_for") != "trusted_git_command_failed"
                        or not isinstance(data, Mapping)
                        or data.get("checkpoint_stage") != "bound"
                        or data.get("repository_code_execution_state")
                        != "not_started"
                    ):
                        break
                    time.sleep(delay)
                    result = self._execute_locked(**arguments)
                return result

    def _execute_locked(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        envelope: AutopilotEnvelopeV1,
        patch: str,
        cancel: CancelCheck,
        executable_plan: ExecutableGateEnvelopeV1 | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            raise ProjectAutopilotContractError(
                f"{MISSION_TYPE} is disabled; enable {FEATURE_FLAG} exactly"
            )
        if hashlib.sha256(patch.encode("utf-8")).hexdigest() != envelope.patch_sha256:
            raise ProjectAutopilotContractError("patch_digest_mismatch")
        normalized_executable_plan = self._normalize_executable_plan(
            executable_plan,
            mission_id=mission_id,
            primary_envelope=envelope,
            binding_digest=binding_digest,
        )
        if normalized_executable_plan is not None and (
            not self._executable_sandbox_enabled
            or self._executable_sandbox_host is None
        ):
            raise ProjectAutopilotContractError(
                "executable_sandbox_not_explicitly_enabled"
            )
        deadline = time.monotonic() + max(1.0, envelope.max_seconds - 0.5)
        time_exhausted = False

        def bounded_cancel() -> bool:
            nonlocal time_exhausted
            if time.monotonic() >= deadline:
                time_exhausted = True
                return True
            return cancel()

        checkpoint = self._read_checkpoint_locked(mission_id)
        stage, gate_index = "bound", 0
        gate_receipts: list[dict[str, Any]] = []
        executable_gate_index = 0
        executable_gate_receipts: list[dict[str, Any]] = []
        executable_gate_intent: dict[str, Any] | None = None
        executable_terminal_outcome: dict[str, Any] | None = None
        repository_code_execution_state = "not_started"
        repository_code_executed = False
        state_receipt: dict[str, Any] | None = None
        clone_session: Any | None = None
        clone_session_entered = False
        operation_session: Any | None = None
        operation_session_entered = False

        def checkpoint_payload(**kwargs: Any) -> dict[str, Any]:
            if normalized_executable_plan is not None:
                kwargs.update(
                    executable_plan_digest=(normalized_executable_plan.plan_digest),
                    executable_gate_index=executable_gate_index,
                    executable_gate_receipts=executable_gate_receipts,
                    executable_gate_intent=executable_gate_intent,
                    executable_terminal_outcome=executable_terminal_outcome,
                    repository_code_execution_state=(repository_code_execution_state),
                )
            return self._checkpoint_payload(**kwargs)

        if checkpoint is not None:
            if (
                checkpoint.get("mission_id") != mission_id
                or checkpoint.get("binding_digest") != binding_digest
                or checkpoint.get("input_digest") != envelope.input_digest
                or checkpoint.get("base_head") != envelope.base_head
                or checkpoint.get("owner_git_sha256") != envelope.owner_git_sha256
                or checkpoint.get("clone") != str(self._clone_path(mission_id))
            ):
                raise ProjectAutopilotContractError("checkpoint_binding_drift")
            stage = str(checkpoint.get("stage", "bound"))
            gate_index = int(checkpoint.get("gate_index", 0))
            gate_receipts = list(checkpoint.get("gate_receipts") or [])
            state_receipt = checkpoint.get("state_receipt")
            executable_keys = {
                "executable_plan_digest",
                "executable_gate_index",
                "executable_gate_receipts",
                "executable_gate_intent",
                "executable_terminal_outcome",
                "repository_code_execution_state",
            }
            present_executable_keys = executable_keys.intersection(checkpoint)
            if normalized_executable_plan is None:
                if present_executable_keys:
                    raise ProjectAutopilotContractError(
                        "checkpoint_executable_binding_drift"
                    )
            else:
                if present_executable_keys != executable_keys:
                    raise ProjectAutopilotContractError(
                        "checkpoint_executable_fields_incomplete"
                    )
                raw_index = checkpoint.get("executable_gate_index")
                raw_receipts = checkpoint.get("executable_gate_receipts")
                raw_intent = checkpoint.get("executable_gate_intent")
                raw_terminal = checkpoint.get("executable_terminal_outcome")
                raw_execution_state = checkpoint.get("repository_code_execution_state")
                if (
                    checkpoint.get("executable_plan_digest")
                    != normalized_executable_plan.plan_digest
                    or isinstance(raw_index, bool)
                    or not isinstance(raw_index, int)
                    or not 0 <= raw_index <= len(normalized_executable_plan.gates)
                    or not isinstance(raw_receipts, list)
                    or len(raw_receipts) != raw_index
                    or raw_execution_state
                    not in {
                        "not_started",
                        "attempted_unknown",
                        "executed_receipt",
                    }
                    or (raw_intent is not None and raw_terminal is not None)
                ):
                    raise ProjectAutopilotContractError(
                        "checkpoint_executable_binding_drift"
                    )
                for receipt_index, receipt in enumerate(raw_receipts):
                    self._verify_executable_receipt(
                        mission_id=mission_id,
                        binding_digest=binding_digest,
                        primary_input_digest=envelope.input_digest,
                        plan=normalized_executable_plan,
                        index=receipt_index,
                        receipt=receipt,
                    )
                    if receipt.get("verdict") != "PASS":
                        raise ProjectAutopilotContractError(
                            "checkpoint_executable_binding_drift"
                        )
                execution_ids = [
                    str(receipt.get("execution_id"))
                    for receipt in raw_receipts
                    if isinstance(receipt, Mapping)
                ]
                if len(set(execution_ids)) != len(execution_ids):
                    raise ProjectAutopilotContractError(
                        "checkpoint_executable_receipt_replay"
                    )
                if raw_intent is not None:
                    if raw_index >= len(normalized_executable_plan.gates):
                        raise ProjectAutopilotContractError(
                            "checkpoint_executable_intent_invalid"
                        )
                    expected_intent = {
                        "index": raw_index,
                        "execution_id": self._execution_id(
                            mission_id=mission_id,
                            binding_digest=binding_digest,
                            primary_input_digest=envelope.input_digest,
                            plan=normalized_executable_plan,
                            index=raw_index,
                        ),
                    }
                    if (
                        not isinstance(raw_intent, Mapping)
                        or dict(raw_intent) != expected_intent
                        or raw_execution_state != "attempted_unknown"
                    ):
                        raise ProjectAutopilotContractError(
                            "checkpoint_executable_intent_invalid"
                        )
                if raw_terminal is not None:
                    if (
                        not isinstance(raw_terminal, Mapping)
                        or set(raw_terminal) != {"receipt", "reason"}
                        or raw_index >= len(normalized_executable_plan.gates)
                    ):
                        raise ProjectAutopilotContractError(
                            "checkpoint_executable_terminal_invalid"
                        )
                    terminal_receipt = raw_terminal.get("receipt")
                    self._verify_executable_receipt(
                        mission_id=mission_id,
                        binding_digest=binding_digest,
                        primary_input_digest=envelope.input_digest,
                        plan=normalized_executable_plan,
                        index=raw_index,
                        receipt=terminal_receipt,
                    )
                    if (
                        not isinstance(terminal_receipt, Mapping)
                        or terminal_receipt.get("verdict") == "PASS"
                        or raw_execution_state != "executed_receipt"
                        or not isinstance(raw_terminal.get("reason"), str)
                    ):
                        raise ProjectAutopilotContractError(
                            "checkpoint_executable_terminal_invalid"
                        )
                expected_execution_state = (
                    "attempted_unknown"
                    if raw_intent is not None
                    else (
                        "executed_receipt"
                        if raw_terminal is not None or raw_receipts
                        else "not_started"
                    )
                )
                if raw_execution_state != expected_execution_state:
                    raise ProjectAutopilotContractError(
                        "checkpoint_executable_execution_state_invalid"
                    )
                executable_gate_index = raw_index
                executable_gate_receipts = list(raw_receipts)
                executable_gate_intent = (
                    None if raw_intent is None else dict(raw_intent)
                )
                executable_terminal_outcome = (
                    None if raw_terminal is None else dict(raw_terminal)
                )
                repository_code_execution_state = str(raw_execution_state)
                repository_code_executed = (
                    repository_code_execution_state != "not_started"
                )
            if stage not in {
                "bound",
                "clone_preparing",
                "clone_building",
                "clone_ready",
                "patch_applied",
                "gates_running",
                "executable_gate_pending",
                "executable_gates_running",
                "executable_gate_terminal",
                "verified",
                "cleanup_planned",
                "deleting",
                "finalizing",
                "root_removed",
                "cleaned",
            }:
                raise ProjectAutopilotContractError("checkpoint_stage_invalid")
            if stage in {
                "cleanup_planned",
                "deleting",
                "finalizing",
                "root_removed",
                "cleaned",
            }:
                raise ProjectAutopilotContractError(
                    "cleanup_checkpoint_execution_refused"
                )
        try:
            if executable_gate_intent is not None:
                raise ProjectAutopilotWaiting("executable_gate_reconciliation_required")
            if executable_terminal_outcome is not None:
                raise ProjectAutopilotWaiting(
                    str(executable_terminal_outcome["reason"])
                )
            owner = self._assert_owner_immutable(mission_id, envelope, bounded_cancel)
            mission_dir = self._mission_dir(mission_id)
            _reject_linked_ancestors(mission_dir.parent)
            mission_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            _reject_linked_ancestors(mission_dir)
            if checkpoint is None:
                self._write_checkpoint(
                    mission_id,
                    checkpoint_payload(
                        mission_id=mission_id,
                        binding_digest=binding_digest,
                        envelope=envelope,
                        stage="bound",
                        gate_index=0,
                        gate_receipts=[],
                        state_receipt=None,
                        waiting_reason=None,
                    ),
                )
                checkpoint = self._read_checkpoint_locked(mission_id)
                if checkpoint is None:
                    raise ProjectAutopilotContractError("bound_checkpoint_missing")
                stage = "bound"
            if self._clone_cleanup is None:
                clone = self._materialize_clone(
                    mission_id,
                    owner,
                    envelope,
                    bounded_cancel,
                    allow_existing=(checkpoint is not None and stage != "bound"),
                )
                if stage == "bound":
                    self._write_checkpoint(
                        mission_id,
                        checkpoint_payload(
                            mission_id=mission_id,
                            binding_digest=binding_digest,
                            envelope=envelope,
                            stage="clone_ready",
                            gate_index=0,
                            gate_receipts=[],
                            state_receipt=None,
                            waiting_reason=None,
                        ),
                    )
                    stage = "clone_ready"
            else:
                try:
                    provenance = self._clone_cleanup.inspect_provenance(
                        mission_id=mission_id,
                        containment_handles=(
                            self._borrowed_containment_handles(mission_id)
                        ),
                    )
                except self._clone_cleanup_errors as exc:
                    self._map_clone_cleanup_error(exc)
                if provenance is not None:
                    immutable = {
                        "mission_id": checkpoint["mission_id"],
                        "binding_digest": checkpoint["binding_digest"],
                        "envelope_digest": checkpoint["input_digest"],
                        "owner_git_sha256": checkpoint["owner_git_sha256"],
                    }
                    if provenance.get("state") == "cleaned":
                        immutable.pop("owner_git_sha256")
                    if any(
                        provenance.get(key) != value for key, value in immutable.items()
                    ):
                        raise ProjectAutopilotContractError(
                            "cross_store_binding_mismatch"
                        )
                provenance_state = (
                    None if provenance is None else str(provenance.get("state"))
                )
                allowed_cross_store: dict[str, set[str | None]] = {
                    "bound": {None, "intent", "prepared"},
                    "clone_preparing": {
                        None,
                        "intent",
                        "prepared",
                    },
                    "clone_building": {"prepared", "finalized"},
                    "clone_ready": {"finalized"},
                    "patch_applied": {"finalized"},
                    "gates_running": {"finalized"},
                    "executable_gate_pending": {"finalized"},
                    "executable_gates_running": {"finalized"},
                    "executable_gate_terminal": {"finalized"},
                    "verified": {"finalized"},
                }
                if (
                    stage in allowed_cross_store
                    and provenance_state not in allowed_cross_store[stage]
                ):
                    raise ProjectAutopilotContractError(
                        "cross_store_state_order_invalid"
                    )
                if stage == "bound":
                    self._write_checkpoint(
                        mission_id,
                        checkpoint_payload(
                            mission_id=mission_id,
                            binding_digest=binding_digest,
                            envelope=envelope,
                            stage="clone_preparing",
                            gate_index=0,
                            gate_receipts=[],
                            state_receipt=None,
                            waiting_reason=None,
                        ),
                    )
                    stage = "clone_preparing"
                if stage == "clone_preparing":
                    try:
                        prepared = self._clone_cleanup.prepare_provenance(
                            mission_id=mission_id,
                            binding_digest=binding_digest,
                            envelope_digest=envelope.input_digest,
                            owner_root=owner,
                            clone_root=self._clone_path(mission_id),
                            owner_git_sha256=envelope.owner_git_sha256,
                            containment_handles=(
                                self._borrowed_containment_handles(mission_id)
                            ),
                        )
                    except self._clone_cleanup_errors as exc:
                        self._map_clone_cleanup_error(exc)
                    if prepared.get("state") != "prepared":
                        raise ProjectAutopilotWaiting(
                            "controlled_clone_prepare_incomplete"
                        )
                    provenance = prepared
                    self._write_checkpoint(
                        mission_id,
                        checkpoint_payload(
                            mission_id=mission_id,
                            binding_digest=binding_digest,
                            envelope=envelope,
                            stage="clone_building",
                            gate_index=0,
                            gate_receipts=[],
                            state_receipt=None,
                            waiting_reason=None,
                        ),
                    )
                    stage = "clone_building"
                clone_session = self._clone_cleanup.clone_session_guard(
                    mission_id=mission_id,
                    binding_digest=binding_digest,
                    envelope_digest=envelope.input_digest,
                    owner_root=owner,
                    clone_root=self._clone_path(mission_id),
                    owner_git_sha256=envelope.owner_git_sha256,
                    containment_handles=(
                        self._borrowed_containment_handles(mission_id)
                    ),
                )
                guarded_clone = clone_session.__enter__()
                clone_session_entered = True
                if guarded_clone != self._clone_path(mission_id):
                    raise ProjectAutopilotContractError(
                        "controlled_clone_guard_path_invalid"
                    )
                clone_record = provenance.get("clone_root")
                if not isinstance(clone_record, dict) or not isinstance(
                    clone_record.get("identity"), dict
                ):
                    raise ProjectAutopilotContractError(
                        "controlled_clone_identity_invalid"
                    )
                namespace_session = self._namespace_sessions.get(mission_id)
                if namespace_session is None:
                    raise ProjectAutopilotContractError(
                        "mission_namespace_session_missing"
                    )
                operation_session = namespace_session.clone_operation(
                    clone_record["identity"]
                )
                clone_files = operation_session.__enter__()
                operation_session_entered = True
                self._clone_operations[mission_id] = clone_files
                if stage == "clone_building":
                    try:
                        provenance = self._clone_cleanup.authenticate_provenance(
                            mission_id=mission_id,
                            binding_digest=binding_digest,
                            envelope_digest=envelope.input_digest,
                            owner_root=owner,
                            clone_root=self._clone_path(mission_id),
                            owner_git_sha256=(envelope.owner_git_sha256),
                            containment_handles=(
                                self._borrowed_containment_handles(mission_id)
                            ),
                        )
                    except self._clone_cleanup_errors as exc:
                        self._map_clone_cleanup_error(exc)
                    if provenance.get("state") == "prepared":
                        self._populate_prepared_clone(
                            mission_id, owner, envelope, bounded_cancel
                        )
                        clone = self._materialize_clone(
                            mission_id,
                            owner,
                            envelope,
                            bounded_cancel,
                            allow_existing=True,
                        )
                        try:
                            provenance = self._clone_cleanup.finalize_provenance(
                                mission_id=mission_id,
                                binding_digest=binding_digest,
                                envelope_digest=(envelope.input_digest),
                                owner_root=owner,
                                clone_root=clone,
                                owner_git_sha256=(envelope.owner_git_sha256),
                                containment_handles=(
                                    self._borrowed_containment_handles(mission_id)
                                ),
                            )
                        except self._clone_cleanup_errors as exc:
                            self._map_clone_cleanup_error(exc)
                    if provenance.get("state") != "finalized":
                        raise ProjectAutopilotWaiting(
                            "controlled_clone_finalize_incomplete"
                        )
                    clone = self._materialize_clone(
                        mission_id,
                        owner,
                        envelope,
                        bounded_cancel,
                        allow_existing=True,
                    )
                    self._write_checkpoint(
                        mission_id,
                        checkpoint_payload(
                            mission_id=mission_id,
                            binding_digest=binding_digest,
                            envelope=envelope,
                            stage="clone_ready",
                            gate_index=0,
                            gate_receipts=[],
                            state_receipt=None,
                            waiting_reason=None,
                        ),
                    )
                    stage = "clone_ready"
                else:
                    try:
                        provenance = self._clone_cleanup.authenticate_provenance(
                            mission_id=mission_id,
                            binding_digest=binding_digest,
                            envelope_digest=envelope.input_digest,
                            owner_root=owner,
                            clone_root=self._clone_path(mission_id),
                            owner_git_sha256=(envelope.owner_git_sha256),
                            containment_handles=(
                                self._borrowed_containment_handles(mission_id)
                            ),
                        )
                    except self._clone_cleanup_errors as exc:
                        self._map_clone_cleanup_error(exc)
                    if provenance.get("state") != "finalized":
                        raise ProjectAutopilotContractError(
                            "controlled_clone_not_finalized"
                        )
                    clone = self._materialize_clone(
                        mission_id,
                        owner,
                        envelope,
                        bounded_cancel,
                        allow_existing=True,
                    )
            if stage == "clone_ready":
                pending_patch_journal = False
                if self._clone_cleanup is not None:
                    from core.phase11_handle_patch_v1 import (
                        JOURNAL_NAME,
                    )

                    active_namespace = self._namespace_sessions.get(mission_id)
                    if active_namespace is None:
                        raise ProjectAutopilotContractError(
                            "mission_namespace_session_missing"
                        )
                    pending_patch_journal = active_namespace.has_entry(
                        JOURNAL_NAME, directory=False
                    )
                if not pending_patch_journal:
                    pristine = self._git(
                        mission_id,
                        clone,
                        (
                            "status",
                            "--porcelain=v2",
                            "-z",
                            "--untracked-files=all",
                        ),
                        timeout=20,
                        output_limit=envelope.max_output_bytes,
                        cancel=bounded_cancel,
                    )
                    if pristine:
                        raise ProjectAutopilotWaiting(
                            "controlled_clone_not_pristine_before_apply"
                        )
                clone_files = self._clone_operations.get(mission_id)
                if self._clone_cleanup is None:
                    self._git(
                        mission_id,
                        clone,
                        (
                            "apply",
                            "--check",
                            "--whitespace=error-all",
                            "-",
                        ),
                        timeout=30,
                        output_limit=envelope.max_output_bytes,
                        cancel=bounded_cancel,
                        input_bytes=patch.encode("utf-8"),
                    )
                    self._git(
                        mission_id,
                        clone,
                        ("apply", "--whitespace=error-all", "-"),
                        timeout=30,
                        output_limit=envelope.max_output_bytes,
                        cancel=bounded_cancel,
                        input_bytes=patch.encode("utf-8"),
                    )
                else:
                    from core.phase11_handle_patch_v1 import (
                        HandlePatchEngineV1,
                    )

                    namespace_session = self._namespace_sessions.get(mission_id)
                    if clone_files is None or namespace_session is None:
                        raise ProjectAutopilotContractError(
                            "controlled_clone_operation_missing"
                        )
                    try:
                        HandlePatchEngineV1(
                            signing_key=self._key,
                            mission=namespace_session,
                            clone=clone_files,
                        ).apply(patch)
                    except self._clone_cleanup_errors as exc:
                        self._map_clone_cleanup_error(exc)
                state_receipt = self._state_receipt(
                    mission_id,
                    clone,
                    envelope,
                    bounded_cancel,
                    clone_files,
                )
                if not state_receipt["dirty_files"]:
                    raise ProjectAutopilotWaiting("patch_produced_no_change")
                self._write_checkpoint(
                    mission_id,
                    checkpoint_payload(
                        mission_id=mission_id,
                        binding_digest=binding_digest,
                        envelope=envelope,
                        stage="patch_applied",
                        gate_index=0,
                        gate_receipts=[],
                        state_receipt=state_receipt,
                        waiting_reason=None,
                    ),
                )
                stage = "patch_applied"
            if stage in {"patch_applied", "gates_running"}:
                for index in range(gate_index, len(envelope.gates)):
                    if bounded_cancel():
                        raise ProjectAutopilotWaiting("kill_requested")
                    self._assert_owner_immutable(mission_id, envelope, bounded_cancel)
                    receipt = self._static_gate(
                        clone,
                        patch,
                        envelope,
                        envelope.gates[index],
                        bounded_cancel,
                        self._clone_operations.get(mission_id),
                    )
                    receipt["index"] = index
                    unsigned = {
                        key: value
                        for key, value in receipt.items()
                        if key != "signature"
                    }
                    receipt["signature"] = self._receipt_signature(unsigned)
                    gate_receipts.append(receipt)
                    gate_index = index + 1
                    stage = "gates_running"
                    self._write_checkpoint(
                        mission_id,
                        checkpoint_payload(
                            mission_id=mission_id,
                            binding_digest=binding_digest,
                            envelope=envelope,
                            stage=stage,
                            gate_index=gate_index,
                            gate_receipts=gate_receipts,
                            state_receipt=state_receipt,
                            waiting_reason=None,
                        ),
                    )
            self._assert_owner_immutable(mission_id, envelope, bounded_cancel)
            verified = IndependentAutopilotVerifierV1(self)._verify_locked(
                mission_id=mission_id,
                binding_digest=binding_digest,
                envelope=envelope,
                cancel=bounded_cancel,
            )
            owner_observed_at_ns = time.time_ns()
            if bounded_cancel():
                raise ProjectAutopilotWaiting("kill_requested")
            if self._clone_cleanup is not None:
                try:
                    final_provenance = self._clone_cleanup.authenticate_provenance(
                        mission_id=mission_id,
                        binding_digest=binding_digest,
                        envelope_digest=envelope.input_digest,
                        owner_root=owner,
                        clone_root=clone,
                        owner_git_sha256=(envelope.owner_git_sha256),
                        containment_handles=(
                            self._borrowed_containment_handles(mission_id)
                        ),
                    )
                except self._clone_cleanup_errors as exc:
                    self._map_clone_cleanup_error(exc)
                if final_provenance.get("state") != "finalized":
                    raise ProjectAutopilotContractError(
                        "controlled_clone_final_reauth_failed"
                    )
            if normalized_executable_plan is not None:
                from core.phase11_executable_sandbox_v1 import (
                    ExecutableSandboxError,
                    ExecutableSandboxRequestV1,
                    SandboxContractError,
                )

                sandbox = self._executable_sandbox(
                    clone=clone,
                    plan=normalized_executable_plan,
                )

                class _BoundedCancelSignal:
                    def is_set(self) -> bool:
                        return bounded_cancel()

                for index in range(
                    executable_gate_index,
                    len(normalized_executable_plan.gates),
                ):
                    if bounded_cancel():
                        raise ProjectAutopilotWaiting("kill_requested")
                    remaining = deadline - time.monotonic()
                    gate = normalized_executable_plan.gates[index]
                    if remaining < gate.timeout_seconds:
                        bounded_cancel()
                        raise ProjectAutopilotWaiting("mission_time_budget_exhausted")
                    self._assert_owner_immutable(mission_id, envelope, bounded_cancel)
                    execution_id = self._execution_id(
                        mission_id=mission_id,
                        binding_digest=binding_digest,
                        primary_input_digest=envelope.input_digest,
                        plan=normalized_executable_plan,
                        index=index,
                    )
                    request = ExecutableSandboxRequestV1(
                        mission_id=mission_id,
                        execution_id=execution_id,
                        clone_root=str(clone.resolve(strict=True)),
                        image_id=normalized_executable_plan.image_id,
                        argv=gate.argv,
                        timeout_seconds=gate.timeout_seconds,
                        max_output_bytes=gate.max_output_bytes,
                    )
                    executable_gate_intent = {
                        "index": index,
                        "execution_id": execution_id,
                    }
                    repository_code_execution_state = "attempted_unknown"
                    repository_code_executed = True
                    stage = "executable_gate_pending"
                    self._write_checkpoint(
                        mission_id,
                        checkpoint_payload(
                            mission_id=mission_id,
                            binding_digest=binding_digest,
                            envelope=envelope,
                            stage=stage,
                            gate_index=len(envelope.gates),
                            gate_receipts=gate_receipts,
                            state_receipt=verified,
                            waiting_reason=None,
                        ),
                    )
                    try:
                        sandbox_receipt = sandbox.execute(
                            request,
                            cancel=_BoundedCancelSignal(),
                        )
                    except SandboxContractError as exc:
                        if str(exc) in {
                            "sandbox_clone_manifest_cancelled",
                            "sandbox_clone_manifest_timeout",
                        }:
                            executable_gate_intent = None
                            repository_code_execution_state = (
                                "executed_receipt"
                                if executable_gate_receipts
                                else "not_started"
                            )
                            repository_code_executed = bool(executable_gate_receipts)
                            stage = (
                                "executable_gates_running"
                                if executable_gate_receipts
                                else "gates_running"
                            )
                            raise ProjectAutopilotWaiting(
                                "kill_requested"
                                if str(exc) == "sandbox_clone_manifest_cancelled"
                                else "mission_time_budget_exhausted"
                            ) from exc
                        raise ProjectAutopilotWaiting(
                            "executable_gate_reconciliation_required"
                        ) from exc
                    except ExecutableSandboxError as exc:
                        raise ProjectAutopilotWaiting(
                            "executable_gate_reconciliation_required"
                        ) from exc
                    wrapped = self._executable_receipt(
                        mission_id=mission_id,
                        binding_digest=binding_digest,
                        primary_input_digest=envelope.input_digest,
                        plan=normalized_executable_plan,
                        gate=gate,
                        index=index,
                        sandbox_receipt=sandbox_receipt,
                    )
                    executable_gate_intent = None
                    repository_code_execution_state = "executed_receipt"
                    repository_code_executed = True
                    if wrapped["verdict"] != "PASS":
                        reason = {
                            "CANCELLED": "kill_requested",
                            "TIMEOUT": "executable_gate_timeout",
                            "OUTPUT_LIMIT": "executable_gate_output_limit",
                            "FAIL": "executable_gate_failed",
                        }.get(
                            str(wrapped["verdict"]),
                            "executable_gate_failed",
                        )
                        executable_terminal_outcome = {
                            "receipt": wrapped,
                            "reason": reason,
                        }
                        stage = "executable_gate_terminal"
                        self._write_checkpoint(
                            mission_id,
                            checkpoint_payload(
                                mission_id=mission_id,
                                binding_digest=binding_digest,
                                envelope=envelope,
                                stage=stage,
                                gate_index=len(envelope.gates),
                                gate_receipts=gate_receipts,
                                state_receipt=verified,
                                waiting_reason=reason,
                            ),
                        )
                        raise ProjectAutopilotWaiting(reason)
                    executable_gate_receipts.append(wrapped)
                    executable_gate_index = index + 1
                    stage = "executable_gates_running"
                    self._write_checkpoint(
                        mission_id,
                        checkpoint_payload(
                            mission_id=mission_id,
                            binding_digest=binding_digest,
                            envelope=envelope,
                            stage=stage,
                            gate_index=len(envelope.gates),
                            gate_receipts=gate_receipts,
                            state_receipt=verified,
                            waiting_reason=None,
                        ),
                    )
                IndependentAutopilotVerifierV1(self)._verify_executable_locked(
                    mission_id=mission_id,
                    binding_digest=binding_digest,
                    primary_input_digest=envelope.input_digest,
                    plan=normalized_executable_plan,
                )
                verified = IndependentAutopilotVerifierV1(self)._verify_locked(
                    mission_id=mission_id,
                    binding_digest=binding_digest,
                    envelope=envelope,
                    cancel=bounded_cancel,
                )
                self._assert_owner_immutable(mission_id, envelope, bounded_cancel)
                if self._clone_cleanup is not None:
                    try:
                        post_execution_provenance = (
                            self._clone_cleanup.authenticate_provenance(
                                mission_id=mission_id,
                                binding_digest=binding_digest,
                                envelope_digest=envelope.input_digest,
                                owner_root=owner,
                                clone_root=clone,
                                owner_git_sha256=envelope.owner_git_sha256,
                                containment_handles=(
                                    self._borrowed_containment_handles(mission_id)
                                ),
                            )
                        )
                    except self._clone_cleanup_errors as exc:
                        self._map_clone_cleanup_error(exc)
                    if post_execution_provenance.get("state") != "finalized":
                        raise ProjectAutopilotContractError(
                            "controlled_clone_post_execution_reauth_failed"
                        )
                owner_observed_at_ns = time.time_ns()
            self._write_checkpoint(
                mission_id,
                checkpoint_payload(
                    mission_id=mission_id,
                    binding_digest=binding_digest,
                    envelope=envelope,
                    stage="verified",
                    gate_index=len(envelope.gates),
                    gate_receipts=gate_receipts,
                    state_receipt=verified,
                    waiting_reason=None,
                ),
            )
            if bounded_cancel():
                raise ProjectAutopilotWaiting("kill_requested")
            return {
                "status": "succeeded",
                "data": {
                    "checkpoint_stage": "verified",
                    "base_head_prefix": envelope.base_head[:12],
                    "patch_digest_prefix": envelope.patch_sha256[:12],
                    "owner_git_digest_prefix": envelope.owner_git_sha256[:12],
                    "owner_verification_observed_at_ns": owner_observed_at_ns,
                    "state_digest_prefix": str(verified["state_sha256"])[:12],
                    "static_gates_passed": len(gate_receipts),
                    **(
                        {"executable_gates_passed": len(executable_gate_receipts)}
                        if normalized_executable_plan is not None
                        else {}
                    ),
                    "repository_code_executed": (
                        normalized_executable_plan is not None
                    ),
                    **(
                        {
                            "repository_code_execution_state": (
                                repository_code_execution_state
                            )
                        }
                        if normalized_executable_plan is not None
                        else {}
                    ),
                    "controlled_clone_retained": True,
                },
                "evidence": [
                    {"type": "local_receipt", "value": str(verified["state_sha256"])}
                ],
                "postconditions": [
                    {
                        "name": (
                            "owner_clean_and_bounded_dot_git_digest_matched"
                            "_at_verification"
                        ),
                        "satisfied": True,
                    },
                    {
                        "name": "patch_applied_only_in_standalone_clone",
                        "satisfied": True,
                    },
                    {
                        "name": (
                            "repository_authored_code_executed_in_sandbox"
                            if normalized_executable_plan is not None
                            else "repository_authored_code_not_executed"
                        ),
                        "satisfied": True,
                    },
                    {"name": "trusted_static_gates_passed", "satisfied": True},
                    {"name": "independent_state_receipt_verified", "satisfied": True},
                ],
                "waiting_for": None,
            }
        except ProjectAutopilotWaiting as exc:
            reason = "mission_time_budget_exhausted" if time_exhausted else exc.reason
            self._write_checkpoint(
                mission_id,
                checkpoint_payload(
                    mission_id=mission_id,
                    binding_digest=binding_digest,
                    envelope=envelope,
                    stage=stage,
                    gate_index=gate_index,
                    gate_receipts=gate_receipts,
                    state_receipt=state_receipt,
                    waiting_reason=reason,
                ),
            )
            return {
                "status": "waiting",
                "data": {
                    "checkpoint_stage": stage,
                    "controlled_clone_retained": self._clone_path(mission_id).exists(),
                    "repository_code_executed": repository_code_executed,
                    **(
                        {
                            "repository_code_execution_state": (
                                repository_code_execution_state
                            )
                        }
                        if normalized_executable_plan is not None
                        else {}
                    ),
                },
                "evidence": [],
                "postconditions": [],
                "waiting_for": reason,
            }
        finally:
            try:
                self._scrub_mission_artifact(mission_id, "patch.diff", MAX_PATCH_BYTES)
            finally:
                try:
                    if operation_session_entered:
                        self._clone_operations.pop(mission_id, None)
                        assert operation_session is not None
                        operation_session.__exit__(*sys.exc_info())
                finally:
                    if clone_session_entered:
                        assert clone_session is not None
                        clone_session.__exit__(*sys.exc_info())

    def cleanup(
        self,
        **arguments: Any,
    ) -> bool:
        mission_id = str(arguments.get("mission_id", ""))
        with self._mission_lock(mission_id):
            with self._mission_process_lock(mission_id):
                return self._cleanup_locked(**arguments)

    def _cleanup_locked(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        owner_root: str | None = None,
        envelope: AutopilotEnvelopeV1 | None = None,
    ) -> bool:
        checkpoint = self._read_checkpoint_locked(mission_id)
        if checkpoint is None or checkpoint.get("binding_digest") != binding_digest:
            raise ProjectAutopilotContractError("cleanup_binding_invalid")
        clone = self._clone_path(mission_id)
        if checkpoint.get("clone") != str(clone):
            raise ProjectAutopilotContractError("cleanup_path_invalid")
        expected_parent = self._mission_dir(mission_id)
        if clone.parent != expected_parent:
            raise ProjectAutopilotContractError("cleanup_path_invalid")
        if self._clone_cleanup is not None:
            if envelope is None:
                raise ProjectAutopilotContractError("cleanup_envelope_required")
            if (
                checkpoint.get("input_digest") != envelope.input_digest
                or checkpoint.get("base_head") != envelope.base_head
                or checkpoint.get("owner_git_sha256") != envelope.owner_git_sha256
            ):
                raise ProjectAutopilotContractError("cleanup_envelope_binding_drift")
            if self._terminal_state_resolver is None:
                raise ProjectAutopilotContractError(
                    "cleanup_terminal_state_resolver_unavailable"
                )
            terminal_state = self._terminal_state_resolver(mission_id)
            if terminal_state not in {
                "succeeded",
                "failed",
                "cancelled",
            }:
                raise ProjectAutopilotWaiting("cleanup_terminal_gate_incomplete")
            owner = envelope.root
            with self._process_lock:
                if mission_id in self._active:
                    raise ProjectAutopilotWaiting("cleanup_mission_active")
            before = self.capture_owner_git_state(owner)
            self._assert_owner_immutable(mission_id, envelope, lambda: False)
            try:
                provenance = self._clone_cleanup.inspect_provenance(
                    mission_id=mission_id,
                    containment_handles=(
                        self._borrowed_containment_handles(mission_id)
                    ),
                )
            except self._clone_cleanup_errors as exc:
                self._map_clone_cleanup_error(exc)
            if provenance is not None:
                immutable = {
                    "mission_id": checkpoint["mission_id"],
                    "binding_digest": checkpoint["binding_digest"],
                    "envelope_digest": checkpoint["input_digest"],
                    "owner_git_sha256": checkpoint["owner_git_sha256"],
                }
                if provenance.get("state") == "cleaned":
                    immutable.pop("owner_git_sha256")
                if any(
                    provenance.get(key) != value for key, value in immutable.items()
                ):
                    raise ProjectAutopilotContractError("cross_store_binding_mismatch")
            provenance_state = (
                None if provenance is None else str(provenance.get("state"))
            )
            cleanup_allowed: dict[str, set[str | None]] = {
                "bound": {None, "intent", "prepared"},
                "clone_preparing": {None, "intent", "prepared"},
                "clone_building": {"prepared", "finalized"},
                "clone_ready": {"prepared", "finalized"},
                "patch_applied": {"finalized"},
                "gates_running": {"finalized"},
                "executable_gate_pending": {"finalized"},
                "executable_gates_running": {"finalized"},
                "executable_gate_terminal": {"finalized"},
                "verified": {"finalized"},
                "cleanup_planned": {"prepared", "finalized"},
                "deleting": {"prepared", "finalized"},
                "finalizing": {"prepared", "finalized"},
                "root_removed": {"prepared", "finalized"},
                "cleaned": {"cleaned"},
            }
            if (
                checkpoint.get("stage") not in cleanup_allowed
                or provenance_state not in cleanup_allowed[str(checkpoint["stage"])]
            ):
                raise ProjectAutopilotContractError("cross_store_state_order_invalid")
            terminal_state = self._terminal_state_resolver(mission_id)
            if terminal_state not in {
                "succeeded",
                "failed",
                "cancelled",
            }:
                raise ProjectAutopilotWaiting("cleanup_terminal_gate_incomplete")
            if provenance is None:
                session = self._namespace_sessions.get(mission_id)
                if session is None or session.has_entry("clone", directory=True):
                    raise ProjectAutopilotContractError(
                        "cross_store_unbound_clone_refused"
                    )
                self._scrub_mission_artifact(mission_id, "patch.diff", MAX_PATCH_BYTES)
                self._scrub_mission_artifact(
                    mission_id,
                    "source.bundle",
                    MAX_OWNER_GIT_BYTES,
                )
                payload = {
                    key: value
                    for key, value in checkpoint.items()
                    if key
                    not in {
                        "checkpoint_digest",
                        "signature",
                        "sequence",
                    }
                }
                payload["stage"] = "cleaned"
                payload["waiting_reason"] = None
                payload["cleanup_manifest_digest"] = None
                self._write_checkpoint(mission_id, payload)
                after = self.capture_owner_git_state(owner)
                if not hmac.compare_digest(before, after):
                    raise ProjectAutopilotContractError(
                        "owner_git_metadata_changed_on_cleanup"
                    )
                return False
            if provenance_state == "intent":
                try:
                    provenance = self._clone_cleanup.prepare_provenance(
                        mission_id=mission_id,
                        binding_digest=str(checkpoint["binding_digest"]),
                        envelope_digest=str(checkpoint["input_digest"]),
                        owner_root=owner,
                        clone_root=clone,
                        owner_git_sha256=str(checkpoint["owner_git_sha256"]),
                        containment_handles=(
                            self._borrowed_containment_handles(mission_id)
                        ),
                    )
                except self._clone_cleanup_errors as exc:
                    self._map_clone_cleanup_error(exc)
                if provenance.get("state") != "prepared":
                    raise ProjectAutopilotContractError(
                        "cross_store_intent_recovery_incomplete"
                    )
            self._scrub_mission_artifact(mission_id, "patch.diff", MAX_PATCH_BYTES)
            self._scrub_mission_artifact(
                mission_id, "source.bundle", MAX_OWNER_GIT_BYTES
            )

            def owner_validator() -> None:
                self._assert_owner_immutable(mission_id, envelope, lambda: False)

            def checkpoint_writer(stage: str, manifest_digest: str | None) -> None:
                latest = self._read_checkpoint_locked(mission_id)
                if (
                    latest is None
                    or latest.get("mission_id") != mission_id
                    or latest.get("binding_digest") != binding_digest
                    or latest.get("input_digest") != envelope.input_digest
                    or latest.get("base_head") != envelope.base_head
                    or latest.get("owner_git_sha256") != envelope.owner_git_sha256
                    or latest.get("clone") != str(clone)
                ):
                    raise ProjectAutopilotContractError(
                        "cleanup_checkpoint_binding_drift"
                    )
                payload = {
                    key: value
                    for key, value in latest.items()
                    if key
                    not in {
                        "checkpoint_digest",
                        "signature",
                        "sequence",
                    }
                }
                payload["stage"] = stage
                payload["waiting_reason"] = None
                payload["cleanup_manifest_digest"] = manifest_digest
                self._write_checkpoint(mission_id, payload)

            with self._process_lock:
                if mission_id in self._active:
                    raise ProjectAutopilotWaiting("cleanup_mission_active")
                terminal_state = self._terminal_state_resolver(mission_id)
                if terminal_state not in {
                    "succeeded",
                    "failed",
                    "cancelled",
                }:
                    raise ProjectAutopilotWaiting("cleanup_terminal_gate_incomplete")
                try:
                    cleanup_checkpoint = checkpoint
                    if checkpoint.get("stage") in {
                        "executable_gate_pending",
                        "executable_gates_running",
                        "executable_gate_terminal",
                    }:
                        cleanup_checkpoint = {
                            **checkpoint,
                            "stage": "gates_running",
                        }
                    cleaned = self._clone_cleanup.cleanup(
                        mission_id=mission_id,
                        binding_digest=binding_digest,
                        envelope_digest=envelope.input_digest,
                        owner_root=owner,
                        clone_root=clone,
                        owner_git_sha256=envelope.owner_git_sha256,
                        terminal_state=terminal_state,
                        checkpoint=cleanup_checkpoint,
                        owner_validator=owner_validator,
                        checkpoint_writer=checkpoint_writer,
                        containment_handles=(
                            self._borrowed_containment_handles(mission_id)
                        ),
                    )
                except self._clone_cleanup_errors as exc:
                    self._map_clone_cleanup_error(exc)
            owner_validator()
            after = self.capture_owner_git_state(owner)
            if not hmac.compare_digest(before, after):
                raise ProjectAutopilotContractError(
                    "owner_git_metadata_changed_on_cleanup"
                )
            return bool(cleaned)
        if owner_root is None:
            raise ProjectAutopilotContractError("cleanup_owner_root_required")
        clone_present = clone.exists() or clone.is_symlink()
        before = self.capture_owner_git_state(owner_root)
        if clone_present:
            _reject_linked_ancestors(clone)
        self._scrub_mission_artifact(mission_id, "patch.diff", MAX_PATCH_BYTES)
        self._scrub_mission_artifact(mission_id, "source.bundle", MAX_OWNER_GIT_BYTES)
        after = self.capture_owner_git_state(owner_root)
        if not hmac.compare_digest(before, after):
            raise ProjectAutopilotContractError("owner_git_metadata_changed_on_cleanup")
        payload = {
            key: value
            for key, value in checkpoint.items()
            if key not in {"checkpoint_digest", "signature", "sequence"}
        }
        reason = "controlled_clone_cleanup_requires_handle_safe_deleter"
        payload["stage"] = "cleanup_refused"
        payload["waiting_reason"] = reason
        self._write_checkpoint(mission_id, payload)
        raise ProjectAutopilotWaiting(reason)


class IndependentAutopilotVerifierV1:
    """Authenticate receipts and recompute final clone and owner state."""

    def __init__(self, executor: ProjectAutopilotV1) -> None:
        self.executor = executor

    def verify(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        envelope: AutopilotEnvelopeV1,
        cancel: CancelCheck,
    ) -> dict[str, Any]:
        with self.executor._mission_lock(mission_id):
            with self.executor._mission_process_lock(mission_id):
                return self._verify_locked(
                    mission_id=mission_id,
                    binding_digest=binding_digest,
                    envelope=envelope,
                    cancel=cancel,
                )

    def _verify_executable_locked(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        primary_input_digest: str,
        plan: ExecutableGatePlanV1,
    ) -> tuple[Mapping[str, Any], ...]:
        """Authenticate the complete executable-gate checkpoint projection."""
        plan.verify(self.executor._approved_executable_image_ids)
        checkpoint = self.executor._read_checkpoint_locked(mission_id)
        if checkpoint is None:
            raise ProjectAutopilotWaiting("checkpoint_missing")
        raw_index = checkpoint.get("executable_gate_index")
        receipts = checkpoint.get("executable_gate_receipts")
        if (
            checkpoint.get("stage") not in {"executable_gates_running", "verified"}
            or checkpoint.get("executable_plan_digest") != plan.plan_digest
            or checkpoint.get("executable_gate_intent") is not None
            or checkpoint.get("executable_terminal_outcome") is not None
            or checkpoint.get("repository_code_execution_state") != "executed_receipt"
            or isinstance(raw_index, bool)
            or not isinstance(raw_index, int)
            or raw_index != len(plan.gates)
            or not isinstance(receipts, list)
            or len(receipts) != len(plan.gates)
        ):
            raise ProjectAutopilotContractError("executable_gate_receipts_incomplete")
        verified: list[Mapping[str, Any]] = []
        execution_ids: set[str] = set()
        for index, receipt in enumerate(receipts):
            self.executor._verify_executable_receipt(
                mission_id=mission_id,
                binding_digest=binding_digest,
                primary_input_digest=primary_input_digest,
                plan=plan,
                index=index,
                receipt=receipt,
            )
            assert isinstance(receipt, Mapping)
            execution_id = str(receipt.get("execution_id"))
            if execution_id in execution_ids:
                raise ProjectAutopilotContractError("executable_gate_receipt_replay")
            execution_ids.add(execution_id)
            verified.append(receipt)
        return tuple(verified)

    def _verify_locked(
        self,
        *,
        mission_id: str,
        binding_digest: str,
        envelope: AutopilotEnvelopeV1,
        cancel: CancelCheck,
    ) -> dict[str, Any]:
        checkpoint = self.executor._read_checkpoint_locked(mission_id)
        if checkpoint is None:
            raise ProjectAutopilotWaiting("checkpoint_missing")
        if (
            checkpoint.get("binding_digest") != binding_digest
            or checkpoint.get("input_digest") != envelope.input_digest
        ):
            raise ProjectAutopilotContractError("verifier_binding_drift")
        receipts = checkpoint.get("gate_receipts")
        if not isinstance(receipts, list) or len(receipts) != len(envelope.gates):
            raise ProjectAutopilotWaiting("static_gate_receipts_incomplete")
        for index, (receipt, gate) in enumerate(zip(receipts, envelope.gates)):
            if not isinstance(receipt, Mapping):
                raise ProjectAutopilotContractError("static_gate_receipt_invalid")
            unsigned = {
                key: value for key, value in receipt.items() if key != "signature"
            }
            expected = self.executor._receipt_signature(unsigned)
            if (
                receipt.get("index") != index
                or receipt.get("argv_sha256") != _digest(list(gate.argv))
                or receipt.get("verdict") != "PASS"
                or receipt.get("executor") != "trusted_onyx_static_v1"
                or receipt.get("repository_code_executed") is not False
                or not hmac.compare_digest(str(receipt.get("signature", "")), expected)
            ):
                raise ProjectAutopilotContractError("static_gate_receipt_invalid")
        self.executor._assert_owner_immutable(mission_id, envelope, cancel)
        clone = self.executor._clone_path(mission_id)
        if not clone.is_dir():
            raise ProjectAutopilotWaiting("controlled_clone_missing")
        observed = self.executor._state_receipt(
            mission_id,
            clone,
            envelope,
            cancel,
            self.executor._clone_operations.get(mission_id),
        )
        cached = checkpoint.get("state_receipt")
        if not isinstance(cached, Mapping) or cached.get(
            "state_sha256"
        ) != observed.get("state_sha256"):
            raise ProjectAutopilotWaiting("controlled_clone_drift")
        return observed


__all__ = [
    "AutopilotEnvelopeV1",
    "ExecutableGateEnvelopeV1",
    "ExecutableGatePlanV1",
    "ExecutableGateSpecV1",
    "FEATURE_FLAG",
    "IndependentAutopilotVerifierV1",
    "MISSION_TYPE",
    "ProjectAutopilotContractError",
    "ProjectAutopilotError",
    "ProjectAutopilotV1",
    "ProjectAutopilotWaiting",
    "TOOL_NAME",
    "feature_enabled",
]
def derive_executable_sandbox_subkey_v1(signing_key: bytes) -> bytes:
    """Derive the executable receipt key without exposing the host key."""

    if not isinstance(signing_key, bytes) or len(signing_key) < 16:
        raise ValueError("autopilot signing key must contain at least 16 bytes")
    return hmac.new(
        signing_key,
        _SANDBOX_SUBKEY_DOMAIN,
        hashlib.sha256,
    ).digest()
