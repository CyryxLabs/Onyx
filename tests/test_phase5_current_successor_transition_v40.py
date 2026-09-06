from __future__ import annotations

import hashlib
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V39 = ROOT / "tests/fixtures/phase5_current_successor_transition_v39.json"
V40 = ROOT / "tests/fixtures/phase5_current_successor_transition_v40.json"


def test_v40_is_the_immutable_predecessor_of_current_v41() -> None:
    retirement.load_current_successor_transition.cache_clear()
    transition = retirement.load_current_successor_transition()
    assert hashlib.sha256(V40.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V40_SHA256
    assert hashlib.sha256(V39.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V39_SHA256
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v41"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v40.json",
        "sha256": retirement.CURRENT_TRANSITION_V40_SHA256,
    }
