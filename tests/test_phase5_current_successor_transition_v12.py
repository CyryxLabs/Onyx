from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V11 = ROOT / "tests/fixtures/phase5_current_successor_transition_v11.json"
V12 = ROOT / "tests/fixtures/phase5_current_successor_transition_v12.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v12_authenticates_exact_v11_predecessor_and_domain_root() -> None:
    _clear()
    transition = json.loads(V12.read_text(encoding="utf-8"))
    assert hashlib.sha256(V12.read_bytes()).hexdigest() == (
        "e57480c4e52afb6e20aa336e4387b0dd4a5e77bf554eef4e5c7410683d7c16c7"
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v12"
    assert transition["issued_at"] == "2026-08-03T17:46:11-04:00"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v11.json",
        "sha256": retirement.CURRENT_TRANSITION_V11_SHA256,
    }
    assert transition["current_root_sha256"] == (
        "dd6ac349a22e6b5fd50a089cd7fe2009dedfe2f79007af64d491d0520c18bc96"
    )


def test_v11_is_exact_immutable_predecessor() -> None:
    assert hashlib.sha256(V11.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V11_SHA256
    )
    assert V11 == retirement.CURRENT_TRANSITION_V11


def test_v12_preserves_identity_and_records_only_current_ui_delta() -> None:
    v11 = json.loads(V11.read_text(encoding="utf-8"))
    v12 = json.loads(V12.read_text(encoding="utf-8"))
    assert [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in v12["historical_bindings"]
    ] == [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in v11["historical_bindings"]
    ]
    assert [
        (item["path"], item["predecessor_sha256"])
        for item in v12["named_successors"]
    ] == [
        (item["path"], item["predecessor_sha256"])
        for item in v11["named_successors"]
    ]
    historical_deltas = {
        current["path"]
        for current, prior in zip(
            v12["historical_bindings"], v11["historical_bindings"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    successor_deltas = {
        current["path"]
        for current, prior in zip(
            v12["named_successors"], v11["named_successors"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert historical_deltas == {"ui.py"}
    assert successor_deltas == set()


def test_v12_changes_no_runtime_authority_policy() -> None:
    _clear()
    transition = json.loads(V12.read_text(encoding="utf-8"))
    assert transition["policy"] == {
        "historical_bindings_are_rewritten": False,
        "historical_hashes_are_rebound": False,
        "predecessor_root_must_remain_reproducible": True,
        "current_paths_are_sha256_bound": True,
        "named_successors_are_sha256_bound": True,
        "runtime_authority_changes": False,
    }
