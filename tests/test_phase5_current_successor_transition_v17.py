from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V16 = ROOT / "tests/fixtures/phase5_current_successor_transition_v16.json"
V17 = ROOT / "tests/fixtures/phase5_current_successor_transition_v17.json"
RELEASE_V3 = ROOT / "tests/fixtures/release_workflow_transition_v3.json"
RELEASE_V4 = ROOT / "tests/fixtures/release_workflow_transition_v4.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v17_authenticates_exact_v16_and_shutdown_reason_delta() -> None:
    _clear()
    transition = json.loads(V17.read_text(encoding="utf-8"))
    assert hashlib.sha256(V17.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V17_SHA256
    )
    assert hashlib.sha256(V16.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V16_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v17"
    assert transition["predecessor"]["path"].endswith(
        "phase5_current_successor_transition_v16.json"
    )
    assert transition["current_root_sha256"] == (
        "2d33d97f437df7c6fe22bb1d1625fc4394d7b73cea1de583811c3352e6194823"
    )
    v16 = json.loads(V16.read_text(encoding="utf-8"))
    changed = {
        current["path"]
        for current, prior in zip(
            transition["historical_bindings"],
            v16["historical_bindings"],
            strict=True,
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert changed == {"main.py"}
    assert transition["policy"]["runtime_authority_changes"] is False


def test_release_v4_authenticates_exact_v3_and_lifecycle_regression() -> None:
    _clear()
    transition = json.loads(RELEASE_V4.read_text(encoding="utf-8"))
    assert hashlib.sha256(RELEASE_V4.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V4_SHA256
    )
    assert hashlib.sha256(RELEASE_V3.read_bytes()).hexdigest() == (
        retirement.RELEASE_TRANSITION_V3_SHA256
    )
    assert transition["schema"] == "onyx.release-workflow-transition.v4"
    paths = {
        item["path"]: item["sha256"]
        for item in transition["current_release_paths"]
    }
    assert paths["main.py"] == (
        "622db6603765613e0a9abc2d63d72aa1e309aedf6ea2de0f867d2c83ec3877e2"
    )
    assert paths["tests/test_runtime_lifecycle_v1.py"] == (
        "480fa9fdeec91c21662b7b0bf7c693d32c6f8fc5f842e2fcad3dc9d76283e7cd"
    )
    assert transition["current_root_sha256"] == (
        "690da4e1f7fd0cd5cdb7bb8f911f140fe3e1a6ccda6b1048ac999f5f56fb1a48"
    )
