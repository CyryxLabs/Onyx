from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V27 = ROOT / "tests/fixtures/phase5_current_successor_transition_v27.json"
V28 = ROOT / "tests/fixtures/phase5_current_successor_transition_v28.json"


def _clear() -> None:
    retirement.load_record.cache_clear()
    retirement.load_current_successor_transition.cache_clear()
    retirement.load_successor_transition.cache_clear()
    retirement.load_release_workflow_transition.cache_clear()


def test_v28_authenticates_v27_and_binds_v22_release_surface() -> None:
    _clear()
    transition = json.loads(V28.read_text(encoding="utf-8"))
    predecessor = json.loads(V27.read_text(encoding="utf-8"))

    assert hashlib.sha256(V28.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V28_SHA256
    )
    assert hashlib.sha256(V27.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V27_SHA256
    )
    assert transition["schema"] == "onyx.phase5-current-successor-transition.v28"
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v27.json",
        "sha256": retirement.CURRENT_TRANSITION_V27_SHA256,
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
    assert changed_historical == {"packaging/onyx.spec", "scripts/build_release.py"}
    assert changed_successors == {
        "scripts/package_hygiene.py",
        "tests/test_package_hygiene_v1.py",
    }
    assert transition["current_root_sha256"] == (
        "9e9b6c7d9d9bbc3ccc75691c09b8b2c3b8a47ba3a4abd3d04ce0ddf54e92c80e"
    )
