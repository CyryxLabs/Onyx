from __future__ import annotations

import hashlib
from pathlib import Path

from scripts.verify_release_workflow_v49 import verify_release_workflow_v49


ROOT = Path(__file__).resolve().parents[1]


def test_release_v49_authenticates_ambient_motion_successor() -> None:
    result = verify_release_workflow_v49(ROOT)
    transition = result["transition"]
    assert transition["schema"] == "onyx.release-workflow-transition.v49"
    assert transition["logical_sequence"] == 49
    assert transition["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v48.json",
        "sha256": hashlib.sha256(
            (ROOT / "tests/fixtures/release_workflow_transition_v48.json").read_bytes()
        ).hexdigest(),
    }
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert {
        "core/onyx_hud_orb_v12.py",
        "core/onyx_hud_current_acceptance_v31.py",
        "tests/fixtures/phase5_current_successor_transition_v49.json",
        "tests/test_onyx_hud_orb_v12.py",
    } <= paths
    assert result["runtime"]["post_load_lifecycle_resynchronised"] is True
    assert result["formal_release_ready"] is False
    assert result["publishable"] is False
