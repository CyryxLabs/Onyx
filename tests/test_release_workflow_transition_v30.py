from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V29 = ROOT / "tests/fixtures/release_workflow_transition_v29.json"
V30 = ROOT / "tests/fixtures/release_workflow_transition_v30.json"


def test_release_v30_authenticates_v29_and_exact_runtime_evidence_closure() -> None:
    retirement.load_release_workflow_transition.cache_clear()
    retirement.load_release_workflow_transition()
    release = json.loads(V30.read_text(encoding="utf-8"))
    assert hashlib.sha256(V30.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V30_SHA256
    assert hashlib.sha256(V29.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V29_SHA256
    assert release["schema"] == "onyx.release-workflow-transition.v30"
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "core/onyx_packaged_runtime_hud_contract_v1.py",
        "core/onyx_packaged_runtime_hud_contract_v1.manifest.json",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V26-E6-001.manifest.json",
        "tests/fixtures/phase5_current_successor_transition_v39.json",
        "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V6.json",
        "tests/test_packaged_runtime_hud_contract_v1.py",
    } <= paths
    assert "scripts/verify_phase5_exit_retirement_v1.py" not in paths
    assert json.loads(V29.read_text(encoding="utf-8"))["schema"] == (
        "onyx.release-workflow-transition.v29"
    )
