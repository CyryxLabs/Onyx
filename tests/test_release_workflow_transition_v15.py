from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V14 = ROOT / "tests/fixtures/release_workflow_transition_v14.json"
V15 = ROOT / "tests/fixtures/release_workflow_transition_v15.json"


def _clear() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_v15_authenticates_v14_and_revokes_corrected_shutdown() -> None:
    _clear()
    release = json.loads(V15.read_text(encoding="utf-8"))

    assert hashlib.sha256(V15.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V15_SHA256
    )
    assert hashlib.sha256(V14.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V14_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v15"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v14.json",
        "sha256": retirement.RELEASE_TRANSITION_V14_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "core/shutdown_intent_v1.py",
        "tests/test_shutdown_intent_v1.py",
    }.issubset(paths)
    assert release["current_root_sha256"] == (
        "ea4bc00f3e1276a773404c4ed7b459494a5c6c8037333c058db019f16c81fb64"
    )
