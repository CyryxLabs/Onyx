from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V12 = ROOT / "tests/fixtures/release_workflow_transition_v12.json"
V13 = ROOT / "tests/fixtures/release_workflow_transition_v13.json"


def _clear() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_v13_authenticates_v12_and_binds_shutdown_authority() -> None:
    _clear()
    release = json.loads(V13.read_text(encoding="utf-8"))

    assert hashlib.sha256(V13.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V13_SHA256
    )
    assert hashlib.sha256(V12.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V12_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v13"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v12.json",
        "sha256": retirement.RELEASE_TRANSITION_V12_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "core/shutdown_intent_v1.py",
        "main.py",
        "tests/fixtures/phase5_current_successor_transition_v26.json",
        "tests/test_phase5_current_successor_transition_v26.py",
        "tests/test_shutdown_intent_v1.py",
    }.issubset(paths)
    assert release["current_root_sha256"] == (
        "0a8f6dedce4fcb29712490d02cfcc08db07b5ea3de8c73f3069eea8d6666d1ba"
    )
