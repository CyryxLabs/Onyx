from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V26 = ROOT / "tests/fixtures/release_workflow_transition_v26.json"
V27 = ROOT / "tests/fixtures/release_workflow_transition_v27.json"


def test_release_v27_authenticates_v26_and_binds_stable_documentation_selector() -> None:
    release = json.loads(V27.read_text(encoding="utf-8"))
    predecessor = json.loads(V26.read_text(encoding="utf-8"))

    assert hashlib.sha256(V27.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V27_SHA256
    )
    assert hashlib.sha256(V26.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V26_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v27"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v26.json",
        "sha256": retirement.RELEASE_TRANSITION_V26_SHA256,
    }
    assert retirement._recorded_release_root(
        predecessor, retirement.RELEASE_TRANSITION_V26_DOMAIN
    ) == predecessor["current_root_sha256"]
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert paths == {
        "docs/onyx/CURRENT_RELEASE_STATUS.md",
        "docs/onyx/DOCUMENTATION_INDEX.md",
        "docs/onyx/FINAL_EVIDENCE_INDEX_1.1.9.md",
        "docs/onyx/IMPLEMENTATION_ROADMAP.md",
        "docs/onyx/ONYX_PROJECT_COMPLETION_ROADMAP_V37_2026-08-04.md",
        "tests/test_phase5_current_successor_transition_v10.py",
        "tests/test_release_workflow_transition_v24.py",
        "tests/test_release_workflow_transition_v26.py",
    }
    assert {
        "scripts/verify_phase5_exit_retirement_v1.py",
        "tests/fixtures/release_workflow_transition_v27.json",
        "tests/test_release_workflow_transition_v27.py",
    }.isdisjoint(paths)
    assert release["current_root_sha256"] == (
        "87cb076d7c4452aefc3be5fee89cca8790911072d0b4fadf83ace15ad32f7620"
    )
