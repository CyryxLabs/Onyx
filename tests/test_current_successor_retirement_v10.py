from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V9 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V9.json"
V10 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V10.json"
HISTORICAL_RELEASE_NODE = (
    "tests/test_release_workflow_transition_v46.py::"
    "test_release_v46_authenticates_hud_v30_and_runtime_closure"
)
HISTORICAL_PHASE5_NODE = (
    "tests/test_phase5_current_successor_transition_v45.py::"
    "test_v45_authenticates_v44_and_current_portable_release_corrections"
)


def test_v10_preserves_v9_and_registers_current_v48_successors() -> None:
    record = json.loads(V10.read_text(encoding="utf-8"))
    assert record["schema"] == "onyx.current-successor-retirement.v10"
    assert record["predecessor"] == {
        "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V9.json",
        "sha256": hashlib.sha256(V9.read_bytes()).hexdigest(),
    }
    registered = retirement.registered_test_ids(ROOT)
    assert {HISTORICAL_RELEASE_NODE, HISTORICAL_PHASE5_NODE} <= registered
    assert retirement.claim_for_test(HISTORICAL_RELEASE_NODE, ROOT)[
        "successor_tests"
    ][0]["path"] == "tests/test_release_workflow_transition_v48.py"
    assert retirement.claim_for_test(HISTORICAL_PHASE5_NODE, ROOT)[
        "successor_tests"
    ][0]["path"] == "tests/test_phase5_current_successor_transition_v48.py"
