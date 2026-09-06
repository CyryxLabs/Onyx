from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V26 = ROOT / "tests/fixtures/phase5_current_successor_transition_v26.json"
V27 = ROOT / "tests/fixtures/phase5_current_successor_transition_v27.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v27_authenticates_v26_and_binds_owned_dashboard_shutdown() -> None:
    _clear()
    transition = json.loads(V27.read_text(encoding="utf-8"))
    predecessor = json.loads(V26.read_text(encoding="utf-8"))

    assert hashlib.sha256(V27.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V27_SHA256
    )
    assert hashlib.sha256(V26.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V26_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v27"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v26.json",
        "sha256": retirement.CURRENT_TRANSITION_V26_SHA256,
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
    assert changed_historical == {"dashboard/server.py", "main.py"}
    assert changed_successors == set()
    assert transition["current_root_sha256"] == (
        "b0f7b11d48b8198c6984c8b3ba8fb7d89ae80a8ba2ee71028466d2dff1b0e10f"
    )
