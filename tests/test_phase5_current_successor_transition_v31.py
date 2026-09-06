from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V30 = ROOT / "tests/fixtures/phase5_current_successor_transition_v30.json"
V31 = ROOT / "tests/fixtures/phase5_current_successor_transition_v31.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v31_authenticates_v30_and_binds_final_cleanroom_packaging() -> None:
    _clear()
    transition = json.loads(V31.read_text(encoding="utf-8"))
    predecessor = json.loads(V30.read_text(encoding="utf-8"))
    assert hashlib.sha256(V31.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V31_SHA256
    )
    assert hashlib.sha256(V30.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V30_SHA256
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v31"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v30.json",
        "sha256": retirement.CURRENT_TRANSITION_V30_SHA256,
    }
    changed_historical = {
        current["path"]
        for current, prior in zip(
            transition["historical_bindings"], predecessor["historical_bindings"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert changed_historical == {"packaging/onyx.spec"}
    assert transition["current_root_sha256"] == (
        "2bae0e32cd1e58a9c4a4dca7cfc44d8a89fefa6489deaa5be304d7e99f4c8a40"
    )
