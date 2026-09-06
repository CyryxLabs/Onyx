from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V23 = ROOT / "tests/fixtures/release_workflow_transition_v23.json"
V24 = ROOT / "tests/fixtures/release_workflow_transition_v24.json"


def test_release_v24_authenticates_v23_root_and_binds_current_delta() -> None:
    release = json.loads(V24.read_text(encoding="utf-8"))
    predecessor = json.loads(V23.read_text(encoding="utf-8"))

    assert hashlib.sha256(V24.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V24_SHA256
    )
    assert hashlib.sha256(V23.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V23_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v24"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v23.json",
        "sha256": retirement.RELEASE_TRANSITION_V23_SHA256,
    }
    assert retirement._recorded_release_root(
        predecessor, retirement.RELEASE_TRANSITION_V23_DOMAIN
    ) == predecessor["current_root_sha256"]

    hashes = {
        entry["path"]: entry["sha256"]
        for entry in release["current_release_paths"]
    }
    predecessor_hashes = {
        entry["path"]: entry["sha256"]
        for entry in predecessor["current_release_paths"]
    }
    assert all(predecessor_hashes.get(path) != digest for path, digest in hashes.items())
    assert {
        "core/onyx_hud_current_acceptance_v24.py",
        "core/onyx_live_activation_v24.py",
        "docs/onyx/acceptance/VE-HUD-CURRENT-V24-E6-001.manifest.json",
        "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V2.json",
        "scripts/verify_current_successor_retirement_v1.py",
        "tests/fixtures/phase5_current_successor_transition_v35.json",
        "tests/fixtures/release_workflow_transition_v23.json",
        "tests/test_onyx_hud_current_acceptance_v24.py",
        "tests/test_phase5_current_successor_transition_v35.py",
        "tests/test_release_workflow_transition_v23.py",
        "ui.py",
    }.issubset(hashes)
    assert {
        "scripts/verify_phase5_exit_retirement_v1.py",
        "tests/fixtures/release_workflow_transition_v24.json",
        "tests/test_release_workflow_transition_v24.py",
    }.isdisjoint(hashes)
    assert len(hashes) == 23
    assert release["current_root_sha256"] == (
        "668b924afb3ca80555b3321eade93005d5e6ae23bb8cbec4dba0ed94c1d0da48"
    )
