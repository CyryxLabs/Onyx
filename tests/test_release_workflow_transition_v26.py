from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V25 = ROOT / "tests/fixtures/release_workflow_transition_v25.json"
V26 = ROOT / "tests/fixtures/release_workflow_transition_v26.json"


def test_release_v26_authenticates_v25_and_binds_prebuild_corrections() -> None:
    release = json.loads(V26.read_text(encoding="utf-8"))
    predecessor = json.loads(V25.read_text(encoding="utf-8"))

    assert hashlib.sha256(V26.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V26_SHA256
    )
    assert hashlib.sha256(V25.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V25_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v26"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v25.json",
        "sha256": retirement.RELEASE_TRANSITION_V25_SHA256,
    }
    assert retirement._recorded_release_root(
        predecessor, retirement.RELEASE_TRANSITION_V25_DOMAIN
    ) == predecessor["current_root_sha256"]
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert paths == {
        "scripts/verify_phase6_current_v1.py",
        "tests/test_bootstrap_onyx_live_v22.py",
        "tests/test_documentation_precedence_v1.py",
        "tests/test_onyx_live_activation_v18.py",
        "tests/test_phase5_current_successor_transition_v34.py",
        "tests/test_phase6_current_v1.py",
        "tests/test_release_workflow_transition_v25.py",
    }
    assert {
        "scripts/verify_phase5_exit_retirement_v1.py",
        "tests/fixtures/release_workflow_transition_v26.json",
        "tests/test_release_workflow_transition_v26.py",
    }.isdisjoint(paths)
    assert release["current_root_sha256"] == (
        "d8b572c3cb6f3e26623a6e5f2eceebcd19b40bdbc03145abdbe17213d6e97c10"
    )
