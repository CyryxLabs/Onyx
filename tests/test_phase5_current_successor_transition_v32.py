from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V31 = ROOT / "tests/fixtures/phase5_current_successor_transition_v31.json"
V32 = ROOT / "tests/fixtures/phase5_current_successor_transition_v32.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v32_authenticates_v31_and_binds_resident_assistant_lifecycle() -> None:
    _clear()
    transition = json.loads(V32.read_text(encoding="utf-8"))
    predecessor = json.loads(V31.read_text(encoding="utf-8"))
    assert hashlib.sha256(V32.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V32_SHA256
    )
    assert hashlib.sha256(V31.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V31_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v32"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v31.json",
        "sha256": retirement.CURRENT_TRANSITION_V31_SHA256,
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
    assert changed_historical == {"main.py", "ui.py"}
    assert transition["current_root_sha256"] == (
        "20a40de4572f893f4e4fc7142eab7966818e25815cba709073cc8ed3386c50f9"
    )
