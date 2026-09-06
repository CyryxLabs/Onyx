from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V10 = ROOT / "tests/fixtures/phase5_current_successor_transition_v10.json"
V11 = ROOT / "tests/fixtures/phase5_current_successor_transition_v11.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v11_authenticates_exact_v10_predecessor_and_domain_root() -> None:
    _clear()
    transition = json.loads(V11.read_text(encoding="utf-8"))
    assert hashlib.sha256(V11.read_bytes()).hexdigest() == (
        "a6153df617e9af19f82a21ee00802a2a48c22af736a3b22e437b41705608cd89"
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v11"
    assert transition["issued_at"] == "2026-08-03T17:16:00-04:00"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v10.json",
        "sha256": retirement.CURRENT_TRANSITION_GRANDPREDECESSOR_SHA256,
    }
    assert transition["current_root_sha256"] == (
        "4941c6e585837e3c7c8d2b679749acafd7807c2b5cf79faeb6a19addcb4a200f"
    )


def test_v10_is_exact_immutable_predecessor() -> None:
    assert hashlib.sha256(V10.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_GRANDPREDECESSOR_SHA256
    )
    assert V10 == retirement.CURRENT_TRANSITION_GRANDPREDECESSOR


def test_v11_preserves_identity_and_records_only_current_byte_deltas() -> None:
    v10 = json.loads(V10.read_text(encoding="utf-8"))
    v11 = json.loads(V11.read_text(encoding="utf-8"))
    assert [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in v11["historical_bindings"]
    ] == [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in v10["historical_bindings"]
    ]
    assert [
        (item["path"], item["predecessor_sha256"])
        for item in v11["named_successors"]
    ] == [
        (item["path"], item["predecessor_sha256"])
        for item in v10["named_successors"]
    ]

    historical_deltas = {
        current["path"]
        for current, prior in zip(
            v11["historical_bindings"], v10["historical_bindings"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    successor_deltas = {
        current["path"]
        for current, prior in zip(
            v11["named_successors"], v10["named_successors"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert historical_deltas == {
        "main.py",
        "packaging/onyx.spec",
        "scripts/build_release.py",
    }
    assert successor_deltas == {
        "scripts/package_hygiene.py",
        "tests/test_package_hygiene_v1.py",
    }


def test_v11_changes_no_runtime_authority_policy() -> None:
    _clear()
    transition = json.loads(V11.read_text(encoding="utf-8"))
    assert transition["policy"] == {
        "historical_bindings_are_rewritten": False,
        "historical_hashes_are_rebound": False,
        "predecessor_root_must_remain_reproducible": True,
        "current_paths_are_sha256_bound": True,
        "named_successors_are_sha256_bound": True,
        "runtime_authority_changes": False,
    }
