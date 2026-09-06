"""Run the bounded two-phase verifier for Capability Nexus V16."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


PROJECT = Path(__file__).resolve().parents[1]
TESTS = "tests/test_capability_nexus_v16.py"
WORKER = "scripts/verify_phase5_capability_nexus_v16_worker.py"
TOTAL_TIMEOUT_SECONDS = 180
MARKER = "P53_CAPABILITY_NEXUS_V16_EVIDENCE_OK"


class V16ParentError(RuntimeError):
    pass


def _remaining(started: float, total_timeout: int) -> int:
    if type(total_timeout) is not int or total_timeout <= 0:
        raise V16ParentError("total timeout is invalid")
    remaining = total_timeout - (time.monotonic() - started)
    if remaining < 1:
        raise V16ParentError(f"total verifier deadline exceeded after {total_timeout}s")
    return max(1, int(remaining))


def _run_phase(command: list[str], *, label: str, timeout: int, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=PROJECT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise V16ParentError(f"{label} timed out after {timeout}s") from exc


def _parse_worker_marker(stdout: str) -> dict[str, object]:
    lines = stdout.splitlines()
    prefix = MARKER + " "
    matching = [line for line in lines if line.startswith(prefix)]
    if len(matching) != 1 or len(lines) != 1:
        raise V16ParentError("pure worker marker is missing, duplicated, or contaminated")
    try:
        payload = json.loads(matching[0][len(prefix):])
    except json.JSONDecodeError as exc:
        raise V16ParentError("pure worker marker payload is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "artifacts", "focused_passed", "live_scan_files", "root_sha256"
    }:
        raise V16ParentError("pure worker marker payload schema is invalid")
    return payload


def _run_parent(
    *,
    total_timeout: int = TOTAL_TIMEOUT_SECONDS,
    focused_command: list[str] | None = None,
    worker_command: list[str] | None = None,
) -> dict[str, object]:
    started = time.monotonic()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    with tempfile.TemporaryDirectory(prefix="onyx-p53-v16-parent-") as directory:
        fresh_junit = Path(directory) / "focused.junit.xml"
        focused = focused_command or [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            TESTS,
            "--disable-warnings",
            "--maxfail=1",
            f"--junitxml={fresh_junit}",
        ]
        completed = _run_phase(
            focused,
            label="direct focused pytest",
            timeout=_remaining(started, total_timeout),
            env=env,
        )
        if completed.returncode:
            raise V16ParentError("direct focused pytest failed")
        worker = worker_command or [sys.executable, WORKER, "--fresh-focused-junit", str(fresh_junit)]
        completed = _run_phase(
            worker,
            label="pure artifact worker",
            timeout=_remaining(started, total_timeout),
            env=env,
        )
        if completed.returncode:
            raise V16ParentError("pure artifact worker failed")
        result = _parse_worker_marker(completed.stdout)
    _remaining(started, total_timeout)
    return result


def main() -> int:
    print(MARKER + " " + json.dumps(_run_parent(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
