"""Run the bounded process-tree-owning verifier for Capability Nexus V17."""

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
TESTS = "tests/test_capability_nexus_v17.py"
WORKER = "scripts/verify_phase5_capability_nexus_v17_worker.py"
TOTAL_TIMEOUT_SECONDS = 180
POST_KILL_DRAIN_SECONDS = 2
MARKER = "P53_CAPABILITY_NEXUS_V17_EVIDENCE_OK"
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION = 1


class V17ParentError(RuntimeError):
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
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


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
        ("TotalUserTime", ctypes.c_int64), ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64), ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD), ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD), ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


class _TreeOwner:
    def __init__(self, process: subprocess.Popen[str]):
        self.process = process
        self.job: int | None = None
        self.pgid: int | None = None
        if os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            job = kernel32.CreateJobObjectW(None, None)
            if not job:
                raise ctypes.WinError(ctypes.get_last_error())
            self.job = int(job)
            limits = _JobExtendedLimit()
            limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel32.SetInformationJobObject(
                wintypes.HANDLE(self.job), _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits), ctypes.sizeof(limits),
            ):
                kernel32.CloseHandle(wintypes.HANDLE(self.job))
                self.job = None
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel32.AssignProcessToJobObject(wintypes.HANDLE(self.job), wintypes.HANDLE(process._handle)):
                kernel32.CloseHandle(wintypes.HANDLE(self.job))
                self.job = None
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            self.pgid = os.getpgid(process.pid)

    def _job_active(self) -> int:
        if self.job is None:
            return 0
        accounting = _JobBasicAccounting()
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if not kernel32.QueryInformationJobObject(
            wintypes.HANDLE(self.job), _JOB_OBJECT_BASIC_ACCOUNTING_INFORMATION,
            ctypes.byref(accounting), ctypes.sizeof(accounting), None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return int(accounting.ActiveProcesses)

    def terminate(self) -> None:
        if os.name == "nt":
            if self.job is not None:
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                if not kernel32.TerminateJobObject(wintypes.HANDLE(self.job), 1):
                    error = ctypes.get_last_error()
                    if error:
                        raise ctypes.WinError(error)
            return
        if self.pgid is not None:
            try:
                os.killpg(self.pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def alive(self) -> bool:
        if os.name == "nt":
            return self._job_active() != 0
        if self.pgid is None:
            return False
        try:
            os.killpg(self.pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def close(self) -> None:
        if self.job is not None:
            ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(wintypes.HANDLE(self.job))
            self.job = None


def _pid_exists(pid: int) -> bool:
    if type(pid) is not int or pid <= 0:
        return False
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = wintypes.DWORD()
        try:
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _remaining(started: float, total_timeout: int) -> float:
    if type(total_timeout) is not int or total_timeout <= POST_KILL_DRAIN_SECONDS + 1:
        raise V17ParentError("total timeout is invalid")
    remaining = total_timeout - (time.monotonic() - started)
    if remaining <= POST_KILL_DRAIN_SECONDS + 1:
        raise V17ParentError(f"total verifier deadline exceeded after {total_timeout}s")
    return remaining


def _phase_timeout(started: float, total_timeout: int) -> float:
    return _remaining(started, total_timeout) - POST_KILL_DRAIN_SECONDS


def _run_phase(
    command: list[str],
    *,
    label: str,
    timeout: float,
    env: dict[str, str] | None = None,
    stdout_mode: str = "pipe",
) -> PhaseResult:
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise V17ParentError(f"{label} timeout is invalid")
    if stdout_mode not in {"pipe", "devnull"}:
        raise V17ParentError(f"{label} stdout mode is invalid")
    stdout_target = subprocess.PIPE if stdout_mode == "pipe" else subprocess.DEVNULL
    kwargs: dict[str, object] = {
        "cwd": PROJECT, "env": env, "text": True, "stdout": stdout_target,
        "stderr": subprocess.PIPE, "start_new_session": os.name != "nt",
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]
    owner: _TreeOwner | None = None
    try:
        owner = _TreeOwner(process)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            owner.terminate()
            try:
                process.communicate(timeout=POST_KILL_DRAIN_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=POST_KILL_DRAIN_SECONDS)
            deadline = time.monotonic() + POST_KILL_DRAIN_SECONDS
            while owner.alive() and time.monotonic() < deadline:
                time.sleep(0.01)
            if process.poll() is None or owner.alive():
                raise V17ParentError(f"{label} process tree survived termination") from exc
            raise V17ParentError(f"{label} timed out after {timeout:.3f}s") from exc
        owner.terminate()
        deadline = time.monotonic() + POST_KILL_DRAIN_SECONDS
        while owner.alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        if process.poll() is None or owner.alive():
            raise V17ParentError(f"{label} process tree survived completion cleanup")
        return PhaseResult(process.returncode, stdout or "", stderr or "")
    except BaseException:
        if owner is not None:
            try:
                owner.terminate()
            except OSError:
                pass
        if process.poll() is None:
            process.kill()
            try:
                process.communicate(timeout=POST_KILL_DRAIN_SECONDS)
            except subprocess.TimeoutExpired:
                pass
        raise
    finally:
        if owner is not None:
            owner.close()


def _parse_worker_marker(stdout: str) -> dict[str, object]:
    lines = stdout.splitlines()
    prefix = MARKER + " "
    matching = [line for line in lines if line.startswith(prefix)]
    if len(matching) != 1 or len(lines) != 1:
        raise V17ParentError("pure worker marker is missing, duplicated, or contaminated")
    try:
        payload = json.loads(matching[0][len(prefix):])
    except json.JSONDecodeError as exc:
        raise V17ParentError("pure worker marker payload is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {"artifacts", "focused_passed", "live_scan_files", "root_sha256"}:
        raise V17ParentError("pure worker marker payload schema is invalid")
    return payload


def _run_parent(
    *, total_timeout: int = TOTAL_TIMEOUT_SECONDS,
    focused_command: list[str] | None = None,
    worker_command: list[str] | None = None,
    focused_stdout_mode: str = "pipe",
    worker_stdout_mode: str = "pipe",
) -> dict[str, object]:
    started = time.monotonic()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="onyx-p53-v17-parent-") as directory:
        fresh_junit = Path(directory) / "focused.junit.xml"
        focused = focused_command or [sys.executable, "-m", "pytest", "-q", TESTS, "--disable-warnings", "--maxfail=1", f"--junitxml={fresh_junit}"]
        completed = _run_phase(focused, label="direct focused pytest", timeout=_phase_timeout(started, total_timeout), env=env, stdout_mode=focused_stdout_mode)
        if completed.returncode:
            raise V17ParentError("direct focused pytest failed")
        worker = worker_command or [sys.executable, WORKER, "--fresh-focused-junit", str(fresh_junit)]
        completed = _run_phase(worker, label="pure artifact worker", timeout=_phase_timeout(started, total_timeout), env=env, stdout_mode=worker_stdout_mode)
        if completed.returncode:
            raise V17ParentError("pure artifact worker failed")
        result = _parse_worker_marker(completed.stdout)
    _remaining(started, total_timeout)
    return result


def main() -> int:
    print(MARKER + " " + json.dumps(_run_parent(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
