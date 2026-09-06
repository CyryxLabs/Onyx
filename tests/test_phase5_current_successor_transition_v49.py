from __future__ import annotations

import hashlib
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V48 = ROOT / "tests/fixtures/phase5_current_successor_transition_v48.json"
V49 = ROOT / "tests/fixtures/phase5_current_successor_transition_v49.json"


def test_v49_authenticates_v48_and_current_motion_successor() -> None:
    retirement.load_current_successor_transition.cache_clear()
    transition = retirement.load_current_successor_transition()
    assert hashlib.sha256(V48.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V48_SHA256
    )
    assert hashlib.sha256(V49.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V49_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v49"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v48.json",
        "sha256": retirement.CURRENT_TRANSITION_V48_SHA256,
    }
    assert transition["predecessor_clock_anomaly"] is None
