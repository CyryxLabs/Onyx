from __future__ import annotations

import hashlib

from scripts import verify_current_successor_retirement_v1 as retirement


def test_retirement_v6_authenticates_v5_and_phase_v39() -> None:
    record = retirement.load_record()
    assert hashlib.sha256(retirement.RECORD.read_bytes()).hexdigest() == retirement.RECORD_SHA256
    assert hashlib.sha256(retirement.CURRENT_PREDECESSOR_RECORD.read_bytes()).hexdigest() == retirement.CURRENT_PREDECESSOR_RECORD_SHA256
    assert record["schema"] == "onyx.current-successor-retirement.v1"
    assert len(retirement.registered_test_ids()) == 17

