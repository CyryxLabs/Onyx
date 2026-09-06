"""Monitor an installed Onyx Windows process and emit durable soak evidence."""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _application_error_count(started_at: datetime, executable_name: str) -> int:
    """Count Application Error 1000 records for the executable since start."""

    try:
        import pywintypes
        import win32evtlog

        handle = win32evtlog.OpenEventLog(None, "Application")
        flags = (
            win32evtlog.EVENTLOG_BACKWARDS_READ
            | win32evtlog.EVENTLOG_SEQUENTIAL_READ
        )
        count = 0
        try:
            while True:
                records = win32evtlog.ReadEventLog(handle, flags, 0)
                if not records:
                    break
                stop = False
                for record in records:
                    generated = record.TimeGenerated
                    if isinstance(generated, pywintypes.TimeType):
                        generated = datetime.fromtimestamp(
                            generated.timestamp(),
                            tz=UTC,
                        )
                    elif generated.tzinfo is None:
                        generated = generated.replace(tzinfo=UTC)
                    if generated < started_at:
                        stop = True
                        break
                    event_id = int(record.EventID) & 0xFFFF
                    strings = "\n".join(record.StringInserts or ())
                    if event_id == 1000 and executable_name.lower() in strings.lower():
                        count += 1
                if stop:
                    break
        finally:
            win32evtlog.CloseEventLog(handle)
        return count
    except (ImportError, OSError, ValueError):
        return 0


def _process_responding(pid: int) -> bool:
    """Return whether the process owns a top-level window and none is hung.

    A resident Onyx window remains a valid health surface after it is hidden to
    the notification area. Visibility is therefore not a responsiveness
    condition; ``IsHungAppWindow`` is.
    """

    if os.name != "nt":
        return True
    user32 = ctypes.windll.user32
    matching_windows: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def visit(hwnd: int, _parameter: int) -> bool:
        owner = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            matching_windows.append(hwnd)
        return True

    user32.EnumWindows(visit, 0)
    return bool(matching_windows) and not any(
        bool(user32.IsHungAppWindow(hwnd)) for hwnd in matching_windows
    )


@dataclass(frozen=True)
class Thresholds:
    average_cpu_pct: float
    maximum_working_set_bytes: int
    maximum_private_memory_bytes: int
    maximum_working_set_growth_bytes: int
    maximum_application_errors: int = 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    _replace_with_retry(temporary, path)


def _replace_with_retry(
    temporary: Path,
    destination: Path,
    *,
    attempts: int = 40,
    initial_delay_seconds: float = 0.05,
) -> None:
    """Atomically publish evidence despite short-lived Windows reader locks.

    PowerShell and antivirus readers can briefly open the destination without
    delete sharing.  ``os.replace`` then raises ``PermissionError`` even though
    neither the payload nor the monitored process is defective.  Retrying the
    same complete temporary file preserves fail-closed atomic publication while
    preventing an evidence reader from terminating an eight-hour monitor.
    """

    if attempts < 1:
        raise ValueError("attempts must be positive")
    delay = initial_delay_seconds
    for attempt in range(attempts):
        try:
            temporary.replace(destination)
            return
        except PermissionError:
            if attempt + 1 >= attempts:
                raise
            time.sleep(delay)
            delay = min(delay * 1.5, 0.5)


def _write_csv(path: Path, samples: Sequence[dict[str, Any]]) -> None:
    columns = (
        "timestamp_utc",
        "elapsed_seconds",
        "responding",
        "whole_host_cpu_pct",
        "working_set_bytes",
        "private_memory_bytes",
        "threads",
    )
    lines = [",".join(columns)]
    lines.extend(
        ",".join(str(sample[column]) for column in columns) for sample in samples
    )
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _replace_with_retry(temporary, path)


