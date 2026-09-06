from __future__ import annotations

import hashlib
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V47 = ROOT / "tests/fixtures/phase5_current_successor_transition_v47.json"
V48 = ROOT / "tests/fixtures/phase5_current_successor_transition_v48.json"


def test_v48_authenticates_v47_and_current_evidence_successor() -> None:
    retirement.load_current_successor_transition.cache_clear()
    transition = retirement.load_current_successor_transition()
    assert hashlib.sha256(V47.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_SHA256
    )
    assert hashlib.sha256(V48.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V48_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v48"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v47.json",
        "sha256": retirement.CURRENT_TRANSITION_SHA256,
    }
    assert transition["predecessor_clock_anomaly"] is None
    successors = {
        entry["path"]: entry["current_sha256"]
        for entry in transition["named_successors"]
    }
    for relative in (
        "scripts/verify_capability_nexus_current_v1.py",
        "scripts/package_hygiene.py",
    ):
        assert successors[relative] == hashlib.sha256(
            (ROOT / relative).read_bytes()
        ).hexdigest()
