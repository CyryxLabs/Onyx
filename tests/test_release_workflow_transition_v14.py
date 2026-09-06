from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V13 = ROOT / "tests/fixtures/release_workflow_transition_v13.json"
V14 = ROOT / "tests/fixtures/release_workflow_transition_v14.json"


def _clear() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_v14_authenticates_v13_and_binds_clean_dashboard_exit() -> None:
    _clear()
    release = json.loads(V14.read_text(encoding="utf-8"))

    assert hashlib.sha256(V14.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V14_SHA256
    )
    assert hashlib.sha256(V13.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V13_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v14"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v13.json",
        "sha256": retirement.RELEASE_TRANSITION_V13_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "dashboard/server.py",
        "main.py",
        "tests/fixtures/phase5_current_successor_transition_v27.json",
        "tests/test_dashboard_shutdown_v1.py",
        "tests/test_phase5_current_successor_transition_v27.py",
        "tests/test_runtime_lifecycle_v1.py",
    }.issubset(paths)
    assert release["current_root_sha256"] == (
        "c76f0e5f88b5ab78cf11f648c114dacf73870128a24af38e978d30751b2a67c5"
    )
