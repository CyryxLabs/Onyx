from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V10 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V10.json"
V11 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V11.json"
HISTORICAL_PHASE5_V50_NODE = (
    "tests/test_phase5_current_successor_transition_v50.py::"
    "test_v50_authenticates_v49_without_runtime_authority_change"
)
HISTORICAL_RELEASE_V50_NODE = (
    "tests/test_release_workflow_transition_v50.py::"
    "test_release_v50_authenticates_post_r10b_evidence_successor"
)


def test_v11_preserves_v10_and_registers_v51_successors() -> None:
    record = json.loads(V11.read_text(encoding="utf-8"))
    assert record["schema"] == "onyx.current-successor-retirement.v11"
    assert record["predecessor"] == {
        "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V10.json",
        "sha256": hashlib.sha256(V10.read_bytes()).hexdigest(),
    }
    registered = retirement.registered_test_ids(ROOT)
    assert {HISTORICAL_PHASE5_V50_NODE, HISTORICAL_RELEASE_V50_NODE} <= registered
    assert retirement.claim_for_test(HISTORICAL_PHASE5_V50_NODE, ROOT)[
        "successor_tests"
    ][0]["path"] == "tests/test_phase5_current_successor_transition_v51.py"
    assert retirement.claim_for_test(HISTORICAL_RELEASE_V50_NODE, ROOT)[
        "successor_tests"
    ][0]["path"] == "tests/test_release_workflow_transition_v51.py"
