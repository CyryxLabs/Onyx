"""Run the phase-only, fail-closed Capability Nexus V32 verifier."""

from __future__ import annotations

import ctypes
from builtins import BaseExceptionGroup
from ctypes import wintypes
from dataclasses import dataclass
import math
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from types import MappingProxyType


PROJECT = Path(__file__).resolve().parents[1]
TESTS = "tests/test_capability_nexus_v32.py"
WORKER = "scripts/verify_phase5_capability_nexus_v32_worker.py"
PRIVATE_BASE = Path(tempfile.gettempdir()) / "onyx-p53-v32-private"
SENTINEL = ".phase53-v32-private"
TOTAL_TIMEOUT_SECONDS = 300
POST_KILL_DRAIN_SECONDS = 2
MARKER = "P53_CAPABILITY_NEXUS_V32_EVIDENCE_OK"
CLEANUP_SNAPSHOT_CONTRACT = "api_read_only_snapshot"
REFLECTION_BOUNDARY_CONTRACT = "not_a_same_process_reflection_security_boundary"
_PRIVATE_CONTRACT = "Phase53CapabilityNexusPrivate.v32"
_TOKEN = re.compile(r"[0-9a-f]{64}")
_KILL_ON_JOB_CLOSE = 0x00002000
_EXTENDED_LIMIT_INFORMATION = 9
_BASIC_ACCOUNTING_INFORMATION = 1
_STILL_ACTIVE = 259
_CREATE_SUSPENDED = 0x00000004
_CREATE_NO_WINDOW = 0x08000000
_STARTF_USESTDHANDLES = 0x00000100
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_CREATE_ALWAYS = 2
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_WAIT_FAILED = 0xFFFFFFFF
_INFINITE_RESUME_FAILURE = 0xFFFFFFFF
_OUTPUT_LIMIT_BYTES = 8 * 1024 * 1024
_RETAINED_HANDLES: dict[int, tuple[object, wintypes.HANDLE, str]] = {}


class V32ParentError(RuntimeError):
    """Fail-closed parent error with an ordinary-API read-only snapshot.

    This runtime object is not a same-process reflection security boundary.
    Durable audit integrity belongs to the separately hash-bound manifests.
    After construction, ordinary assignment and deletion reject every attribute;
    attribute names must also be exact built-in strings.
    """

    __slots__ = (
        "_v32_attachment_failures",
        "_v32_cleanup_failures",
        "_v32_cleanup_overflow",
        "_v32_primary_failure",
    )

    _PROTECTED_EVIDENCE_FIELDS = frozenset(
        {
            "attachment_failures",
            "cleanup_failures",
            "cleanup_overflow",
            "primary_failure",
            "_v32_attachment_failures",
            "_v32_cleanup_failures",
            "_v32_cleanup_overflow",
            "_v32_primary_failure",
        }
    )

    def __init__(
        self,
        message: str,
        *,
        cleanup_records: tuple[CleanupFailureRecord, ...] | None = None,
        overflow_record: CleanupFailureRecord | None = None,
        primary_record: CleanupFailureRecord | None = None,
        attachment_records: tuple[CleanupFailureRecord, ...] = (),
    ) -> None:
        RuntimeError.__init__(self, message)
        if (
            (cleanup_records is not None and type(cleanup_records) is not tuple)
            or type(attachment_records) is not tuple
            or (
                cleanup_records is not None
                and any(type(item) is not CleanupFailureRecord for item in cleanup_records)
            )
            or any(type(item) is not CleanupFailureRecord for item in attachment_records)
            or (overflow_record is not None and type(overflow_record) is not CleanupFailureRecord)
            or (primary_record is not None and type(primary_record) is not CleanupFailureRecord)
        ):
            raise TypeError("V32 cleanup snapshot is not canonical")
        object.__setattr__(
            self,
            "_v32_cleanup_failures",
            None
            if cleanup_records is None
            else tuple(self._read_only_record(item) for item in cleanup_records),
        )
        object.__setattr__(
            self,
            "_v32_cleanup_overflow",
            None if overflow_record is None else self._read_only_record(overflow_record),
        )
        object.__setattr__(
            self,
            "_v32_primary_failure",
            None if primary_record is None else self._read_only_record(primary_record),
        )
        object.__setattr__(
            self,
            "_v32_attachment_failures",
            tuple(self._read_only_record(item) for item in attachment_records),
        )

    @staticmethod
    def _read_only_record(record: CleanupFailureRecord) -> MappingProxyType:
        return MappingProxyType(
            {
                "operation": record.operation,
                "type": record.exception_type,
                "message": record.message,
            }
        )

    def _trusted_cleanup_payload(self) -> tuple[dict[str, str], ...] | None:
        records = object.__getattribute__(self, "_v32_cleanup_failures")
        if records is None:
            return None
        return tuple(
            {
                "operation": item["operation"],
                "type": item["type"],
                "message": item["message"],
            }
            for item in records
        )

    @property
    def cleanup_failures(self):
        value = object.__getattribute__(self, "_v32_cleanup_failures")
        if value is None:
            raise AttributeError("cleanup_failures")
        return value

    @property
    def cleanup_overflow(self):
        value = object.__getattribute__(self, "_v32_cleanup_overflow")
        if value is None:
            raise AttributeError("cleanup_overflow")
        return value

    @property
    def primary_failure(self):
        return object.__getattribute__(self, "_v32_primary_failure")

    @property
    def attachment_failures(self):
        return object.__getattribute__(self, "_v32_attachment_failures")

    def __setattr__(self, name: str, value: object) -> None:
        if type(name) is not str:
            raise TypeError("V32 attribute name must be exact built-in str")
        raise AttributeError("V32 parent error is API read-only after construction")

    def __delattr__(self, name: str) -> None:
        if type(name) is not str:
            raise TypeError("V32 attribute name must be exact built-in str")
        raise AttributeError("V32 parent error is API read-only after construction")


