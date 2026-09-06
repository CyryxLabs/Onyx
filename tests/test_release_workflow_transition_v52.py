from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.verify_release_workflow_v52 import verify_release_workflow_v52


ROOT = Path(__file__).resolve().parents[1]


def test_release_v52_authenticates_legal_evidence_successor() -> None:
    result = verify_release_workflow_v52(ROOT)
    transition = result["transition"]
    assert transition["schema"] == "onyx.release-workflow-transition.v52"
    assert transition["logical_sequence"] == 52
    assert transition["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v51.json",
        "sha256": hashlib.sha256(
            (ROOT / "tests/fixtures/release_workflow_transition_v51.json").read_bytes()
        ).hexdigest(),
    }
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert {
        "THIRD_PARTY_NOTICES.md",
        "scripts/missing_distribution_license_bundle.py",
        "tests/test_missing_distribution_license_bundle_v1.py",
        "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V13.json",
    } <= paths
    assert result["phase5"]["schema"] == (
        "onyx.phase5-current-successor-transition.v51"
    )
    assert result["runtime_authority_changed"] is False
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
