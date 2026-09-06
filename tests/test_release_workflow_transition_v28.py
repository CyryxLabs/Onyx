from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement
from scripts.verify_release_workflow_v39 import verify_release_workflow_v39


ROOT = Path(__file__).resolve().parents[1]
V27 = ROOT / "tests/fixtures/release_workflow_transition_v27.json"
V28 = ROOT / "tests/fixtures/release_workflow_transition_v28.json"


def test_release_v28_authenticates_v27_and_binds_packaged_runtime_contract() -> None:
    verify_release_workflow_v39(ROOT)
    release = json.loads(V28.read_text(encoding="utf-8"))
    predecessor = json.loads(V27.read_text(encoding="utf-8"))
    assert hashlib.sha256(V28.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V28_SHA256
    )
    assert hashlib.sha256(V27.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V27_SHA256
    assert release["schema"] == "onyx.release-workflow-transition.v28"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v27.json",
        "sha256": retirement.RELEASE_TRANSITION_V27_SHA256,
    }
    assert retirement._recorded_release_root(
        predecessor, retirement.RELEASE_TRANSITION_V27_DOMAIN
    ) == predecessor["current_root_sha256"]
    paths = {entry["path"] for entry in release["current_release_paths"]}
    for required in (
        "core/onyx_hud_current_acceptance_v25.py",
        "core/onyx_packaged_runtime_hud_contract_v1.py",
        "core/onyx_packaged_runtime_hud_contract_v1.manifest.json",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V25-E6-001.manifest.json",
        "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V4.json",
        "tests/fixtures/phase5_current_successor_transition_v37.json",
        "tests/test_packaged_runtime_hud_contract_v1.py",
    ):
        assert required in paths
    assert {
        "scripts/verify_phase5_exit_retirement_v1.py",
        "tests/fixtures/release_workflow_transition_v28.json",
        "tests/test_release_workflow_transition_v28.py",
    }.isdisjoint(paths)
