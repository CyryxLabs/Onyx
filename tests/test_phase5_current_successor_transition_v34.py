from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts import verify_phase5_exit_retirement_v1 as retirement


ROOT = Path(__file__).resolve().parents[1]
V33 = ROOT / "tests/fixtures/phase5_current_successor_transition_v33.json"
V34 = ROOT / "tests/fixtures/phase5_current_successor_transition_v34.json"


def test_v34_authenticates_v33_and_binds_final_v37_source() -> None:
    transition = json.loads(V34.read_text(encoding="utf-8"))
    predecessor = json.loads(V33.read_text(encoding="utf-8"))
    assert hashlib.sha256(V34.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V34_SHA256
    )
    assert hashlib.sha256(V33.read_bytes()).hexdigest() == (
        retirement.CURRENT_TRANSITION_V33_SHA256
    )
    assert transition["predecessor"] == {
        "path": "tests/fixtures/phase5_current_successor_transition_v33.json",
        "sha256": retirement.CURRENT_TRANSITION_V33_SHA256,
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
    assert changed_historical == {
        "docs/onyx/VERIFICATION_EVIDENCE.md",
        "main.py",
        "packaging/onyx.spec",
        "packaging/windows/onyx.iss",
        "scripts/build_release.py",
        "ui.py",
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
    assert changed_successors == {
        "scripts/package_hygiene.py",
        "tests/test_package_hygiene_v1.py",
    }
    assert transition["current_root_sha256"] == (
        "c11463c3c697cd20ebf9cf014daaa7de7954cec9901178ccfd4211cf79c768ea"
    )
