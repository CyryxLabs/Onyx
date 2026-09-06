from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts.verify_release_workflow_v42 import (
    EXPECTED_CLOCK_ANOMALY,
    RECEIPT_RELATIVE,
    RELEASE_V41_RELATIVE,
    RELEASE_V42_RELATIVE,
    RELEASE_V42_ROOT_SHA256,
    RELEASE_V42_SHA256,
    TEST_RELATIVE,
    VERIFIER_RELATIVE,
    ReleaseWorkflowV42Error,
    _validate_chronology,
    verify_release_workflow_v42,
)


ROOT = Path(__file__).resolve().parents[1]


def _chronology_records() -> tuple[dict[str, object], dict[str, object]]:
    transition = json.loads((ROOT / RELEASE_V42_RELATIVE).read_text(encoding="utf-8"))
    predecessor = json.loads((ROOT / RELEASE_V41_RELATIVE).read_text(encoding="utf-8"))
    return transition, predecessor


def test_release_v42_authenticates_linux_preflight_and_mission_corrections() -> None:
    fixture = ROOT / RELEASE_V42_RELATIVE
    transition = json.loads(fixture.read_text(encoding="utf-8"))
    assert transition["schema"] == "onyx.release-workflow-transition.v42"
    assert transition["current_root_sha256"] == RELEASE_V42_ROOT_SHA256
    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == RELEASE_V42_SHA256
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert "scripts/build_release.py" in paths
    assert "core/missions.py" in paths
    assert "scripts/monitor_windows_long_session.py" in paths


def test_release_v42_records_exact_predecessor_clock_anomaly() -> None:
    transition, predecessor = _chronology_records()
    _validate_chronology(transition, predecessor)
    assert transition["predecessor_clock_anomaly"] == EXPECTED_CLOCK_ANOMALY
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert VERIFIER_RELATIVE.as_posix() not in paths
    assert RECEIPT_RELATIVE.as_posix() not in paths
    assert TEST_RELATIVE.as_posix() not in paths


def test_release_v42_rejects_clock_anomaly_drift() -> None:
    transition, predecessor = _chronology_records()
    drifted = copy.deepcopy(transition)
    drifted["predecessor_clock_anomaly"]["reason"] = "clock_skew"
    with pytest.raises(ReleaseWorkflowV42Error, match="clock anomaly drifted"):
        _validate_chronology(drifted, predecessor)

    false = copy.deepcopy(transition)
    false["issued_at"] = "2026-08-10T19:01:00-04:00"
    false["predecessor_clock_anomaly"]["observed_at"] = false["issued_at"]
    with pytest.raises(ReleaseWorkflowV42Error, match="false predecessor"):
        _validate_chronology(false, predecessor)


def test_release_v42_rejects_noncanonical_project_root(tmp_path: Path) -> None:
    with pytest.raises((FileNotFoundError, ReleaseWorkflowV42Error)):
        verify_release_workflow_v42(tmp_path)
