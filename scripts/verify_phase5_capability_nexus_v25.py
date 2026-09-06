"""Run the phase-only, fail-closed Capability Nexus V25 verifier."""

from __future__ import annotations

import ctypes
from builtins import BaseExceptionGroup
from ctypes import wintypes
from dataclasses import dataclass
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time


PROJECT = Path(__file__).resolve().parents[1]
TESTS = "tests/test_capability_nexus_v25.py"
WORKER = "scripts/verify_phase5_capability_nexus_v25_worker.py"
PRIVATE_BASE = Path(tempfile.gettempdir()) / "onyx-p53-v25-private"
SENTINEL = ".phase53-v25-private"
TOTAL_TIMEOUT_SECONDS = 180
POST_KILL_DRAIN_SECONDS = 2
MARKER = "P53_CAPABILITY_NEXUS_V25_EVIDENCE_OK"
_PRIVATE_CONTRACT = "Phase53CapabilityNexusPrivate.v25"
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


class V25ParentError(RuntimeError):
    pass


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
        raise V25ParentError("Windows Job APIs requested on a non-Windows host")
    if ctypes.sizeof(wintypes.HANDLE) != ctypes.sizeof(ctypes.c_void_p):
        raise V25ParentError("Windows HANDLE width does not match pointer width")
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
        raise V25ParentError("Windows handle is invalid or truncated")
    return wintypes.HANDLE(value)


def _handle_value(handle: wintypes.HANDLE) -> int:
    value = handle.value
    if not isinstance(value, int) or value <= 0:
        raise V25ParentError("Windows handle ownership record is invalid")
    return value


