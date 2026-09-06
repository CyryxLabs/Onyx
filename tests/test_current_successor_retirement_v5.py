from __future__ import annotations

import hashlib
from pathlib import Path

from scripts import verify_current_successor_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]


def test_retirement_v5_authenticates_v4_and_phase_v38() -> None:
    record = retirement.load_record()
    assert hashlib.sha256(retirement.RECORD.read_bytes()).hexdigest() == retirement.RECORD_SHA256
    assert hashlib.sha256(retirement.CURRENT_PREDECESSOR_RECORD.read_bytes()).hexdigest() == retirement.CURRENT_PREDECESSOR_RECORD_SHA256
    assert record["schema"] == "onyx.current-successor-retirement.v1"
    assert len(retirement.registered_test_ids()) == 17
