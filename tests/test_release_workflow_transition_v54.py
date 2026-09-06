from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.verify_release_workflow_v54 import verify_release_workflow_v54


ROOT = Path(__file__).resolve().parents[1]


def test_release_v54_authenticates_packaging_closure_successor() -> None:
    result = verify_release_workflow_v54(ROOT)
    transition = result["transition"]
    assert transition["schema"] == "onyx.release-workflow-transition.v54"
    assert transition["logical_sequence"] == 54
    assert transition["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v53.json",
        "sha256": hashlib.sha256(
            (ROOT / "tests/fixtures/release_workflow_transition_v53.json").read_bytes()
        ).hexdigest(),
    }
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert {
        "core/capability_ports/__init__.py",
        "packaging/onyx.spec",
        "scripts/build_release.py",
        "scripts/verify_release_runtime_closure_v2.py",
        "tests/test_release_runtime_closure_v2.py",
    } <= paths
    assert result["closure"]["tests_in_runtime"] is False
    assert result["runtime_authority_changed"] is True
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
