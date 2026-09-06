from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_release_workflow_transition_v3_preserves_v2_without_rebinding() -> None:
    path = ROOT / "tests/fixtures/release_workflow_transition_v3.json"
    transition = json.loads(path.read_text(encoding="utf-8"))
    assert transition["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v2.json",
        "sha256": retirement.RELEASE_TRANSITION_V2_SHA256,
    }
    assert transition["policy"]["historical_hashes_are_rebound"] is False
    paths = {entry["path"] for entry in transition["current_release_paths"]}
    assert {
        ".github/workflows/release-packages.yml",
        "scripts/build_release.py",
        "scripts/check_release_eligibility.py",
        "scripts/windows_native_eligibility.py",
        "scripts/windows_release.py",
        "scripts/linux_lifecycle_validation.py",
        "scripts/macos_lifecycle_validation.py",
        "scripts/windows_lifecycle_validation.py",
        "scripts/primp_license_bundle.py",
        "scripts/missing_distribution_license_bundle.py",
    }.issubset(paths)


def test_transition_authenticates_predecessor_current_paths_and_root() -> None:
    _clear()
    transition = retirement.load_successor_transition()
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v8.json",
        "sha256": retirement.TRANSITION_PREDECESSOR_SHA256,
    }
    assert len(transition["historical_bindings"]) == 18
    assert len(transition["named_successors"]) == 7
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v9"
    assert transition["current_root_sha256"] == (
        "bb16f4cf23ae75919e5d6fb05ddb30adcb814e537b73778c8744d80e6e1e9671"
    )


def test_v8_transition_is_an_exact_immutable_predecessor() -> None:
    assert hashlib.sha256(retirement.TRANSITION_PREDECESSOR.read_bytes()).hexdigest() == (
        retirement.TRANSITION_PREDECESSOR_SHA256
    )


def test_v8_predecessor_tamper_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tampered = tmp_path / "transition-v8.json"
    tampered.write_bytes(retirement.TRANSITION_PREDECESSOR.read_bytes() + b" ")
    monkeypatch.setattr(retirement, "TRANSITION_PREDECESSOR", tampered)
    _clear()
    with pytest.raises(
        retirement.Phase5ExitRetirementError,
        match="successor predecessor drifted",
    ):
        retirement.load_successor_transition()
    _clear()


def test_transition_preserves_every_predecessor_binding_without_rebinding() -> None:
    _clear()
    predecessor = retirement.load_record()
    transition = retirement.load_successor_transition()
    assert [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in transition["historical_bindings"]
    ] == [
        (
            item["path"],
            item["historical_sha256"],
            item["state"],
            item["successor"],
        )
        for item in predecessor["bindings"]
    ]


def test_transition_manifest_tamper_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tampered = tmp_path / "transition.json"
    tampered.write_bytes(retirement.TRANSITION.read_bytes() + b" ")
    monkeypatch.setattr(retirement, "TRANSITION", tampered)
    _clear()
    with pytest.raises(
        retirement.Phase5ExitRetirementError,
        match="successor transition drifted",
    ):
        retirement.load_successor_transition()
    _clear()


def test_current_target_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
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
        match="(?:current release policy target drifted|current historical target drifted): dashboard/server.py",
    ):
        retirement.load_successor_transition()
    _clear()


def test_predecessor_record_root_remains_reproducible() -> None:
    assert hashlib.sha256(retirement.RECORD.read_bytes()).hexdigest() == (
        retirement.RECORD_SHA256
    )
