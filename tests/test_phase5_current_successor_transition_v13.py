from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V12 = ROOT / "tests/fixtures/phase5_current_successor_transition_v12.json"
V13 = ROOT / "tests/fixtures/phase5_current_successor_transition_v13.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v13_authenticates_exact_v12_predecessor_and_domain_root() -> None:
    _clear()
    transition = json.loads(V13.read_text(encoding="utf-8"))
    assert hashlib.sha256(V13.read_bytes()).hexdigest() == (
        "3b7770fb458d2350028ec764418a5ad1071cb34282e0a9e342bfcc76a1d0da42"
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v13"
    assert transition["issued_at"] == "2026-08-03T17:55:23-04:00"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v12.json",
        "sha256": retirement.CURRENT_TRANSITION_V12_SHA256,
    }
    assert transition["current_root_sha256"] == (
        "8471086587dff899727438fb31652886ae846d720c8e85a7cc42d0ba271b0568"
    )


def test_v12_is_exact_immutable_predecessor() -> None:
    assert hashlib.sha256(V12.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V12_SHA256
    )
    assert V12 == retirement.CURRENT_TRANSITION_V12


def test_v13_preserves_identity_and_records_only_current_ui_delta() -> None:
    v12 = json.loads(V12.read_text(encoding="utf-8"))
    v13 = json.loads(V13.read_text(encoding="utf-8"))
    assert [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in v13["historical_bindings"]
    ] == [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in v12["historical_bindings"]
    ]
    assert [
        (item["path"], item["predecessor_sha256"])
        for item in v13["named_successors"]
    ] == [
        (item["path"], item["predecessor_sha256"])
        for item in v12["named_successors"]
    ]
    historical_deltas = {
        current["path"]
        for current, prior in zip(
            v13["historical_bindings"], v12["historical_bindings"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    successor_deltas = {
        current["path"]
        for current, prior in zip(
            v13["named_successors"], v12["named_successors"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert historical_deltas == {"ui.py"}
    assert successor_deltas == set()


def test_v13_changes_no_runtime_authority_policy() -> None:
    _clear()
    transition = json.loads(V13.read_text(encoding="utf-8"))
    assert transition["policy"] == {
        "historical_bindings_are_rewritten": False,
        "historical_hashes_are_rebound": False,
        "predecessor_root_must_remain_reproducible": True,
        "current_paths_are_sha256_bound": True,
        "named_successors_are_sha256_bound": True,
        "runtime_authority_changes": False,
    }
