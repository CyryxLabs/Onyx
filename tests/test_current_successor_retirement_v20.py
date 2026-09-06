from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_current_successor_retirement_v20 as retirement


ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V20.json"


def test_v20_preserves_v19_and_overrides_only_current_liquid_metal_claim() -> None:
    claims = retirement._current_claims(ROOT)
    assert claims[0]["id"] == "liquid-metal-hud-v36-packaged-v5-release-v61"
    assert len(claims[0]["historical_test_ids"]) == 9
    assert (
        claims[0]["successor_tests"][-1]["path"]
        == "tests/test_release_workflow_transition_v61.py"
    )
    assert len(retirement.registered_test_ids(ROOT)) == 380
    for nodeid in claims[0]["historical_test_ids"]:
        assert retirement.claim_for_test(nodeid, ROOT) == claims[0]


def test_v20_rejects_record_and_successor_tamper() -> None:
    raw = RECORD.read_bytes()
    with pytest.raises(
        retirement.CurrentSuccessorRetirementV20Error, match="digest drifted"
    ):
        retirement._claim(ROOT, raw + b" ", retirement.RECORD_SHA256)
    record = json.loads(raw.decode())
    record["additional_claims"][0]["successor_tests"][0]["sha256"] = "0" * 64
    changed = (json.dumps(record, indent=2) + "\n").encode()
    with pytest.raises(
        retirement.CurrentSuccessorRetirementV20Error, match="successor drifted"
    ):
        retirement._claim(ROOT, changed, hashlib.sha256(changed).hexdigest())


def test_v20_rejects_extra_node_registration() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    record["additional_claims"][0]["historical_test_ids"].append(
        "tests/test_release_workflow_transition_v61.py::test_release_v61_authenticates_current_runtime_closure"
    )
    raw = (json.dumps(record, indent=2) + "\n").encode()
    with pytest.raises(
        retirement.CurrentSuccessorRetirementV20Error, match="claim drifted"
    ):
        retirement._claim(ROOT, raw, hashlib.sha256(raw).hexdigest())
