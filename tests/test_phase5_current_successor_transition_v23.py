from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V22 = ROOT / "tests/fixtures/phase5_current_successor_transition_v22.json"
V23 = ROOT / "tests/fixtures/phase5_current_successor_transition_v23.json"
RELEASE_V8 = ROOT / "tests/fixtures/release_workflow_transition_v8.json"
RELEASE_V9 = ROOT / "tests/fixtures/release_workflow_transition_v9.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v23_authenticates_v22_and_rebinds_current_release_builder_and_hud() -> None:
    _clear()
    transition = json.loads(V23.read_text(encoding="utf-8"))
    predecessor = json.loads(V22.read_text(encoding="utf-8"))

    assert hashlib.sha256(V23.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V23_SHA256
    )
    assert hashlib.sha256(V22.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V22_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v23"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v22.json",
        "sha256": retirement.CURRENT_TRANSITION_V22_SHA256,
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
    assert changed_historical == {"scripts/build_release.py", "ui.py"}
    assert changed_successors == set()
    assert transition["current_root_sha256"] == (
        "ce3494f7a25b8d1e43dd5b14757e42f4e59fcf48f2d33cb04578dd389881aba6"
    )


def test_release_v9_authenticates_v8_and_binds_advanced_operations() -> None:
    _clear()
    release = json.loads(RELEASE_V9.read_text(encoding="utf-8"))

    assert hashlib.sha256(RELEASE_V9.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V9_SHA256
    )
    assert hashlib.sha256(RELEASE_V8.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V8_SHA256
    )
    assert release["schema"] == "onyx.release-workflow-transition.v9"
    assert release["predecessor"] == {
        "path": "tests/fixtures/release_workflow_transition_v8.json",
        "sha256": retirement.RELEASE_TRANSITION_V8_SHA256,
    }
    paths = {entry["path"] for entry in release["current_release_paths"]}
    assert {
        "core/context_graph_v1.py",
        "core/workflow_graph_v1.py",
        "core/onyx_live_activation_v21.py",
        "docs/onyx/acceptance/VE-ADVANCED-OPS-V21-001.manifest.json",
        "tests/test_advanced_operations_source_acceptance_v1.py",
        "ui.py",
    }.issubset(paths)
    assert release["current_root_sha256"] == (
        "5f44736e7621ae00f326b36579376c7cba7bcf3598677e5bb60e44f005d9705d"
    )
