from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V43 = ROOT / "tests/fixtures/phase5_current_successor_transition_v43.json"


def test_v43_authenticates_v42_and_isolated_installer_smoke_authority() -> None:
    retirement.load_current_successor_transition.cache_clear()
    transition = retirement.load_current_successor_transition()
    assert hashlib.sha256(V43.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V43_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v45"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v44.json",
        "sha256": retirement.CURRENT_TRANSITION_V44_SHA256,
    }
    historical_transition = json.loads(V43.read_text(encoding="utf-8"))
    historical = {
        entry["path"]: entry["current_sha256"]
        for entry in historical_transition["historical_bindings"]
    }
    assert historical["packaging/windows/onyx.iss"] == (
        "055d7d9daa848a0a9bc49819e26489872a0ceb1d203ad03154ae829367637c8a"
    )
    assert historical["scripts/build_release.py"] == (
        "4996309d8f38593934ed0fbe295ae06884f1b62bd6cde563a50e4de3672a4c20"
    )
