from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V49 = ROOT / "tests/fixtures/phase5_current_successor_transition_v49.json"
V50 = ROOT / "tests/fixtures/phase5_current_successor_transition_v50.json"


def test_v50_authenticates_v49_without_runtime_authority_change() -> None:
    retirement.load_current_successor_transition.cache_clear()
    transition = retirement.load_current_successor_transition()
    assert hashlib.sha256(V49.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V49_SHA256
    )
    assert hashlib.sha256(V50.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V50_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v50"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v49.json",
        "sha256": retirement.CURRENT_TRANSITION_V49_SHA256,
    }
    assert transition["predecessor_clock_anomaly"] is None
    predecessor = json.loads(V49.read_text(encoding="utf-8"))
    assert transition["policy"] == predecessor["policy"]
