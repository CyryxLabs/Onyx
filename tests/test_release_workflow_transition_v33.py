from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from core.onyx_hud_current_acceptance_v26 import (
    CURRENT_RUNTIME_PATHS,
    MANIFEST_RELATIVE,
    PREDECESSOR_ACCEPTANCE_RELATIVE,
    PREDECESSOR_MANIFEST_RELATIVE,
)
from scripts.verify_release_workflow_v33 import (
    RECEIPT_RELATIVE,
    RELEASE_V31_RELATIVE,
    RELEASE_V32_RECEIPT_RELATIVE,
    RELEASE_V32_RELATIVE,
    RELEASE_V32_SHA256,
    RELEASE_V32_VERIFIER_RELATIVE,
    RELEASE_V33_RELATIVE,
    RELEASE_V33_ROOT_SHA256,
    RELEASE_V33_SHA256,
    TEST_RELATIVE,
    VERIFIER_RELATIVE,
    ReleaseWorkflowV33Error,
    _validate_chronology,
    verify_release_workflow_v33,
)
from scripts.verify_release_workflow_v39 import verify_release_workflow_v39


ROOT = Path(__file__).resolve().parents[1]


def _chronology_records() -> tuple[dict[str, object], dict[str, object]]:
    transition = json.loads(
        (ROOT / RELEASE_V33_RELATIVE).read_text(encoding="utf-8")
    )
    predecessor = json.loads(
        (ROOT / RELEASE_V32_RELATIVE).read_text(encoding="utf-8")
    )
    return transition, predecessor


def _copy_v33_closure(destination: Path) -> None:
    transition = json.loads((ROOT / RELEASE_V33_RELATIVE).read_text(encoding="utf-8"))
    predecessor = json.loads(
        (ROOT / RELEASE_V32_RELATIVE).read_text(encoding="utf-8")
    )
    v31 = json.loads((ROOT / RELEASE_V31_RELATIVE).read_text(encoding="utf-8"))
    relatives = {
        RELEASE_V33_RELATIVE,
        RELEASE_V32_RELATIVE,
        RELEASE_V31_RELATIVE,
        RELEASE_V32_RECEIPT_RELATIVE,
        RELEASE_V32_VERIFIER_RELATIVE,
        RECEIPT_RELATIVE,
        VERIFIER_RELATIVE,
        TEST_RELATIVE,
        MANIFEST_RELATIVE,
        PREDECESSOR_ACCEPTANCE_RELATIVE,
        PREDECESSOR_MANIFEST_RELATIVE,
        *CURRENT_RUNTIME_PATHS,
        *(Path(entry["path"]) for entry in transition["current_release_paths"]),
        *(Path(entry["path"]) for entry in predecessor["current_release_paths"]),
        *(Path(entry["path"]) for entry in v31["current_release_paths"]),
    }
    for relative in relatives:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)


def test_release_v33_authenticates_icon_fix_v32_and_runtime() -> None:
    verify_release_workflow_v39(ROOT)
    transition = json.loads(
        (ROOT / RELEASE_V33_RELATIVE).read_text(encoding="utf-8")
    )
    assert hashlib.sha256((ROOT / RELEASE_V33_RELATIVE).read_bytes()).hexdigest() == (
        RELEASE_V33_SHA256
    )
    assert hashlib.sha256((ROOT / RELEASE_V32_RELATIVE).read_bytes()).hexdigest() == (
        RELEASE_V32_SHA256
    )
    assert transition["schema"] == "onyx.release-workflow-transition.v33"
    assert transition["current_root_sha256"] == RELEASE_V33_ROOT_SHA256
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert {
        "packaging/assets/onyx-app-icon-master-v2.png",
        "packaging/onyx.spec",
        "scripts/build_release.py",
        "scripts/generate_icons.py",
        "scripts/verify_phase5_exit_retirement_v1.py",
        "scripts/verify_release_runtime_closure_v1.py",
        "tests/test_onyx_app_icon_v1.py",
        "tests/test_release_workflow_transition_v32.py",
    } <= paths
    assert VERIFIER_RELATIVE.as_posix() not in paths
    assert RECEIPT_RELATIVE.as_posix() not in paths
    assert TEST_RELATIVE.as_posix() not in paths


def test_release_v33_accepts_only_the_exact_authenticated_clock_anomaly() -> None:
    transition, predecessor = _chronology_records()
    _validate_chronology(transition, predecessor)
    assert transition["logical_sequence"] == 33
    assert transition["predecessor_clock_anomaly"] == {
        "predecessor_issued_at": predecessor["issued_at"],
        "observed_at": transition["issued_at"],
        "reason": "predecessor_future_dated",
    }