def _win_failure(operation: str) -> V25ParentError:
    return V25ParentError(
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
        raise V25ParentError(
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
            except V25ParentError as close_failure:
                raise V25ParentError(
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
        raise V25ParentError(f"{label} process tree survived termination")


def _phase_command(phase: str, junit: Path) -> list[str]:
    if not isinstance(phase, str):
        raise V25ParentError("phase id must be focused or worker")
    if phase == "focused":
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
        return [sys.executable, WORKER, "--fresh-focused-junit", str(junit)]
    raise V25ParentError("phase id must be focused or worker")


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
        raise V25ParentError(f"{label} output exceeds bounded evidence limit")
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
            raise V25ParentError(f"{label} timed out after {timeout:.3f}s")
        if wait == _WAIT_FAILED or wait != _WAIT_OBJECT_0:
            raise _win_failure("WaitForSingleObject")
        code = wintypes.DWORD()
        if not api.GetExitCodeProcess(process_handle, ctypes.byref(code)):
            raise _win_failure("GetExitCodeProcess")
        try:
            _wait_job_empty(job, label)
        except V25ParentError as exc:
            raise V25ParentError(
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
        raise V25ParentError(f"{label} suspended process was not safely completed")
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
        raise V25ParentError(f"{label} POSIX process group survived cleanup")


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
        seen: set[int] = set()
        if self.overflowed:
            return
        state = {"nodes": 0, "payload_items": 0}
        self._flatten(operation, failure, seen, state, 0)

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
        if self._overflow_reason is None:
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
        structured = getattr(failure, "cleanup_failures", None)
        consumed = False
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
                    if (
                        type(item) is not dict
                        or set(item) != {"operation", "type", "message"}
                        or any(
                            not isinstance(item.get(key), str)
                            for key in ("operation", "type", "message")
                        )
                        or not item["operation"]
                        or not item["type"]
                        or len(item["operation"]) > 128
                        or len(item["type"]) > 256
                        or len(item["message"]) > 4096
                    ):
                        self._append(
                            CleanupFailureRecord(
                                f"{operation}.payload",
                                "onyx.cleanup.MalformedPayload",
                                "cleanup_failures record schema is invalid",
                            )
                        )
                    else:
                        self._append(
                            CleanupFailureRecord(
                                item["operation"], item["type"], item["message"]
                            )
                        )
                    if self.overflowed:
                        seen.remove(identity)
                        return
        if isinstance(failure, BaseExceptionGroup):
            consumed = True
            for child in failure.exceptions:
                if self.overflowed:
                    seen.remove(identity)
                    return
                self._flatten(operation, child, seen, state, depth + 1)
        if self.overflowed:
            seen.remove(identity)
            return
        cause = failure.__cause__
        if cause is not None:
            consumed = True
            self._flatten(operation, cause, seen, state, depth + 1)
        elif failure.__context__ is not None and not failure.__suppress_context__:
            consumed = True
            self._flatten(operation, failure.__context__, seen, state, depth + 1)
        if self.overflowed:
            seen.remove(identity)
            return
        if consumed:
            seen.remove(identity)
            return
        try:
            message = str(failure)
        except BaseException as stringify_failure:
            message = f"<message-unavailable:{type(stringify_failure).__module__}.{type(stringify_failure).__qualname__}>"
        record = CleanupFailureRecord(
            operation,
            f"{type(failure).__module__}.{type(failure).__qualname__}",
            message,
        )
        self._append(record)
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
        if primary is None:
            primary = V25ParentError("cleanup failed closed")
        payload = tuple(
            {
                "operation": item.operation,
                "type": item.exception_type,
                "message": item.message,
            }
            for item in self.records
        )
        setattr(primary, "cleanup_failures", payload)
        for record in self.records:
            primary.add_note(self.note(record))
        if self._overflow_reason is not None:
            overflow = {
                "operation": "collector.overflow",
                "type": "onyx.cleanup.CollectorOverflow",
                "message": self._overflow_reason,
            }
            setattr(primary, "cleanup_overflow", overflow)
            primary.add_note(
                "cleanup_overflow operation=collector.overflow "
                f"type=onyx.cleanup.CollectorOverflow message={self._overflow_reason}"
            )
        return primary


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
                V25ParentError(f"{label} direct child was not reaped"),
            )
    except BaseException as exc:
        failures.add("direct.poll.reap", exc)
    try:
        if _pid_exists(process.pid):
            failures.add(
                "direct.pid.proof",
                V25ParentError(f"{label} direct child PID survived cleanup"),
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
                failure = V25ParentError(
                    f"{label} POSIX process group ownership mismatch",
                )
            else:
                pgid = acquired
        if failure is None:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                failure = V25ParentError(f"{label} timed out after {timeout:.3f}s")
                failure.__cause__ = exc
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
                failure = V25ParentError(
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
        raise V25ParentError("private evidence path contains a reparse component")


def _validated_junit_path(evidence_nonce: str, *, require_file: bool) -> Path:
    if _TOKEN.fullmatch(evidence_nonce) is None:
        raise V25ParentError("private evidence nonce is invalid")
    base = PRIVATE_BASE.resolve(strict=True)
    expected = Path(tempfile.gettempdir()).resolve(strict=True) / PRIVATE_BASE.name
    if base != expected:
        raise V25ParentError("private evidence base realpath is invalid")
    _plain_component(PRIVATE_BASE)
    directory = PRIVATE_BASE / evidence_nonce
    _plain_component(directory)
    resolved = directory.resolve(strict=True)
    if resolved.parent != base or resolved.name != evidence_nonce:
        raise V25ParentError("private evidence directory realpath is invalid")
    sentinel = directory / SENTINEL
    _plain_component(sentinel)
    if (
        sentinel.read_text(encoding="ascii")
        != f"{_PRIVATE_CONTRACT}:{evidence_nonce}\n"
    ):
        raise V25ParentError("private evidence sentinel is invalid")
    junit = directory / "focused.junit.xml"
    if require_file:
        _plain_component(junit)
        if not junit.is_file() or junit.resolve(strict=True).parent != resolved:
            raise V25ParentError(
                "fresh focused JUnit is outside private evidence scope"
            )
    elif junit.exists():
        raise V25ParentError("fresh focused JUnit already exists")
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
        raise V25ParentError("phase id must be focused or worker")
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise V25ParentError(f"{label} timeout is invalid")
    if stdout_mode not in {"pipe", "devnull"}:
        raise V25ParentError(f"{label} stdout mode is invalid")
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
        raise V25ParentError("total timeout is invalid")
    remaining = total_timeout - (time.monotonic() - started)
    if remaining <= POST_KILL_DRAIN_SECONDS + 1:
        raise V25ParentError(f"total verifier deadline exceeded after {total_timeout}s")
    return remaining


def _phase_timeout(started: float, total_timeout: int) -> float:
    return _remaining(started, total_timeout) - POST_KILL_DRAIN_SECONDS


def _parse_worker_marker(stdout: str) -> dict[str, object]:
    lines = stdout.splitlines()
    prefix = MARKER + " "
    matching = [line for line in lines if line.startswith(prefix)]
    if len(matching) != 1 or len(lines) != 1:
        raise V25ParentError(
            "pure worker marker is missing, duplicated, or contaminated"
        )
    import json  # noqa: PLC0415

    try:
        payload = json.loads(matching[0][len(prefix) :])
    except json.JSONDecodeError as exc:
        raise V25ParentError("pure worker marker payload is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "artifacts",
        "focused_passed",
        "live_scan_files",
        "root_sha256",
    }:
        raise V25ParentError("pure worker marker payload schema is invalid")
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
            raise V25ParentError("fixed focused pytest failed")
        worker = _run_phase(
            "worker",
            evidence_nonce=evidence_nonce,
            label="fixed pure artifact worker",
            timeout=_phase_timeout(started, total_timeout),
            env=env,
        )
        if worker.returncode:
            raise V25ParentError("fixed pure artifact worker failed")
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
