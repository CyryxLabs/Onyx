from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.verify_release_workflow_v51 import verify_release_workflow_v51


ROOT = Path(__file__).resolve().parents[1]


def test_release_v51_authenticates_exact_qualification_pipeline() -> None:
    result = verify_release_workflow_v51(ROOT)
    transition = result["transition"]
    assert transition["schema"] == "onyx.release-workflow-transition.v51"
    assert transition["logical_sequence"] == 51
    assert transition["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v50.json",
        "sha256": hashlib.sha256(
            (ROOT / "tests/fixtures/release_workflow_transition_v50.json").read_bytes()
        ).hexdigest(),
    }
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert {
        ".github/workflows/release-packages.yml",
        ".github/workflows/release-qualification.yml",
        "docs/onyx/FINAL_EVIDENCE_REVIEW_PROTOCOL.md",
        "docs/onyx/FORMAL_RELEASE_CONTRACT.md",
        "scripts/generate_final_qualification_provenance_v1.py",
        "scripts/generate_phase5_current_successor_transition_v51.py",
        "scripts/prepare_qualification_artifacts_v1.py",
        "scripts/verify_final_release_qualification_v1.py",
        "tests/fixtures/phase5_current_successor_transition_v51.json",
        "tests/test_final_release_qualification_v1.py",
        "tests/test_phase5_current_successor_transition_v51.py",
        "tests/test_release_qualification_artifacts_v1.py",
    } <= paths
    assert result["phase5"]["schema"] == (
        "onyx.phase5-current-successor-transition.v51"
    )
    assert result["runtime_authority_changed"] is False
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
