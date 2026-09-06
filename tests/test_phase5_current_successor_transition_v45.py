from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V45 = ROOT / "tests/fixtures/phase5_current_successor_transition_v45.json"


def test_v45_authenticates_v44_and_current_portable_release_corrections() -> None:
    transition = json.loads(V45.read_text(encoding="utf-8"))
    assert hashlib.sha256(V45.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V45_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v45"
    assert transition["predecessor_clock_anomaly"] == {
        "predecessor_issued_at": "2026-08-10T18:30:00-04:00",
        "observed_at": "2026-08-10T15:55:00-04:00",
        "reason": "predecessor_future_dated",
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