@pytest.mark.parametrize(
    "invalid",
    ["not-a-date", "2026-08-05T04:16:06", "2026-08-05 04:16:06-04:00"],
)
def test_release_v33_rejects_invalid_or_naive_rfc3339(invalid: str) -> None:
    transition, predecessor = _chronology_records()
    transition["issued_at"] = invalid
    transition["predecessor_clock_anomaly"]["observed_at"] = invalid
    with pytest.raises(ReleaseWorkflowV33Error, match="timezone-aware RFC3339"):
        _validate_chronology(transition, predecessor)


@pytest.mark.parametrize(
    "invalid",
    ["invalid", "2026-08-05T09:10:00", "2026-08-05 09:10:00-04:00"],
)
def test_release_v33_rejects_invalid_or_naive_predecessor_rfc3339(
    invalid: str,
) -> None:
    transition, predecessor = _chronology_records()
    predecessor["issued_at"] = invalid
    transition["predecessor_clock_anomaly"]["predecessor_issued_at"] = invalid
    with pytest.raises(ReleaseWorkflowV33Error, match="timezone-aware RFC3339"):
        _validate_chronology(transition, predecessor)


def test_release_v33_rejects_equal_predecessor_time() -> None:
    transition, predecessor = _chronology_records()
    transition["issued_at"] = predecessor["issued_at"]
    transition["predecessor_clock_anomaly"]["observed_at"] = predecessor["issued_at"]
    with pytest.raises(ReleaseWorkflowV33Error, match="cannot be equal"):
        _validate_chronology(transition, predecessor)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("predecessor_issued_at", "2026-08-05T09:11:00-04:00"),
        ("observed_at", "2026-08-05T04:16:07-04:00"),
        ("reason", "clock_skew"),
    ],
)
def test_release_v33_rejects_backdated_clock_anomaly_drift(
    field: str, value: str
) -> None:
    transition, predecessor = _chronology_records()
    drifted = copy.deepcopy(transition)
    drifted["predecessor_clock_anomaly"][field] = value
    with pytest.raises(ReleaseWorkflowV33Error, match="clock anomaly drifted"):
        _validate_chronology(drifted, predecessor)


def test_release_v33_rejects_missing_or_false_clock_anomaly() -> None:
    transition, predecessor = _chronology_records()
    missing = copy.deepcopy(transition)
    missing["predecessor_clock_anomaly"] = None
    with pytest.raises(ReleaseWorkflowV33Error, match="clock anomaly drifted"):
        _validate_chronology(missing, predecessor)

    future = copy.deepcopy(transition)
    future["issued_at"] = "2026-08-05T09:11:00-04:00"
    with pytest.raises(ReleaseWorkflowV33Error, match="false predecessor"):
        _validate_chronology(future, predecessor)


def test_release_v33_rejects_non_successor_logical_sequence() -> None:
    transition, predecessor = _chronology_records()
    transition["logical_sequence"] = 32
    with pytest.raises(ReleaseWorkflowV33Error, match="logical sequence drifted"):
        _validate_chronology(transition, predecessor)


def test_release_v33_rejects_isolated_icon_generator_tamper(tmp_path: Path) -> None:
    _copy_v33_closure(tmp_path)
    target = tmp_path / "scripts/generate_icons.py"
    target.write_bytes(target.read_bytes() + b"\n# isolated icon tamper\n")

    with pytest.raises(ReleaseWorkflowV33Error, match="current release target drifted"):
        verify_release_workflow_v33(tmp_path)


def test_release_v33_rejects_immutable_v32_fixture_tamper(tmp_path: Path) -> None:
    _copy_v33_closure(tmp_path)
    target = tmp_path / RELEASE_V32_RELATIVE
    target.write_bytes(target.read_bytes() + b"\n")

    with pytest.raises(
        ReleaseWorkflowV33Error, match="Release V32 predecessor digest drifted"
    ):
        verify_release_workflow_v33(tmp_path)


def test_release_v33_external_receipt_pins_ungraphed_verifier() -> None:
    receipt = json.loads((ROOT / RECEIPT_RELATIVE).read_text(encoding="utf-8"))
    assert receipt["verifier_sha256"] == hashlib.sha256(
        (ROOT / VERIFIER_RELATIVE).read_bytes()
    ).hexdigest()
    assert receipt["release_sha256"] == RELEASE_V33_SHA256
    current_test_sha = hashlib.sha256((ROOT / TEST_RELATIVE).read_bytes()).hexdigest()
    assert receipt["test_sha256"] == (
        "b1896d4421525bfcdcefd4998f908ef89277fd60710a1c3fa0c3645d73ab1f36"
    )
    assert current_test_sha != receipt["test_sha256"]
    current = verify_release_workflow_v39(ROOT)["transition"]
    current_hashes = {
        entry["path"]: entry["sha256"]
        for entry in current["current_release_paths"]
    }
    assert current_hashes[TEST_RELATIVE.as_posix()] == current_test_sha
