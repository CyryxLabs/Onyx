"""Run the phase-only, fail-closed Capability Nexus V19 verifier."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import math
import os
from pathlib import Path
import queue
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time


PROJECT = Path(__file__).resolve().parents[1]
TESTS = "tests/test_capability_nexus_v19.py"
WORKER = "scripts/verify_phase5_capability_nexus_v19_worker.py"
BOOTSTRAP = "scripts/phase5_capability_nexus_v19_bootstrap.py"
PRIVATE_BASE = Path(tempfile.gettempdir()) / "onyx-p53-v19-private"
SENTINEL = ".phase53-v19-private"
TOTAL_TIMEOUT_SECONDS = 180
POST_KILL_DRAIN_SECONDS = 2
READINESS_TIMEOUT_SECONDS = 2
MARKER = "P53_CAPABILITY_NEXUS_V19_EVIDENCE_OK"
_BOOTSTRAP_CONTRACT = "Phase53CapabilityNexusBootstrap.v19"
_TOKEN = re.compile(r"[0-9a-f]{64}")
_KILL_ON_JOB_CLOSE = 0x00002000
_EXTENDED_LIMIT_INFORMATION = 9
_BASIC_ACCOUNTING_INFORMATION = 1
_STILL_ACTIVE = 259
_RETAINED_HANDLES: dict[int, tuple[object, wintypes.HANDLE, str]] = {}


class V19ParentError(RuntimeError):
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
        raise V19ParentError("Windows Job APIs requested on a non-Windows host")
    if ctypes.sizeof(wintypes.HANDLE) != ctypes.sizeof(ctypes.c_void_p):
        raise V19ParentError("Windows HANDLE width does not match pointer width")
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
        raise V19ParentError("Windows handle is invalid or truncated")
    return wintypes.HANDLE(value)


def _handle_value(handle: wintypes.HANDLE) -> int:
    value = handle.value
    if not isinstance(value, int) or value <= 0:
        raise V19ParentError("Windows handle ownership record is invalid")
    return value


def _win_failure(operation: str) -> V19ParentError:
    return V19ParentError(f"{operation} failed with Windows error {ctypes.get_last_error()}")


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
        raise V19ParentError("retained Windows handle cleanup failed: " + ",".join(sorted(failures)))


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
            self.handle, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits),
        ):
            failure = _win_failure("SetInformationJobObject")
            try:
                self.close()
            except V19ParentError as close_failure:
                raise V19ParentError(
                    f"{failure}; CloseHandle(Job) also failed and ownership is retained"
                ) from close_failure
            raise failure

    def assign(self, process: subprocess.Popen[str]) -> None:
        process_handle = _validated_handle(process._handle)
        if not self.api.AssignProcessToJobObject(self.handle, process_handle):
            raise _win_failure("AssignProcessToJobObject")

    def terminate(self) -> None:
        if self.handle and not self.api.TerminateJobObject(self.handle, 1):
            raise _win_failure("TerminateJobObject")

    def active(self) -> int:
        accounting = _JobBasicAccounting()
        if not self.api.QueryInformationJobObject(
            self.handle, _BASIC_ACCOUNTING_INFORMATION, ctypes.byref(accounting),
            ctypes.sizeof(accounting), None,
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


def _wait_job_empty(job: _WindowsJob, process: subprocess.Popen[str], label: str) -> None:
    deadline = time.monotonic() + POST_KILL_DRAIN_SECONDS
    while job.active() and time.monotonic() < deadline:
        time.sleep(0.01)
    if process.poll() is None or job.active():
        raise V19ParentError(f"{label} process tree survived termination")


def _readline_bounded(stream, timeout: float, label: str) -> str:
    received: queue.Queue[object] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            received.put(stream.readline())
        except BaseException as exc:
            received.put(exc)

    threading.Thread(target=read, daemon=True, name="onyx-v19-bootstrap-ready").start()
    try:
        value = received.get(timeout=min(timeout, READINESS_TIMEOUT_SECONDS))
    except queue.Empty as exc:
        raise V19ParentError(f"{label} bootstrap readiness timed out") from exc
    if isinstance(value, BaseException):
        raise V19ParentError(f"{label} bootstrap readiness read failed") from value
    return str(value)


def _phase_command(phase: str, junit: Path) -> list[str]:
    if not isinstance(phase, str):
        raise V19ParentError("phase id must be focused or worker")
    if phase == "focused":
        return [
            sys.executable, "-m", "pytest", "-q", TESTS, "--disable-warnings",
            "--maxfail=1", f"--junitxml={junit}",
        ]
    if phase == "worker":
        return [sys.executable, WORKER, "--fresh-focused-junit", str(junit)]
    raise V19ParentError("phase id must be focused or worker")


def _windows_phase(
    phase: str, *, evidence_nonce: str, label: str, timeout: float,
    env: dict[str, str] | None, stdout_mode: str,
) -> PhaseResult:
    del env
    job = _WindowsJob()
    process: subprocess.Popen[str] | None = None
    launch_nonce = secrets.token_hex(32)
    try:
        process = subprocess.Popen(
            [sys.executable, BOOTSTRAP], cwd=PROJECT, text=True, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        job.assign(process)
        if process.stdin is None or process.stdout is None:
            raise V19ParentError(f"{label} bootstrap private pipes are unavailable")
        process.stdin.write(f"HELLO {phase} {launch_nonce} {evidence_nonce}\n")
        process.stdin.flush()
        readiness = _readline_bounded(process.stdout, timeout, label)
        if readiness != f"READY {phase} {launch_nonce}\n":
            raise V19ParentError(f"{label} bootstrap readiness authentication failed")
        process.stdin.write(f"GO {launch_nonce}\n")
        process.stdin.flush()
        process.stdin.close()
        process.stdin = None
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            job.terminate()
            _drain(process)
            _wait_job_empty(job, process, label)
            raise V19ParentError(f"{label} timed out after {timeout:.3f}s") from exc
        job.terminate()
        _wait_job_empty(job, process, label)
        return PhaseResult(process.returncode, (stdout or "") if stdout_mode == "pipe" else "", stderr or "")
    except BaseException:
        try:
            job.terminate()
        except V19ParentError:
            pass
        if process is not None and process.poll() is None:
            _drain(process)
        if process is not None:
            _wait_job_empty(job, process, label)
        raise
    finally:
        job.close()


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
        raise V19ParentError(f"{label} POSIX process group survived cleanup")


def _posix_phase(
    phase: str, *, evidence_nonce: str, label: str, timeout: float,
    env: dict[str, str] | None, stdout_mode: str,
) -> PhaseResult:
    junit = _validated_junit_path(evidence_nonce, require_file=phase == "worker")
    command = _phase_command(phase, junit)
    process = subprocess.Popen(
        command, cwd=PROJECT, env=env, text=True, shell=False, start_new_session=True,
        stdout=subprocess.PIPE if stdout_mode == "pipe" else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    pgid = os.getpgid(process.pid)
    stdout = stderr = ""
    failure: BaseException | None = None
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        failure = V19ParentError(f"{label} timed out after {timeout:.3f}s")
        failure.__cause__ = exc
        timed_out = True
    except BaseException as exc:
        failure = exc
    residual = False
    try:
        residual = _posix_group_exists(pgid)
    except BaseException as exc:
        if failure is None:
            failure = exc
        residual = True
    cleanup_error: BaseException | None = None
    if failure is not None or residual:
        try:
            _kill_posix_group(pgid)
            _drain(process)
            _wait_posix_group_empty(pgid, label)
        except BaseException as exc:
            cleanup_error = exc
    else:
        try:
            _wait_posix_group_empty(pgid, label)
        except BaseException as exc:
            cleanup_error = exc
    if cleanup_error is not None:
        if failure is not None:
            raise cleanup_error from failure
        raise cleanup_error
    if failure is not None:
        raise failure
    if residual:
        raise V19ParentError(f"{label} left residual descendants after normal completion")
    if timed_out:
        raise V19ParentError(f"{label} timed out")
    return PhaseResult(process.returncode, stdout or "", stderr or "")


def _plain_component(path: Path) -> None:
    info = path.lstat()
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & reparse:
        raise V19ParentError("private evidence path contains a reparse component")


def _validated_junit_path(evidence_nonce: str, *, require_file: bool) -> Path:
    if _TOKEN.fullmatch(evidence_nonce) is None:
        raise V19ParentError("private evidence nonce is invalid")
    base = PRIVATE_BASE.resolve(strict=True)
    expected = Path(tempfile.gettempdir()).resolve(strict=True) / PRIVATE_BASE.name
    if base != expected:
        raise V19ParentError("private evidence base realpath is invalid")
    _plain_component(PRIVATE_BASE)
    directory = PRIVATE_BASE / evidence_nonce
    _plain_component(directory)
    resolved = directory.resolve(strict=True)
    if resolved.parent != base or resolved.name != evidence_nonce:
        raise V19ParentError("private evidence directory realpath is invalid")
    sentinel = directory / SENTINEL
    _plain_component(sentinel)
    if sentinel.read_text(encoding="ascii") != f"{_BOOTSTRAP_CONTRACT}:{evidence_nonce}\n":
        raise V19ParentError("private evidence sentinel is invalid")
    junit = directory / "focused.junit.xml"
    if require_file:
        _plain_component(junit)
        if not junit.is_file() or junit.resolve(strict=True).parent != resolved:
            raise V19ParentError("fresh focused JUnit is outside private evidence scope")
    elif junit.exists():
        raise V19ParentError("fresh focused JUnit already exists")
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
            f"{_BOOTSTRAP_CONTRACT}:{self.nonce}\n", encoding="ascii", newline="\n",
        )
        _validated_junit_path(self.nonce, require_file=False)
        return self.nonce

    def __exit__(self, exc_type, exc, traceback) -> None:
        shutil.rmtree(self.directory)


def _run_phase(
    phase: str, *, evidence_nonce: str, label: str, timeout: float,
    env: dict[str, str] | None = None, stdout_mode: str = "pipe",
) -> PhaseResult:
    if not isinstance(phase, str) or phase not in {"focused", "worker"}:
        raise V19ParentError("phase id must be focused or worker")
    if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise V19ParentError(f"{label} timeout is invalid")
    if stdout_mode not in {"pipe", "devnull"}:
        raise V19ParentError(f"{label} stdout mode is invalid")
    _validated_junit_path(evidence_nonce, require_file=phase == "worker")
    runner = _windows_phase if os.name == "nt" else _posix_phase
    return runner(phase, evidence_nonce=evidence_nonce, label=label, timeout=timeout, env=env, stdout_mode=stdout_mode)


def _remaining(started: float, total_timeout: int) -> float:
    if type(total_timeout) is not int or total_timeout <= POST_KILL_DRAIN_SECONDS + 1:
        raise V19ParentError("total timeout is invalid")
    remaining = total_timeout - (time.monotonic() - started)
    if remaining <= POST_KILL_DRAIN_SECONDS + 1:
        raise V19ParentError(f"total verifier deadline exceeded after {total_timeout}s")
    return remaining


def _phase_timeout(started: float, total_timeout: int) -> float:
    return _remaining(started, total_timeout) - POST_KILL_DRAIN_SECONDS


def _parse_worker_marker(stdout: str) -> dict[str, object]:
    lines = stdout.splitlines()
    prefix = MARKER + " "
    matching = [line for line in lines if line.startswith(prefix)]
    if len(matching) != 1 or len(lines) != 1:
        raise V19ParentError("pure worker marker is missing, duplicated, or contaminated")
    import json  # noqa: PLC0415
    try:
        payload = json.loads(matching[0][len(prefix):])
    except json.JSONDecodeError as exc:
        raise V19ParentError("pure worker marker payload is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {"artifacts", "focused_passed", "live_scan_files", "root_sha256"}:
        raise V19ParentError("pure worker marker payload schema is invalid")
    return payload


def _run_parent(*, total_timeout: int = TOTAL_TIMEOUT_SECONDS) -> dict[str, object]:
    started = time.monotonic()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with _PrivateEvidence() as evidence_nonce:
        focused = _run_phase(
            "focused", evidence_nonce=evidence_nonce, label="fixed focused pytest",
            timeout=_phase_timeout(started, total_timeout), env=env,
        )
        if focused.returncode:
            raise V19ParentError("fixed focused pytest failed")
        worker = _run_phase(
            "worker", evidence_nonce=evidence_nonce, label="fixed pure artifact worker",
            timeout=_phase_timeout(started, total_timeout), env=env,
        )
        if worker.returncode:
            raise V19ParentError("fixed pure artifact worker failed")
        payload = _parse_worker_marker(worker.stdout)
    _remaining(started, total_timeout)
    return payload


def main() -> int:
    import json  # noqa: PLC0415
    print(MARKER + " " + json.dumps(_run_parent(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