@dataclass(frozen=True)
class PhaseResult:
    returncode: int
    stdout: str
    stderr: str


class _JobBasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
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
        (name, ctypes.c_uint64)
        for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )
    ]


class _JobExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimit),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JobBasicAccounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _StartupInfoW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_ubyte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _kernel32():
    if os.name != "nt":
        raise V32ParentError("Windows Job APIs requested on a non-Windows host")
    if ctypes.sizeof(wintypes.HANDLE) != ctypes.sizeof(ctypes.c_void_p):
        raise V32ParentError("Windows HANDLE width does not match pointer width")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    api.SetInformationJobObject.restype = wintypes.BOOL
    api.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    api.AssignProcessToJobObject.restype = wintypes.BOOL
    api.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    api.TerminateJobObject.restype = wintypes.BOOL
    api.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    )
    api.QueryInformationJobObject.restype = wintypes.BOOL
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    api.OpenProcess.restype = wintypes.HANDLE
    api.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    api.GetExitCodeProcess.restype = wintypes.BOOL
    api.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_SecurityAttributes),
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    api.CreateFileW.restype = wintypes.HANDLE
    api.CreateProcessW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(_StartupInfoW),
        ctypes.POINTER(_ProcessInformation),
    )
    api.CreateProcessW.restype = wintypes.BOOL
    api.ResumeThread.argtypes = (wintypes.HANDLE,)
    api.ResumeThread.restype = wintypes.DWORD
    api.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    api.WaitForSingleObject.restype = wintypes.DWORD
    api.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
    api.TerminateProcess.restype = wintypes.BOOL
    return api


def _validated_handle(raw: object) -> wintypes.HANDLE:
    value = raw.value if isinstance(raw, ctypes.c_void_p) else raw
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value >= 1 << (ctypes.sizeof(ctypes.c_void_p) * 8)
    ):
        raise V32ParentError("Windows handle is invalid or truncated")
    return wintypes.HANDLE(value)


def _handle_value(handle: wintypes.HANDLE) -> int:
    value = handle.value
    if not isinstance(value, int) or value <= 0:
        raise V32ParentError("Windows handle ownership record is invalid")
    return value


def _win_failure(operation: str) -> V32ParentError:
    return V32ParentError(
        f"{operation} failed with Windows error {ctypes.get_last_error()}"
    )


def _checked_close(api: object, handle: wintypes.HANDLE, owner: str) -> None:
    value = _handle_value(handle)
    if not api.CloseHandle(handle):
        _RETAINED_HANDLES[value] = (api, handle, owner)
        raise _win_failure(f"CloseHandle({owner})")
    _RETAINED_HANDLES.pop(value, None)


def _cleanup_retained_handles() -> None:
    failures = []
    for value, (api, handle, owner) in tuple(_RETAINED_HANDLES.items()):
        if api.CloseHandle(handle):
            _RETAINED_HANDLES.pop(value, None)
        else:
            failures.append(owner)
    if failures:
        raise V32ParentError(
            "retained Windows handle cleanup failed: " + ",".join(sorted(failures))
        )


