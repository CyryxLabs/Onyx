from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V36 = ROOT / "tests/fixtures/phase5_current_successor_transition_v36.json"
V37 = ROOT / "tests/fixtures/phase5_current_successor_transition_v37.json"


def test_v37_authenticates_v36_and_current_package_authorities() -> None:
    retirement.load_current_successor_transition.cache_clear()
    transition = retirement.load_current_successor_transition()
    predecessor = json.loads(V36.read_text(encoding="utf-8"))
    assert hashlib.sha256(V37.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_SHA256
    assert hashlib.sha256(V36.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V36_SHA256
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v36.json",
        "sha256": retirement.CURRENT_TRANSITION_V36_SHA256,
    }
    assert transition["current_root_sha256"] == "51cbb15251a3ce2befb3efc7599f7ab5c1e3c26bd7081747ed45aad39bfac5c9"
    assert transition["historical_bindings"] != predecessor["historical_bindings"]
    assert transition["named_successors"] != predecessor["named_successors"]
