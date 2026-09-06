from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V24 = ROOT / "tests/fixtures/release_workflow_transition_v24.json"
V25 = ROOT / "tests/fixtures/release_workflow_transition_v25.json"


def test_release_v25_authenticates_v24_and_binds_neutral_successors() -> None:
    release = json.loads(V25.read_text(encoding="utf-8"))
    predecessor = json.loads(V24.read_text(encoding="utf-8"))

    assert hashlib.sha256(V25.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V25_SHA256
    )
    assert hashlib.sha256(V24.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V24_SHA256
    assert release["schema"] == "onyx.release-workflow-transition.v25"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v24.json",
        "sha256": retirement.RELEASE_TRANSITION_V24_SHA256,
    }
    assert retirement._recorded_release_root(
        predecessor, retirement.RELEASE_TRANSITION_V24_DOMAIN
    ) == predecessor["current_root_sha256"]
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert paths == {
        "docs/onyx/CURRENT_RELEASE_STATUS.md",
        "docs/onyx/DOCUMENTATION_INDEX.md",
        "docs/onyx/FINAL_EVIDENCE_INDEX_1.1.9.md",
        "docs/onyx/IMPLEMENTATION_ROADMAP.md",
        "docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_V37_2026-08-04.md",
        "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V3.json",
        "scripts/verify_current_successor_retirement_v1.py",
        "tests/fixtures/phase5_current_successor_transition_v36.json",
        "tests/test_current_successor_retirement_v3.py",
        "tests/test_phase5_current_successor_transition_v10.py",
        "tests/test_phase5_current_successor_transition_v35.py",
        "tests/test_phase5_current_successor_transition_v36.py",
    }
    assert {
        "scripts/verify_phase5_exit_retirement_v1.py",
        "tests/fixtures/release_workflow_transition_v25.json",
        "tests/test_release_workflow_transition_v25.py",
    }.isdisjoint(paths)
    assert release["current_root_sha256"] == (
        "f7f0bc7287144b5cbe13cd37214e3f65273e7cbd57f6bf6d55c3e859cbbcd68e"
    )
