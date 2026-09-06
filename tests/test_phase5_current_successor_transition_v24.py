from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V23 = ROOT / "tests/fixtures/phase5_current_successor_transition_v23.json"
V24 = ROOT / "tests/fixtures/phase5_current_successor_transition_v24.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v24_authenticates_v23_and_rebinds_only_package_hygiene_test() -> None:
    _clear()
    transition = json.loads(V24.read_text(encoding="utf-8"))
    predecessor = json.loads(V23.read_text(encoding="utf-8"))

    assert hashlib.sha256(V24.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V24_SHA256
    )
    assert hashlib.sha256(V23.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V23_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v24"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v23.json",
        "sha256": retirement.CURRENT_TRANSITION_V23_SHA256,
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
    assert changed_historical == set()
    assert changed_successors == {"tests/test_package_hygiene_v1.py"}
    assert transition["current_root_sha256"] == (
        "0ed9beb50037fce2e6694fe5639734539399e38a90cb6ffa6073163e57413b77"
    )
