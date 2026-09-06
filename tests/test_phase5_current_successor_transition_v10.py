from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V9 = ROOT / "tests/fixtures/phase5_current_successor_transition_v9.json"
V10 = ROOT / "tests/fixtures/phase5_current_successor_transition_v10.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v10_authenticates_exact_v9_predecessor_and_domain_root() -> None:
    transition = json.loads(V10.read_text(encoding="utf-8"))
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v10"
    assert transition["issued_at"] == "2026-08-03T10:09:29-04:00"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v9.json",
        "sha256": retirement.TRANSITION_SHA256,
    }
    assert len(transition["historical_bindings"]) == 18
    assert len(transition["named_successors"]) == 7
    assert transition["current_root_sha256"] == (
        "84de2478f97e9bfcfd2eab1e9d28f7c4b0fbe66f98ff21e000cbd53b9d3fbeb4"
    )


def test_v9_is_an_exact_immutable_predecessor() -> None:
    assert hashlib.sha256(V9.read_bytes()).hexdigest() == (
        "27991fabab95e3220ab34d86aec00a29d84ba49a82dc6e1ea075dc8662ca2200"
    )
    assert V9 == retirement.TRANSITION


def test_v10_preserves_all_v9_identities_and_records_only_real_deltas() -> None:
    _clear()
    v9 = json.loads(V9.read_text(encoding="utf-8"))
    v10 = json.loads(V10.read_text(encoding="utf-8"))
    assert [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in v10["historical_bindings"]
    ] == [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in v9["historical_bindings"]
    ]
    assert [
        (item["path"], item["predecessor_sha256"])
        for item in v10["named_successors"]
    ] == [
        (item["path"], item["predecessor_sha256"])
        for item in v9["named_successors"]
    ]

    historical_deltas = {
        current["path"]
        for current, prior in zip(
            v10["historical_bindings"], v9["historical_bindings"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    successor_deltas = {
        current["path"]
        for current, prior in zip(
            v10["named_successors"], v9["named_successors"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert historical_deltas == {
        ".github/workflows/release-packages.yml",
        "docs/onyx/CAPABILITY_MATRIX.md",
        "scripts/build_release.py",
        "scripts/check_release_eligibility.py",
    }
    assert successor_deltas == {"tests/test_package_hygiene_v1.py"}


def test_v13_predecessor_tamper_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tampered = tmp_path / "transition-v12.json"
    tampered.write_bytes(retirement.CURRENT_TRANSITION_PREDECESSOR.read_bytes() + b" ")
    monkeypatch.setattr(retirement, "CURRENT_TRANSITION_PREDECESSOR", tampered)
    _clear()
    with pytest.raises(
        retirement.Phase5ExitRetirementError,
        match="current Phase 5 successor predecessor drifted",
    ):
        retirement.load_current_successor_transition()
    _clear()


def test_v13_manifest_tamper_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tampered = tmp_path / "transition-v13.json"
    tampered.write_bytes(retirement.CURRENT_TRANSITION.read_bytes() + b" ")
    monkeypatch.setattr(retirement, "CURRENT_TRANSITION", tampered)
    _clear()
    with pytest.raises(
        retirement.Phase5ExitRetirementError,
        match="current Phase 5 successor transition drifted",
    ):
        retirement.load_current_successor_transition()
    _clear()


def test_v13_current_target_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = retirement._read

    def drift(root: Path, relative: str) -> bytes:
        payload = original(root, relative)
        if relative == "dashboard/server.py":
            return payload + b"\n"
        return payload

    monkeypatch.setattr(retirement, "_read", drift)
    _clear()
    with pytest.raises(
        retirement.Phase5ExitRetirementError,
        match="current historical target drifted: dashboard/server.py",
    ):
        retirement.load_current_successor_transition()
    _clear()


def test_v31_and_release_v20_keep_the_full_predecessor_chain_reproducible() -> None:
    _clear()
    current = json.loads(retirement.CURRENT_TRANSITION_V31.read_text(encoding="utf-8"))
    release = json.loads(retirement.RELEASE_TRANSITION_V20.read_text(encoding="utf-8"))
    v9 = json.loads(V9.read_text(encoding="utf-8"))
    assert hashlib.sha256(retirement.CURRENT_TRANSITION_V31.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V31_SHA256
    )
    assert hashlib.sha256(retirement.RELEASE_TRANSITION_V20.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V20_SHA256
    )
    assert current["schema"] == "onyx.phase5-current-successor-transition.v31"
    assert current["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v30.json",
        "sha256": retirement.CURRENT_TRANSITION_V30_SHA256,
    }
    assert release["schema"] == "onyx.release-workflow-transition.v20"
    assert release["predecessor"]["sha256"] == (
        retirement.RELEASE_TRANSITION_V19_SHA256
    )
    assert v9["current_root_sha256"] == (
        "bb16f4cf23ae75919e5d6fb05ddb30adcb814e537b73778c8744d80e6e1e9671"
    )
    assert current["policy"]["runtime_authority_changes"] is True


def test_predecessors_are_retained_and_current_documentation_preserves_v31_history() -> None:
    status = (ROOT / "docs/onyx/CURRENT_RELEASE_STATUS.md").read_text(
        encoding="utf-8"
    )
    index = (ROOT / "docs/onyx/DOCUMENTATION_INDEX.md").read_text(
        encoding="utf-8"
    )
    checkpoint = (
        ROOT / "docs/onyx/checkpoints/PHASE5_CURRENT_SUCCESSOR_TRANSITION_V10.md"
    ).read_text(encoding="utf-8")

    assert "Current installed product: **Onyx 1.1.9 Windows x64 V31**" in status
    assert "Current worktree candidate: **V37 source only; not built or installed**" in status
    assert "The first V31 eight-hour attempt **failed after 2,381.543 seconds**" in status
    assert "Onyx is not\ncomplete until every open row above" in status
    assert (
        "Current authenticated source evidence: **current authenticated source "
        "evidence selected by the direct verifier**"
    ) in index
    assert "scripts/verify_phase5_exit_retirement_v1.py" in index
    assert "Current selector:" in index
    assert "complete immutable predecessor chains" in index
    assert "tests/fixtures/phase5_current_successor_transition_v" not in index
    assert "tests/fixtures/release_workflow_transition_v" not in index
    assert "V31 long-session receipt | Failed at 2,381.543s" in index
    assert "`BUILD_NO_GO`" in checkpoint