class _WindowsJob:
    def __init__(self):
        self.api = _kernel32()
        raw = self.api.CreateJobObjectW(None, None)
        if not raw:
            raise _win_failure("CreateJobObjectW")
        self.handle = _validated_handle(raw)
        limits = _JobExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(
            self.handle,
            _EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            failure = _win_failure("SetInformationJobObject")
            try:
                self.close()
            except V32ParentError as close_failure:
                raise V32ParentError(
                    f"{failure}; CloseHandle(Job) also failed and ownership is retained"
                ) from close_failure
            raise failure

    def assign(self, process: subprocess.Popen[str]) -> None:
        process_handle = _validated_handle(process._handle)
        self.assign_handle(process_handle)

    def assign_handle(self, process_handle: wintypes.HANDLE) -> None:
        if not self.api.AssignProcessToJobObject(self.handle, process_handle):
            raise _win_failure("AssignProcessToJobObject")

    def terminate(self) -> None:
        if self.handle and not self.api.TerminateJobObject(self.handle, 1):
            raise _win_failure("TerminateJobObject")

    def active(self) -> int:
        accounting = _JobBasicAccounting()
        if not self.api.QueryInformationJobObject(
            self.handle,
            _BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(accounting),
            ctypes.sizeof(accounting),
            None,
        ):
            raise _win_failure("QueryInformationJobObject")
        return int(accounting.ActiveProcesses)

    def close(self) -> None:
        handle = getattr(self, "handle", None)
        if handle:
            _checked_close(self.api, handle, "Job")
            self.handle = wintypes.HANDLE()


def _pid_exists(pid: int) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        api = _kernel32()
        raw = api.OpenProcess(0x1000, False, pid)
        if not raw:
            return False
        handle = _validated_handle(raw)
        code = wintypes.DWORD()
        result: bool | None = None
        failure: BaseException | None = None
        try:
            if not api.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise _win_failure("GetExitCodeProcess")
            result = code.value == _STILL_ACTIVE
        except BaseException as exc:
            failure = exc
        try:
            _checked_close(api, handle, "Process")
        except BaseException as close_failure:
            if failure is not None:
                raise close_failure from failure
            raise
        if failure is not None:
            raise failure
        return bool(result)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _drain(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=POST_KILL_DRAIN_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate(timeout=POST_KILL_DRAIN_SECONDS)
    return stdout or "", stderr or ""


def _wait_job_empty(job: _WindowsJob, label: str) -> None:
    deadline = time.monotonic() + POST_KILL_DRAIN_SECONDS
    while job.active() and time.monotonic() < deadline:
        time.sleep(0.01)
    if job.active():
        raise V32ParentError(f"{label} process tree survived termination")


def _assert_fixed_phase_target(relative: str) -> None:
    """Reject aliases/reparse metadata under a stable filesystem-state contract.

    Validation and CreateProcess/Popen are separate operations. This precheck is
    not an atomic concurrent-writer or TOCTOU security boundary.
    """
    pure = PurePosixPath(relative)
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or pure.is_absolute()
        or pure.as_posix() != relative
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise V32ParentError("fixed phase target path is not canonical")
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    try:
        root_info = PROJECT.lstat()
        root_resolved = PROJECT.resolve(strict=True)
    except OSError as exc:
        raise V32ParentError("fixed phase workspace root is missing") from exc
    if (
        stat.S_ISLNK(root_info.st_mode)
        or getattr(root_info, "st_file_attributes", 0) & reparse_flag
        or str(PROJECT.absolute()) != str(root_resolved)
    ):
        raise V32ParentError("fixed phase workspace root is aliased or reparsed")
    current = PROJECT
    for component in pure.parts:
        current /= component
        try:
            info = current.lstat()
            resolved = current.resolve(strict=True)
        except OSError as exc:
            raise V32ParentError("fixed phase target is missing") from exc
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & reparse_flag:
            raise V32ParentError("fixed phase target contains a reparse component")
        if resolved.name != component:
            raise V32ParentError("fixed phase target uses a case or name alias")
    try:
        current.resolve(strict=True).relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise V32ParentError("fixed phase target escapes workspace") from exc


def _phase_command(phase: str, junit: Path) -> list[str]:
    if not isinstance(phase, str):
        raise V32ParentError("phase id must be focused or worker")
    if phase == "focused":
        _assert_fixed_phase_target(TESTS)
        return [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            TESTS,
            "--disable-warnings",
            "--maxfail=1",
            f"--junitxml={junit}",
        ]
    if phase == "worker":
        _assert_fixed_phase_target(WORKER)
        return [sys.executable, WORKER, "--fresh-focused-junit", str(junit)]
    raise V32ParentError("phase id must be focused or worker")


def _create_file_handle(
    api: object, path: str, *, access: int, creation: int
) -> wintypes.HANDLE:
    security = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
    raw = api.CreateFileW(
        path,
        access,
        _FILE_SHARE_READ,
        ctypes.byref(security),
        creation,
        _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    value = raw.value if isinstance(raw, ctypes.c_void_p) else raw
    invalid = (1 << (ctypes.sizeof(ctypes.c_void_p) * 8)) - 1
    if value in {None, 0, -1, invalid}:
        raise _win_failure("CreateFileW")
    return _validated_handle(raw)


def _bounded_output(path: Path, label: str) -> str:
    size = path.stat().st_size
    if size > _OUTPUT_LIMIT_BYTES:
        raise V32ParentError(f"{label} output exceeds bounded evidence limit")
    return path.read_bytes().decode("utf-8", errors="replace")


def _windows_phase(
    phase: str,
    *,
    evidence_nonce: str,
    label: str,
    timeout: float,
    env: dict[str, str] | None,
    stdout_mode: str,
) -> PhaseResult:
    del env
    job = _WindowsJob()
    api = job.api
    directory = PRIVATE_BASE / evidence_nonce
    stdout_path = directory / f"{phase}.stdout"
    stderr_path = directory / f"{phase}.stderr"
    handles: list[tuple[wintypes.HANDLE, str]] = []
    process_info = _ProcessInformation()
    pending: BaseException | None = None
    result: PhaseResult | None = None
    resumed = False
    try:
        stdout_handle = _create_file_handle(
            api, str(stdout_path), access=_GENERIC_WRITE, creation=_CREATE_ALWAYS
        )
        handles.append((stdout_handle, "StdoutFile"))
        stderr_handle = _create_file_handle(
            api, str(stderr_path), access=_GENERIC_WRITE, creation=_CREATE_ALWAYS
        )
        handles.append((stderr_handle, "StderrFile"))
        stdin_handle = _create_file_handle(api, "NUL", access=0x80000000, creation=3)
        handles.append((stdin_handle, "StdinNull"))
        startup = _StartupInfoW()
        startup.cb = ctypes.sizeof(startup)
        startup.dwFlags = _STARTF_USESTDHANDLES
        startup.hStdInput = stdin_handle
        startup.hStdOutput = stdout_handle
        startup.hStdError = stderr_handle
        command = _phase_command(
            phase, _validated_junit_path(evidence_nonce, require_file=phase == "worker")
        )
        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(command))
        if not api.CreateProcessW(
            sys.executable,
            command_line,
            None,
            None,
            True,
            _CREATE_SUSPENDED | _CREATE_NO_WINDOW,
            None,
            str(PROJECT),
            ctypes.byref(startup),
            ctypes.byref(process_info),
        ):
            raise _win_failure("CreateProcessW")
        process_handle = _validated_handle(process_info.hProcess)
        thread_handle = _validated_handle(process_info.hThread)
        handles.extend(((thread_handle, "PrimaryThread"), (process_handle, "Process")))
        job.assign_handle(process_handle)
        if api.ResumeThread(thread_handle) == _INFINITE_RESUME_FAILURE:
            raise _win_failure("ResumeThread")
        resumed = True
        wait = api.WaitForSingleObject(
            process_handle, max(1, min(int(timeout * 1000), 0xFFFFFFFE))
        )
        if wait == _WAIT_TIMEOUT:
            raise V32ParentError(f"{label} timed out after {timeout:.3f}s")
        if wait == _WAIT_FAILED or wait != _WAIT_OBJECT_0:
            raise _win_failure("WaitForSingleObject")
        code = wintypes.DWORD()
        if not api.GetExitCodeProcess(process_handle, ctypes.byref(code)):
            raise _win_failure("GetExitCodeProcess")
        try:
            _wait_job_empty(job, label)
        except V32ParentError as exc:
            raise V32ParentError(
                f"{label} left residual descendants after normal completion"
            ) from exc
        for _ in range(3):
            handle, owner = handles.pop(0)
            _checked_close(api, handle, owner)
        stdout = (
            _bounded_output(stdout_path, f"{label} stdout")
            if stdout_mode == "pipe"
            else ""
        )
        stderr = _bounded_output(stderr_path, f"{label} stderr")
        result = PhaseResult(int(code.value), stdout, stderr)
    except BaseException as exc:
        pending = exc
    cleanup_failures: list[BaseException] = []
    if pending is not None and process_info.hProcess:
        state = api.WaitForSingleObject(process_info.hProcess, 0)
        if state == _WAIT_TIMEOUT and not api.TerminateProcess(
            process_info.hProcess, 1
        ):
            cleanup_failures.append(_win_failure("TerminateProcess"))
        elif state not in {_WAIT_TIMEOUT, _WAIT_OBJECT_0}:
            cleanup_failures.append(_win_failure("WaitForSingleObject(cleanup)"))
        try:
            job.terminate()
            _wait_job_empty(job, label)
        except BaseException as exc:
            cleanup_failures.append(exc)
    for handle, owner in reversed(handles):
        try:
            _checked_close(api, handle, owner)
        except BaseException as exc:
            cleanup_failures.append(exc)
    try:
        job.close()
    except BaseException as exc:
        cleanup_failures.append(exc)
    if cleanup_failures:
        raise cleanup_failures[0] from pending
    if pending is not None:
        raise pending
    if not resumed or result is None:
        raise V32ParentError(f"{label} suspended process was not safely completed")
    return result


def _posix_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_posix_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _wait_posix_group_empty(pgid: int, label: str) -> None:
    deadline = time.monotonic() + POST_KILL_DRAIN_SECONDS
    while _posix_group_exists(pgid) and time.monotonic() < deadline:
        time.sleep(0.01)
    if _posix_group_exists(pgid):
        raise V32ParentError(f"{label} POSIX process group survived cleanup")


@dataclass(frozen=True)
class CleanupFailureRecord:
    operation: str
    exception_type: str
    message: str


class _CleanupFailures:
    MAX_DEPTH = 16
    MAX_NODES = 128
    MAX_PAYLOAD_ITEMS = 128
    MAX_RECORDS = 128

    def __init__(self) -> None:
        self.records: list[CleanupFailureRecord] = []
        self._seen: set[CleanupFailureRecord] = set()
        self._overflow_reason: str | None = None

    @property
    def overflowed(self) -> bool:
        return self._overflow_reason is not None

    def add(self, operation: str, failure: BaseException) -> None:
        if self.overflowed:
            return
        if type(operation) is not str or not operation or len(operation) > 128:
            operation = "collector.invalid_operation"
            self._append(
                CleanupFailureRecord(
                    "collector.operation_access",
                    "onyx.cleanup.InvalidOperation",
                    "cleanup operation is not an exact bounded string",
                )
            )
        if not self._is_exception(failure):
            self._append(
                CleanupFailureRecord(
                    "collector.failure_access",
                    "onyx.cleanup.InvalidFailure",
                    "cleanup failure is not a BaseException",
                )
            )
            return
        seen: set[int] = set()
        state = {"nodes": 0, "payload_items": 0}
        self._flatten(operation, failure, seen, state, 0)

    @staticmethod
    def _is_exception(value: object) -> bool:
        try:
            return issubclass(type(value), BaseException)
        except BaseException:
            return False

    @staticmethod
    def _safe_type_name(value: object) -> str:
        try:
            cls = type(value)
            module = type.__getattribute__(cls, "__module__")
            qualname = type.__getattribute__(cls, "__qualname__")
            if (
                type(module) is str
                and type(qualname) is str
                and module
                and qualname
                and len(module) <= 128
                and len(qualname) <= 128
            ):
                return f"{module}.{qualname}"
        except BaseException:
            pass
        return "onyx.cleanup.UnknownException"

    def _render_message(self, failure: BaseException) -> tuple[str, BaseException | None]:
        try:
            message = str(failure)
        except BaseException as render_failure:
            return f"<message-unavailable:{self._safe_type_name(failure)}>", render_failure
        if type(message) is not str:
            return f"<message-unavailable:{self._safe_type_name(failure)}>", TypeError(
                "exception string result is not exact str"
            )
        if len(message) > 4096:
            return message[:4096], None
        return message, None

    def _record_render_failure(self, failure: BaseException) -> None:
        self._append(
            CleanupFailureRecord(
                "collector.message_access",
                self._safe_type_name(failure),
                "exception message rendering failed",
            )
        )

    def _record_accessor_failure(self, field: str, failure: BaseException) -> None:
        message, render_failure = self._render_message(failure)
        self._append(
            CleanupFailureRecord(
                f"collector.{field}_access",
                self._safe_type_name(failure),
                message,
            )
        )
        if render_failure is not None and not self.overflowed:
            self._record_render_failure(render_failure)

    def _append_leaf(self, operation: str, failure: BaseException) -> None:
        message, render_failure = self._render_message(failure)
        self._append(
            CleanupFailureRecord(operation, self._safe_type_name(failure), message)
        )
        if render_failure is not None and not self.overflowed:
            self._record_render_failure(render_failure)

    def _read_accessor(
        self,
        failure: BaseException,
        field: str,
        *,
        missing_is_none: bool = False,
    ) -> tuple[object, bool]:
        if type(failure) is V32ParentError and field == "cleanup_failures":
            try:
                trusted = V32ParentError._trusted_cleanup_payload(failure)
            except BaseException as access_failure:
                self._record_accessor_failure(field, access_failure)
                return None, False
            if trusted is not None:
                return trusted, True
        try:
            return getattr(failure, field), True
        except AttributeError as access_failure:
            if missing_is_none and not self._declares_cleanup_accessor(failure, field):
                return None, True
            self._record_accessor_failure(field.strip("_"), access_failure)
            return None, False
        except BaseException as access_failure:
            self._record_accessor_failure(field.strip("_"), access_failure)
            return None, False

    @staticmethod
    def _declares_cleanup_accessor(failure: BaseException, field: str) -> bool:
        try:
            values = BaseException.__getattribute__(failure, "__dict__")
            if type(values) is dict:
                for key in dict.keys(values):
                    if type(key) is str and key == field:
                        return True
            hierarchy = type.__getattribute__(type(failure), "__mro__")
            if type(hierarchy) is not tuple:
                return True
            for cls in hierarchy:
                namespace = type.__getattribute__(cls, "__dict__")
                for key in namespace:
                    if type(key) is not str:
                        continue
                    if key == field:
                        return True
                    if (
                        key == "__getattribute__"
                        and cls is not BaseException
                        and cls is not Exception
                        and cls is not object
                    ):
                        return True
        except BaseException:
            return True
        return False

    def _append(self, record: CleanupFailureRecord) -> None:
        if self.overflowed:
            return
        if type(record) is not CleanupFailureRecord or any(
            type(value) is not str
            for value in (record.operation, record.exception_type, record.message)
        ):
            self._overflow("cleanup record is not canonical")
            return
        if (
            not record.operation
            or not record.exception_type
            or len(record.operation) > 128
            or len(record.exception_type) > 256
            or len(record.message) > 4096
        ):
            self._overflow("cleanup record is outside canonical bounds")
            return
        if record in self._seen:
            return
        if len(self.records) >= self.MAX_RECORDS:
            self._overflow("payload record budget exceeded")
            return
        self._seen.add(record)
        self.records.append(record)

    def _overflow(self, message: str) -> None:
        if self._overflow_reason is None and type(message) is str:
            self._overflow_reason = message[:4096]

    def _flatten(
        self,
        operation: str,
        failure: BaseException,
        seen: set[int],
        state: dict[str, object],
        depth: int,
    ) -> None:
        if self.overflowed:
            return
        if depth > self.MAX_DEPTH or int(state["nodes"]) >= self.MAX_NODES:
            self._overflow("flatten depth or node budget exceeded")
            return
        identity = id(failure)
        if identity in seen:
            self._append(
                CleanupFailureRecord(
                    "collector.cycle", "onyx.cleanup.ExceptionCycle", operation
                )
            )
            return
        seen.add(identity)
        state["nodes"] = int(state["nodes"]) + 1
        consumed = False
        preserve_wrapper = False
        structured, structured_ok = self._read_accessor(
            failure, "cleanup_failures", missing_is_none=True
        )
        if not structured_ok:
            preserve_wrapper = True
            self._append_leaf(operation, failure)
        if self.overflowed:
            seen.remove(identity)
            return
        if structured is not None:
            consumed = True
            if type(structured) not in {tuple, list}:
                self._append(
                    CleanupFailureRecord(
                        f"{operation}.payload",
                        "onyx.cleanup.MalformedPayload",
                        "cleanup_failures must be a list or tuple",
                    )
                )
            else:
                if len(structured) > self.MAX_PAYLOAD_ITEMS:
                    self._overflow("cleanup_failures payload item budget exceeded")
                    seen.remove(identity)
                    return
                if not structured:
                    self._append(
                        CleanupFailureRecord(
                            f"{operation}.payload",
                            "onyx.cleanup.EmptyCleanupPayload",
                            "cleanup_failures payload is empty",
                        )
                    )
                for item in structured:
                    if self.overflowed:
                        seen.remove(identity)
                        return
                    state["payload_items"] = int(state["payload_items"]) + 1
                    if int(state["payload_items"]) > self.MAX_PAYLOAD_ITEMS:
                        self._overflow("cleanup_failures payload work budget exceeded")
                        seen.remove(identity)
                        return
                    values: tuple[str, str, str] | None = None
                    if type(item) is dict:
                        keys = tuple(dict.keys(item))
                        if (
                            len(keys) == 3
                            and all(type(key) is str for key in keys)
                            and tuple(sorted(keys)) == ("message", "operation", "type")
                        ):
                            operation_value = dict.__getitem__(item, "operation")
                            type_value = dict.__getitem__(item, "type")
                            message_value = dict.__getitem__(item, "message")
                            if (
                                type(operation_value) is str
                                and type(type_value) is str
                                and type(message_value) is str
                                and operation_value
                                and type_value
                                and len(operation_value) <= 128
                                and len(type_value) <= 256
                                and len(message_value) <= 4096
                            ):
                                values = (operation_value, type_value, message_value)
                    if values is None:
                        self._append(
                            CleanupFailureRecord(
                                f"{operation}.payload",
                                "onyx.cleanup.MalformedPayload",
                                "cleanup_failures record schema is invalid",
                            )
                        )
                    else:
                        self._append(CleanupFailureRecord(*values))
                    if self.overflowed:
                        seen.remove(identity)
                        return
        try:
            is_group = isinstance(failure, BaseExceptionGroup)
        except BaseException as group_check_failure:
            is_group = False
            preserve_wrapper = True
            self._record_accessor_failure("exceptions", group_check_failure)
            self._append_leaf(operation, failure)
        if is_group:
            consumed = True
            children, children_ok = self._read_accessor(failure, "exceptions")
            if not children_ok or type(children) is not tuple:
                preserve_wrapper = True
                if children_ok:
                    self._record_accessor_failure(
                        "exceptions", TypeError("exception group children must be exact tuple")
                    )
                self._append_leaf(operation, failure)
            elif len(children) > self.MAX_NODES:
                self._overflow("exception group child budget exceeded")
            else:
                for child in children:
                    if self.overflowed:
                        seen.remove(identity)
                        return
                    if not self._is_exception(child):
                        preserve_wrapper = True
                        self._record_accessor_failure(
                            "exceptions", TypeError("exception group child is not BaseException")
                        )
                        self._append_leaf(operation, failure)
                        break
                    self._flatten(operation, child, seen, state, depth + 1)
        if self.overflowed:
            seen.remove(identity)
            return
        cause, cause_ok = self._read_accessor(failure, "__cause__")
        if not cause_ok:
            preserve_wrapper = True
            self._append_leaf(operation, failure)
        elif cause is not None and not self._is_exception(cause):
            preserve_wrapper = True
            self._record_accessor_failure("cause", TypeError("exception cause is invalid"))
            self._append_leaf(operation, failure)
        elif cause is not None:
            consumed = True
            self._flatten(operation, cause, seen, state, depth + 1)
        else:
            context, context_ok = self._read_accessor(failure, "__context__")
            if not context_ok:
                preserve_wrapper = True
                self._append_leaf(operation, failure)
            elif context is not None and not self._is_exception(context):
                preserve_wrapper = True
                self._record_accessor_failure("context", TypeError("exception context is invalid"))
                self._append_leaf(operation, failure)
            elif context is not None:
                suppress, suppress_ok = self._read_accessor(failure, "__suppress_context__")
                if not suppress_ok or type(suppress) is not bool:
                    preserve_wrapper = True
                    if suppress_ok:
                        self._record_accessor_failure(
                            "suppress_context",
                            TypeError("exception suppress-context flag is not exact bool"),
                        )
                    self._append_leaf(operation, failure)
                elif not suppress:
                    consumed = True
                    self._flatten(operation, context, seen, state, depth + 1)
        if self.overflowed:
            seen.remove(identity)
            return
        if consumed or preserve_wrapper:
            seen.remove(identity)
            return
        self._append_leaf(operation, failure)
        seen.remove(identity)

    @staticmethod
    def note(record: CleanupFailureRecord) -> str:
        return (
            f"cleanup_failure operation={record.operation} "
            f"type={record.exception_type} message={record.message}"
        )

    def finish(self, primary: BaseException | None) -> BaseException | None:
        if not self.records and not self.overflowed:
            return primary
        cleanup_records = tuple(self.records)
        overflow_record = (
            None
            if self._overflow_reason is None
            else CleanupFailureRecord(
                "collector.overflow",
                "onyx.cleanup.CollectorOverflow",
                self._overflow_reason,
            )
        )
        return self._trusted_wrapper(
            primary,
            cleanup_records,
            overflow_record,
            (),
            "cleanup failed closed",
        )

    def _trusted_wrapper(
        self,
        primary: BaseException | None,
        cleanup_records: tuple[CleanupFailureRecord, ...],
        overflow_record: CleanupFailureRecord | None,
        attachment_records: tuple[CleanupFailureRecord, ...],
        message: str,
    ) -> V32ParentError:
        primary_record: CleanupFailureRecord | None = None
        if primary is not None:
            rendered, _render_failure = self._render_message(primary)
            primary_record = CleanupFailureRecord(
                "primary",
                self._safe_type_name(primary),
                rendered,
            )
            message = rendered
        wrapper = V32ParentError(
            message,
            cleanup_records=cleanup_records,
            overflow_record=overflow_record,
            primary_record=primary_record,
            attachment_records=attachment_records,
        )
        if primary is not None:
            try:
                BaseException.__setattr__(wrapper, "__cause__", primary)
            except BaseException as cause_failure:
                rendered, _render_failure = self._render_message(cause_failure)
                attachment_records = attachment_records + (
                    CleanupFailureRecord(
                        "attachment.primary_cause",
                        self._safe_type_name(cause_failure),
                        rendered,
                    ),
                )
                wrapper = V32ParentError(
                    message,
                    cleanup_records=cleanup_records,
                    overflow_record=overflow_record,
                    primary_record=primary_record,
                    attachment_records=attachment_records,
                )
        notes = [self.note(record) for record in cleanup_records]
        if overflow_record is not None:
            notes.append(
                "cleanup_overflow operation=collector.overflow "
                "type=onyx.cleanup.CollectorOverflow "
                f"message={overflow_record.message}"
            )
        for record in attachment_records:
            notes.append("attachment_failure " + self.note(record))
        if notes:
            BaseException.__setattr__(wrapper, "__notes__", notes)
        return wrapper


def _direct_child_cleanup(
    process: subprocess.Popen[str],
    label: str,
    failures: _CleanupFailures,
) -> None:
    active = True
    try:
        active = process.poll() is None
    except BaseException as exc:
        failures.add("direct.poll.initial", exc)
    if active:
        try:
            process.kill()
        except BaseException as exc:
            failures.add("direct.kill", exc)
    try:
        process.communicate(timeout=POST_KILL_DRAIN_SECONDS)
    except subprocess.TimeoutExpired as exc:
        failures.add("direct.communicate.timeout", exc)
        try:
            process.kill()
        except BaseException as kill_exc:
            failures.add("direct.kill.retry", kill_exc)
        try:
            process.communicate(timeout=POST_KILL_DRAIN_SECONDS)
        except BaseException as drain_exc:
            failures.add("direct.communicate.retry", drain_exc)
    except BaseException as exc:
        failures.add("direct.communicate", exc)
    try:
        if process.poll() is None:
            failures.add(
                "direct.poll.reap",
                V32ParentError(f"{label} direct child was not reaped"),
            )
    except BaseException as exc:
        failures.add("direct.poll.reap", exc)
    try:
        if _pid_exists(process.pid):
            failures.add(
                "direct.pid.proof",
                V32ParentError(f"{label} direct child PID survived cleanup"),
            )
    except BaseException as exc:
        failures.add("direct.pid.proof", exc)


def _posix_phase(
    phase: str,
    *,
    evidence_nonce: str,
    label: str,
    timeout: float,
    env: dict[str, str] | None,
    stdout_mode: str,
) -> PhaseResult:
    junit = _validated_junit_path(evidence_nonce, require_file=phase == "worker")
    command = _phase_command(phase, junit)
    process = subprocess.Popen(
        command,
        cwd=PROJECT,
        env=env,
        text=True,
        shell=False,
        start_new_session=True,
        stdout=subprocess.PIPE if stdout_mode == "pipe" else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    pgid: int | None = None
    stdout = stderr = ""
    failure: BaseException | None = None
    cleanup_failures = _CleanupFailures()
    try:
        try:
            acquired = os.getpgid(process.pid)
        except BaseException as exc:
            failure = exc
        else:
            if acquired != process.pid:
                failure = V32ParentError(
                    f"{label} POSIX process group ownership mismatch",
                )
            else:
                pgid = acquired
        if failure is None:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                failure = V32ParentError(f"{label} timed out after {timeout:.3f}s")
                BaseException.__setattr__(failure, "__cause__", exc)
            except BaseException as exc:
                failure = exc
    finally:
        if pgid is None:
            _direct_child_cleanup(process, label, cleanup_failures)
        else:
            residual = False
            try:
                residual = _posix_group_exists(pgid)
            except BaseException as exc:
                cleanup_failures.add("group.exists", exc)
                residual = True
            if residual and failure is None:
                failure = V32ParentError(
                    f"{label} left residual descendants after normal completion",
                )
            if failure is not None or residual:
                try:
                    _kill_posix_group(pgid)
                except BaseException as exc:
                    cleanup_failures.add("group.kill", exc)
                try:
                    _drain(process)
                except BaseException as exc:
                    cleanup_failures.add("group.drain", exc)
            try:
                _wait_posix_group_empty(pgid, label)
            except BaseException as exc:
                cleanup_failures.add("group.empty.proof", exc)
    failure = cleanup_failures.finish(failure)
    if failure is not None:
        raise failure
    return PhaseResult(process.returncode, stdout or "", stderr or "")


def _plain_component(path: Path) -> None:
    info = path.lstat()
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & reparse:
        raise V32ParentError("private evidence path contains a reparse component")


def _validated_junit_path(evidence_nonce: str, *, require_file: bool) -> Path:
    if _TOKEN.fullmatch(evidence_nonce) is None:
        raise V32ParentError("private evidence nonce is invalid")
    base = PRIVATE_BASE.resolve(strict=True)
    expected = Path(tempfile.gettempdir()).resolve(strict=True) / PRIVATE_BASE.name
    if base != expected:
        raise V32ParentError("private evidence base realpath is invalid")
    _plain_component(PRIVATE_BASE)
    directory = PRIVATE_BASE / evidence_nonce
    _plain_component(directory)
    resolved = directory.resolve(strict=True)
    if resolved.parent != base or resolved.name != evidence_nonce:
        raise V32ParentError("private evidence directory realpath is invalid")
    sentinel = directory / SENTINEL
    _plain_component(sentinel)
    if (
        sentinel.read_text(encoding="ascii")
        != f"{_PRIVATE_CONTRACT}:{evidence_nonce}\n"
    ):
        raise V32ParentError("private evidence sentinel is invalid")
    junit = directory / "focused.junit.xml"
    if require_file:
        _plain_component(junit)
        if not junit.is_file() or junit.resolve(strict=True).parent != resolved:
            raise V32ParentError(
                "fresh focused JUnit is outside private evidence scope"
            )
    elif junit.exists():
        raise V32ParentError("fresh focused JUnit already exists")
    return junit


class _PrivateEvidence:
    def __init__(self):
        self.nonce = secrets.token_hex(32)
        self.directory = PRIVATE_BASE / self.nonce

    def __enter__(self) -> str:
        PRIVATE_BASE.mkdir(mode=0o700, parents=True, exist_ok=True)
        _plain_component(PRIVATE_BASE)
        self.directory.mkdir(mode=0o700)
        (self.directory / SENTINEL).write_text(
            f"{_PRIVATE_CONTRACT}:{self.nonce}\n",
            encoding="ascii",
            newline="\n",
        )
        _validated_junit_path(self.nonce, require_file=False)
        return self.nonce

    def __exit__(self, exc_type, exc, traceback) -> None:
        deadline = time.monotonic() + POST_KILL_DRAIN_SECONDS
        last_failure: BaseException | None = None
        while True:
            try:
                shutil.rmtree(self.directory)
                return
            except PermissionError as failure:
                last_failure = failure
                if time.monotonic() >= deadline:
                    failures = _CleanupFailures()
                    failures.add("private.remove", last_failure)
                    combined = failures.finish(exc)
                    if combined is exc:
                        return
                    raise combined
                time.sleep(0.01)


def _run_phase(
    phase: str,
    *,
    evidence_nonce: str,
    label: str,
    timeout: float,
    env: dict[str, str] | None = None,
    stdout_mode: str = "pipe",
) -> PhaseResult:
    if not isinstance(phase, str) or phase not in {"focused", "worker"}:
        raise V32ParentError("phase id must be focused or worker")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise V32ParentError(f"{label} timeout is invalid")
    if stdout_mode not in {"pipe", "devnull"}:
        raise V32ParentError(f"{label} stdout mode is invalid")
    _validated_junit_path(evidence_nonce, require_file=phase == "worker")
    runner = _windows_phase if os.name == "nt" else _posix_phase
    return runner(
        phase,
        evidence_nonce=evidence_nonce,
        label=label,
        timeout=timeout,
        env=env,
        stdout_mode=stdout_mode,
    )


def _remaining(started: float, total_timeout: int) -> float:
    if type(total_timeout) is not int or total_timeout <= POST_KILL_DRAIN_SECONDS + 1:
        raise V32ParentError("total timeout is invalid")
    remaining = total_timeout - (time.monotonic() - started)
    if remaining <= POST_KILL_DRAIN_SECONDS + 1:
        raise V32ParentError(f"total verifier deadline exceeded after {total_timeout}s")
    return remaining


def _phase_timeout(started: float, total_timeout: int) -> float:
    return _remaining(started, total_timeout) - POST_KILL_DRAIN_SECONDS


def _parse_worker_marker(stdout: str) -> dict[str, object]:
    lines = stdout.splitlines()
    prefix = MARKER + " "
    matching = [line for line in lines if line.startswith(prefix)]
    if len(matching) != 1 or len(lines) != 1:
        raise V32ParentError(
            "pure worker marker is missing, duplicated, or contaminated"
        )
    import json  # noqa: PLC0415

    try:
        payload = json.loads(matching[0][len(prefix) :])
    except json.JSONDecodeError as exc:
        raise V32ParentError("pure worker marker payload is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "artifacts",
        "focused_passed",
        "live_scan_files",
        "root_sha256",
    }:
        raise V32ParentError("pure worker marker payload schema is invalid")
    return payload


def _run_parent(*, total_timeout: int = TOTAL_TIMEOUT_SECONDS) -> dict[str, object]:
    started = time.monotonic()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with _PrivateEvidence() as evidence_nonce:
        focused = _run_phase(
            "focused",
            evidence_nonce=evidence_nonce,
            label="fixed focused pytest",
            timeout=_phase_timeout(started, total_timeout),
            env=env,
        )
        if focused.returncode:
            raise V32ParentError("fixed focused pytest failed")
        worker = _run_phase(
            "worker",
            evidence_nonce=evidence_nonce,
            label="fixed pure artifact worker",
            timeout=_phase_timeout(started, total_timeout),
            env=env,
        )
        if worker.returncode:
            raise V32ParentError("fixed pure artifact worker failed")
        payload = _parse_worker_marker(worker.stdout)
    _remaining(started, total_timeout)
    return payload


def main() -> int:
    import json  # noqa: PLC0415

    print(
        MARKER + " " + json.dumps(_run_parent(), sort_keys=True, separators=(",", ":"))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
