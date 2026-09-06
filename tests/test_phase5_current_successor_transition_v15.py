from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V14 = ROOT / "tests/fixtures/phase5_current_successor_transition_v14.json"
V15 = ROOT / "tests/fixtures/phase5_current_successor_transition_v15.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v15_authenticates_exact_v14_predecessor_and_domain_root() -> None:
    transition = json.loads(V15.read_text(encoding="utf-8"))
    assert hashlib.sha256(V15.read_bytes()).hexdigest() == (
        "f80347f24b3fb2f20a3e7ed3729f7ec28a30947a1d4c3b823baa834a0e8ecb18"
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v15"
    assert transition["issued_at"] == "2026-08-03T22:30:00-04:00"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v14.json",
        "sha256": retirement.CURRENT_TRANSITION_V14_SHA256,
    }
    assert transition["current_root_sha256"] == (
        "fb449ec9b536c4bc612bf7a76c9dcd0082f3d9aadf3edfef0c7be5752eba4404"
    )


def test_v14_is_exact_immutable_predecessor() -> None:
    assert hashlib.sha256(V14.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V14_SHA256
    )
    assert V14 == retirement.CURRENT_TRANSITION_V14


def test_v15_preserves_identity_and_records_only_current_source_deltas() -> None:
    v14 = json.loads(V14.read_text(encoding="utf-8"))
    v15 = json.loads(V15.read_text(encoding="utf-8"))
    assert [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in v15["historical_bindings"]
    ] == [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in v14["historical_bindings"]
    ]
    assert [
        (item["path"], item["predecessor_sha256"])
        for item in v15["named_successors"]
    ] == [
        (item["path"], item["predecessor_sha256"])
        for item in v14["named_successors"]
    ]
    historical_deltas = {
        current["path"]
        for current, prior in zip(
            v15["historical_bindings"], v14["historical_bindings"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    successor_deltas = {
        current["path"]
        for current, prior in zip(
            v15["named_successors"], v14["named_successors"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert historical_deltas == {
        "docs/onyx/CAPABILITY_MATRIX.md",
        "main.py",
        "packaging/onyx.spec",
        "scripts/build_release.py",
        "ui.py",
    }
    assert successor_deltas == set()


def test_v15_changes_no_runtime_authority_policy() -> None:
    transition = json.loads(V15.read_text(encoding="utf-8"))
    assert transition["policy"] == {
        "historical_bindings_are_rewritten": False,
        "historical_hashes_are_rebound": False,
        "predecessor_root_must_remain_reproducible": True,
        "current_paths_are_sha256_bound": True,
        "named_successors_are_sha256_bound": True,
        "runtime_authority_changes": False,
    }