def _metrics(samples: Sequence[dict[str, Any]]) -> dict[str, float | int]:
    if not samples:
        return {
            "average_whole_host_cpu_pct": 0.0,
            "maximum_working_set_bytes": 0,
            "maximum_private_memory_bytes": 0,
            "working_set_growth_bytes": 0,
        }
    working = [int(item["working_set_bytes"]) for item in samples]
    return {
        "average_whole_host_cpu_pct": round(
            sum(float(item["whole_host_cpu_pct"]) for item in samples)
            / len(samples),
            6,
        ),
        "maximum_working_set_bytes": max(working),
        "maximum_private_memory_bytes": max(
            int(item["private_memory_bytes"]) for item in samples
        ),
        "working_set_growth_bytes": max(0, max(working) - working[0]),
    }


def _rotation_gate_proven(args: argparse.Namespace) -> bool:
    return (
        args.rotation_receives > 0
        and args.microphone_starts > 0
        and args.playback_starts > 0
        and args.rotation_application_errors == 0
    )


def monitor(args: argparse.Namespace) -> int:
    executable = args.executable.resolve()
    receipt_path = args.receipt.resolve()
    samples_path = args.samples.resolve()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    samples_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.unlink(missing_ok=True)
    samples_path.unlink(missing_ok=True)

    thresholds = Thresholds(
        average_cpu_pct=args.average_cpu_limit,
        maximum_working_set_bytes=args.working_set_limit,
        maximum_private_memory_bytes=args.private_memory_limit,
        maximum_working_set_growth_bytes=args.working_set_growth_limit,
    )
    process = psutil.Process(args.pid)
    process_started_at = datetime.fromtimestamp(process.create_time(), tz=UTC)
    if Path(process.exe()).resolve() != executable:
        raise RuntimeError("monitored PID does not own the expected executable")
    started_at = _utc_now()
    samples: list[dict[str, Any]] = []
    all_responsive = True
    failure_reason: str | None = None
    application_errors = 0
    logical_processors = psutil.cpu_count(logical=True) or 1
    process.cpu_percent(interval=None)

    rotation_proven = _rotation_gate_proven(args)

    def receipt(status: str, elapsed: float, alive: bool) -> dict[str, Any]:
        metrics = _metrics(samples)
        return {
            "contract": "OnyxWindowsLongSession.v1",
            "candidate": args.candidate,
            "status": status,
            "pid": args.pid,
            "executable": str(executable),
            "executable_sha256": _sha256(executable),
            "process_started_at": _iso(process_started_at),
            "started_at": _iso(started_at),
            "updated_at": _iso(_utc_now()),
            "duration_required_seconds": args.duration,
            "duration_observed_seconds": round(elapsed, 3),
            "sample_interval_seconds": args.interval,
            "sample_count": len(samples),
            "full_duration": elapsed >= args.duration,
            "alive_at_update": alive,
            "all_responsive": all_responsive,
            **metrics,
            "application_error_count": application_errors,
            "failure_reason": failure_reason,
            "rotation_gate": {
                "status": "passed" if rotation_proven else "not_proven",
                "required_for_performance_status": False,
                "gemini_receive_starts": args.rotation_receives,
                "microphone_starts": args.microphone_starts,
                "playback_starts": args.playback_starts,
                "application_errors_at_gate": args.rotation_application_errors,
            },
            "artifacts": {
                "setup_sha256": args.setup_sha256,
                "portable_sha256": args.portable_sha256,
                "bundle_root_sha256": args.bundle_root_sha256,
                "source_transition_sha256": args.source_transition_sha256,
                "sbom_sha256": args.sbom_sha256,
            },
            "thresholds": {
                "average_whole_host_cpu_pct": thresholds.average_cpu_pct,
                "maximum_working_set_bytes": thresholds.maximum_working_set_bytes,
                "maximum_private_memory_bytes": (
                    thresholds.maximum_private_memory_bytes
                ),
                "maximum_working_set_growth_bytes": (
                    thresholds.maximum_working_set_growth_bytes
                ),
                "maximum_application_errors": thresholds.maximum_application_errors,
                "require_all_responsive": True,
            },
            "samples_csv": str(samples_path),
            "process_left_running": alive,
        }

    _write_json(receipt_path, receipt("in_progress", 0.0, True))
    next_sample = time.monotonic() + args.interval
    started_monotonic = time.monotonic()
    while True:
        elapsed = time.monotonic() - started_monotonic
        if elapsed >= args.duration:
            break
        time.sleep(min(args.poll_interval, max(0.1, args.duration - elapsed)))
        elapsed = time.monotonic() - started_monotonic
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            failure_reason = "process_exited_before_duration"
            break
        responding = _process_responding(args.pid)
        all_responsive = all_responsive and responding
        if time.monotonic() >= next_sample:
            memory = process.memory_info()
            raw_cpu = process.cpu_percent(interval=None)
            samples.append(
                {
                    "timestamp_utc": _iso(_utc_now()),
                    "elapsed_seconds": round(elapsed, 3),
                    "responding": responding,
                    "whole_host_cpu_pct": round(raw_cpu / logical_processors, 6),
                    "working_set_bytes": int(memory.rss),
                    "private_memory_bytes": int(
                        getattr(memory, "private", memory.vms)
                    ),
                    "threads": process.num_threads(),
                }
            )
            application_errors = _application_error_count(
                started_at,
                executable.name,
            )
            _write_csv(samples_path, samples)
            _write_json(receipt_path, receipt("in_progress", elapsed, True))
            next_sample += args.interval

    elapsed = time.monotonic() - started_monotonic
    alive = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    application_errors = _application_error_count(started_at, executable.name)
    values = _metrics(samples)
    if failure_reason is None:
        if elapsed < args.duration:
            failure_reason = "duration_not_reached"
        elif not alive:
            failure_reason = "process_exited_at_completion"
        elif not all_responsive:
            failure_reason = "unresponsive_sample"
        elif values["average_whole_host_cpu_pct"] > thresholds.average_cpu_pct:
            failure_reason = "average_cpu_threshold_exceeded"
        elif values["maximum_working_set_bytes"] > thresholds.maximum_working_set_bytes:
            failure_reason = "working_set_threshold_exceeded"
        elif (
            values["maximum_private_memory_bytes"]
            > thresholds.maximum_private_memory_bytes
        ):
            failure_reason = "private_memory_threshold_exceeded"
        elif (
            values["working_set_growth_bytes"]
            > thresholds.maximum_working_set_growth_bytes
        ):
            failure_reason = "working_set_growth_threshold_exceeded"
        elif application_errors > thresholds.maximum_application_errors:
            failure_reason = "application_error_detected"
    status = "failed" if failure_reason else "passed"
    _write_json(receipt_path, receipt(status, elapsed, alive))
    return 1 if failure_reason else 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--pid", type=int, required=True)
    result.add_argument("--candidate", required=True)
    result.add_argument("--executable", type=Path, required=True)
    result.add_argument("--receipt", type=Path, required=True)
    result.add_argument("--samples", type=Path, required=True)
    result.add_argument("--duration", type=float, default=28_800)
    result.add_argument("--interval", type=float, default=60)
    result.add_argument("--poll-interval", type=float, default=5)
    result.add_argument("--average-cpu-limit", type=float, default=1.5)
    result.add_argument("--working-set-limit", type=int, default=786_432_000)
    result.add_argument("--private-memory-limit", type=int, default=1_610_612_736)
    result.add_argument("--working-set-growth-limit", type=int, default=268_435_456)
    result.add_argument("--rotation-receives", type=int, required=True)
    result.add_argument("--microphone-starts", type=int, required=True)
    result.add_argument("--playback-starts", type=int, required=True)
    result.add_argument("--rotation-application-errors", type=int, required=True)
    result.add_argument("--setup-sha256", required=True)
    result.add_argument("--portable-sha256", required=True)
    result.add_argument("--bundle-root-sha256", required=True)
    result.add_argument("--source-transition-sha256", required=True)
    result.add_argument("--sbom-sha256", required=True)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    if os.name != "nt":
        raise RuntimeError("Windows long-session monitoring requires Windows")
    return monitor(parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
