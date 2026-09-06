from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V35 = ROOT / "tests/fixtures/phase5_current_successor_transition_v35.json"
V36 = ROOT / "tests/fixtures/phase5_current_successor_transition_v36.json"


def test_v36_authenticates_v35_without_rebinding_historical_claims() -> None:
    transition = json.loads(V36.read_text(encoding="utf-8"))
    predecessor = json.loads(V35.read_text(encoding="utf-8"))

    assert hashlib.sha256(V36.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V36_SHA256
    assert hashlib.sha256(V35.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V35_SHA256
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v35.json",
        "sha256": retirement.CURRENT_TRANSITION_V35_SHA256,
    }
    assert transition["historical_bindings"] == predecessor["historical_bindings"]
    assert transition["named_successors"] == predecessor["named_successors"]
    assert transition["current_root_sha256"] == (
        "f79ea153782a1ae2ee45e5198bd03d059f932087c4a07ee1b0fdc9d7f6897b96"
    )
