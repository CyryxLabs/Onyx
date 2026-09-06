from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V21 = ROOT / "tests/fixtures/phase5_current_successor_transition_v21.json"
V22 = ROOT / "tests/fixtures/phase5_current_successor_transition_v22.json"
RELEASE_V7 = ROOT / "tests/fixtures/release_workflow_transition_v7.json"
RELEASE_V8 = ROOT / "tests/fixtures/release_workflow_transition_v8.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v22_authenticates_v21_and_only_rebinds_release_builder() -> None:
    _clear()
    transition = json.loads(V22.read_text(encoding="utf-8"))
    predecessor = json.loads(V21.read_text(encoding="utf-8"))

    assert hashlib.sha256(V22.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V22_SHA256
    )
    assert hashlib.sha256(V21.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V21_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v22"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v21.json",
        "sha256": retirement.CURRENT_TRANSITION_V21_SHA256,
    }
    changed_historical = {
        current["path"]
        for current, prior in zip(
            transition["historical_bindings"],
            predecessor["historical_bindings"],
            strict=True,
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    changed_successors = {
        current["path"]
        for current, prior in zip(
            transition["named_successors"],
            predecessor["named_successors"],
            strict=True,
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert changed_historical == {"scripts/build_release.py"}
    assert changed_successors == set()
    assert transition["policy"]["runtime_authority_changes"] is True
    assert transition["current_root_sha256"] == (
        "d901e0e1699ac3c0a54e9c13d842df2df7886b83276119803b3938ae1f2a7ac6"
    )


def test_release_v8_authenticates_v7_and_binds_smoke_cleanup() -> None:
    _clear()
    release = json.loads(RELEASE_V8.read_text(encoding="utf-8"))

    assert hashlib.sha256(RELEASE_V8.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V8_SHA256
    )
    assert hashlib.sha256(RELEASE_V7.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V7_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v8"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v7.json",
        "sha256": retirement.RELEASE_TRANSITION_V7_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert "scripts/build_release.py" in paths
    assert "tests/test_smoke_credential_cleanup_v1.py" in paths
    assert release["current_root_sha256"] == (
        "a2d60dfc7b7725f1d1dc4ffa15eb4b6e11e294a601013d65d485a6995eec5434"
    )
