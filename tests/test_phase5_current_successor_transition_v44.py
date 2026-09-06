from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V44 = ROOT / "tests/fixtures/phase5_current_successor_transition_v44.json"


def test_v44_authenticates_v43_and_linux_preflight_gate_correction() -> None:
    retirement.load_current_successor_transition.cache_clear()
    transition = retirement.load_current_successor_transition()
    assert hashlib.sha256(V44.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V44_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v45"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v44.json",
        "sha256": retirement.CURRENT_TRANSITION_V44_SHA256,
    }
    historical_transition = json.loads(V44.read_text(encoding="utf-8"))
    assert historical_transition["predecessor_clock_anomaly"] == {
        "predecessor_issued_at": "2026-08-10T18:30:00-04:00",
        "observed_at": "2026-08-10T15:55:00-04:00",
        "reason": "predecessor_future_dated",
    }
    historical = {
        entry["path"]: entry["current_sha256"]
        for entry in historical_transition["historical_bindings"]
    }
    assert historical["scripts/build_release.py"] == (
        "93efb11c2c843a761cfec8b90bab2a2a341f62808697ae9e24c71cf9c1915805"
    )
