from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_current_successor_retirement_v18 as retirement


ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "docs/onyx/checkpoints/CURRENT_SUCCESSOR_RETIREMENT_V18.json"


def _encoded(record: dict[str, object]) -> bytes:
    return (json.dumps(record, indent=2) + "\n").encode()


def test_v18_enumerates_exact_junit_residual_and_preserves_v17() -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    excluded = set(record["source_junit"]["excluded_passing_nodeids"])
    assert excluded == {
        "tests/test_orb_3d.py::OrbHostTests::test_package_smoke_test_instantiates_quick3d_root",
        "tests/test_onyx_hud_accessibility_stability_v1.py::test_current_host_publishes_only_the_final_qml_root",
    }
    assert len(retirement.v18_test_ids(ROOT)) == 155
    v17_nodes = retirement.predecessor.registered_test_ids(ROOT)
    assert len(v17_nodes) == 222
    assert v17_nodes <= retirement.registered_test_ids(ROOT)
    assert not excluded & retirement.v18_test_ids(ROOT)


def test_v18_precedes_v17_on_overlap() -> None:
    overlaps = retirement.v18_test_ids(ROOT) & retirement.predecessor.registered_test_ids(ROOT)
    assert overlaps
    for nodeid in overlaps:
        assert retirement.claim_for_test(nodeid, ROOT) in retirement._v18_claims(ROOT)


def test_v18_rejects_hash_tamper_extras_and_duplicates() -> None:
    raw = RECORD.read_bytes()
    with pytest.raises(retirement.CurrentSuccessorRetirementV18Error, match="digest drifted"):
        retirement._claim(ROOT, raw + b" ", retirement.RECORD_SHA256)
    record = json.loads(raw.decode())
    for mutation in ("extra", "duplicate"):
        changed = copy.deepcopy(record)
        nodes = changed["additional_claims"][0]["historical_test_ids"]
        nodes.append("tests/test_extra.py::test_extra" if mutation == "extra" else nodes[0])
        changed["additional_claims"][0]["validated_tests"] += 1
        encoded = _encoded(changed)
        with pytest.raises(retirement.CurrentSuccessorRetirementV18Error, match="contract drifted"):
            retirement._claim(ROOT, encoded, hashlib.sha256(encoded).hexdigest())


def test_v18_rejects_path_symlink_and_successor_tamper(tmp_path: Path) -> None:
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    changed = copy.deepcopy(record)
    changed["additional_claims"][0]["successor_tests"][0]["path"] = "../escape.py"
    encoded = _encoded(changed)
    with pytest.raises(retirement.CurrentSuccessorRetirementV18Error, match="contract drifted"):
        retirement._claim(ROOT, encoded, hashlib.sha256(encoded).hexdigest())

    link = tmp_path / "linked.json"
    try:
        link.symlink_to(RECORD)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(retirement.CurrentSuccessorRetirementV18Error, match="path is invalid"):
        retirement._strict_relative_file(tmp_path, "linked.json", "record")

    successor = json.loads(RECORD.read_text(encoding="utf-8"))["additional_claims"][0]["successor_tests"][0]
    assert hashlib.sha256((ROOT / successor["path"]).read_bytes()).hexdigest() == successor["sha256"]
