from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.verify_release_workflow_v53 import verify_release_workflow_v53


ROOT = Path(__file__).resolve().parents[1]


def test_release_v53_authenticates_portable_test_successor() -> None:
    result = verify_release_workflow_v53(ROOT)
    transition = result["transition"]
    assert transition["schema"] == "onyx.release-workflow-transition.v53"
    assert transition["logical_sequence"] == 53
    assert transition["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v52.json",
        "sha256": hashlib.sha256(
            (ROOT / "tests/fixtures/release_workflow_transition_v52.json").read_bytes()
        ).hexdigest(),
    }
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert {
        "tests/test_portable_activation_injection_v1.py",
        "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V14.json",
        "scripts/verify_source_freeze_v1.py",
        "tests/test_freeze_release_source_v53.py",
    } <= paths
    assert result["phase5"]["schema"] == (
        "onyx.phase5-current-successor-transition.v51"
    )
    assert result["runtime_authority_changed"] is False
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
