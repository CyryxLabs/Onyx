from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V3 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V3.json"
V4 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V4.json"


def test_retirement_v4_authenticates_v3_and_phase_v37() -> None:
    record = retirement.load_record()
    successor = json.loads(V4.read_text(encoding="utf-8"))
    assert hashlib.sha256(V4.read_bytes()).hexdigest() == retirement.RECORD_SHA256
    assert hashlib.sha256(V3.read_bytes()).hexdigest() == retirement.PREDECESSOR_RECORD_SHA256
    assert successor["schema"] == "onyx.current-successor-retirement.v4"
    assert successor["phase5_current_successor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v37.json",
        "sha256": "7e6ad9282d101666953f80b11278349c95aed5715f2530c2870c18bebc9341af",
    }
    assert record["schema"] == "onyx.current-successor-retirement.v1"
    assert len(retirement.registered_test_ids()) == 17
