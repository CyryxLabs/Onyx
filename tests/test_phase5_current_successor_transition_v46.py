from __future__ import annotations

import hashlib
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V46 = ROOT / "tests/fixtures/phase5_current_successor_transition_v46.json"


def test_v46_authenticates_v45_and_current_hud_successor() -> None:
    retirement.load_current_successor_transition.cache_clear()
    transition = retirement.load_current_successor_transition()
    assert hashlib.sha256(V46.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v46"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v45.json",
        "sha256": retirement.CURRENT_TRANSITION_V45_SHA256,
    }
    assert transition["predecessor_clock_anomaly"] == {
        "predecessor_issued_at": "2026-08-10T18:55:00-04:00",
        "observed_at": "2026-08-10T19:45:00-04:00",
        "reason": "normal_successor",
    }
    historical = {
        entry["path"]: entry["current_sha256"]
        for entry in transition["historical_bindings"]
    }
    assert (
        historical[".github/workflows/release-packages.yml"]
        == hashlib.sha256(
            (ROOT / ".github/workflows/release-packages.yml").read_bytes()
        ).hexdigest()
    )
