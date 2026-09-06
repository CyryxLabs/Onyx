from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v1 as current_retirement
from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V20 = ROOT / "tests/fixtures/phase5_current_successor_transition_v20.json"
V21 = ROOT / "tests/fixtures/phase5_current_successor_transition_v21.json"
RELEASE_V6 = ROOT / "tests/fixtures/release_workflow_transition_v6.json"
RELEASE_V7 = ROOT / "tests/fixtures/release_workflow_transition_v7.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v21_authenticates_v20_and_only_rebinds_runtime_isolation_targets() -> None:
    _clear()
    transition = json.loads(V21.read_text(encoding="utf-8"))
    predecessor = json.loads(V20.read_text(encoding="utf-8"))

    assert hashlib.sha256(V21.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V21_SHA256
    )
    assert hashlib.sha256(V20.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V20_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v21"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v20.json",
        "sha256": retirement.CURRENT_TRANSITION_V20_SHA256,
    }
    changed_historical = {
        current["path"]
        for current, prior in zip(
            transition["historical_bindings"],
            predecessor["historical_bindings"],
            strict=True,
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    changed_successors = {
        current["path"]
        for current, prior in zip(
            transition["named_successors"],
            predecessor["named_successors"],
            strict=True,
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert changed_historical == {"scripts/build_release.py"}
    assert changed_successors == {
        "scripts/package_hygiene.py",
        "tests/test_onyx_live_activation_v19.py",
    }
    assert transition["policy"]["runtime_authority_changes"] is True
    assert transition["current_root_sha256"] == (
        "31f90a01875c6f0558e329cdbbb125c7d805a9e3e9d56c9e008a36cf158c4980"
    )


def test_release_v7_authenticates_v6_and_binds_validation_isolation() -> None:
    _clear()
    release = json.loads(RELEASE_V7.read_text(encoding="utf-8"))

    assert hashlib.sha256(RELEASE_V7.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V7_SHA256
    )
    assert hashlib.sha256(RELEASE_V6.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V6_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v7"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v6.json",
        "sha256": retirement.RELEASE_TRANSITION_V6_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert "scripts/package_hygiene.py" in paths
    assert "tests/test_runtime_validation_bundle_v1.py" in paths
    assert release["current_root_sha256"] == (
        "b4ed1b3b1695e7498835e01675281ad14cf14d7ae5c52d13d4b8b4c69e399e44"
    )


def test_historical_retirement_accepts_v19_test_only_through_current_transition() -> None:
    _clear()
    record = current_retirement.load_record()
    successor = next(
        item
        for claim in record["claims"]
        for item in claim["successor_tests"]
        if item["path"] == "tests/test_onyx_live_activation_v19.py"
    )
    transition = retirement.load_current_successor_transition()
    current = next(
        item
        for item in transition["named_successors"]
        if item["path"] == successor["path"]
    )
    assert current["predecessor_sha256"] == successor["sha256"]
    assert current["current_sha256"] == hashlib.sha256(
        (ROOT / successor["path"]).read_bytes()
    ).hexdigest()
