from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_current_successor_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V11 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V11.json"
V12 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V12.json"
HISTORICAL_FREEZE_V48_NODE = (
    "tests/test_freeze_release_source_v48.py::"
    "test_freezer_selects_exact_v48_current_authorities"
)


def test_v12_preserves_v11_and_registers_v51_freezer() -> None:
    record = json.loads(V12.read_text(encoding="utf-8"))
    assert record["schema"] == "onyx.current-successor-retirement.v12"
    assert record["predecessor"] == {
        "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V11.json",
        "sha256": hashlib.sha256(V11.read_bytes()).hexdigest(),
    }
    registered = retirement.registered_test_ids(ROOT)
    assert HISTORICAL_FREEZE_V48_NODE in registered
    claim = retirement.claim_for_test(HISTORICAL_FREEZE_V48_NODE, ROOT)
    assert claim["successor_tests"] == [
        {
            "path": "tests/test_freeze_release_source_v51.py",
            "sha256": hashlib.sha256(
                (ROOT / "tests/test_freeze_release_source_v51.py").read_bytes()
            ).hexdigest(),
        }
    ]
