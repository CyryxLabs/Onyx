from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V38 = ROOT / "tests/fixtures/phase5_current_successor_transition_v38.json"
V39 = ROOT / "tests/fixtures/phase5_current_successor_transition_v39.json"


def test_v39_authenticates_v38_and_exact_runtime_evidence_authorities() -> None:
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_current_successor_transition()
    transition = json.loads(V39.read_text(encoding="utf-8"))
    assert hashlib.sha256(V39.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V39_SHA256
    assert hashlib.sha256(V38.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V38_SHA256
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v39"
    successors = {
        entry["path"]: entry["current_sha256"]
        for entry in transition["named_successors"]
    }
    assert successors["scripts/package_hygiene.py"] == (
        "278411f4bc0b4bec1bede1686a7dabfa86fb06d747238dffab7a25cc5a985d6d"
    )
    assert successors["tests/test_package_hygiene_v1.py"] == (
        "44881fbf0f87c9237a9c6989ed391e6c7297d1bb774ba0e107885e97d66ffce2"
    )
