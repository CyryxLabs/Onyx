"""Run the race-free process-tree verifier for Capability Nexus V18."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


PROJECT = Path(__file__).resolve().parents[1]
TESTS = "tests/test_capability_nexus_v18.py"
WORKER = "scripts/verify_phase5_capability_nexus_v18_worker.py"
BOOTSTRAP = "scripts/phase5_capability_nexus_v18_bootstrap.py"
TOTAL_TIMEOUT_SECONDS = 180
POST_KILL_DRAIN_SECONDS = 2
MARKER = "P53_CAPABILITY_NEXUS_V18_EVIDENCE_OK"
_BOOTSTRAP_CONTRACT = "Phase53CapabilityNexusBootstrap.v18"
_KILL_ON_JOB_CLOSE = 0x00002000
_EXTENDED_LIMIT_INFORMATION = 9
_BASIC_ACCOUNTING_INFORMATION = 1
_STILL_ACTIVE = 259


class V18ParentError(RuntimeError):
    pass


@dataclass(frozen=True)
class PhaseResult:
    returncode: int
    stdout: str
    stderr: str


class _JobBasicLimit(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _JobExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimit), ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _JobBasicAccounting(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


def _kernel32():
    if os.name != "nt":
        raise V18ParentError("Windows Job APIs requested on a non-Windows host")
    if ctypes.sizeof(wintypes.HANDLE) != ctypes.sizeof(ctypes.c_void_p):
        raise V18ParentError("Windows HANDLE width does not match pointer width")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    api.CreateJobObjectW.restype = wintypes.HANDLE
    api.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    api.SetInformationJobObject.restype = wintypes.BOOL
    api.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    api.AssignProcessToJobObject.restype = wintypes.BOOL
    api.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
    api.TerminateJobObject.restype = wintypes.BOOL
    api.QueryInformationJobObject.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    )
    api.QueryInformationJobObject.restype = wintypes.BOOL
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    api.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    api.OpenProcess.restype = wintypes.HANDLE
    api.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
    api.GetExitCodeProcess.restype = wintypes.BOOL
    return api


def _validated_handle(raw: object) -> wintypes.HANDLE:
    value = raw.value if isinstance(raw, ctypes.c_void_p) else raw
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value >= 1 << (ctypes.sizeof(ctypes.c_void_p) * 8)
    ):
        raise V18ParentError("Windows handle is invalid or truncated")
    return wintypes.HANDLE(value)


class _WindowsJob:
    def __init__(self):
        self.api = _kernel32()
        raw = self.api.CreateJobObjectW(None, None)
        self.handle = _validated_handle(raw)
        limits = _JobExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(
            self.handle, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits),
        ):
            error = ctypes.get_last_error()
            self.close()
            raise ctypes.WinError(error)

    def assign(self, process: subprocess.Popen[str]) -> None:
        process_handle = _validated_handle(process._handle)
        if not self.api.AssignProcessToJobObject(self.handle, process_handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self) -> None:
        if self.handle and not self.api.TerminateJobObject(self.handle, 1):
            error = ctypes.get_last_error()
            if error:
                raise ctypes.WinError(error)

    def active(self) -> int:
        accounting = _JobBasicAccounting()
        if not self.api.QueryInformationJobObject(
            self.handle, _BASIC_ACCOUNTING_INFORMATION, ctypes.byref(accounting),
            ctypes.sizeof(accounting), None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(accounting.ActiveProcesses)

    def close(self) -> None:
        handle = getattr(self, "handle", None)
        if handle:
            self.api.CloseHandle(handle)
            self.handle = wintypes.HANDLE()


def _pid_exists(pid: int) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        api = _kernel32()
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        try:
            return bool(api.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == _STILL_ACTIVE
        finally:
            api.CloseHandle(handle)
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


def _wait_job_empty(job: _WindowsJob, process: subprocess.Popen[str], label: str) -> None:
    deadline = time.monotonic() + POST_KILL_DRAIN_SECONDS
    while job.active() and time.monotonic() < deadline:
        time.sleep(0.01)
    if process.poll() is None or job.active():
        raise V18ParentError(f"{label} process tree survived termination")


def _windows_phase(
    command: list[str], *, label: str, timeout: float,
    env: dict[str, str] | None, stdout_mode: str,
) -> PhaseResult:
    job = _WindowsJob()
    bootstrap_env = (env or os.environ).copy()
    bootstrap_env.update({
        "ONYX_P53_V18_BOOTSTRAP_COMMAND": json.dumps(command, ensure_ascii=True, separators=(",", ":")),
        "ONYX_P53_V18_BOOTSTRAP_STDOUT_MODE": stdout_mode,
        "ONYX_P53_V18_BOOTSTRAP_CONTRACT": _BOOTSTRAP_CONTRACT,
    })
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            [sys.executable, BOOTSTRAP], cwd=PROJECT, env=bootstrap_env, text=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE if stdout_mode == "pipe" else subprocess.DEVNULL,
            stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        job.assign(process)
        if process.stdin is None:
            raise V18ParentError(f"{label} bootstrap stdin is unavailable")
        try:
            process.stdin.write("GO\n")
            process.stdin.flush()
            process.stdin.close()
            process.stdin = None
        except OSError as exc:
            raise V18ParentError(f"{label} bootstrap GO failed") from exc
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            job.terminate()
            _drain(process)
            _wait_job_empty(job, process, label)
            raise V18ParentError(f"{label} timed out after {timeout:.3f}s") from exc
        job.terminate()
        _wait_job_empty(job, process, label)
        return PhaseResult(process.returncode, stdout or "", stderr or "")
    except BaseException:
        try:
            job.terminate()
        except OSError:
            pass
        if process is not None and process.poll() is None:
            _drain(process)
        if process is not None:
            _wait_job_empty(job, process, label)
        raise
    finally:
        job.close()


def _posix_phase(
    command: list[str], *, label: str, timeout: float,
    env: dict[str, str] | None, stdout_mode: str,
) -> PhaseResult:
    process = subprocess.Popen(
        command, cwd=PROJECT, env=env, text=True, shell=False, start_new_session=True,
        stdout=subprocess.PIPE if stdout_mode == "pipe" else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    pgid = os.getpgid(process.pid)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _drain(process)
        raise V18ParentError(f"{label} timed out after {timeout:.3f}s") from exc
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    return PhaseResult(process.returncode, stdout or "", stderr or "")


def _run_phase(
    command: list[str], *, label: str, timeout: float,
    env: dict[str, str] | None = None, stdout_mode: str = "pipe",
) -> PhaseResult:
    if not command or any(not isinstance(item, str) or not item for item in command):
        raise V18ParentError(f"{label} command is invalid")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise V18ParentError(f"{label} timeout is invalid")
    if stdout_mode not in {"pipe", "devnull"}:
        raise V18ParentError(f"{label} stdout mode is invalid")
    runner = _windows_phase if os.name == "nt" else _posix_phase
    return runner(command, label=label, timeout=timeout, env=env, stdout_mode=stdout_mode)


def _remaining(started: float, total_timeout: int) -> float:
    if type(total_timeout) is not int or total_timeout <= POST_KILL_DRAIN_SECONDS + 1:
        raise V18ParentError("total timeout is invalid")
    remaining = total_timeout - (time.monotonic() - started)
    if remaining <= POST_KILL_DRAIN_SECONDS + 1:
        raise V18ParentError(f"total verifier deadline exceeded after {total_timeout}s")
    return remaining


def _phase_timeout(started: float, total_timeout: int) -> float:
    return _remaining(started, total_timeout) - POST_KILL_DRAIN_SECONDS


def _parse_worker_marker(stdout: str) -> dict[str, object]:
    lines = stdout.splitlines()
    prefix = MARKER + " "
    matching = [line for line in lines if line.startswith(prefix)]
    if len(matching) != 1 or len(lines) != 1:
        raise V18ParentError("pure worker marker is missing, duplicated, or contaminated")
    try:
        payload = json.loads(matching[0][len(prefix):])
    except json.JSONDecodeError as exc:
        raise V18ParentError("pure worker marker payload is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {"artifacts", "focused_passed", "live_scan_files", "root_sha256"}:
        raise V18ParentError("pure worker marker payload schema is invalid")
    return payload


def _run_parent(
    *, total_timeout: int = TOTAL_TIMEOUT_SECONDS,
    focused_command: list[str] | None = None, worker_command: list[str] | None = None,
    focused_stdout_mode: str = "pipe", worker_stdout_mode: str = "pipe",
) -> dict[str, object]:
    started = time.monotonic()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="onyx-p53-v18-parent-") as directory:
        junit = Path(directory) / "focused.junit.xml"
        focused = focused_command or [sys.executable, "-m", "pytest", "-q", TESTS, "--disable-warnings", "--maxfail=1", f"--junitxml={junit}"]
        result = _run_phase(focused, label="direct focused pytest", timeout=_phase_timeout(started, total_timeout), env=env, stdout_mode=focused_stdout_mode)
        if result.returncode:
            raise V18ParentError("direct focused pytest failed")
        worker = worker_command or [sys.executable, WORKER, "--fresh-focused-junit", str(junit)]
        result = _run_phase(worker, label="pure artifact worker", timeout=_phase_timeout(started, total_timeout), env=env, stdout_mode=worker_stdout_mode)
        if result.returncode:
            raise V18ParentError("pure artifact worker failed")
        payload = _parse_worker_marker(result.stdout)
    _remaining(started, total_timeout)
    return payload


def main() -> int:
    print(MARKER + " " + json.dumps(_run_parent(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
