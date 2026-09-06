from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V17 = ROOT / "tests/fixtures/phase5_current_successor_transition_v17.json"
V18 = ROOT / "tests/fixtures/phase5_current_successor_transition_v18.json"
RELEASE_V4 = ROOT / "tests/fixtures/release_workflow_transition_v4.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v18_authenticates_exact_v17_and_daily_rhythm_ui_delta() -> None:
    _clear()
    transition = json.loads(V18.read_text(encoding="utf-8"))
    assert hashlib.sha256(V18.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V18_SHA256
    )
    assert hashlib.sha256(V17.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V17_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v18"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v17.json",
        "sha256": retirement.CURRENT_TRANSITION_V17_SHA256,
    }
    assert transition["current_root_sha256"] == (
        "19df4b7f8465232f4b99180fda5ba51c711e08343ca7c07bcf82792f176aeecb"
    )
    predecessor = json.loads(V17.read_text(encoding="utf-8"))
    changed = {
        current["path"]
        for current, prior in zip(
            transition["historical_bindings"],
            predecessor["historical_bindings"],
            strict=True,
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert changed == {"ui.py"}
    assert transition["policy"]["runtime_authority_changes"] is False


def test_v18_keeps_release_v4_exactly_bound() -> None:
    _clear()
    release = json.loads(RELEASE_V4.read_text(encoding="utf-8"))
    assert release["schema"] == "onyx.release-workflow-transition.v4"
    assert release["current_root_sha256"] == (
        "690da4e1f7fd0cd5cdb7bb8f911f140fe3e1a6ccda6b1048ac999f5f56fb1a48"
    )
