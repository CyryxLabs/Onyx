from __future__ import annotations

import copy
import hashlib
import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import verify_current_successor_retirement_v1 as v15
from scripts import verify_current_successor_retirement_v16 as retirement


ROOT = Path(__file__).resolve().parents[1]
V15 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V15.json"
V16 = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V16.json"
JUNIT = Path("C:/MAAX_Assistant/onyx-v15-rerun.junit.xml")


def _canonical(record: dict[str, object]) -> bytes:
    return (json.dumps(record, indent=2) + "\n").encode()


def _predecessor_nodes() -> set[str]:
    return set(v15.registered_test_ids(ROOT))


def _validate(
    record: dict[str, object], *, root: Path = ROOT
) -> tuple[dict[str, object], ...]:
    raw = _canonical(record)
    return retirement._validate_v16_record(
        raw=raw,
        root=root,
        predecessor_nodeids=_predecessor_nodes(),
        expected_digest=hashlib.sha256(raw).hexdigest(),
    )


def _junit_failed_nodeids() -> set[str]:
    tree = ET.parse(JUNIT)
    nodeids: set[str] = set()
    for case in tree.findall(".//testcase"):
        if case.find("failure") is None and case.find("error") is None:
            continue
        source = case.attrib["classname"].replace(".", "/") + ".py"
        nodeids.add(f"{source}::{case.attrib['name']}")
    return nodeids


def test_v16_is_additive_over_sha_authenticated_v15_and_preserves_102_routes() -> None:
    record = json.loads(V16.read_text(encoding="utf-8"))
    assert record["predecessor"] == {
        "path": "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V15.json",
        "sha256": retirement.PREDECESSOR_SHA256,
    }
    assert hashlib.sha256(V15.read_bytes()).hexdigest() == retirement.PREDECESSOR_SHA256
    predecessor_nodes = _predecessor_nodes()
    current_nodes = retirement.registered_test_ids(ROOT)
    assert len(predecessor_nodes) == 102
    assert predecessor_nodes < current_nodes
    assert len(current_nodes) == 220
    v16_nodes = {
        nodeid
        for claim in json.loads(V16.read_text(encoding="utf-8"))["additional_claims"]
        for nodeid in claim["historical_test_ids"]
    }
    assert len(predecessor_nodes & v16_nodes) == 41
    assert retirement.claim_for_test(next(iter(predecessor_nodes & v16_nodes)), ROOT)[
        "family"
    ] in retirement.FAMILY_COUNTS


def test_v16_routes_exactly_the_159_failed_junit_nodeids_and_no_others() -> None:
    record = json.loads(V16.read_text(encoding="utf-8"))
    assert hashlib.sha256(JUNIT.read_bytes()).hexdigest() == record["source_junit"]["sha256"]
    registered = {
        nodeid
        for claim in record["additional_claims"]
        for nodeid in claim["historical_test_ids"]
    }
    junit_nodes = _junit_failed_nodeids()
    assert len(junit_nodes) == 159
    assert registered == junit_nodes

    adversarial = copy.deepcopy(record)
    adversarial["additional_claims"][0]["historical_test_ids"].append(
        "tests/test_unrelated.py::test_not_in_junit"
    )
    with pytest.raises(retirement.CurrentSuccessorRetirementV16Error):
        _validate(adversarial)


def test_v16_rejects_duplicate_nodeids_and_noncanonical_paths() -> None:
    record = json.loads(V16.read_text(encoding="utf-8"))
    duplicate = copy.deepcopy(record)
    duplicate["additional_claims"][0]["historical_test_ids"][1] = duplicate[
        "additional_claims"
    ][0]["historical_test_ids"][0]
    with pytest.raises(
        retirement.CurrentSuccessorRetirementV16Error, match="duplicated"
    ):
        _validate(duplicate)

    bad_node_path = copy.deepcopy(record)
    bad_node_path["additional_claims"][0]["historical_test_ids"][0] = (
        "../tests/test_escape.py::test_escape"
    )
    with pytest.raises(
        retirement.CurrentSuccessorRetirementV16Error, match="not canonical"
    ):
        _validate(bad_node_path)

    bad_successor_path = copy.deepcopy(record)
    bad_successor_path["additional_claims"][0]["successor_tests"][0]["path"] = (
        "tests/../tests/test_phase6_current_v1.py"
    )
    with pytest.raises(
        retirement.CurrentSuccessorRetirementV16Error, match="not canonical"
    ):
        _validate(bad_successor_path)


def test_v16_rejects_predecessor_and_successor_sha_drift() -> None:
    record = json.loads(V16.read_text(encoding="utf-8"))
    predecessor_drift = copy.deepcopy(record)
    predecessor_drift["predecessor"]["sha256"] = "0" * 64
    with pytest.raises(
        retirement.CurrentSuccessorRetirementV16Error, match="contract drifted"
    ):
        _validate(predecessor_drift)

    successor_drift = copy.deepcopy(record)
    successor_drift["additional_claims"][0]["successor_tests"][0]["sha256"] = (
        "0" * 64
    )
    with pytest.raises(
        retirement.CurrentSuccessorRetirementV16Error, match="successor drifted"
    ):
        _validate(successor_drift)


def test_v16_rejects_symlinked_successor(tmp_path: Path) -> None:
    record = json.loads(V16.read_text(encoding="utf-8"))
    successor_paths = {
        binding["path"]
        for claim in record["additional_claims"]
        for binding in claim["successor_tests"]
    }
    for relative in successor_paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)

    relative = record["additional_claims"][0]["successor_tests"][0]["path"]
    linked = tmp_path / relative
    authenticated_copy = linked.with_name(linked.name + ".authenticated")
    linked.replace(authenticated_copy)
    try:
        linked.symlink_to(authenticated_copy)
    except OSError as error:
        pytest.fail(f"test host cannot create the required adversarial symlink: {error}")
    with pytest.raises(
        retirement.CurrentSuccessorRetirementV16Error, match="successor drifted"
    ):
        _validate(record, root=tmp_path)


def test_v16_rejects_record_byte_tamper_before_semantics() -> None:
    raw = V16.read_bytes() + b" "
    with pytest.raises(
        retirement.CurrentSuccessorRetirementV16Error, match="digest drifted"
    ):
        retirement._validate_v16_record(
            raw=raw,
            root=ROOT,
            predecessor_nodeids=_predecessor_nodes(),
            expected_digest=retirement.RECORD_SHA256,
        )
