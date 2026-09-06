from __future__ import annotations

import hashlib
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V17 = ROOT / "tests/fixtures/release_workflow_transition_v17.json"
V18 = ROOT / "tests/fixtures/release_workflow_transition_v18.json"


def _clear() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_v18_authenticates_v17_and_binds_cleanroom_gap_successor() -> None:
    _clear()
    import json
    release = json.loads(V18.read_text(encoding="utf-8"))
    assert hashlib.sha256(V18.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V18_SHA256
    assert hashlib.sha256(V17.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V17_SHA256
    assert release["schema"] == "onyx.release-workflow-transition.v18"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v17.json",
        "sha256": retirement.RELEASE_TRANSITION_V17_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "core/device_pairing_v1.py",
        "core/official_messaging_v1.py",
        "tests/test_dashboard_pairing_v1.py",
        "tests/test_device_pairing_v1.py",
        "tests/test_official_messaging_v1.py",
        "tests/fixtures/phase5_current_successor_transition_v30.json",
    }.issubset(paths)
    assert release["current_root_sha256"] == (
        "cc724467c6b15d5b4690c0f5bd4c13e2c8bd4131096287b7f7966eef03bcb972"
    )
