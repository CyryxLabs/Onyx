from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_current_successor_retirement_v17 as retirement


ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V17.json"


def test_v17_preserves_v16_and_overrides_only_release_v56() -> None:
    claims = retirement._current_claims(ROOT)
    assert claims[0]["id"] == "release-v56-to-v57-current-authority"
    assert len(claims[0]["historical_test_ids"]) == 2
    assert claims[0]["successor_tests"][0]["path"] == "tests/test_release_workflow_transition_v57.py"
    assert len(retirement.registered_test_ids(ROOT)) == 222
    for nodeid in claims[0]["historical_test_ids"]:
        assert retirement.claim_for_test(nodeid, ROOT) == claims[0]


def test_v17_rejects_record_and_successor_tamper() -> None:
    raw = RECORD.read_bytes()
    with pytest.raises(retirement.CurrentSuccessorRetirementV17Error, match="digest drifted"):
        retirement._claim(ROOT, raw + b" ", retirement.RECORD_SHA256)
    record = json.loads(raw.decode())
    record["additional_claims"][0]["successor_tests"][0]["sha256"] = "0" * 64
    changed = (json.dumps(record, indent=2) + "\n").encode()
    with pytest.raises(retirement.CurrentSuccessorRetirementV17Error, match="successor drifted"):
        retirement._claim(ROOT, changed, hashlib.sha256(changed).hexdigest())


def test_v17_rejects_extra_node_registration() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    changed = copy.deepcopy(record)
    changed["additional_claims"][0]["historical_test_ids"].append(
        "tests/test_release_workflow_transition_v57.py::test_release_v57_authenticates_current_closure"
    )
    raw = (json.dumps(changed, indent=2) + "\n").encode()
    with pytest.raises(retirement.CurrentSuccessorRetirementV17Error, match="claim drifted"):
        retirement._claim(ROOT, raw, hashlib.sha256(raw).hexdigest())
