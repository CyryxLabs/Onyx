from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V16 = ROOT / "tests/fixtures/release_workflow_transition_v16.json"
V17 = ROOT / "tests/fixtures/release_workflow_transition_v17.json"


def _clear() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_v17_authenticates_v16_and_binds_operational_events_v23() -> None:
    _clear()
    release = json.loads(V17.read_text(encoding="utf-8"))
    assert hashlib.sha256(V17.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V17_SHA256
    assert hashlib.sha256(V16.read_bytes()).hexdigest() == retirement.RELEASE_TRANSITION_V16_SHA256
    assert release["schema"] == "onyx.release-workflow-transition.v17"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v16.json",
        "sha256": retirement.RELEASE_TRANSITION_V16_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "core/onyx_live_activation_v23.py",
        "core/operational_event_bridge_v1.py",
        "core/operational_event_controller_v1.py",
        "scripts/bootstrap_onyx_live_v23.pyw",
        "scripts/launch_onyx_live_v23.pyw",
        "tests/fixtures/phase5_current_successor_transition_v29.json",
    }.issubset(paths)
    assert release["current_root_sha256"] == (
        "9a373c25af4d063317279dd7222261e9aa74a91d0371fdc09c96749b00636bc4"
    )
