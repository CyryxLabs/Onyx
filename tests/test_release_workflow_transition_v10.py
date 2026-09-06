from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V9 = ROOT / "tests/fixtures/release_workflow_transition_v9.json"
V10 = ROOT / "tests/fixtures/release_workflow_transition_v10.json"


def _clear() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_v10_authenticates_v9_and_binds_current_v15_anchor() -> None:
    release = json.loads(V10.read_text(encoding="utf-8"))

    assert hashlib.sha256(V10.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V10_SHA256
    )
    assert hashlib.sha256(V9.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V9_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v10"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v9.json",
        "sha256": retirement.RELEASE_TRANSITION_V9_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V15-CURRENT-SOURCE-002.manifest.json",
        "docs/onyx/acceptance/VE-ONYX-LIVE-ACTIVATION-V15-CURRENT-SOURCE-002.md",
        "scripts/verify_onyx_live_activation_v15_current_source.py",
        "tests/test_onyx_live_activation_v15_current_source.py",
    }.issubset(paths)
    assert release["current_root_sha256"] == (
        "63013a5240a9cb0437705c9bfa4f04ac101306d638e358ee316df51c0142388c"
    )
