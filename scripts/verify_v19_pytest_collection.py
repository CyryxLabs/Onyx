"""Fail closed unless pytest collects the named V19 regression surface."""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[1]
V19_TEST_FILES: Final = (
    "tests/test_capability_nexus_current_v1.py",
    "tests/test_capability_nexus_v19.py",
    "tests/test_dayops_connection_v19.py",
    "tests/test_dayops_persistent_v19.py",
    "tests/test_dayops_ui_v19.py",
    "tests/test_onyx_hud_current_acceptance_v19.py",
    "tests/test_onyx_live_activation_v19.py",
)


def _node_ids(stdout: str) -> tuple[str, ...]:
    return tuple(
        line.strip().replace("\\", "/")
        for line in stdout.splitlines()
        if "::" in line and line.strip().startswith("tests/")
    )


def collect_v19_tests(
    *,
    root: Path = ROOT,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, ...]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-m",
        "not skip and not skipif",
        *V19_TEST_FILES,
    ]
    result = runner(
        command,
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            "V19 pytest collection failed: "
            + (result.stderr or result.stdout)[-2_000:]
        )
    nodes = _node_ids(result.stdout)
    if not nodes:
        raise RuntimeError("V19 pytest collection returned zero tests (non-skipped)")
    missing = [
        path
        for path in V19_TEST_FILES
        if not any(node.startswith(path + "::") for node in nodes)
    ]
    if missing:
        raise RuntimeError(
            "V19 pytest collection omitted named files or has no non-skipped nodes: "
            + ", ".join(missing)
        )
    return nodes


def main() -> int:
    nodes = collect_v19_tests()
    print(
        json.dumps(
            {
                "contract": "OnyxV19PytestCollection.v1",
                "files": list(V19_TEST_FILES),
                "status": "passed",
                "tests_collected": len(nodes),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
