from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_current_successor_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V14 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V14.json"
V15 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V15.json"
SUCCESSORS = {
    "tests/test_current_capability_status_v1.py",
    "tests/test_onyx_hud_current_acceptance_v34.py",
    "tests/test_packaged_runtime_hud_contract_v3.py",
    "tests/test_phase4_governed_successor_v2.py",
    "tests/test_phase6_current_v1.py",
    "tests/test_release_workflow_transition_v56.py",
}
FORBIDDEN_NODE_WORDS = {"tamper", "reject", "refuse", "security"}


def _canonical(record: dict[str, object]) -> bytes:
    return (json.dumps(record, indent=2) + "\n").encode()


def _prior_nodes() -> set[str]:
    return {f"tests/historical_{index}.py::test_positive_{index}" for index in range(76)}


def _validate(record: dict[str, object]) -> tuple[dict[str, object], ...]:
    raw = _canonical(record)
    policy = json.loads(V14.read_text(encoding="utf-8"))["policy"]
    return retirement._validate_v15_record(
        raw=raw,
        root=ROOT,
        policy=policy,
        registered_nodeids=_prior_nodes(),
        expected_digest=hashlib.sha256(raw).hexdigest(),
    )


def test_v15_preserves_v14_and_routes_only_closed_positive_nodes() -> None:
    record = json.loads(V15.read_text(encoding="utf-8"))
    assert record["schema"] == "onyx.current-successor-retirement.v15"
    assert record["predecessor"] == {
        "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V14.json",
        "sha256": "84edfabc9e1b3a0b8a143586e695e98827b16f840839b727f8cec40e5a81b9a7",
    }
    assert record["predecessor"]["sha256"] == hashlib.sha256(V14.read_bytes()).hexdigest()
    claims = retirement._current_claims(ROOT)
    assert len(retirement.registered_test_ids(ROOT)) == 102
    v15_claims = claims[-6:]
    assert {
        binding["path"]
        for claim in v15_claims
        for binding in claim["successor_tests"]
    } == SUCCESSORS
    nodeids = {
        nodeid
        for claim in v15_claims
        for nodeid in claim["historical_test_ids"]
    }
    assert len(nodeids) == 26
    assert all(
        word not in nodeid.lower()
        for nodeid in nodeids
        for word in FORBIDDEN_NODE_WORDS
    )


def test_v15_rejects_broad_or_tamper_security_registration() -> None:
    record = json.loads(V15.read_text(encoding="utf-8"))
    broad = copy.deepcopy(record)
    broad["additional_claims"][0]["historical_test_ids"].append(
        "tests/test_unrelated_history.py::test_unrelated_positive"
    )
    with pytest.raises(retirement.CurrentSuccessorRetirementError, match="registry drifted"):
        _validate(broad)

    for prohibited in ("test_leaf_tamper", "test_security_boundary"):
        adversarial = copy.deepcopy(record)
        adversarial["additional_claims"][0]["historical_test_ids"][0] = (
            f"tests/test_onyx_hud_current_acceptance_v30.py::{prohibited}"
        )
        with pytest.raises(
            retirement.CurrentSuccessorRetirementError,
            match="test ID is invalid",
        ):
            _validate(adversarial)


def test_v15_rejects_wrong_predecessor_and_successor_hashes() -> None:
    record = json.loads(V15.read_text(encoding="utf-8"))
    wrong_predecessor = copy.deepcopy(record)
    wrong_predecessor["predecessor"]["sha256"] = "0" * 64
    with pytest.raises(retirement.CurrentSuccessorRetirementError, match="contract drifted"):
        _validate(wrong_predecessor)

    wrong_successor = copy.deepcopy(record)
    wrong_successor["additional_claims"][0]["successor_tests"][0]["sha256"] = "0" * 64
    with pytest.raises(retirement.CurrentSuccessorRetirementError, match="successor drifted"):
        _validate(wrong_successor)


def test_v15_rejects_record_byte_tamper_before_semantics() -> None:
    raw = V15.read_bytes() + b" "
    policy = json.loads(V14.read_text(encoding="utf-8"))["policy"]
    with pytest.raises(retirement.CurrentSuccessorRetirementError, match="digest drifted"):
        retirement._validate_v15_record(
            raw=raw,
            root=ROOT,
            policy=policy,
            registered_nodeids=_prior_nodes(),
            expected_digest=retirement.CURRENT_EXTENSION_RECORD_V15_SHA256,
        )
