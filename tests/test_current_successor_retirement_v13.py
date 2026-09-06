from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V12 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V12.json"
V13 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V13.json"
HISTORICAL_RELEASE_V51_NODE = (
    "tests/test_release_workflow_transition_v51.py::"
    "test_release_v51_authenticates_exact_qualification_pipeline"
)
HISTORICAL_FREEZE_V51_NODE = (
    "tests/test_freeze_release_source_v51.py::"
    "test_freezer_selects_exact_v51_current_authorities"
)


def test_v13_preserves_v12_and_registers_v52_successor() -> None:
    record = json.loads(V13.read_text(encoding="utf-8"))
    assert record["schema"] == "onyx.current-successor-retirement.v13"
    assert record["predecessor"] == {
        "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V12.json",
        "sha256": hashlib.sha256(V12.read_bytes()).hexdigest(),
    }
    registered = retirement.registered_test_ids(ROOT)
    assert HISTORICAL_RELEASE_V51_NODE in registered
    assert HISTORICAL_FREEZE_V51_NODE in registered
    claim = retirement.claim_for_test(HISTORICAL_RELEASE_V51_NODE, ROOT)
    assert claim["successor_tests"] == [
        {
            "path": "tests/test_freeze_release_source_v52.py",
            "sha256": hashlib.sha256(
                (ROOT / "tests/test_freeze_release_source_v52.py").read_bytes()
            ).hexdigest(),
        },
        {
            "path": "tests/test_release_workflow_transition_v52.py",
            "sha256": hashlib.sha256(
                (ROOT / "tests/test_release_workflow_transition_v52.py").read_bytes()
            ).hexdigest(),
        },
    ]
