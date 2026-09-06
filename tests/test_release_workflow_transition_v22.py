from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V21 = ROOT / "tests/fixtures/release_workflow_transition_v21.json"
V22 = ROOT / "tests/fixtures/release_workflow_transition_v22.json"


def test_release_v22_binds_resident_exit_runtime_qml_and_tests() -> None:
    release = json.loads(V22.read_text(encoding="utf-8"))
    assert hashlib.sha256(V22.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V22_SHA256
    )
    assert hashlib.sha256(V21.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V21_SHA256
    )
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v21.json",
        "sha256": retirement.RELEASE_TRANSITION_V21_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "main.py",
        "ui.py",
        "qml/OnyxLiveShellV5.qml",
        "tests/fixtures/phase5_current_successor_transition_v33.json",
        "tests/test_phase5_current_successor_transition_v33.py",
        "tests/test_close_to_background_v1.py",
        "tests/test_shutdown_intent_v1.py",
        "tests/test_runtime_lifecycle_v1.py",
    }.issubset(paths)
    assert release["current_root_sha256"] == (
        "6b673150db1476dcb5c3b97371692a8f9aa3bc7fef8314a86fa5fabf1bee19d8"
    )
