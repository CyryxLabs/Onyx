from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V8 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V8.json"
V9 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V9.json"
HISTORICAL_NODE = (
    "tests/test_advanced_operations_source_acceptance_v1.py::"
    "test_advanced_operations_source_manifest_authenticates_exact_files"
)


def test_v9_preserves_v8_and_registers_the_stale_advanced_operations_node() -> None:
    record = json.loads(V9.read_text(encoding="utf-8"))
    assert record["schema"] == "onyx.current-successor-retirement.v9"
    assert record["predecessor"] == {
        "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V8.json",
        "sha256": hashlib.sha256(V8.read_bytes()).hexdigest(),
    }
    assert HISTORICAL_NODE in retirement.registered_test_ids(ROOT)
    claim = retirement.claim_for_test(HISTORICAL_NODE, ROOT)
    assert claim["disposition"] == "superseded-not-rebound"
    assert claim["successor_tests"] == [
        {
            "path": "tests/test_advanced_operations_controller_v1.py",
            "sha256": hashlib.sha256(
                (ROOT / "tests/test_advanced_operations_controller_v1.py").read_bytes()
            ).hexdigest(),
        }
    ]
