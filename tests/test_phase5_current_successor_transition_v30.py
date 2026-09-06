from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V29 = ROOT / "tests/fixtures/phase5_current_successor_transition_v29.json"
V30 = ROOT / "tests/fixtures/phase5_current_successor_transition_v30.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v30_authenticates_v29_and_binds_safe_pairing_release_surface() -> None:
    _clear()
    transition = json.loads(V30.read_text(encoding="utf-8"))
    predecessor = json.loads(V29.read_text(encoding="utf-8"))
    assert hashlib.sha256(V30.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V30_SHA256
    assert hashlib.sha256(V29.read_bytes()).hexdigest() == retirement.CURRENT_TRANSITION_V29_SHA256
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v30"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v29.json",
        "sha256": retirement.CURRENT_TRANSITION_V29_SHA256,
    }
    changed_historical = {
        current["path"]
        for current, prior in zip(
            transition["historical_bindings"], predecessor["historical_bindings"], strict=True
        )
        if current["current_sha256"] != prior["current_sha256"]
    }
    assert changed_historical == {
        "dashboard/server.py",
        "main.py",
        "packaging/onyx.spec",
        "packaging/windows/onyx.iss",
    }
    assert transition["current_root_sha256"] == (
        "bcd12f490e85e88ec415bb09a7018b5bc3ecaf548c2974c932ecba3aec9ef8ac"
    )
