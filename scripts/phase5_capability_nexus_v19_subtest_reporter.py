"""Deterministic pytest reporter for the frozen V19 regression evidence."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from _pytest.subtests import SubtestReport


_BASE: dict[str, dict[str, str]] = {}
_SUBTESTS: list[dict[str, object]] = []
_ORDINALS: dict[str, int] = {}


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _identity(kind: str, value: object) -> str:
    return hashlib.sha256(f"{kind}\0{_canonical(value)}".encode("ascii")).hexdigest()


def pytest_runtest_logreport(report: Any) -> None:
    if report.when != "call":
        return
    parent = str(report.nodeid)
    outcome = str(report.outcome)
    if isinstance(report, SubtestReport):
        ordinal = _ORDINALS.get(parent, 0)
        _ORDINALS[parent] = ordinal + 1
        context = {
            "message": report.context.msg,
            "parameters": dict(sorted(report.context.kwargs.items())),
        }
        descriptor = {"context": context, "ordinal": ordinal, "parent_nodeid": parent}
        identity = _identity("subtest", descriptor)
        _SUBTESTS.append(
            {
                "context": context,
                "identity": identity,
                "nodeid": f"{parent}::subtest[{identity[:16]}]",
                "ordinal": ordinal,
                "outcome": outcome,
                "parent_nodeid": parent,
            }
        )
        return
    record = {"nodeid": parent, "outcome": outcome}
    record["identity"] = _identity("base", record)
    if parent in _BASE:
        raise RuntimeError(f"duplicate base test report: {parent}")
    _BASE[parent] = record


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    destination = os.environ.get("ONYX_P53_V19_SUBTEST_REPORT")
    if not destination:
        raise RuntimeError("ONYX_P53_V19_SUBTEST_REPORT is required")
    payload = {
        "base_tests": sorted(_BASE.values(), key=lambda item: item["nodeid"]),
        "contract": "Phase53CapabilityNexusRegressionReport.v19",
        "exit_status": int(exitstatus),
        "subtests": sorted(_SUBTESTS, key=lambda item: (item["parent_nodeid"], item["ordinal"])),
    }
    Path(destination).write_text(_canonical(payload) + "\n", encoding="utf-8", newline="\n")
