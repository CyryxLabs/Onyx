from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.verify_release_workflow_v48 import verify_release_workflow_v48


ROOT = Path(__file__).resolve().parents[1]


def test_release_v48_authenticates_v47_and_current_evidence_corrections() -> None:
    result = verify_release_workflow_v48(ROOT)
    transition = result["transition"]
    assert transition["schema"] == "onyx.release-workflow-transition.v48"
    assert transition["logical_sequence"] == 48
    assert transition["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v47.json",
        "sha256": hashlib.sha256(
            (ROOT / "tests/fixtures/release_workflow_transition_v47.json").read_bytes()
        ).hexdigest(),
    }
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert {
        "tests/fixtures/phase5_current_successor_transition_v48.json",
        "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V10.json",
        "tests/fixtures/phase5_exit_retirement_v2.json",
        "tests/test_orb_3d.py",
    } <= paths
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False

