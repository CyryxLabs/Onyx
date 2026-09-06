from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V15 = ROOT / "tests/fixtures/release_workflow_transition_v15.json"
V16 = ROOT / "tests/fixtures/release_workflow_transition_v16.json"


def _clear() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_v16_authenticates_v15_and_binds_owner_context_v22() -> None:
    _clear()
    release = json.loads(V16.read_text(encoding="utf-8"))

    assert hashlib.sha256(V16.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V16_SHA256
    )
    assert hashlib.sha256(V15.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V15_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v16"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v15.json",
        "sha256": retirement.RELEASE_TRANSITION_V15_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "core/owner_context_controller_v1.py",
        "core/owner_context_profile_v1.py",
        "core/onyx_live_activation_v22.py",
        "scripts/bootstrap_onyx_live_v22.pyw",
        "scripts/launch_onyx_live_v22.pyw",
        "tests/fixtures/phase5_current_successor_transition_v28.json",
    }.issubset(paths)
    assert release["current_root_sha256"] == (
        "53565a8facfe141a239c08bc46ec8d1e30fc2f77dfe349426649070e7a1dabe0"
    )
