from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V24 = ROOT / "tests/fixtures/phase5_current_successor_transition_v24.json"
V25 = ROOT / "tests/fixtures/phase5_current_successor_transition_v25.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v25_authenticates_v24_and_binds_pinned_appimage_runtime() -> None:
    _clear()
    transition = json.loads(V25.read_text(encoding="utf-8"))
    predecessor = json.loads(V24.read_text(encoding="utf-8"))

    assert hashlib.sha256(V25.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V25_SHA256
    )
    assert hashlib.sha256(V24.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V24_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v25"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v24.json",
        "sha256": retirement.CURRENT_TRANSITION_V24_SHA256,
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
    assert changed_historical == {
        ".github/workflows/release-packages.yml",
        "scripts/build_release.py",
    }
    assert changed_successors == set()
    assert transition["current_root_sha256"] == (
        "b6b531ae865cf7f388d8b4ae4749c87119d94ab931bd3e76eead34a76923441c"
    )
