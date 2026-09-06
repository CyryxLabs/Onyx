from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V28 = ROOT / "tests/fixtures/release_workflow_transition_v28.json"
V29 = ROOT / "tests/fixtures/release_workflow_transition_v29.json"


def test_release_v29_authenticates_v28_and_frozen_runtime_closure() -> None:
    retirement.load_release_workflow_transition.cache_clear()
    retirement.load_release_workflow_transition()
    release = json.loads(V29.read_text(encoding="utf-8"))
    assert hashlib.sha256(V29.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V29_SHA256
    assert hashlib.sha256(V28.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V28_SHA256
    assert release["schema"] == "onyx.release-workflow-transition.v29"
    assert release["current_root_sha256"] == "182440c25224cd103874e4f310aa4c1d6221891bec8a06c545a2f1c0d4c257e0"
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert len(paths) == 23
    assert {
        "core/native_startup_smoke_v1.py",
        "core/onyx_hud_current_acceptance_v26.py",
        "scripts/bootstrap_onyx.pyw",
        "tests/fixtures/phase5_current_successor_transition_v38.json",
        "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V5.json",
    } <= paths
    assert "scripts/verify_phase5_exit_retirement_v1.py" not in paths
    assert json.loads(V28.read_text(encoding="utf-8"))["schema"] == (
        "onyx.release-workflow-transition.v28"
    )
