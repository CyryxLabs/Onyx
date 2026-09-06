from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V13 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V13.json"
V14 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V14.json"
HISTORICAL_RELEASE_V52_NODE = (
    "tests/test_release_workflow_transition_v52.py::"
    "test_release_v52_authenticates_legal_evidence_successor"
)
HISTORICAL_FREEZE_V52_NODE = (
    "tests/test_freeze_release_source_v52.py::"
    "test_freezer_selects_phase5_v51_and_release_v52_authorities"
)


def test_v14_preserves_v13_and_registers_v53_successor() -> None:
    record = json.loads(V14.read_text(encoding="utf-8"))
    assert record["schema"] == "onyx.current-successor-retirement.v14"
    assert record["predecessor"] == {
        "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V13.json",
        "sha256": hashlib.sha256(V13.read_bytes()).hexdigest(),
    }
    registered = retirement.registered_test_ids(ROOT)
    assert HISTORICAL_RELEASE_V52_NODE in registered
    assert HISTORICAL_FREEZE_V52_NODE in registered
    claim = retirement.claim_for_test(HISTORICAL_RELEASE_V52_NODE, ROOT)
    assert claim["successor_tests"] == [
        {
            "path": "tests/test_freeze_release_source_v53.py",
            "sha256": hashlib.sha256(
                (ROOT / "tests/test_freeze_release_source_v53.py").read_bytes()
            ).hexdigest(),
        },
        {
            "path": "tests/test_release_workflow_transition_v53.py",
            "sha256": hashlib.sha256(
                (ROOT / "tests/test_release_workflow_transition_v53.py").read_bytes()
            ).hexdigest(),
        },
    ]
