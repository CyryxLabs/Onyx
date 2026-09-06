from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V2.json"
V3 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V3.json"


def test_retirement_v3_authenticates_v2_and_current_phase5_successor() -> None:
    record = json.loads(
        (ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V1.json").read_text(
            encoding="utf-8"
        )
    )
    successor = json.loads(V3.read_text(encoding="utf-8"))

    assert hashlib.sha256(V3.read_bytes()).hexdigest() == "4521b734b40c7bcc309980aa4a8c81d6a8434455d0194ed62396c90ba19abe8a"
    assert hashlib.sha256(V2.read_bytes()).hexdigest() == "e73f77e0b83d3a6de0d277131a6ba742ea1e204c8c8d248d03f994b24f903d37"
    assert successor["schema"] == "onyx.current-successor-retirement.v3"
    assert successor["predecessor"] == {
        "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V2.json",
        "sha256": "e73f77e0b83d3a6de0d277131a6ba742ea1e204c8c8d248d03f994b24f903d37",
    }
    assert successor["phase5_current_successor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v36.json",
        "sha256": "a1685eeeeaed0cdbcc7d4b1405036b64548733890e5bfc38c0e5053db6696546",
    }
    assert record["schema"] == "onyx.current-successor-retirement.v1"
    assert sum(len(claim["historical_test_ids"]) for claim in record["claims"]) == 17
